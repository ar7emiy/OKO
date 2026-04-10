"""Label store connector — abstract interface and in-memory stub."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from oko.connectors.base import LabelStoreConnector

if TYPE_CHECKING:
    from oko.config import ScoringConfig


class InMemoryLabelStoreConnector(LabelStoreConnector):
    """In-memory implementation backed by a Series and optional weights.

    Parameters
    ----------
    config : ScoringConfig
    labels : Series mapping node_id -> label (0/1/NaN)
    sample_weights : Series mapping node_id -> weight (default 1.0)
    """

    def __init__(
        self,
        config: ScoringConfig,
        labels: pd.Series | None = None,
        sample_weights: pd.Series | None = None,
    ) -> None:
        super().__init__(config)
        self._labels = labels if labels is not None else pd.Series(dtype=float)
        self._weights = sample_weights if sample_weights is not None else pd.Series(dtype=float)

    def fetch_labels(self, node_ids: list[str]) -> pd.Series:
        return self._labels.reindex(node_ids)

    def fetch_sample_weights(self, node_ids: list[str]) -> pd.Series:
        return self._weights.reindex(node_ids).fillna(1.0)
