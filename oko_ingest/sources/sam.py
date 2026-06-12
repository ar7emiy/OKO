"""SAM.gov exclusions: Public V2 extract (monthly full + daily deltas).

The extracts route is the practical bulk path (the query API is capped at
~1K requests/day for non-federal keys). Requires a free SAM.gov API key in
the SAM_API_KEY environment variable. Endpoint and layout were verified
only via search snapshots of open.gsa.gov (403 to automated fetches) —
confirm on first live run.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from oko_ingest.fetch import PoliteFetcher
from oko_ingest.sources.base import BulkSource, clean_str, pick_column, to_date

EXTRACT_URL = "https://api.sam.gov/data-services/v1/extracts"


def _compose_name(raw: pd.DataFrame) -> pd.Series:
    """Entity rows carry Name; individual rows carry First/Last."""
    name = clean_str(pick_column(raw, "Name"))
    first = clean_str(pick_column(raw, "First"))
    last = clean_str(pick_column(raw, "Last"))
    composed = (first.fillna("") + " " + last.fillna("")).str.strip()
    return name.fillna(composed.where(composed != ""))


class SAMExclusionsSource(BulkSource):
    name = "sam"
    tables = ("sam_exclusions",)

    def download(self, fetcher: PoliteFetcher, dest_dir: Path) -> list[Path]:
        api_key = os.environ.get("SAM_API_KEY")
        if not api_key:
            raise RuntimeError(
                "SAM_API_KEY not set. Register a free SAM.gov account, request an "
                "API key, and export SAM_API_KEY before pulling this source."
            )
        dest = dest_dir / "sam_exclusions_extract.zip"
        return [
            fetcher.download(
                EXTRACT_URL,
                dest,
                params={"api_key": api_key, "fileType": "EXCLUSION"},
            )
        ]

    def parse(self, files: list[Path]) -> dict[str, pd.DataFrame]:
        frames = []
        for path in files:
            raw = pd.read_csv(path, dtype=str, low_memory=False)
            out = pd.DataFrame(index=raw.index)
            out["classification"] = clean_str(pick_column(raw, "Classification"))
            out["name"] = _compose_name(raw)
            out["uei"] = clean_str(pick_column(raw, "Unique Entity ID", "UEI"))
            out["cage"] = clean_str(pick_column(raw, "CAGE"))
            out["exclusion_type"] = clean_str(pick_column(raw, "Exclusion Type"))
            out["exclusion_program"] = clean_str(pick_column(raw, "Exclusion Program"))
            out["excluding_agency"] = clean_str(pick_column(raw, "Excluding Agency"))
            out["activation_date"] = to_date(
                pick_column(raw, "Activation Date", "Active Date")
            )
            out["termination_date"] = to_date(pick_column(raw, "Termination Date"))
            out["city"] = clean_str(pick_column(raw, "City"))
            out["state"] = clean_str(pick_column(raw, "State / Province", "State"))
            out["zip"] = clean_str(pick_column(raw, "Zip Code", "Zip"))
            frames.append(out)
        merged = pd.concat(frames, ignore_index=True).dropna(subset=["name"])
        return {"sam_exclusions": merged.reset_index(drop=True)}
