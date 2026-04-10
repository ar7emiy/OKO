"""R-GCN backbone using PyG's to_hetero() on a homogeneous GNN."""

from __future__ import annotations

from typing import TYPE_CHECKING

import torch
import torch.nn.functional as F
from torch import Tensor, nn
from torch_geometric.nn import GraphConv, to_hetero

from oko.models.backbones.base import BaseBackbone

if TYPE_CHECKING:
    from oko.config import BackboneConfig


class _HomogeneousGNN(nn.Module):
    """Simple GNN stack that to_hetero() will clone per relation type."""

    def __init__(self, hidden_dim: int, num_layers: int, dropout: float) -> None:
        super().__init__()
        self.convs = nn.ModuleList()
        for _ in range(num_layers):
            self.convs.append(GraphConv(-1, hidden_dim))
        self.dropout = dropout

    def forward(self, x: Tensor, edge_index: Tensor) -> Tensor:
        for conv in self.convs:
            x = conv(x, edge_index)
            x = F.relu(x)
            x = F.dropout(x, p=self.dropout, training=self.training)
        return x


class RGCNBackbone(BaseBackbone):
    """R-GCN-style backbone via PyG ``to_hetero()``.

    Each node type gets a learned linear projection from its input
    dimension to ``hidden_dim``, then a shared GNN architecture is
    cloned per relation type by ``to_hetero()``.
    """

    def __init__(
        self,
        metadata: tuple[list[str], list[tuple[str, str, str]]],
        config: BackboneConfig,
        input_dims: dict[str, int],
    ) -> None:
        super().__init__(metadata, config, input_dims)

        # Per-type input projections
        self.projections = nn.ModuleDict(
            {ntype: nn.Linear(dim, config.hidden_dim) for ntype, dim in input_dims.items()}
        )

        # Homogeneous GNN, converted to heterogeneous
        homo = _HomogeneousGNN(config.hidden_dim, config.num_layers, config.dropout)
        self.hetero_gnn = to_hetero(homo, metadata, aggr="sum")

    def forward(
        self,
        x_dict: dict[str, Tensor],
        edge_index_dict: dict[tuple[str, str, str], Tensor],
    ) -> dict[str, Tensor]:
        # Project each node type to hidden_dim
        h_dict = {}
        for ntype, x in x_dict.items():
            if ntype in self.projections:
                h_dict[ntype] = F.relu(self.projections[ntype](x))
            else:
                h_dict[ntype] = x

        # Message passing
        return self.hetero_gnn(h_dict, edge_index_dict)
