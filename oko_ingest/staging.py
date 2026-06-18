"""Snapshot-dated Parquet staging store with DuckDB query access.

Layout (append-only; snapshots are immutable once written):

    <root>/<table>/snapshot_date=YYYY-MM-DD/data.parquet

Vintage retention is a hard requirement (docs/data-sourcing-engine.md §6 M1):
as-of reconstruction backs the Track-A temporal backtest, so snapshots are
never overwritten or deleted by this module.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import duckdb
import pandas as pd

_DATE_RE = re.compile(r"^snapshot_date=(\d{4}-\d{2}-\d{2})$")


def _parse_date(value: str | dt.date) -> dt.date:
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(value)


class SnapshotStore:
    """Append-only store of snapshot-dated Parquet tables."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _partition_dir(self, table: str, snapshot_date: dt.date) -> Path:
        return self.root / table / f"snapshot_date={snapshot_date.isoformat()}"

    def write(
        self,
        table: str,
        df: pd.DataFrame,
        snapshot_date: str | dt.date,
        overwrite: bool = False,
    ) -> Path:
        """Write one immutable snapshot partition. Refuses to overwrite."""
        date = _parse_date(snapshot_date)
        part = self._partition_dir(table, date)
        target = part / "data.parquet"
        if target.exists() and not overwrite:
            raise FileExistsError(
                f"Snapshot {table}@{date} already exists; snapshots are immutable "
                f"(pass overwrite=True only to repair a corrupt partition)."
            )
        part.mkdir(parents=True, exist_ok=True)
        tmp = part / ".data.parquet.tmp"
        df.to_parquet(tmp, index=False)
        tmp.replace(target)
        return target

    def vintages(self, table: str) -> list[dt.date]:
        """All snapshot dates available for a table, ascending."""
        tdir = self.root / table
        if not tdir.is_dir():
            return []
        dates = []
        for child in tdir.iterdir():
            m = _DATE_RE.match(child.name)
            if m and (child / "data.parquet").exists():
                dates.append(dt.date.fromisoformat(m.group(1)))
        return sorted(dates)

    def as_of(self, table: str, date: str | dt.date) -> dt.date:
        """Resolve the latest snapshot date <= the given date."""
        target = _parse_date(date)
        eligible = [d for d in self.vintages(table) if d <= target]
        if not eligible:
            raise LookupError(f"No snapshot of '{table}' on or before {target}.")
        return eligible[-1]

    def read(self, table: str, snapshot_date: str | dt.date | None = None) -> pd.DataFrame:
        """Read one snapshot (default: latest)."""
        if snapshot_date is None:
            vintages = self.vintages(table)
            if not vintages:
                raise LookupError(f"No snapshots of '{table}'.")
            date = vintages[-1]
        else:
            date = self.as_of(table, snapshot_date)
        return pd.read_parquet(self._partition_dir(table, date) / "data.parquet")

    def connect(self) -> duckdb.DuckDBPyConnection:
        """DuckDB connection with one view per table across all vintages.

        Each view exposes the hive `snapshot_date` partition column so
        queries can select or diff vintages.
        """
        con = duckdb.connect()
        for tdir in sorted(self.root.iterdir()) if self.root.is_dir() else []:
            if tdir.is_dir() and self.vintages(tdir.name):
                pattern = str(tdir / "snapshot_date=*" / "data.parquet")
                con.execute(
                    f'CREATE VIEW "{tdir.name}" AS '
                    f"SELECT * FROM read_parquet('{pattern}', hive_partitioning=true)"
                )
        return con
