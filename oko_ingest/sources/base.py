"""Base class and parsing helpers shared by all bulk sources."""

from __future__ import annotations

import datetime as dt
import logging
from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd

from oko_ingest.fetch import PoliteFetcher
from oko_ingest.schemas import validate
from oko_ingest.staging import SnapshotStore

logger = logging.getLogger(__name__)


def read_csv(path_or_buffer, **kwargs):
    """Read a government CSV robustly.

    CMS/OIG files are commonly Windows-1252/Latin-1, not UTF-8 (stray bytes
    like 0xA0 break a UTF-8 read). Try UTF-8, then cp1252, then Latin-1 —
    the last is byte-lossless and never raises. Defaults to all-string dtype.
    """
    kwargs.setdefault("dtype", str)
    kwargs.setdefault("low_memory", False)
    if "encoding" in kwargs:  # caller forced one (e.g. chunked reads)
        return pd.read_csv(path_or_buffer, **kwargs)
    for enc in ("utf-8", "cp1252"):
        try:
            return pd.read_csv(path_or_buffer, encoding=enc, **kwargs)
        except UnicodeDecodeError:
            if hasattr(path_or_buffer, "seek"):
                path_or_buffer.seek(0)
    return pd.read_csv(path_or_buffer, encoding="latin-1", **kwargs)


class BulkSource(ABC):
    """A Tier-1 bulk dataset: download raw files, parse to staged tables.

    Live download URLs were research-verified against official pages but
    several .gov hosts block automated verification — every source keeps its
    URLs in overridable class attributes so the first live run can correct
    them without code changes (`--url` in the CLI).
    """

    name: str
    tables: tuple[str, ...]

    @abstractmethod
    def download(self, fetcher: PoliteFetcher, dest_dir: Path) -> list[Path]:
        """Fetch the raw file(s) for the current vintage into dest_dir."""

    @abstractmethod
    def parse(self, files: list[Path]) -> dict[str, pd.DataFrame]:
        """Parse raw file(s) into staged-table DataFrames keyed by table name."""

    def ingest(
        self,
        store: SnapshotStore,
        files: list[Path],
        snapshot_date: str | dt.date | None = None,
    ) -> dict[str, Path]:
        """Parse, validate, and write one snapshot per produced table."""
        date = snapshot_date or dt.date.today()
        written = {}
        for table, df in self.parse(files).items():
            df = validate(table, df)
            written[table] = store.write(table, df, date)
            logger.info("Staged %s@%s: %d rows", table, date, len(df))
        return written


def pick_column(df: pd.DataFrame, *candidates: str) -> pd.Series:
    """Return the first matching column (case/space-insensitive), else NA.

    Bulk-file headers drift between vintages; parsers declare candidate
    names rather than hard-coding one header.
    """
    normalized = {c.strip().lower(): c for c in df.columns}
    for cand in candidates:
        col = normalized.get(cand.strip().lower())
        if col is not None:
            return df[col]
    return pd.Series(pd.NA, index=df.index, dtype="object")


def to_date(series: pd.Series) -> pd.Series:
    """Parse mixed-format date strings to datetime64, NaT on failure.

    Handles the two formats seen across these files: MM/DD/YYYY (NPPES,
    PECOS, SAM) and YYYYMMDD (LEIE).
    """
    s = series.astype("string").str.strip().replace({"": pd.NA, "0": pd.NA})
    parsed = pd.to_datetime(s, format="%m/%d/%Y", errors="coerce")
    yyyymmdd = pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    return parsed.fillna(yyyymmdd)


def clean_str(series: pd.Series) -> pd.Series:
    """Strip whitespace; collapse empties to real NA; "string" dtype."""
    s = series.astype("string").str.strip()
    return s.where(s.notna() & (s != ""), pd.NA)
