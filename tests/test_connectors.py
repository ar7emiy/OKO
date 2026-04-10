"""Tests for data source connectors."""

import numpy as np
import pandas as pd

from oko.config import ScoringConfig
from oko.connectors.graph_db import InMemoryGraphDBConnector
from oko.connectors.vector_db import InMemoryVectorDBConnector
from oko.connectors.structured import InMemoryStructuredDataConnector
from oko.connectors.label_store import InMemoryLabelStoreConnector


def test_graph_db_connector():
    config = ScoringConfig()
    nodes = {"claim": pd.DataFrame({"node_id": ["c1", "c2"], "amount": [100, 200]})}
    edges = {("entity", "files", "claim"): pd.DataFrame({"src_id": ["e1"], "dst_id": ["c1"]})}
    conn = InMemoryGraphDBConnector(config, nodes=nodes, edges=edges)

    df = conn.fetch_nodes("claim")
    assert len(df) == 2
    assert "node_id" in df.columns

    edge_df = conn.fetch_edges(("entity", "files", "claim"))
    assert len(edge_df) == 1

    # Missing type returns empty
    empty = conn.fetch_nodes("nonexistent")
    assert empty.empty


def test_vector_db_connector():
    config = ScoringConfig()
    embs = {"claim": {"c1": np.ones(768, dtype=np.float32)}}
    conn = InMemoryVectorDBConnector(config, embeddings=embs)

    result = conn.fetch_embeddings("claim", ["c1", "c2"])
    assert result.shape == (2, 768)
    assert result[0].sum() == 768.0  # c1 has ones
    assert result[1].sum() == 0.0    # c2 has zeros


def test_structured_data_connector():
    config = ScoringConfig()
    features = {"claim": pd.DataFrame({"f1": [1.0, 2.0]}, index=["c1", "c2"])}
    conn = InMemoryStructuredDataConnector(config, features=features)

    df = conn.fetch_features("claim", ["c1", "c2", "c3"])
    assert len(df) == 3
    assert df.loc["c3", "f1"] == 0.0  # missing filled with 0


def test_label_store_connector():
    config = ScoringConfig()
    labels = pd.Series([1.0, 0.0], index=["c1", "c2"])
    conn = InMemoryLabelStoreConnector(config, labels=labels)

    result = conn.fetch_labels(["c1", "c2", "c3"])
    assert result["c1"] == 1.0
    assert pd.isna(result["c3"])

    weights = conn.fetch_sample_weights(["c1", "c2"])
    assert weights["c1"] == 1.0  # default weight
