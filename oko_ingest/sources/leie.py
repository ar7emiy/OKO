"""OIG LEIE exclusion list: full UPDATED.csv plus monthly supplements.

OIG's own guidance is to re-download the full file monthly rather than
chain supplements, and this source follows it: `download()` fetches the
full file; `apply_supplements()` exists for mid-month refreshes between
full pulls.

Privacy gate (sourcing doc §1 #7): DOB and UPIN columns are dropped at
parse time and never staged.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from oko_ingest.fetch import PoliteFetcher
from oko_ingest.npi import is_valid_npi
from oko_ingest.sources.base import BulkSource, clean_str, pick_column, to_date

FULL_CSV_URL = "https://oig.hhs.gov/exclusions/downloadables/UPDATED.csv"

_FIELDS = {
    "last_name": ("LASTNAME",),
    "first_name": ("FIRSTNAME",),
    "mid_name": ("MIDNAME",),
    "bus_name": ("BUSNAME",),
    "general": ("GENERAL",),
    "specialty": ("SPECIALTY",),
    "npi": ("NPI",),
    "address": ("ADDRESS",),
    "city": ("CITY",),
    "state": ("STATE",),
    "zip": ("ZIP",),
    "excl_type": ("EXCLTYPE",),
}
_DATES = {
    "excl_date": ("EXCLDATE",),
    "rein_date": ("REINDATE",),
    "waiver_date": ("WAIVERDATE",),
}
_MATCH_KEYS = ["last_name", "first_name", "bus_name", "excl_date"]


def parse_leie_csv(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, dtype=str, low_memory=False)
    out = pd.DataFrame(index=raw.index)
    for field, candidates in _FIELDS.items():
        out[field] = clean_str(pick_column(raw, *candidates))
    for field, candidates in _DATES.items():
        out[field] = to_date(pick_column(raw, *candidates))
    # LEIE uses 0000000000 for "no NPI"; checksum-invalid values are noise.
    out["npi"] = out["npi"].where(out["npi"].map(is_valid_npi), None)
    return out.reset_index(drop=True)


def apply_supplements(
    full: pd.DataFrame,
    exclusion_supplements: list[pd.DataFrame] | None = None,
    reinstatement_supplements: list[pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Apply monthly supplement files to a full LEIE table.

    Exclusion supplements append new exclusion rows; reinstatement
    supplements set `rein_date` on existing rows, matched on
    (last_name, first_name, bus_name, excl_date).
    """
    current = full.copy()
    for supp in exclusion_supplements or []:
        current = pd.concat([current, supp], ignore_index=True)
        current = current.drop_duplicates(subset=_MATCH_KEYS, keep="last")
    for supp in reinstatement_supplements or []:
        rein = supp.dropna(subset=["rein_date"]).set_index(
            ["last_name", "first_name", "bus_name", "excl_date"]
        )["rein_date"]
        idx = current.set_index(_MATCH_KEYS).index
        updates = idx.map(rein.to_dict())
        current["rein_date"] = pd.Series(updates, index=current.index).fillna(
            current["rein_date"]
        )
    return current.reset_index(drop=True)


class LEIESource(BulkSource):
    name = "leie"
    tables = ("leie",)

    def download(self, fetcher: PoliteFetcher, dest_dir: Path) -> list[Path]:
        return [fetcher.download(FULL_CSV_URL, dest_dir / "UPDATED.csv")]

    def parse(self, files: list[Path]) -> dict[str, pd.DataFrame]:
        frames = [parse_leie_csv(p) for p in files]
        full, supplements = frames[0], frames[1:]
        return {"leie": apply_supplements(full, exclusion_supplements=supplements)}
