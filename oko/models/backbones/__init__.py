"""GNN backbone registry and factory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from oko.models.backbones.base import BaseBackbone
from oko.models.backbones.hgt import HGTBackbone
from oko.models.backbones.rgcn import RGCNBackbone

if TYPE_CHECKING:
    from oko.config import BackboneConfig

BACKBONE_REGISTRY: dict[str, type[BaseBackbone]] = {
    "rgcn": RGCNBackbone,
    "hgt": HGTBackbone,
}


def build_backbone(
    metadata: tuple[list[str], list[tuple[str, str, str]]],
    config: BackboneConfig,
    input_dims: dict[str, int],
) -> BaseBackbone:
    """Construct a backbone by config.architecture name."""
    cls = BACKBONE_REGISTRY.get(config.architecture)
    if cls is None:
        raise ValueError(
            f"Unknown backbone '{config.architecture}'. "
            f"Available: {list(BACKBONE_REGISTRY)}"
        )
    return cls(metadata=metadata, config=config, input_dims=input_dims)


__all__ = ["BaseBackbone", "RGCNBackbone", "HGTBackbone", "build_backbone", "BACKBONE_REGISTRY"]
