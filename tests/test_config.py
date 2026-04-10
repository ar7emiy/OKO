"""Tests for configuration loading and serialization."""

import tempfile
from pathlib import Path

from oko.config import ScoringConfig, load_config, save_config, config_to_dict


def test_default_config():
    config = ScoringConfig()
    assert config.backbone.architecture == "rgcn"
    assert config.pretrain.strategy == "dgi"
    assert config.data.note_embedding_dim == 768
    assert len(config.graph_schema.node_types) == 4


def test_load_config():
    config = load_config("configs/default.yaml")
    assert config.backbone.architecture == "rgcn"
    assert config.backbone.hidden_dim == 128
    assert config.train.loss == "focal"
    assert len(config.graph_schema.edge_type_tuples) == 6


def test_config_round_trip():
    original = ScoringConfig()
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        save_config(original, f.name)
        loaded = load_config(f.name)

    assert loaded.backbone.architecture == original.backbone.architecture
    assert loaded.backbone.hidden_dim == original.backbone.hidden_dim
    assert loaded.data.note_embedding_dim == original.data.note_embedding_dim
    assert loaded.train.loss == original.train.loss


def test_edge_type_tuples():
    config = ScoringConfig()
    tuples = config.graph_schema.edge_type_tuples
    assert all(isinstance(t, tuple) and len(t) == 3 for t in tuples)
    assert ("entity", "files", "claim") in tuples
