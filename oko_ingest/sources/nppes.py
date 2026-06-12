"""NPPES NPI registry: monthly full replacement + weekly incrementals.

Files ship as ZIPs from https://download.cms.gov/nppes/NPI_Files.html; this
source discovers current file links from that index page. V2 file format
only (V1 retired 2026-03-03). The deactivation file is a separate member of
the monthly ZIP.

Current-state semantics: the monthly full file is the base; weekly
incremental rows (same format) supersede by NPI; the deactivation file
overlays deactivation dates. `parse()` accepts the monthly CSV plus any
number of weekly CSVs and an optional deactivation CSV, in that spirit —
callers pass extracted CSVs, not ZIPs.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

from oko_ingest.fetch import PoliteFetcher
from oko_ingest.npi import is_valid_npi
from oko_ingest.sources.base import BulkSource, clean_str, pick_column, to_date

logger = logging.getLogger(__name__)

INDEX_URL = "https://download.cms.gov/nppes/NPI_Files.html"
_ZIP_LINK_RE = re.compile(r"NPPES_Data_Dissemination[^\"']*V2\.zip", re.IGNORECASE)

# Official V2 headers (candidates tolerate vintage drift).
_COLS = {
    "npi": ("NPI",),
    "entity_type": ("Entity Type Code",),
    "org_name": ("Provider Organization Name (Legal Business Name)",),
    "last_name": ("Provider Last Name (Legal Name)",),
    "first_name": ("Provider First Name",),
    "taxonomy_code": ("Healthcare Provider Taxonomy Code_1",),
    "address_1": ("Provider First Line Business Practice Location Address",),
    "city": ("Provider Business Practice Location Address City Name",),
    "state": ("Provider Business Practice Location Address State Name",),
    "zip": ("Provider Business Practice Location Address Postal Code",),
    "enumeration_date": ("Provider Enumeration Date",),
    "last_update_date": ("Last Update Date",),
    "deactivation_date": ("NPI Deactivation Date",),
}


def _is_deactivation_file(df: pd.DataFrame) -> bool:
    cols = {c.strip().lower() for c in df.columns}
    return "nppes deactivation date" in cols and len(cols) <= 3


def _parse_main(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["npi"] = clean_str(pick_column(df, *_COLS["npi"]))
    out["entity_type"] = pd.to_numeric(
        pick_column(df, *_COLS["entity_type"]), errors="coerce"
    ).astype("Int64")
    for field in ("org_name", "last_name", "first_name", "taxonomy_code",
                  "address_1", "city", "state", "zip"):
        out[field] = clean_str(pick_column(df, *_COLS[field]))
    for field in ("enumeration_date", "last_update_date", "deactivation_date"):
        out[field] = to_date(pick_column(df, *_COLS[field]))

    invalid = ~out["npi"].map(is_valid_npi)
    if invalid.any():
        logger.warning("Dropping %d rows with invalid NPI checksum", int(invalid.sum()))
        out = out[~invalid]
    return out


class NPPESSource(BulkSource):
    name = "nppes"
    tables = ("nppes",)

    def download(self, fetcher: PoliteFetcher, dest_dir: Path) -> list[Path]:
        index = fetcher.get(INDEX_URL).text
        links = sorted(set(_ZIP_LINK_RE.findall(index)))
        if not links:
            raise RuntimeError(
                f"No V2 dissemination ZIP links found on {INDEX_URL}; "
                "the index layout may have changed — verify manually."
            )
        paths = []
        for link in links:
            url = link if link.startswith("http") else f"https://download.cms.gov/nppes/{link}"
            paths.append(fetcher.download(url, dest_dir / Path(link).name))
        return paths

    def parse(self, files: list[Path]) -> dict[str, pd.DataFrame]:
        mains: list[pd.DataFrame] = []
        deactivations: list[pd.DataFrame] = []
        for path in files:
            raw = pd.read_csv(path, dtype=str, low_memory=False)
            if _is_deactivation_file(raw):
                deactivations.append(raw)
            else:
                mains.append(_parse_main(raw))
        if not mains:
            raise ValueError("NPPES parse requires at least one main (monthly/weekly) CSV.")

        # Later files supersede earlier ones per NPI: pass the monthly full
        # file first, then weekly incrementals in chronological order.
        current = pd.concat(mains, ignore_index=True)
        current = current.drop_duplicates(subset="npi", keep="last")

        for deact in deactivations:
            d = pd.DataFrame(
                {
                    "npi": clean_str(pick_column(deact, "NPI")),
                    "deactivation_date": to_date(
                        pick_column(deact, "NPPES Deactivation Date")
                    ),
                }
            ).dropna(subset=["npi"])
            overlay = current["npi"].map(
                d.set_index("npi")["deactivation_date"].to_dict()
            )
            current["deactivation_date"] = overlay.fillna(current["deactivation_date"])

        current["is_deactivated"] = current["deactivation_date"].notna()
        return {"nppes": current.reset_index(drop=True)}
