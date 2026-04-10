"""Pretraining task registry and factory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from oko.models.pretrain.base import BasePretrainTask
from oko.models.pretrain.dgi import HeteroDGI
from oko.models.pretrain.graphmae import HeteroGraphMAE

if TYPE_CHECKING:
    from oko.config import PretrainConfig
    from oko.models.backbones.base import BaseBackbone

PRETRAIN_REGISTRY: dict[str, type[BasePretrainTask]] = {
    "dgi": HeteroDGI,
    "graphmae": HeteroGraphMAE,
}


def build_pretrain_task(
    backbone: BaseBackbone,
    config: PretrainConfig,
    metadata: tuple[list[str], list[tuple[str, str, str]]],
) -> BasePretrainTask:
    """Construct a pretraining task by config.strategy name."""
    cls = PRETRAIN_REGISTRY.get(config.strategy)
    if cls is None:
        raise ValueError(
            f"Unknown pretrain strategy '{config.strategy}'. "
            f"Available: {list(PRETRAIN_REGISTRY)}"
        )
    return cls(backbone=backbone, config=config, metadata=metadata)


__all__ = ["BasePretrainTask", "HeteroDGI", "HeteroGraphMAE", "build_pretrain_task", "PRETRAIN_REGISTRY"]
