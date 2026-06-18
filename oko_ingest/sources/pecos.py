"""PECOS Medicare FFS public enrollment + reassignment-of-benefits edges.

Quarterly files on data.cms.gov. The reassignment sub-file (who bills under
whom, by enrollment ID) is the highest-value output: joined to enrollment
it yields provider→provider billing edges for the reference graph.

data.cms.gov serves dataset distributions through stable dataset pages; the
distribution UUIDs rotate per release, so `download()` resolves the current
CSV via the public DCAT catalog (data.json) by dataset title. Titles are
matched on whitespace-normalized, case-insensitive text (the live enrollment
title contains a double space).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from oko_ingest.fetch import PoliteFetcher
from oko_ingest.npi import is_valid_npi
from oko_ingest.sources.base import BulkSource, clean_str, pick_column, read_csv

# Standard DCAT catalog for the main data.cms.gov platform.
DCAT_CATALOG_URL = "https://data.cms.gov/data.json"
DATASET_TITLES = {
    "enrollment": "Medicare Fee-For-Service Public Provider Enrollment",
    "reassignment": "Revalidation Reassignment List",
}


def _norm_title(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _csv_download_url(item: dict) -> str | None:
    """First CSV distribution downloadURL for a DCAT dataset item."""
    for dist in item.get("distribution", []):
        url = dist.get("downloadURL") or dist.get("data", {}).get("downloadURL", "")
        media = (dist.get("mediaType") or "").lower()
        if media == "text/csv" or str(url).lower().endswith(".csv"):
            return url
    return None


def _looks_like_reassignment(df: pd.DataFrame) -> bool:
    cols = {c.strip().lower() for c in df.columns}
    # Real PECOS revalidation-reassignment files pair Individual↔Group
    # enrollment IDs; the older REASGN/RCV naming is kept as a fallback.
    if {"individual enrollment id", "group enrollment id"} <= cols:
        return True
    return any("reasgn" in c or "rcv" in c for c in cols)


class PECOSSource(BulkSource):
    name = "pecos"
    tables = ("pecos_enrollment", "pecos_reassignment")

    def download(self, fetcher: PoliteFetcher, dest_dir: Path) -> list[Path]:
        catalog = fetcher.get(DCAT_CATALOG_URL).json()
        datasets = catalog.get("dataset", catalog if isinstance(catalog, list) else [])
        by_title = {_norm_title(d.get("title", "")): d for d in datasets}
        paths = []
        for key, title in DATASET_TITLES.items():
            item = by_title.get(_norm_title(title))
            if item is None:
                raise RuntimeError(
                    f"Dataset '{title}' not found in {DCAT_CATALOG_URL}; "
                    "title may have changed — verify manually."
                )
            url = _csv_download_url(item)
            if not url:
                raise RuntimeError(f"No CSV distribution for dataset '{title}'.")
            paths.append(fetcher.download(url, dest_dir / f"pecos_{key}.csv"))
        return paths

    def parse(self, files: list[Path]) -> dict[str, pd.DataFrame]:
        enrollment_frames, reassignment_frames = [], []
        for path in files:
            raw = read_csv(path)
            if _looks_like_reassignment(raw):
                # Edge direction: an Individual provider reassigns benefits to
                # a Group org (the org bills on their behalf) → provider→org.
                out = pd.DataFrame(index=raw.index)
                out["reassigning_enrollment_id"] = clean_str(
                    pick_column(raw, "Individual Enrollment ID", "REASGN_BNFT_ENRLMT_ID")
                )
                out["receiving_enrollment_id"] = clean_str(
                    pick_column(raw, "Group Enrollment ID", "RCV_BNFT_ENRLMT_ID")
                )
                reassignment_frames.append(out.dropna())
            else:
                out = pd.DataFrame(index=raw.index)
                out["enrollment_id"] = clean_str(pick_column(raw, "ENRLMT_ID"))
                out["npi"] = clean_str(pick_column(raw, "NPI"))
                out["provider_type"] = clean_str(pick_column(raw, "PROVIDER_TYPE_DESC"))
                out["state"] = clean_str(pick_column(raw, "STATE_CD"))
                out["org_name"] = clean_str(pick_column(raw, "ORG_NAME"))
                out["first_name"] = clean_str(pick_column(raw, "FIRST_NAME"))
                out["last_name"] = clean_str(pick_column(raw, "LAST_NAME"))
                out = out.dropna(subset=["enrollment_id", "npi"])
                out = out[out["npi"].map(is_valid_npi)]
                enrollment_frames.append(out)

        result: dict[str, pd.DataFrame] = {}
        if enrollment_frames:
            result["pecos_enrollment"] = pd.concat(
                enrollment_frames, ignore_index=True
            )
        if reassignment_frames:
            result["pecos_reassignment"] = pd.concat(
                reassignment_frames, ignore_index=True
            )
        if not result:
            raise ValueError("No recognizable PECOS files among inputs.")
        return result
