"""Tests for losses, training pipeline, and evaluation."""

import torch
from dataclasses import replace

from oko.training.losses import FocalLoss, WeightedBCELoss, build_loss
from oko.training.evaluate import Evaluator, EvalMetrics
from oko.training.pipeline import ScoringPipeline


def test_focal_loss():
    loss_fn = FocalLoss(gamma=2.0, alpha=0.25)
    logits = torch.randn(10)
    targets = torch.randint(0, 2, (10,)).float()
    loss = loss_fn(logits, targets)
    assert loss.dim() == 0
    assert loss.item() > 0


def test_focal_loss_with_weights():
    loss_fn = FocalLoss()
    logits = torch.randn(10)
    targets = torch.randint(0, 2, (10,)).float()
    weights = torch.ones(10) * 0.5
    loss = loss_fn(logits, targets, weight=weights)
    assert loss.dim() == 0


def test_weighted_bce_loss():
    loss_fn = WeightedBCELoss(pos_weight=10.0)
    logits = torch.randn(10)
    targets = torch.randint(0, 2, (10,)).float()
    loss = loss_fn(logits, targets)
    assert loss.dim() == 0
    assert loss.item() > 0


def test_build_loss():
    from oko.config import TrainConfig
    config = TrainConfig(loss="focal")
    loss_fn = build_loss(config)
    assert isinstance(loss_fn, FocalLoss)

    config = TrainConfig(loss="weighted_bce")
    loss_fn = build_loss(config)
    assert isinstance(loss_fn, WeightedBCELoss)


def test_evaluator(tiny_config, tiny_data):
    from oko.models.scorer import FraudScorer
    from oko.training.pipeline import _compute_input_dims

    metadata = tiny_data.metadata()
    input_dims = _compute_input_dims(tiny_data, tiny_config)
    scorer = FraudScorer(metadata, tiny_config, input_dims)

    evaluator = Evaluator(device="cpu")
    metrics = evaluator.evaluate(scorer, tiny_data, tiny_data["claim"].test_mask)
    assert isinstance(metrics, EvalMetrics)
    assert 0.0 <= metrics.auc_roc <= 1.0


def test_full_pipeline(tiny_config, tiny_data):
    """Smoke test: run the full pretrain -> finetune -> evaluate pipeline."""
    pipeline = ScoringPipeline(tiny_config)
    scorer, metrics = pipeline.run(tiny_data)
    assert isinstance(metrics, EvalMetrics)
    assert scorer is not None
    # Model should produce valid probabilities
    probs = scorer.predict_proba(tiny_data)
    assert probs.min() >= 0.0
    assert probs.max() <= 1.0


def test_pipeline_skip_pretrain(tiny_config, tiny_data):
    """Pipeline works without pretraining."""
    pipeline = ScoringPipeline(tiny_config)
    scorer, metrics = pipeline.run(tiny_data, skip_pretrain=True)
    assert isinstance(metrics, EvalMetrics)


def test_pipeline_with_hgt(tiny_config, tiny_data):
    """Pipeline works with HGT backbone."""
    config = replace(tiny_config, backbone=replace(tiny_config.backbone, architecture="hgt"))
    pipeline = ScoringPipeline(config)
    scorer, metrics = pipeline.run(config_data_pair(config))
    assert isinstance(metrics, EvalMetrics)


def config_data_pair(config):
    """Generate fresh data for a config (since backbone dims may differ)."""
    from oko.synthetic.generator import SyntheticGraphGenerator
    return SyntheticGraphGenerator(config).generate()


def test_pipeline_with_graphmae(tiny_config):
    """Pipeline works with GraphMAE pretraining."""
    config = replace(tiny_config, pretrain=replace(tiny_config.pretrain, strategy="graphmae"))
    data = config_data_pair(config)
    pipeline = ScoringPipeline(config)
    scorer, metrics = pipeline.run(data)
    assert isinstance(metrics, EvalMetrics)
