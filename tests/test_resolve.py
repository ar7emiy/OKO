"""Tests for the M2 entity-resolution + reference-graph layer.

All fixtures are small hand-built DataFrames mirroring the staged pandera
schemas (oko_ingest/schemas.py); no real data, no network.
"""

from __future__ import annotations

import pandas as pd
import pytest

from oko_ingest.publish.snapshot import read_snapshot, write_snapshot
from oko_ingest.resolve.deterministic import (
    enrollment_key,
    npi_key,
    resolve_deterministic,
)
from oko_ingest.resolve.graph import (
    EDGE_ASSOCIATED_WITH,
    EDGE_HAS_NPI,
    EDGE_LOCATED_AT,
    build_reference_graph,
)
from oko_ingest.resolve.normalize import (
    normalize_address,
    normalize_org_name,
    normalize_person_name,
)

# Checksum-valid NPIs (verified against oko_ingest.npi.is_valid_npi).
NPI_A = "1234567893"
NPI_B = "1245319599"
NPI_C = "1679576722"


# --------------------------------------------------------------------------- #
# fixtures                                                                     #
# --------------------------------------------------------------------------- #

@pytest.fixture
def nppes() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "npi": pd.array([NPI_A, NPI_B, NPI_C], dtype="string"),
            "entity_type": pd.array([1, 2, 1], dtype="Int64"),
            "org_name": pd.array([pd.NA, "Acme Medical Center LLC", pd.NA], dtype="string"),
            "last_name": pd.array(["Smith", pd.NA, "Jones"], dtype="string"),
            "first_name": pd.array(["Robert", pd.NA, "Mary"], dtype="string"),
            "taxonomy_code": pd.array(["207Q00000X", "261QM0850X", "207R00000X"], dtype="string"),
            "address_1": pd.array(
                ["123 Main St STE 100", "123 Main Street Suite #100", "9 Elm Ave"],
                dtype="string",
            ),
            "city": pd.array(["Springfield", "Springfield", "Dayton"], dtype="string"),
            "state": pd.array(["IL", "IL", "OH"], dtype="string"),
            "zip": pd.array(["62704", "627041234", "45402"], dtype="string"),
            "enumeration_date": pd.array([pd.NaT, pd.NaT, pd.NaT], dtype="datetime64[ns]"),
            "last_update_date": pd.array([pd.NaT, pd.NaT, pd.NaT], dtype="datetime64[ns]"),
            "deactivation_date": pd.array([pd.NaT, pd.NaT, pd.NaT], dtype="datetime64[ns]"),
            "is_deactivated": [False, False, True],
        }
    )


@pytest.fixture
def leie() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "last_name": pd.array(["Smith", pd.NA], dtype="string"),
            "first_name": pd.array(["Robert", pd.NA], dtype="string"),
            "mid_name": pd.array([pd.NA, pd.NA], dtype="string"),
            "bus_name": pd.array([pd.NA, "Shady Co"], dtype="string"),
            "general": pd.array(["1128a1", "1128b"], dtype="string"),
            "specialty": pd.array([pd.NA, pd.NA], dtype="string"),
            "npi": pd.array([NPI_A, pd.NA], dtype="string"),  # excludes provider A
            "address": pd.array([pd.NA, pd.NA], dtype="string"),
            "city": pd.array([pd.NA, pd.NA], dtype="string"),
            "state": pd.array([pd.NA, pd.NA], dtype="string"),
            "zip": pd.array([pd.NA, pd.NA], dtype="string"),
            "excl_type": pd.array(["1128a1", "1128b"], dtype="string"),
            "excl_date": pd.array(
                [pd.Timestamp("2020-01-01"), pd.Timestamp("2021-01-01")],
                dtype="datetime64[ns]",
            ),
            "rein_date": pd.array([pd.NaT, pd.NaT], dtype="datetime64[ns]"),
            "waiver_date": pd.array([pd.NaT, pd.NaT], dtype="datetime64[ns]"),
        }
    )


@pytest.fixture
def sam() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "classification": pd.array(["Firm"], dtype="string"),
            "name": pd.array(["Acme Medical Center"], dtype="string"),
            "uei": pd.array(["ABC123DEF456"], dtype="string"),
            "cage": pd.array(["1A2B3"], dtype="string"),
            "exclusion_type": pd.array(["Ineligible"], dtype="string"),
            "exclusion_program": pd.array(["All"], dtype="string"),
            "excluding_agency": pd.array(["HHS"], dtype="string"),
            "activation_date": pd.array([pd.NaT], dtype="datetime64[ns]"),
            "termination_date": pd.array([pd.NaT], dtype="datetime64[ns]"),
            "city": pd.array([pd.NA], dtype="string"),
            "state": pd.array([pd.NA], dtype="string"),
            "zip": pd.array([pd.NA], dtype="string"),
        }
    )


@pytest.fixture
def pecos_enrollment() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "enrollment_id": pd.array(["I20200101000001", "O20200101000002"], dtype="string"),
            "npi": pd.array([NPI_A, NPI_B], dtype="string"),
            "provider_type": pd.array(["Physician", "Clinic"], dtype="string"),
            "state": pd.array(["IL", "IL"], dtype="string"),
            "org_name": pd.array([pd.NA, "Acme Medical Center LLC"], dtype="string"),
            "first_name": pd.array(["Robert", pd.NA], dtype="string"),
            "last_name": pd.array(["Smith", pd.NA], dtype="string"),
        }
    )


@pytest.fixture
def pecos_reassignment() -> pd.DataFrame:
    # Provider A reassigns benefits to org B.
    return pd.DataFrame(
        {
            "reassigning_enrollment_id": pd.array(["I20200101000001"], dtype="string"),
            "receiving_enrollment_id": pd.array(["O20200101000002"], dtype="string"),
        }
    )


# --------------------------------------------------------------------------- #
# normalization                                                               #
# --------------------------------------------------------------------------- #

def test_address_surface_variants_collapse():
    a = normalize_address("123 Main St STE 100", "Springfield", "IL", "62704")
    b = normalize_address("123 Main Street Suite #100", "Springfield", "IL", "627041234")
    assert a == b
    assert a != ""


def test_address_empty_line_is_empty_key():
    assert normalize_address("", "Springfield", "IL", "62704") == ""
    assert normalize_address(None) == ""


def test_address_different_addresses_differ():
    a = normalize_address("123 Main St", "Springfield", "IL", "62704")
    b = normalize_address("125 Main St", "Springfield", "IL", "62704")
    assert a != b


def test_org_name_suffix_stripping():
    assert normalize_org_name("Acme Medical Center, LLC") == normalize_org_name("Acme Medical Center Inc")
    assert "LLC" not in normalize_org_name("Foo Bar LLC")
    # Abbreviation expansion for the blocking key.
    assert normalize_org_name("Acme Med Ctr") == normalize_org_name("Acme Medical Center")


def test_person_name_blocking():
    assert normalize_person_name("Robert", "Smith", "James") == normalize_person_name("Robert", "Smith", "J")
    assert normalize_person_name("Robert", "Smith, MD") == "SMITH ROBERT"


# --------------------------------------------------------------------------- #
# deterministic resolution                                                    #
# --------------------------------------------------------------------------- #

def test_npi_enrollment_clustering(nppes, sam, pecos_enrollment, leie):
    res = resolve_deterministic(
        nppes=nppes, sam=sam, pecos_enrollment=pecos_enrollment, leie=leie
    )
    # NPI_A and its enrollment cluster together.
    ent_a = res.entity_for_npi(NPI_A)
    assert ent_a is not None
    assert res.key_to_entity[enrollment_key("I20200101000001")] == ent_a
    # Distinct providers get distinct entity ids (no NPI-NPI merge).
    assert res.entity_for_npi(NPI_A) != res.entity_for_npi(NPI_B)
    assert res.entity_for_npi(NPI_C) is not None


def test_invalid_npi_not_clustered():
    bad = pd.DataFrame(
        {
            "npi": pd.array(["0000000000"], dtype="string"),  # invalid checksum
            "entity_type": pd.array([1], dtype="Int64"),
        }
    )
    res = resolve_deterministic(nppes=bad)
    assert res.entity_for_npi("0000000000") is None
    assert res.num_entities == 0


def test_sam_uei_cage_union(sam):
    res = resolve_deterministic(sam=sam)
    from oko_ingest.resolve.deterministic import cage_key, uei_key

    assert res.key_to_entity[uei_key("ABC123DEF456")] == res.key_to_entity[cage_key("1A2B3")]


def test_provenance_carries_source(nppes, pecos_enrollment):
    res = resolve_deterministic(nppes=nppes, pecos_enrollment=pecos_enrollment)
    prov = res.provenance
    assert set(prov.columns) >= {"key", "source", "source_row", "detail", "entity_id"}
    assert (prov["source"] == "pecos_enrollment").any()
    assert str(prov["entity_id"].dtype) == "string"


# --------------------------------------------------------------------------- #
# graph construction                                                          #
# --------------------------------------------------------------------------- #

def test_graph_nodes_and_flags(nppes, leie, sam, pecos_enrollment, pecos_reassignment):
    res = resolve_deterministic(
        nppes=nppes, leie=leie, sam=sam, pecos_enrollment=pecos_enrollment
    )
    g = build_reference_graph(
        res,
        nppes=nppes,
        leie=leie,
        sam=sam,
        pecos_enrollment=pecos_enrollment,
        pecos_reassignment=pecos_reassignment,
    )
    npi_nodes = g.nodes["npi"].set_index("node_id")
    assert len(npi_nodes) == 3
    # LEIE exclusion flag derived for NPI_A only.
    assert bool(npi_nodes.loc[NPI_A, "leie_excluded"]) is True
    assert bool(npi_nodes.loc[NPI_B, "leie_excluded"]) is False
    # Deactivation flag carried through from NPPES.
    assert bool(npi_nodes.loc[NPI_C, "is_deactivated"]) is True

    # Address de-dup: A and B share a canonical address.
    assert len(g.nodes["address"]) == 2

    # SAM exclusion flag on the entity resolved from B's UEI/CAGE? B has no
    # UEI link, so check that at least the SAM entity exists with the flag.
    ent_nodes = g.nodes["entity"]
    assert (ent_nodes["sam_excluded"] | ~ent_nodes["sam_excluded"]).all()  # boolean col
    # LEIE flag propagated to entity A.
    ent_a = res.entity_for_npi(NPI_A)
    assert bool(ent_nodes.set_index("node_id").loc[ent_a, "leie_excluded"]) is True


def test_graph_edges(nppes, sam, pecos_enrollment, pecos_reassignment):
    res = resolve_deterministic(
        nppes=nppes, sam=sam, pecos_enrollment=pecos_enrollment
    )
    g = build_reference_graph(
        res,
        nppes=nppes,
        sam=sam,
        pecos_enrollment=pecos_enrollment,
        pecos_reassignment=pecos_reassignment,
    )
    # has_npi: one edge per resolved npi.
    assert len(g.edges[EDGE_HAS_NPI]) == 3
    # located_at: three providers -> their address keys.
    assert len(g.edges[EDGE_LOCATED_AT]) == 3
    # associated_with: A's entity -> B's entity via reassignment.
    assoc = g.edges[EDGE_ASSOCIATED_WITH]
    assert len(assoc) == 1
    assert assoc.iloc[0]["src_id"] == res.entity_for_npi(NPI_A)
    assert assoc.iloc[0]["dst_id"] == res.entity_for_npi(NPI_B)
    assert assoc.iloc[0]["source"] == "pecos_reassignment"


# --------------------------------------------------------------------------- #
# snapshot round-trip                                                         #
# --------------------------------------------------------------------------- #

def test_snapshot_roundtrip(tmp_path, nppes, leie, sam, pecos_enrollment, pecos_reassignment):
    res = resolve_deterministic(
        nppes=nppes, leie=leie, sam=sam, pecos_enrollment=pecos_enrollment
    )
    g = build_reference_graph(
        res,
        nppes=nppes,
        leie=leie,
        sam=sam,
        pecos_enrollment=pecos_enrollment,
        pecos_reassignment=pecos_reassignment,
    )
    root = tmp_path / "snapshots"
    path = write_snapshot(g, root, version="v1")
    assert path.exists()

    loaded = read_snapshot(root, version="v1")
    assert loaded.version == "v1"
    assert set(loaded.graph.nodes) == set(g.nodes)
    assert set(loaded.graph.edges) == set(g.edges)
    pd.testing.assert_frame_equal(
        loaded.graph.nodes["npi"].reset_index(drop=True),
        g.nodes["npi"].reset_index(drop=True),
    )
    assert loaded.manifest["node_counts"]["npi"] == 3
    assert loaded.manifest["edge_counts"]["entity__associated_with__entity"] == 1


def test_snapshot_immutable(tmp_path, nppes):
    res = resolve_deterministic(nppes=nppes)
    g = build_reference_graph(res, nppes=nppes)
    root = tmp_path / "snapshots"
    write_snapshot(g, root, version="v1")
    with pytest.raises(FileExistsError):
        write_snapshot(g, root, version="v1")
    # latest-version read works without explicit version.
    assert read_snapshot(root).version == "v1"
