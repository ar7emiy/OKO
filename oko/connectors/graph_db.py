"""Graph DB connector — abstract interface and in-memory stub."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from oko.connectors.base import GraphDBConnector

if TYPE_CHECKING:
    from oko.config import ScoringConfig


class InMemoryGraphDBConnector(GraphDBConnector):
    """In-memory implementation backed by dicts of DataFrames.

    Parameters
    ----------
    config : ScoringConfig
    nodes : dict mapping node_type -> DataFrame (must have ``node_id`` column)
    edges : dict mapping (src_type, rel, dst_type) -> DataFrame
            (must have ``src_id``, ``dst_id`` columns)
    """

    def __init__(
        self,
        config: ScoringConfig,
        nodes: dict[str, pd.DataFrame] | None = None,
        edges: dict[tuple[str, str, str], pd.DataFrame] | None = None,
    ) -> None:
        super().__init__(config)
        self._nodes = nodes or {}
        self._edges = edges or {}

    def fetch_nodes(self, node_type: str) -> pd.DataFrame:
        return self._nodes.get(node_type, pd.DataFrame(columns=["node_id"]))

    def fetch_edges(self, edge_type: tuple[str, str, str]) -> pd.DataFrame:
        return self._edges.get(edge_type, pd.DataFrame(columns=["src_id", "dst_id"]))
