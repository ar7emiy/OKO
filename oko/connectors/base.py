"""Abstract base classes for all data source connectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from oko.config import ScoringConfig


class GraphDBConnector(ABC):
    """Interface for fetching nodes and edges from a graph database."""

    def __init__(self, config: ScoringConfig) -> None:
        self.config = config

    @abstractmethod
    def fetch_nodes(self, node_type: str) -> pd.DataFrame:
        """Return a DataFrame with columns: [node_id, ...type-specific attributes].

        The ``node_id`` column must contain unique string identifiers.
        Remaining columns are type-specific numeric attributes.
        """

    @abstractmethod
    def fetch_edges(self, edge_type: tuple[str, str, str]) -> pd.DataFrame:
        """Return a DataFrame with columns: [src_id, dst_id, ...edge attributes].

        ``src_id`` / ``dst_id`` are string node identifiers matching the
        ``node_id`` values returned by :meth:`fetch_nodes`.
        """


class VectorDBConnector(ABC):
    """Interface for fetching pre-computed embeddings (e.g. note embeddings)."""

    def __init__(self, config: ScoringConfig) -> None:
        self.config = config

    @abstractmethod
    def fetch_embeddings(self, node_type: str, node_ids: list[str]) -> np.ndarray:
        """Return an (N, embedding_dim) float array for the given node IDs.

        Rows must align 1-to-1 with *node_ids*.  If a node has no embedding
        the row should be all zeros.
        """


class StructuredDataConnector(ABC):
    """Interface for fetching structured / tabular features per node."""

    def __init__(self, config: ScoringConfig) -> None:
        self.config = config

    @abstractmethod
    def fetch_features(self, node_type: str, node_ids: list[str]) -> pd.DataFrame:
        """Return a DataFrame indexed by node_id with numeric feature columns.

        Rows must align 1-to-1 with *node_ids*.
        """


class LabelStoreConnector(ABC):
    """Interface for fetching fraud labels (SME decisions)."""

    def __init__(self, config: ScoringConfig) -> None:
        self.config = config

    @abstractmethod
    def fetch_labels(self, node_ids: list[str]) -> pd.Series:
        """Return a Series mapping node_id -> label.

        Labels: 1 = fraud, 0 = not fraud, NaN = unlabeled.
        Index must align with *node_ids*.
        """

    @abstractmethod
    def fetch_sample_weights(self, node_ids: list[str]) -> pd.Series:
        """Return a Series mapping node_id -> sample weight.

        Used for single-client downweighting.  Default weight is 1.0.
        """
