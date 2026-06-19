"""Construct the canonical reference-graph node/edge tables.

Takes staged tables (:mod:`oko_ingest.schemas`) plus a Stage-1
:class:`~oko_ingest.resolve.deterministic.ResolutionResult` and builds the node
and edge DataFrames that back the Reference Graph Snapshot (§5.2). Node types
mirror :class:`oko.config.GraphSchemaConfig` (``entity``, ``address``, ``npi``;
``claim`` is client-supplied, never built here).

Design rules:

- **Provenance on everything.** Every node and edge carries a ``source`` column
  naming the staged table(s) that produced it; merged nodes carry semicolon-
  joined sources.
- **Non-destructive.** Exclusion/deactivation are *boolean feature flags*
  derived by join, not deletions. NPIs keep their own node identity even when
  resolved into an entity (the ``has_npi`` edge carries the relationship), per
  the §3.4 rule that Type-1 person NPIs follow the clinician, not the org.
- **Deterministic.** Output ordering is sorted by id; flags are pure joins.

Returns a :class:`ReferenceGraph` of node tables keyed by node type and edge
tables keyed by ``(src, rel, dst)`` matching the schema edge types
``has_npi``, ``located_at``, ``associated_with``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from oko_ingest.npi import is_valid_npi
from oko_ingest.resolve.deterministic import ResolutionResult, enrollment_key, npi_key
from oko_ingest.resolve.normalize import (
    normalize_address,
    normalize_org_name,
    normalize_person_name,
)

# Edge type tuples mirror oko.config.GraphSchemaConfig.edge_types (the subset
# the reference graph can populate without client claims).
EDGE_HAS_NPI = ("entity", "has_npi", "npi")
EDGE_LOCATED_AT = ("entity", "located_at", "address")
EDGE_ASSOCIATED_WITH = ("entity", "associated_with", "entity")


@dataclass
class ReferenceGraph:
    """Canonical node/edge tables for the reference graph."""

    nodes: dict[str, pd.DataFrame] = field(default_factory=dict)
    edges: dict[tuple[str, str, str], pd.DataFrame] = field(default_factory=dict)


def _as_string(df: pd.DataFrame) -> pd.DataFrame:
    return df.astype("string")


def _valid_npis(series: pd.Series) -> pd.Series:
    return series.map(lambda v: not pd.isna(v) and is_valid_npi(str(v).strip()))


def build_reference_graph(
    resolution: ResolutionResult,
    nppes: pd.DataFrame | None = None,
    leie: pd.DataFrame | None = None,
    sam: pd.DataFrame | None = None,
    pecos_enrollment: pd.DataFrame | None = None,
    pecos_reassignment: pd.DataFrame | None = None,
) -> ReferenceGraph:
    """Build the canonical reference graph from staged + resolved data."""
    nppes = nppes if nppes is not None else _empty_nppes()
    graph = ReferenceGraph()

    # --- exclusion / deactivation lookups -----------------------------------
    leie_npis = set()
    if leie is not None and not leie.empty:
        valid = leie[_valid_npis(leie["npi"])]
        leie_npis = {str(v).strip() for v in valid["npi"].dropna()}

    # SAM exclusion flags attach to entities by UEI/CAGE (no NPI in public tier).
    sam_excluded_entities: set[str] = set()
    if sam is not None and not sam.empty:
        from oko_ingest.resolve.deterministic import cage_key, uei_key

        for _, row in sam.iterrows():
            for fn, val in ((uei_key, row.get("uei")), (cage_key, row.get("cage"))):
                if not pd.isna(val):
                    ent = resolution.key_to_entity.get(fn(str(val).strip()))
                    if ent:
                        sam_excluded_entities.add(ent)

    # --- npi nodes ----------------------------------------------------------
    npi_rows = []
    for _, row in nppes.iterrows():
        npi = row.get("npi")
        if pd.isna(npi) or not is_valid_npi(str(npi).strip()):
            continue
        npi = str(npi).strip()
        npi_rows.append(
            {
                "node_id": npi,
                "entity_type": _int_or_na(row.get("entity_type")),
                "taxonomy_code": _str_or_na(row.get("taxonomy_code")),
                "is_deactivated": bool(row.get("is_deactivated", False)),
                "leie_excluded": npi in leie_npis,
                "entity_id": resolution.entity_for_npi(npi) or pd.NA,
                "source": "nppes",
            }
        )
    npi_df = pd.DataFrame(
        npi_rows,
        columns=[
            "node_id", "entity_type", "taxonomy_code", "is_deactivated",
            "leie_excluded", "entity_id", "source",
        ],
    ).drop_duplicates(subset="node_id").sort_values("node_id").reset_index(drop=True)
    graph.nodes["npi"] = npi_df

    # --- address nodes ------------------------------------------------------
    addr_map: dict[str, dict] = {}
    for _, row in nppes.iterrows():
        key = normalize_address(
            row.get("address_1"), row.get("city"), row.get("state"), row.get("zip")
        )
        if not key:
            continue
        rec = addr_map.setdefault(
            key,
            {
                "node_id": key,
                "city": _str_or_na(row.get("city")),
                "state": _str_or_na(row.get("state")),
                "zip5": _zip5_or_na(row.get("zip")),
                "address_type": "unknown",  # classifier is a later milestone
                "source": "nppes",
            },
        )
    addr_df = pd.DataFrame(
        list(addr_map.values()),
        columns=["node_id", "city", "state", "zip5", "address_type", "source"],
    ).sort_values("node_id").reset_index(drop=True)
    graph.nodes["address"] = addr_df

    # --- entity nodes -------------------------------------------------------
    # One entity node per canonical entity_id. Display attributes are survived
    # from NPPES (org name for Type-2, person name for Type-1) with provenance.
    entity_attrs: dict[str, dict] = {}
    for _, row in nppes.iterrows():
        npi = row.get("npi")
        if pd.isna(npi) or not is_valid_npi(str(npi).strip()):
            continue
        ent = resolution.entity_for_npi(str(npi).strip())
        if ent is None:
            continue
        etype = _int_or_na(row.get("entity_type"))
        is_org = etype == 2
        rec = entity_attrs.setdefault(
            ent,
            {
                "node_id": ent,
                "entity_kind": "org" if is_org else "person",
                "name_key": pd.NA,
                "leie_excluded": False,
                "sam_excluded": ent in sam_excluded_entities,
                "sources": set(),
            },
        )
        rec["sources"].add("nppes")
        if is_org:
            nk = normalize_org_name(_str_or_na(row.get("org_name")))
        else:
            nk = normalize_person_name(
                _str_or_na(row.get("first_name")), _str_or_na(row.get("last_name"))
            )
        if nk and pd.isna(rec["name_key"]):
            rec["name_key"] = nk
        npi_s = str(npi).strip()
        if npi_s in leie_npis:
            rec["leie_excluded"] = True

    entity_rows = []
    for ent, rec in entity_attrs.items():
        entity_rows.append(
            {
                "node_id": rec["node_id"],
                "entity_kind": rec["entity_kind"],
                "name_key": rec["name_key"],
                "leie_excluded": rec["leie_excluded"],
                "sam_excluded": rec["sam_excluded"],
                "source": ";".join(sorted(rec["sources"])),
            }
        )
    entity_df = pd.DataFrame(
        entity_rows,
        columns=[
            "node_id", "entity_kind", "name_key",
            "leie_excluded", "sam_excluded", "source",
        ],
    ).sort_values("node_id").reset_index(drop=True)
    graph.nodes["entity"] = entity_df

    # --- has_npi edges (entity -> npi) --------------------------------------
    has_npi_rows = []
    for _, row in npi_df.iterrows():
        if not pd.isna(row["entity_id"]):
            has_npi_rows.append(
                {"src_id": row["entity_id"], "dst_id": row["node_id"], "source": "nppes"}
            )
    graph.edges[EDGE_HAS_NPI] = pd.DataFrame(
        has_npi_rows, columns=["src_id", "dst_id", "source"]
    ).drop_duplicates().reset_index(drop=True)

    # --- located_at edges (entity -> address) -------------------------------
    located_rows = []
    for _, row in nppes.iterrows():
        npi = row.get("npi")
        if pd.isna(npi) or not is_valid_npi(str(npi).strip()):
            continue
        ent = resolution.entity_for_npi(str(npi).strip())
        key = normalize_address(
            row.get("address_1"), row.get("city"), row.get("state"), row.get("zip")
        )
        if ent and key:
            located_rows.append({"src_id": ent, "dst_id": key, "source": "nppes"})
    graph.edges[EDGE_LOCATED_AT] = pd.DataFrame(
        located_rows, columns=["src_id", "dst_id", "source"]
    ).drop_duplicates().reset_index(drop=True)

    # --- associated_with edges (entity -> entity) via PECOS reassignment -----
    # reassignment links two enrollment_ids; map each enrollment -> NPI ->
    # entity_id through the resolution result.
    assoc_rows = []
    if pecos_reassignment is not None and not pecos_reassignment.empty:
        k2e = resolution.key_to_entity
        for _, row in pecos_reassignment.iterrows():
            a = row.get("reassigning_enrollment_id")
            b = row.get("receiving_enrollment_id")
            if pd.isna(a) or pd.isna(b):
                continue
            ea = k2e.get(enrollment_key(str(a).strip()))
            eb = k2e.get(enrollment_key(str(b).strip()))
            if ea and eb and ea != eb:
                assoc_rows.append(
                    {"src_id": ea, "dst_id": eb, "source": "pecos_reassignment"}
                )
    graph.edges[EDGE_ASSOCIATED_WITH] = pd.DataFrame(
        assoc_rows, columns=["src_id", "dst_id", "source"]
    ).drop_duplicates().reset_index(drop=True)

    # Enforce "string"-where-textual dtype discipline on id/source columns.
    for ntype, df in graph.nodes.items():
        graph.nodes[ntype] = _coerce_node_dtypes(df)
    for etype, df in graph.edges.items():
        graph.edges[etype] = df.astype({"src_id": "string", "dst_id": "string", "source": "string"})

    return graph


# --- small helpers ----------------------------------------------------------

def _coerce_node_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].astype("string")
    return df


def _str_or_na(value) -> object:
    if pd.isna(value):
        return pd.NA
    s = str(value).strip()
    return s if s else pd.NA


def _int_or_na(value) -> object:
    if pd.isna(value):
        return pd.NA
    try:
        return int(value)
    except (TypeError, ValueError):
        return pd.NA


def _zip5_or_na(value) -> object:
    if pd.isna(value):
        return pd.NA
    import re

    digits = re.sub(r"\D", "", str(value))
    return digits[:5] if digits else pd.NA


def _empty_nppes() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "npi", "entity_type", "org_name", "last_name", "first_name",
            "taxonomy_code", "address_1", "city", "state", "zip",
            "enumeration_date", "last_update_date", "deactivation_date",
            "is_deactivated",
        ]
    )
