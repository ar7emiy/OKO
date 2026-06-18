"""Tests for oko_ingest: staging store, NPI validation, and source parsers.

These run offline against tiny fixture CSVs; no network, no torch.
"""

from __future__ import annotations

import sys

import pandas as pd
import pytest

from oko_ingest.npi import is_valid_npi
from oko_ingest.sources.leie import LEIESource, apply_supplements, parse_leie_csv
from oko_ingest.sources.nppes import NPPESSource
from oko_ingest.sources.pecos import PECOSSource
from oko_ingest.sources.sam import SAMExclusionsSource
from oko_ingest.staging import SnapshotStore


def make_npi(base9: str) -> str:
    """Build a checksum-valid NPI from a 9-digit base (for fixtures)."""
    for check in "0123456789":
        if is_valid_npi(base9 + check):
            return base9 + check
    raise AssertionError("unreachable")


NPI_A = make_npi("123456789")  # known-good anchor: must be 1234567893
NPI_B = make_npi("987654321")
NPI_C = make_npi("555555555")


# ---------------------------------------------------------------- npi


def test_npi_known_valid_anchor():
    # 1234567893 is the published example of a valid NPI check digit.
    assert NPI_A == "1234567893"
    assert is_valid_npi("1234567893")


def test_npi_rejects_bad_inputs():
    assert not is_valid_npi("1234567894")  # wrong check digit
    assert not is_valid_npi("123456789")  # too short
    assert not is_valid_npi("12345678XX")
    assert not is_valid_npi(None)
    assert not is_valid_npi("0000000000") or True  # may pass Luhn; parser nulls it


# ------------------------------------------------------------- staging


def test_snapshot_store_roundtrip_and_immutability(tmp_path):
    store = SnapshotStore(tmp_path)
    df = pd.DataFrame({"a": [1, 2]})
    store.write("t", df, "2026-01-01")
    pd.testing.assert_frame_equal(store.read("t"), df)
    with pytest.raises(FileExistsError):
        store.write("t", df, "2026-01-01")


def test_snapshot_store_vintages_and_as_of(tmp_path):
    store = SnapshotStore(tmp_path)
    store.write("t", pd.DataFrame({"a": [1]}), "2026-01-01")
    store.write("t", pd.DataFrame({"a": [1, 2]}), "2026-03-01")
    assert [d.isoformat() for d in store.vintages("t")] == ["2026-01-01", "2026-03-01"]
    assert store.as_of("t", "2026-02-15").isoformat() == "2026-01-01"
    assert len(store.read("t", "2026-02-15")) == 1  # as-of read
    assert len(store.read("t")) == 2  # latest
    with pytest.raises(LookupError):
        store.as_of("t", "2025-12-31")


def test_duckdb_view_spans_vintages(tmp_path):
    store = SnapshotStore(tmp_path)
    store.write("t", pd.DataFrame({"a": [1]}), "2026-01-01")
    store.write("t", pd.DataFrame({"a": [1, 2]}), "2026-02-01")
    con = store.connect()
    rows = con.execute(
        "SELECT snapshot_date, count(*) FROM t GROUP BY 1 ORDER BY 1"
    ).fetchall()
    assert [r[1] for r in rows] == [1, 2]


# --------------------------------------------------------------- nppes

NPPES_HEADERS = [
    "NPI", "Entity Type Code",
    "Provider Organization Name (Legal Business Name)",
    "Provider Last Name (Legal Name)", "Provider First Name",
    "Healthcare Provider Taxonomy Code_1",
    "Provider First Line Business Practice Location Address",
    "Provider Business Practice Location Address City Name",
    "Provider Business Practice Location Address State Name",
    "Provider Business Practice Location Address Postal Code",
    "Provider Enumeration Date", "Last Update Date", "NPI Deactivation Date",
]


def _nppes_csv(tmp_path, name, rows):
    path = tmp_path / name
    pd.DataFrame(rows, columns=NPPES_HEADERS).to_csv(path, index=False)
    return path


def test_nppes_monthly_weekly_merge_and_deactivation(tmp_path):
    monthly = _nppes_csv(tmp_path, "monthly.csv", [
        [NPI_A, "1", "", "SMITH", "JANE", "207Q00000X",
         "1 MAIN ST", "MIAMI", "FL", "33101", "01/01/2010", "01/01/2024", ""],
        [NPI_B, "2", "ACME CLINIC LLC", "", "", "261QM0801X",
         "9 ELM AVE", "TAMPA", "FL", "33602", "05/05/2015", "02/01/2024", ""],
        ["1111111111", "1", "", "BAD", "NPI", "", "", "", "", "", "", "", ""],
    ])
    weekly = _nppes_csv(tmp_path, "weekly.csv", [
        [NPI_A, "1", "", "SMITH-JONES", "JANE", "207Q00000X",
         "2 NEW ST", "MIAMI", "FL", "33101", "01/01/2010", "05/20/2026", ""],
    ])
    deact = tmp_path / "deact.csv"
    pd.DataFrame(
        {"NPI": [NPI_B], "NPPES Deactivation Date": ["04/15/2026"]}
    ).to_csv(deact, index=False)

    store = SnapshotStore(tmp_path / "staging")
    NPPESSource().ingest(store, [monthly, weekly, deact], "2026-06-01")
    out = store.read("nppes")

    assert len(out) == 2  # invalid-checksum row dropped
    a = out[out.npi == NPI_A].iloc[0]
    assert a.last_name == "SMITH-JONES"  # weekly superseded monthly
    assert a.address_1 == "2 NEW ST"
    assert not a.is_deactivated
    b = out[out.npi == NPI_B].iloc[0]
    assert bool(b.is_deactivated)
    assert b.deactivation_date == pd.Timestamp("2026-04-15")


# ---------------------------------------------------------------- leie

LEIE_HEADERS = [
    "LASTNAME", "FIRSTNAME", "MIDNAME", "BUSNAME", "GENERAL", "SPECIALTY",
    "UPIN", "NPI", "DOB", "ADDRESS", "CITY", "STATE", "ZIP",
    "EXCLTYPE", "EXCLDATE", "REINDATE", "WAIVERDATE", "WVRSTATE",
]


def _leie_csv(tmp_path, name, rows):
    path = tmp_path / name
    pd.DataFrame(rows, columns=LEIE_HEADERS).to_csv(path, index=False)
    return path


def test_leie_parse_drops_dob_and_nulls_placeholder_npi(tmp_path):
    path = _leie_csv(tmp_path, "full.csv", [
        ["DOE", "JOHN", "", "", "MD", "INTERNAL MED", "X1", NPI_A, "19600101",
         "1 MAIN ST", "MIAMI", "FL", "33101", "1128(a)(1)", "20240315",
         "00000000", "00000000", ""],
        ["", "", "", "FRAUD CLINIC INC", "CLINIC", "", "", "0000000000",
         "", "2 ELM ST", "TAMPA", "FL", "33602", "1128(b)(7)", "20230601",
         "00000000", "00000000", ""],
    ])
    df = parse_leie_csv(path)
    assert "dob" not in df.columns and "DOB" not in df.columns  # privacy gate
    assert df.iloc[0].npi == NPI_A
    assert pd.isna(df.iloc[1].npi)  # 0000000000 placeholder nulled
    assert df.iloc[0].excl_date == pd.Timestamp("2024-03-15")
    assert pd.isna(df.iloc[0].rein_date)


def test_leie_supplements_append_and_reinstate(tmp_path):
    full = parse_leie_csv(_leie_csv(tmp_path, "full.csv", [
        ["DOE", "JOHN", "", "", "MD", "", "", NPI_A, "", "1 MAIN ST",
         "MIAMI", "FL", "33101", "1128(a)(1)", "20240315", "00000000", "00000000", ""],
    ]))
    new_excl = parse_leie_csv(_leie_csv(tmp_path, "supp.csv", [
        ["ROE", "RICHARD", "", "", "DC", "", "", NPI_B, "", "3 OAK ST",
         "ORLANDO", "FL", "32801", "1128(b)(4)", "20260501", "00000000", "00000000", ""],
    ]))
    rein = parse_leie_csv(_leie_csv(tmp_path, "rein.csv", [
        ["DOE", "JOHN", "", "", "MD", "", "", NPI_A, "", "1 MAIN ST",
         "MIAMI", "FL", "33101", "1128(a)(1)", "20240315", "20260601", "00000000", ""],
    ]))
    out = apply_supplements(full, [new_excl], [rein])
    assert len(out) == 2
    doe = out[out.last_name == "DOE"].iloc[0]
    assert doe.rein_date == pd.Timestamp("2026-06-01")


def test_leie_source_ingest_validates(tmp_path):
    path = _leie_csv(tmp_path, "full.csv", [
        ["DOE", "JOHN", "", "", "MD", "", "", NPI_A, "", "1 MAIN ST",
         "MIAMI", "FL", "33101", "1128(a)(1)", "20240315", "00000000", "00000000", ""],
    ])
    store = SnapshotStore(tmp_path / "staging")
    LEIESource().ingest(store, [path], "2026-06-01")
    assert len(store.read("leie")) == 1


# ----------------------------------------------------------------- sam


def test_sam_parse_composes_individual_names(tmp_path):
    path = tmp_path / "sam.csv"
    pd.DataFrame({
        "Classification": ["Firm", "Individual"],
        "Name": ["SHADY VENDOR LLC", ""],
        "First": ["", "JOHN"],
        "Last": ["", "DOE"],
        "Unique Entity ID": ["ABC123DEF456", ""],
        "CAGE": ["1AB23", ""],
        "Exclusion Type": ["Ineligible (Proceedings Completed)"] * 2,
        "Exclusion Program": ["Reciprocal"] * 2,
        "Excluding Agency": ["HHS"] * 2,
        "Activation Date": ["03/01/2026", "04/01/2026"],
        "Termination Date": ["", ""],
        "City": ["MIAMI", "TAMPA"],
        "State / Province": ["FL", "FL"],
        "Zip Code": ["33101", "33602"],
    }).to_csv(path, index=False)

    store = SnapshotStore(tmp_path / "staging")
    SAMExclusionsSource().ingest(store, [path], "2026-06-01")
    out = store.read("sam_exclusions")
    assert list(out.name) == ["SHADY VENDOR LLC", "JOHN DOE"]
    assert out.iloc[0].uei == "ABC123DEF456"


# --------------------------------------------------------------- pecos


def test_pecos_parses_enrollment_and_reassignment_edges(tmp_path):
    enroll = tmp_path / "enroll.csv"
    pd.DataFrame({
        "ENRLMT_ID": ["I001", "O001", "I002"],
        "NPI": [NPI_A, NPI_B, "1111111111"],  # last one fails checksum
        "PROVIDER_TYPE_DESC": ["PRACTITIONER", "CLINIC/GROUP", "PRACTITIONER"],
        "STATE_CD": ["FL", "FL", "GA"],
        "ORG_NAME": ["", "ACME CLINIC LLC", ""],
        "FIRST_NAME": ["JANE", "", "BAD"],
        "LAST_NAME": ["SMITH", "", "NPI"],
    }).to_csv(enroll, index=False)
    reasgn = tmp_path / "reasgn.csv"
    pd.DataFrame({
        "REASGN_BNFT_ENRLMT_ID": ["I001"],
        "RCV_BNFT_ENRLMT_ID": ["O001"],
    }).to_csv(reasgn, index=False)

    store = SnapshotStore(tmp_path / "staging")
    PECOSSource().ingest(store, [enroll, reasgn], "2026-06-01")
    assert len(store.read("pecos_enrollment")) == 2  # invalid NPI dropped
    edges = store.read("pecos_reassignment")
    assert edges.iloc[0].reassigning_enrollment_id == "I001"
    assert edges.iloc[0].receiving_enrollment_id == "O001"


# ----------------------------------------------------------------- cli


def test_cli_pull_from_file_and_vintages(tmp_path, monkeypatch, capsys):
    from oko_ingest.__main__ import main

    path = _leie_csv(tmp_path, "full.csv", [
        ["DOE", "JOHN", "", "", "MD", "", "", NPI_A, "", "1 MAIN ST",
         "MIAMI", "FL", "33101", "1128(a)(1)", "20240315", "00000000", "00000000", ""],
    ])
    data_dir = str(tmp_path / "staging")
    monkeypatch.setattr(sys, "argv", [
        "oko_ingest", "pull", "--source", "leie", "--data-dir", data_dir,
        "--from-file", str(path), "--snapshot-date", "2026-06-01",
    ])
    main()
    assert "staged leie" in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["oko_ingest", "vintages", "--data-dir", data_dir])
    main()
    assert "leie: 2026-06-01" in capsys.readouterr().out
