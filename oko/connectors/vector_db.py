"""Vector DB connector — abstract interface and in-memory stub."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from oko.connectors.base import VectorDBConnector

if TYPE_CHECKING:
    from oko.config import ScoringConfig


class InMemoryVectorDBConnector(VectorDBConnector):
    """In-memory implementation backed by a dict of arrays.

    Parameters
    ----------
    config : ScoringConfig
    embeddings : dict mapping node_type -> dict mapping node_id -> 1-D array
    """

    def __init__(
        self,
        config: ScoringConfig,
        embeddings: dict[str, dict[str, np.ndarray]] | None = None,
    ) -> None:
        super().__init__(config)
        self._embeddings = embeddings or {}

    def fetch_embeddings(self, node_type: str, node_ids: list[str]) -> np.ndarray:
        dim = self.config.data.note_embedding_dim
        type_embs = self._embeddings.get(node_type, {})
        out = np.zeros((len(node_ids), dim), dtype=np.float32)
        for i, nid in enumerate(node_ids):
            if nid in type_embs:
                out[i] = type_embs[nid]
        return out
