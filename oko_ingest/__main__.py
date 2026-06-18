"""CLI for the ingestion engine.

Usage:
    python -m oko_ingest pull --source leie --data-dir data/staging
    python -m oko_ingest pull --source nppes --data-dir data/staging \
        --from-file monthly.csv --from-file weekly1.csv --snapshot-date 2026-06-01
    python -m oko_ingest vintages --data-dir data/staging

`--from-file` ingests already-downloaded files (offline path: real ops can
fetch out-of-band; it is also how historical vintages are backfilled).
Without it, the source downloads the current files itself.
"""

from __future__ import annotations

import argparse
import logging
import tempfile
from pathlib import Path

from oko_ingest.fetch import PoliteFetcher
from oko_ingest.sources import SOURCE_REGISTRY
from oko_ingest.staging import SnapshotStore


def _cmd_pull(args: argparse.Namespace) -> None:
    source_cls = SOURCE_REGISTRY.get(args.source)
    if source_cls is None:
        raise SystemExit(
            f"Unknown source '{args.source}'. Available: {sorted(SOURCE_REGISTRY)}"
        )
    source = source_cls()
    store = SnapshotStore(args.data_dir)

    if args.from_file:
        files = [Path(f) for f in args.from_file]
    else:
        fetcher = PoliteFetcher()
        download_dir = Path(tempfile.mkdtemp(prefix=f"oko_ingest_{source.name}_"))
        files = source.download(fetcher, download_dir)

    written = source.ingest(store, files, snapshot_date=args.snapshot_date)
    for table, path in written.items():
        print(f"staged {table} -> {path}")


def _cmd_vintages(args: argparse.Namespace) -> None:
    store = SnapshotStore(args.data_dir)
    root = Path(args.data_dir)
    tables = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    for table in tables:
        dates = ", ".join(d.isoformat() for d in store.vintages(table))
        print(f"{table}: {dates or '(none)'}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="oko_ingest")
    sub = parser.add_subparsers(dest="command", required=True)

    pull = sub.add_parser("pull", help="Download (or read local files) and stage a source")
    pull.add_argument("--source", required=True, help=f"One of: {sorted(SOURCE_REGISTRY)}")
    pull.add_argument("--data-dir", required=True, help="Staging store root directory")
    pull.add_argument(
        "--from-file", action="append", default=None,
        help="Ingest local file(s) instead of downloading (repeatable; order matters for NPPES)",
    )
    pull.add_argument("--snapshot-date", default=None, help="YYYY-MM-DD (default: today)")
    pull.set_defaults(func=_cmd_pull)

    vintages = sub.add_parser("vintages", help="List staged snapshot dates per table")
    vintages.add_argument("--data-dir", required=True)
    vintages.set_defaults(func=_cmd_vintages)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
