"""Abstract base class for GNN backbones."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import torch
from torch import Tensor, nn

if TYPE_CHECKING:
    from oko.config import BackboneConfig


class BaseBackbone(nn.Module, ABC):
    """A heterogeneous GNN backbone that produces per-node-type embeddings.

    Parameters
    ----------
    metadata : tuple of (node_types, edge_types)
        As returned by ``HeteroData.metadata()``.
    config : BackboneConfig
    input_dims : dict mapping node_type -> input feature dimension
    """

    def __init__(
        self,
        metadata: tuple[list[str], list[tuple[str, str, str]]],
        config: BackboneConfig,
        input_dims: dict[str, int],
    ) -> None:
        super().__init__()
        self.node_types = metadata[0]
        self.edge_types = metadata[1]
        self.config = config
        self.input_dims = input_dims

    @abstractmethod
    def forward(
        self,
        x_dict: dict[str, Tensor],
        edge_index_dict: dict[tuple[str, str, str], Tensor],
    ) -> dict[str, Tensor]:
        """Run message passing and return per-node-type embeddings.

        Returns
        -------
        dict mapping node_type -> Tensor of shape (num_nodes, hidden_dim)
        """
