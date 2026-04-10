"""End-to-end scoring pipeline: pretrain -> finetune -> evaluate."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import torch
from torch_geometric.data import HeteroData

from oko.models.backbones import build_backbone
from oko.models.pretrain import build_pretrain_task
from oko.models.scorer import FraudScorer, NoteProjection
from oko.training.evaluate import EvalMetrics, Evaluator
from oko.training.finetune_loop import FinetuneRunner
from oko.training.pretrain_loop import PretrainRunner

if TYPE_CHECKING:
    from oko.config import ScoringConfig

logger = logging.getLogger(__name__)


def _compute_input_dims(data: HeteroData, config: ScoringConfig) -> dict[str, int]:
    """Compute the per-type input feature dimensions (structured + projected embedding)."""
    dims: dict[str, int] = {}
    for ntype in data.node_types:
        d = 0
        if hasattr(data[ntype], "x") and data[ntype].x is not None:
            d += data[ntype].x.size(-1)
        if hasattr(data[ntype], "note_emb") and data[ntype].note_emb is not None:
            d += config.data.projection_dim
        if d == 0:
            d = 1  # fallback
        dims[ntype] = d
    return dims


def _compute_raw_structured_dims(data: HeteroData) -> dict[str, int]:
    """Get per-type structured feature dimensions (without embeddings)."""
    dims: dict[str, int] = {}
    for ntype in data.node_types:
        if hasattr(data[ntype], "x") and data[ntype].x is not None:
            dims[ntype] = data[ntype].x.size(-1)
        else:
            dims[ntype] = 1
    return dims


class ScoringPipeline:
    """Orchestrate the full pretrain -> finetune -> evaluate flow.

    Parameters
    ----------
    config : ScoringConfig
    """

    def __init__(self, config: ScoringConfig) -> None:
        self.config = config

    def run(
        self,
        data: HeteroData,
        skip_pretrain: bool = False,
        checkpoint_dir: str | Path | None = None,
    ) -> tuple[FraudScorer, EvalMetrics]:
        """Run the full pipeline.

        Parameters
        ----------
        data : HeteroData
        skip_pretrain : bool
            If True, skip pretraining and use random initialization.
        checkpoint_dir : str or Path, optional
            Directory to save checkpoints. If None, no checkpoints saved.

        Returns
        -------
        tuple of (trained FraudScorer, EvalMetrics on test set)
        """
        device = self.config.device
        input_dims = _compute_input_dims(data, self.config)
        metadata = data.metadata()

        logger.info("Input dims per node type: %s", input_dims)
        logger.info("Metadata: %s node types, %s edge types",
                     len(metadata[0]), len(metadata[1]))

        # --- Phase 1: Self-supervised pretraining ---
        pretrained_backbone = None
        note_proj = NoteProjection(
            self.config.data.note_embedding_dim, self.config.data.projection_dim
        )

        if not skip_pretrain:
            logger.info("=== Phase 1: Pretraining (%s) ===", self.config.pretrain.strategy)
            backbone = build_backbone(metadata, self.config.backbone, input_dims)
            pretrain_task = build_pretrain_task(backbone, self.config.pretrain, metadata)
            runner = PretrainRunner(
                pretrain_task, self.config.pretrain, device, note_projection=note_proj
            )
            pretrained_backbone = runner.run(data)

            if checkpoint_dir:
                ckpt_path = Path(checkpoint_dir) / "backbone_pretrained.pt"
                torch.save(pretrained_backbone.state_dict(), ckpt_path)
                logger.info("Saved pretrained backbone to %s", ckpt_path)
        else:
            logger.info("=== Skipping pretraining ===")

        # --- Phase 2: Supervised fine-tuning ---
        logger.info("=== Phase 2: Fine-tuning ===")
        scorer = FraudScorer(metadata, self.config, input_dims)

        # Transfer pretrained weights
        if pretrained_backbone is not None:
            scorer.backbone.load_state_dict(pretrained_backbone.state_dict())
            scorer.note_projection.load_state_dict(note_proj.state_dict())
            logger.info("Transferred pretrained backbone weights")

        finetune_runner = FinetuneRunner(scorer, self.config.train, device)
        trained_scorer = finetune_runner.run(data)

        if checkpoint_dir:
            ckpt_path = Path(checkpoint_dir) / "scorer_finetuned.pt"
            torch.save(trained_scorer.state_dict(), ckpt_path)
            logger.info("Saved fine-tuned scorer to %s", ckpt_path)

        # --- Phase 3: Evaluation ---
        logger.info("=== Phase 3: Evaluation ===")
        target = trained_scorer.target_node_type
        evaluator = Evaluator(device)
        metrics = evaluator.evaluate(trained_scorer, data, data[target].test_mask)
        logger.info("Test metrics: %s", metrics)

        return trained_scorer, metrics
