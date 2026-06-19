"""Write/read the **Reference Graph Snapshot** (docs/data-sourcing-engine.md §5.2).

A snapshot is a versioned, immutable directory:

    <root>/<version>/
    ├── nodes/<ntype>.parquet                  # node_id + feature columns
    ├── edges/<src>__<rel>__<dst>.parquet      # src_id, dst_id (+ provenance)
    └── manifest.json                          # version, created_at, counts

The layout matches the client data contract (§5.2) so the same connectors serve
reference and client data. Immutability follows :class:`SnapshotStore`'s
discipline: a version directory is never overwritten (a tmp dir is renamed into
place atomically), so a pinned snapshot version is reproducible.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from oko_ingest.resolve.graph import ReferenceGraph

_EDGE_SEP = "__"


def _edge_filename(edge_type: tuple[str, str, str]) -> str:
    return _EDGE_SEP.join(edge_type) + ".parquet"


def _parse_edge_filename(name: str) -> tuple[str, str, str]:
    stem = name[: -len(".parquet")] if name.endswith(".parquet") else name
    parts = stem.split(_EDGE_SEP)
    if len(parts) != 3:
        raise ValueError(f"Malformed edge filename: {name!r}")
    return (parts[0], parts[1], parts[2])


@dataclass
class ReferenceGraphSnapshot:
    """A loaded snapshot: its graph plus its version directory + manifest."""

    version: str
    path: Path
    graph: ReferenceGraph
    manifest: dict


def write_snapshot(
    graph: ReferenceGraph,
    root: str | Path,
    version: str | None = None,
    overwrite: bool = False,
) -> Path:
    """Write an immutable snapshot version; returns the version directory.

    ``version`` defaults to a UTC timestamp (``YYYYMMDDTHHMMSSZ``). Refuses to
    overwrite an existing version unless ``overwrite=True`` (repair only).
    """
    root = Path(root)
    version = version or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = root / version
    if target.exists():
        if not overwrite:
            raise FileExistsError(
                f"Snapshot version {version!r} already exists at {target}; "
                "snapshots are immutable (pass overwrite=True only to repair)."
            )
        shutil.rmtree(target)

    # Stage into a tmp dir, then atomic-rename into place.
    tmp = root / f".{version}.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    (tmp / "nodes").mkdir(parents=True)
    (tmp / "edges").mkdir(parents=True)

    node_counts = {}
    for ntype, df in graph.nodes.items():
        df.to_parquet(tmp / "nodes" / f"{ntype}.parquet", index=False)
        node_counts[ntype] = int(len(df))

    edge_counts = {}
    for etype, df in graph.edges.items():
        fname = _edge_filename(etype)
        df.to_parquet(tmp / "edges" / fname, index=False)
        edge_counts[_EDGE_SEP.join(etype)] = int(len(df))

    manifest = {
        "version": version,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "contract": "reference-graph-snapshot/v1 (data-sourcing-engine.md §5.2)",
        "node_counts": node_counts,
        "edge_counts": edge_counts,
    }
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    root.mkdir(parents=True, exist_ok=True)
    tmp.replace(target)
    return target


def read_snapshot(
    root: str | Path, version: str | None = None
) -> ReferenceGraphSnapshot:
    """Read a snapshot version (default: latest lexicographic version)."""
    root = Path(root)
    if version is None:
        versions = sorted(
            p.name
            for p in root.iterdir()
            if p.is_dir() and not p.name.startswith(".") and (p / "manifest.json").exists()
        )
        if not versions:
            raise LookupError(f"No snapshot versions under {root}.")
        version = versions[-1]
    path = root / version
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))

    graph = ReferenceGraph()
    nodes_dir = path / "nodes"
    if nodes_dir.is_dir():
        for f in sorted(nodes_dir.glob("*.parquet")):
            graph.nodes[f.stem] = pd.read_parquet(f)
    edges_dir = path / "edges"
    if edges_dir.is_dir():
        for f in sorted(edges_dir.glob("*.parquet")):
            graph.edges[_parse_edge_filename(f.name)] = pd.read_parquet(f)

    return ReferenceGraphSnapshot(
        version=version, path=path, graph=graph, manifest=manifest
    )
