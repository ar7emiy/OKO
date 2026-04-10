"""Structured data connector — abstract interface and in-memory stub."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from oko.connectors.base import StructuredDataConnector

if TYPE_CHECKING:
    from oko.config import ScoringConfig


class InMemoryStructuredDataConnector(StructuredDataConnector):
    """In-memory implementation backed by a dict of DataFrames.

    Parameters
    ----------
    config : ScoringConfig
    features : dict mapping node_type -> DataFrame indexed by node_id
    """

    def __init__(
        self,
        config: ScoringConfig,
        features: dict[str, pd.DataFrame] | None = None,
    ) -> None:
        super().__init__(config)
        self._features = features or {}

    def fetch_features(self, node_type: str, node_ids: list[str]) -> pd.DataFrame:
        df = self._features.get(node_type, pd.DataFrame())
        if df.empty:
            return pd.DataFrame(index=node_ids)
        return df.reindex(node_ids).fillna(0.0)
