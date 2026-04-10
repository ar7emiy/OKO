"""Shared test fixtures."""

from __future__ import annotations

import pytest

from oko.config import ScoringConfig, DataConfig, BackboneConfig, PretrainConfig, TrainConfig, HeadConfig


@pytest.fixture
def tiny_config() -> ScoringConfig:
    """Small config for fast tests."""
    return ScoringConfig(
        data=DataConfig(
            synthetic_num_claims=100,
            synthetic_num_entities=80,
            synthetic_num_addresses=30,
            synthetic_num_npis=15,
            synthetic_fraud_ratio=0.1,
            note_embedding_dim=32,
            projection_dim=8,
        ),
        backbone=BackboneConfig(
            architecture="rgcn",
            num_layers=1,
            hidden_dim=16,
            num_heads=2,
            dropout=0.1,
        ),
        pretrain=PretrainConfig(
            strategy="dgi",
            epochs=3,
            lr=1e-3,
            patience=5,
        ),
        head=HeadConfig(
            hidden_dims=[8],
            dropout=0.1,
        ),
        train=TrainConfig(
            loss="focal",
            epochs=3,
            lr=1e-3,
            patience=5,
        ),
        seed=42,
        device="cpu",
    )


@pytest.fixture
def tiny_data(tiny_config):
    """Small synthetic HeteroData graph."""
    from oko.synthetic.generator import SyntheticGraphGenerator
    gen = SyntheticGraphGenerator(tiny_config)
    return gen.generate()
