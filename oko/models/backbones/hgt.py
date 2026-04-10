"""HGT (Heterogeneous Graph Transformer) backbone."""

from __future__ import annotations

from typing import TYPE_CHECKING

import torch
import torch.nn.functional as F
from torch import Tensor, nn
from torch_geometric.nn import HGTConv

from oko.models.backbones.base import BaseBackbone

if TYPE_CHECKING:
    from oko.config import BackboneConfig


class HGTBackbone(BaseBackbone):
    """Heterogeneous Graph Transformer backbone using ``HGTConv``.

    HGTConv is natively heterogeneous — it learns separate attention
    weights per relation type and per node type.
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

        # Stacked HGT layers
        self.convs = nn.ModuleList()
        for _ in range(config.num_layers):
            self.convs.append(
                HGTConv(
                    in_channels=config.hidden_dim,
                    out_channels=config.hidden_dim,
                    metadata=metadata,
                    heads=config.num_heads,
                )
            )
        self.dropout = config.dropout

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

        # Stacked HGT message passing
        for conv in self.convs:
            h_dict = conv(h_dict, edge_index_dict)
            h_dict = {k: F.dropout(F.relu(v), p=self.dropout, training=self.training)
                      for k, v in h_dict.items()}

        return h_dict
