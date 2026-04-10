"""Hyperparameter sweep runner using Optuna."""

from __future__ import annotations

import copy
import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from torch_geometric.data import HeteroData

from oko.config import (
    BackboneConfig,
    DataConfig,
    HeadConfig,
    PretrainConfig,
    ScoringConfig,
    TrainConfig,
)
from oko.training.pipeline import ScoringPipeline

if TYPE_CHECKING:
    import optuna

logger = logging.getLogger(__name__)


def define_search_space(trial: optuna.Trial, base: ScoringConfig) -> ScoringConfig:
    """Map Optuna trial suggestions to a ScoringConfig.

    Uses the base config as defaults. Each parameter is suggested from a
    sensible range, allowing Optuna to explore the space.
    """
    backbone = replace(
        base.backbone,
        architecture=trial.suggest_categorical("backbone_arch", ["rgcn", "hgt"]),
        num_layers=trial.suggest_int("num_layers", 1, 4),
        hidden_dim=trial.suggest_categorical("hidden_dim", [64, 128, 256]),
        num_heads=trial.suggest_categorical("num_heads", [2, 4, 8]),
        dropout=trial.suggest_float("backbone_dropout", 0.1, 0.5),
    )

    pretrain = replace(
        base.pretrain,
        strategy=trial.suggest_categorical("pretrain_strategy", ["dgi", "graphmae"]),
        lr=trial.suggest_float("pretrain_lr", 1e-4, 1e-2, log=True),
        mask_ratio=trial.suggest_float("mask_ratio", 0.3, 0.7),
    )

    data = replace(
        base.data,
        projection_dim=trial.suggest_categorical("projection_dim", [32, 64, 128]),
    )

    head = replace(
        base.head,
        hidden_dims=[trial.suggest_categorical("head_hidden", [32, 64, 128])],
        dropout=trial.suggest_float("head_dropout", 0.1, 0.5),
    )

    train = replace(
        base.train,
        loss=trial.suggest_categorical("loss_fn", ["focal", "weighted_bce"]),
        focal_gamma=trial.suggest_float("focal_gamma", 1.0, 5.0),
        focal_alpha=trial.suggest_float("focal_alpha", 0.1, 0.5),
        lr=trial.suggest_float("finetune_lr", 1e-4, 1e-2, log=True),
        downweight_ratio=trial.suggest_float("downweight_ratio", 0.1, 1.0),
    )

    return replace(
        base,
        backbone=backbone,
        pretrain=pretrain,
        data=data,
        head=head,
        train=train,
    )


class SweepRunner:
    """Run an Optuna hyperparameter sweep.

    Parameters
    ----------
    base_config : ScoringConfig
        Base configuration (non-swept params keep these values).
    data : HeteroData
        Prebuilt graph data (built once, reused across trials).
    n_trials : int
    """

    def __init__(
        self,
        base_config: ScoringConfig,
        data: HeteroData,
        n_trials: int | None = None,
    ) -> None:
        self.base_config = base_config
        self.data = data
        self.n_trials = n_trials or base_config.sweep.n_trials

    def objective(self, trial: optuna.Trial) -> float:
        """Single trial: build config, run pipeline, return metric."""
        config = define_search_space(trial, self.base_config)
        logger.info("Trial %d: %s", trial.number, trial.params)

        try:
            pipeline = ScoringPipeline(config)
            _, metrics = pipeline.run(self.data)
            value = getattr(metrics, self.base_config.sweep.metric)
            logger.info("Trial %d result: %s = %.4f", trial.number, self.base_config.sweep.metric, value)
            return value
        except Exception as e:
            logger.warning("Trial %d failed: %s", trial.number, e)
            return 0.0

    def run(self) -> optuna.Study:
        """Execute the sweep and return the Optuna study."""
        import optuna

        study = optuna.create_study(
            direction=self.base_config.sweep.direction,
            study_name="oko_sweep",
        )
        study.optimize(self.objective, n_trials=self.n_trials)

        logger.info("Best trial: %s", study.best_trial.params)
        logger.info("Best value: %.4f", study.best_value)

        return study
