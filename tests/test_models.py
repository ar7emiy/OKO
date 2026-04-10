"""Tests for backbones, heads, and scorer."""

import torch
from oko.config import BackboneConfig, HeadConfig
from oko.models.backbones import build_backbone
from oko.models.heads import ClassificationHead
from oko.models.scorer import FraudScorer, NoteProjection


def test_rgcn_backbone_forward(tiny_config, tiny_data):
    metadata = tiny_data.metadata()
    input_dims = {ntype: tiny_data[ntype].x.size(-1) for ntype in tiny_data.node_types}
    config = tiny_config.backbone

    backbone = build_backbone(metadata, config, input_dims)
    out = backbone(
        {ntype: tiny_data[ntype].x for ntype in tiny_data.node_types},
        tiny_data.edge_index_dict,
    )
    for ntype in tiny_data.node_types:
        assert ntype in out
        assert out[ntype].shape == (tiny_data[ntype].num_nodes, config.hidden_dim)


def test_hgt_backbone_forward(tiny_config, tiny_data):
    from dataclasses import replace
    config = replace(tiny_config.backbone, architecture="hgt")
    metadata = tiny_data.metadata()
    input_dims = {ntype: tiny_data[ntype].x.size(-1) for ntype in tiny_data.node_types}

    backbone = build_backbone(metadata, config, input_dims)
    out = backbone(
        {ntype: tiny_data[ntype].x for ntype in tiny_data.node_types},
        tiny_data.edge_index_dict,
    )
    for ntype in tiny_data.node_types:
        assert ntype in out
        assert out[ntype].shape[1] == config.hidden_dim


def test_classification_head():
    config = HeadConfig(hidden_dims=[32, 16], dropout=0.1)
    head = ClassificationHead(64, config)
    x = torch.randn(10, 64)
    out = head(x)
    assert out.shape == (10, 1)


def test_note_projection():
    proj = NoteProjection(768, 64)
    x = torch.randn(5, 768)
    out = proj(x)
    assert out.shape == (5, 64)


def test_fraud_scorer_forward(tiny_config, tiny_data):
    from oko.training.pipeline import _compute_input_dims

    metadata = tiny_data.metadata()
    input_dims = _compute_input_dims(tiny_data, tiny_config)
    scorer = FraudScorer(metadata, tiny_config, input_dims)
    logits = scorer(tiny_data)
    assert logits.shape == (tiny_data["claim"].num_nodes, 1)


def test_fraud_scorer_predict_proba(tiny_config, tiny_data):
    from oko.training.pipeline import _compute_input_dims

    metadata = tiny_data.metadata()
    input_dims = _compute_input_dims(tiny_data, tiny_config)
    scorer = FraudScorer(metadata, tiny_config, input_dims)
    probs = scorer.predict_proba(tiny_data)
    assert probs.min() >= 0.0
    assert probs.max() <= 1.0


def test_backbone_registry():
    from oko.models.backbones import BACKBONE_REGISTRY
    assert "rgcn" in BACKBONE_REGISTRY
    assert "hgt" in BACKBONE_REGISTRY
