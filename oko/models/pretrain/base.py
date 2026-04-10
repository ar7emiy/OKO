"""Abstract base class for self-supervised pretraining tasks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from torch import Tensor, nn
from torch_geometric.data import HeteroData

if TYPE_CHECKING:
    from oko.config import PretrainConfig
    from oko.models.backbones.base import BaseBackbone


class BasePretrainTask(nn.Module, ABC):
    """A self-supervised pretraining task wrapping a backbone.

    The backbone's weights are trained via the pretraining objective.
    After pretraining, extract the backbone via ``self.backbone``.

    Parameters
    ----------
    backbone : BaseBackbone
    config : PretrainConfig
    metadata : tuple of (node_types, edge_types)
    """

    def __init__(
        self,
        backbone: BaseBackbone,
        config: PretrainConfig,
        metadata: tuple[list[str], list[tuple[str, str, str]]],
    ) -> None:
        super().__init__()
        self.backbone = backbone
        self.config = config
        self.metadata = metadata

    @abstractmethod
    def forward(
        self,
        x_dict: dict[str, Tensor],
        edge_index_dict: dict[tuple[str, str, str], Tensor],
    ) -> Tensor:
        """Compute and return the scalar pretraining loss."""
