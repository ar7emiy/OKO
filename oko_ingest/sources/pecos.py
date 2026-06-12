"""PECOS Medicare FFS public enrollment + reassignment-of-benefits edges.

Quarterly files on data.cms.gov. The reassignment sub-file (who bills under
whom, by enrollment ID) is the highest-value output: joined to enrollment
it yields provider→provider billing edges for the reference graph.

data.cms.gov serves dataset distributions through stable dataset pages; the
distribution UUIDs rotate per release, so `download()` resolves them via
the public metastore API by dataset title — verify titles on first live run.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from oko_ingest.fetch import PoliteFetcher
from oko_ingest.npi import is_valid_npi
from oko_ingest.sources.base import BulkSource, clean_str, pick_column

METASTORE_URL = "https://data.cms.gov/api/1/metastore/schemas/dataset/items"
DATASET_TITLES = {
    "enrollment": "Medicare Fee-For-Service  Public Provider Enrollment",
    "reassignment": "Revalidation Reassignment List",
}


def _looks_like_reassignment(df: pd.DataFrame) -> bool:
    cols = {c.strip().lower() for c in df.columns}
    return any("reasgn" in c or "rcv" in c for c in cols)


class PECOSSource(BulkSource):
    name = "pecos"
    tables = ("pecos_enrollment", "pecos_reassignment")

    def download(self, fetcher: PoliteFetcher, dest_dir: Path) -> list[Path]:
        items = fetcher.get(METASTORE_URL).json()
        by_title = {item.get("title", "").strip(): item for item in items}
        paths = []
        for key, title in DATASET_TITLES.items():
            item = by_title.get(title)
            if item is None:
                raise RuntimeError(
                    f"Dataset titled '{title}' not found in data.cms.gov metastore; "
                    "title may have changed — verify manually."
                )
            dist = item["distribution"][0]
            url = dist.get("downloadURL") or dist.get("data", {}).get("downloadURL")
            paths.append(fetcher.download(url, dest_dir / f"pecos_{key}.csv"))
        return paths

    def parse(self, files: list[Path]) -> dict[str, pd.DataFrame]:
        enrollment_frames, reassignment_frames = [], []
        for path in files:
            raw = pd.read_csv(path, dtype=str, low_memory=False)
            if _looks_like_reassignment(raw):
                out = pd.DataFrame(index=raw.index)
                out["reassigning_enrollment_id"] = clean_str(
                    pick_column(raw, "REASGN_BNFT_ENRLMT_ID")
                )
                out["receiving_enrollment_id"] = clean_str(
                    pick_column(raw, "RCV_BNFT_ENRLMT_ID")
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
