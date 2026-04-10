"""Deep Graph Infomax (DGI) for heterogeneous graphs.

Pretraining objective: maximize mutual information between node-level
embeddings and a global graph summary, while minimizing it for
corrupted (shuffled) node features.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import torch
import torch.nn.functional as F
from torch import Tensor, nn

from oko.models.pretrain.base import BasePretrainTask

if TYPE_CHECKING:
    from oko.config import PretrainConfig
    from oko.models.backbones.base import BaseBackbone


class _Discriminator(nn.Module):
    """Bilinear discriminator scoring (node_embedding, summary) pairs."""

    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.weight = nn.Parameter(torch.empty(hidden_dim, hidden_dim))
        nn.init.xavier_uniform_(self.weight)

    def forward(self, node_emb: Tensor, summary: Tensor) -> Tensor:
        # node_emb: (N, D), summary: (D,) -> scores: (N,)
        return (node_emb @ self.weight * summary.unsqueeze(0)).sum(dim=-1)


class HeteroDGI(BasePretrainTask):
    """Heterogeneous Deep Graph Infomax.

    Per-type discriminators score (node_emb, type_summary) pairs.
    Positive samples use real features; negatives use shuffled features.
    """

    def __init__(
        self,
        backbone: BaseBackbone,
        config: PretrainConfig,
        metadata: tuple[list[str], list[tuple[str, str, str]]],
    ) -> None:
        super().__init__(backbone, config, metadata)
        hidden_dim = backbone.config.hidden_dim
        self.discriminators = nn.ModuleDict(
            {ntype: _Discriminator(hidden_dim) for ntype in metadata[0]}
        )

    def _corrupt(self, x_dict: dict[str, Tensor]) -> dict[str, Tensor]:
        """Shuffle node features within each type (corruption function)."""
        corrupted: dict[str, Tensor] = {}
        for ntype, x in x_dict.items():
            perm = torch.randperm(x.size(0), device=x.device)
            corrupted[ntype] = x[perm]
        return corrupted

    def forward(
        self,
        x_dict: dict[str, Tensor],
        edge_index_dict: dict[tuple[str, str, str], Tensor],
    ) -> Tensor:
        # Positive: real embeddings
        pos_emb = self.backbone(x_dict, edge_index_dict)

        # Negative: corrupted embeddings
        x_corrupt = self._corrupt(x_dict)
        neg_emb = self.backbone(x_corrupt, edge_index_dict)

        loss = torch.tensor(0.0, device=next(self.parameters()).device)
        n_types = 0

        for ntype in pos_emb:
            if ntype not in self.discriminators:
                continue
            disc = self.discriminators[ntype]

            # Summary: mean pooling of positive embeddings for this type
            summary = pos_emb[ntype].mean(dim=0)

            # Positive scores
            pos_scores = disc(pos_emb[ntype], summary)
            # Negative scores
            neg_scores = disc(neg_emb[ntype], summary)

            # BCE loss
            pos_loss = F.binary_cross_entropy_with_logits(
                pos_scores, torch.ones_like(pos_scores)
            )
            neg_loss = F.binary_cross_entropy_with_logits(
                neg_scores, torch.zeros_like(neg_scores)
            )
            loss = loss + (pos_loss + neg_loss)
            n_types += 1

        return loss / max(n_types, 1)
