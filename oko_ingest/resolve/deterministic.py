"""Stage-1 deterministic entity resolution (docs/data-sourcing-engine.md §3.4).

Union-find clustering on *exact, immutable* keys only:

- **NPI** (checksum-validated via :mod:`oko_ingest.npi`) — the canonical
  individual (Type 1) and org (Type 2) key.
- **UEI** and **CAGE** (SAM exclusions).
- **enrollment_id <-> NPI** (PECOS enrollment) — ties a PECOS enrollment to a
  provider NPI.

Two hard domain rules from §3.4 are honored upstream of this module by *what
keys we union on*: we never union a Type-1 person NPI into a Type-2 org NPI
(NPIs are unioned only to themselves and to non-NPI keys, never NPI-to-NPI), and
address keys are deliberately NOT used here — fuzzy/address evidence is the
probabilistic stage's job (see ``probabilistic.py``).

Output: a :class:`ResolutionResult` mapping every source row to a canonical
``entity_id`` (deterministic ``ent_<hash>`` derived from the cluster's keys),
with full provenance (which ``source`` / row contributed which key).

Everything here is deterministic: cluster membership depends only on the set of
keys, and the canonical id is a content hash of the sorted key set.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import pandas as pd

from oko_ingest.npi import is_valid_npi


class UnionFind:
    """Minimal union-find over hashable keys (path compression + union by rank)."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._rank: dict[str, int] = {}

    def add(self, x: str) -> None:
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0

    def find(self, x: str) -> str:
        self.add(x)
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        # Path compression.
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1

    def roots(self) -> set[str]:
        return {self.find(x) for x in self._parent}


# Typed key namespaces keep distinct identifier spaces from colliding
# (an NPI that happens to equal a CAGE string must not union).
def npi_key(value: str) -> str:
    return f"NPI:{value}"


def uei_key(value: str) -> str:
    return f"UEI:{value}"


def cage_key(value: str) -> str:
    return f"CAGE:{value}"


def enrollment_key(value: str) -> str:
    return f"ENR:{value}"


@dataclass
class ResolutionResult:
    """Result of deterministic resolution.

    Attributes:
        key_to_entity: typed key (e.g. ``"NPI:1234567893"``) -> canonical
            ``entity_id``.
        provenance: long-form DataFrame, one row per (entity_id, key, source)
            contribution, "string" dtype throughout.
    """

    key_to_entity: dict[str, str]
    provenance: pd.DataFrame

    def entity_for_npi(self, npi: str) -> str | None:
        return self.key_to_entity.get(npi_key(npi))

    @property
    def num_entities(self) -> int:
        return len(set(self.key_to_entity.values()))


def _canonical_entity_id(keys: list[str]) -> str:
    """Deterministic canonical id = ``ent_<sha1(sorted keys)>`` (12 hex)."""
    digest = hashlib.sha1("|".join(sorted(keys)).encode("utf-8")).hexdigest()
    return f"ent_{digest[:12]}"


def _add_key(
    uf: UnionFind,
    rows: list[dict[str, str]],
    key: str,
    source: str,
    source_row: int,
    detail: str,
) -> None:
    uf.add(key)
    rows.append(
        {
            "key": key,
            "source": source,
            "source_row": str(source_row),
            "detail": detail,
        }
    )


def resolve_deterministic(
    nppes: pd.DataFrame | None = None,
    sam: pd.DataFrame | None = None,
    pecos_enrollment: pd.DataFrame | None = None,
    leie: pd.DataFrame | None = None,
) -> ResolutionResult:
    """Run Stage-1 deterministic resolution over staged tables.

    Each argument matches the corresponding pandera-validated staged schema
    (:mod:`oko_ingest.schemas`). All are optional; missing tables are skipped.
    Only checksum-valid NPIs are unioned (invalid NPIs are ignored as keys but
    do not crash resolution).
    """
    uf = UnionFind()
    prov_rows: list[dict[str, str]] = []

    def valid_npi(value) -> str | None:
        if pd.isna(value):
            return None
        s = str(value).strip()
        return s if is_valid_npi(s) else None

    # NPPES: one NPI per row; union the NPI key to itself (anchors a cluster).
    if nppes is not None:
        for i, row in nppes.reset_index(drop=True).iterrows():
            npi = valid_npi(row.get("npi"))
            if npi:
                _add_key(uf, prov_rows, npi_key(npi), "nppes", i, "npi")

    # PECOS enrollment: enrollment_id <-> NPI exact edge.
    if pecos_enrollment is not None:
        for i, row in pecos_enrollment.reset_index(drop=True).iterrows():
            npi = valid_npi(row.get("npi"))
            enr = row.get("enrollment_id")
            enr = str(enr).strip() if not pd.isna(enr) else None
            if npi:
                _add_key(uf, prov_rows, npi_key(npi), "pecos_enrollment", i, "npi")
            if enr:
                _add_key(uf, prov_rows, enrollment_key(enr), "pecos_enrollment", i, "enrollment_id")
            if npi and enr:
                uf.union(npi_key(npi), enrollment_key(enr))

    # SAM exclusions: union UEI<->CAGE for the same exclusion row. SAM carries
    # no NPI in the public tier, so these clusters stand alone unless a later
    # (probabilistic) stage links them.
    if sam is not None:
        for i, row in sam.reset_index(drop=True).iterrows():
            uei = row.get("uei")
            cage = row.get("cage")
            uei = str(uei).strip() if not pd.isna(uei) else None
            cage = str(cage).strip() if not pd.isna(cage) else None
            keys: list[str] = []
            if uei:
                _add_key(uf, prov_rows, uei_key(uei), "sam_exclusions", i, "uei")
                keys.append(uei_key(uei))
            if cage:
                _add_key(uf, prov_rows, cage_key(cage), "sam_exclusions", i, "cage")
                keys.append(cage_key(cage))
            for k in keys[1:]:
                uf.union(keys[0], k)

    # LEIE: NPI is sparse (post-2008 only). Where present and valid it merges
    # the exclusion into the provider's NPI cluster.
    if leie is not None:
        for i, row in leie.reset_index(drop=True).iterrows():
            npi = valid_npi(row.get("npi"))
            if npi:
                _add_key(uf, prov_rows, npi_key(npi), "leie", i, "npi")

    # Assign canonical entity ids from cluster membership.
    members: dict[str, list[str]] = {}
    for key in list(uf.roots() | set(uf._parent)):
        members.setdefault(uf.find(key), []).append(key)

    root_to_entity = {
        root: _canonical_entity_id(keys) for root, keys in members.items()
    }
    key_to_entity = {
        key: root_to_entity[uf.find(key)] for key in uf._parent
    }

    prov = pd.DataFrame(prov_rows, columns=["key", "source", "source_row", "detail"])
    if not prov.empty:
        prov["entity_id"] = prov["key"].map(key_to_entity)
    else:
        prov["entity_id"] = pd.Series(dtype="object")
    prov = prov.astype("string")

    return ResolutionResult(key_to_entity=key_to_entity, provenance=prov)
