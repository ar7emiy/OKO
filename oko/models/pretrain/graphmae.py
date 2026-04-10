"""GraphMAE for heterogeneous graphs.

Pretraining objective: mask a fraction of node features, encode the
remaining graph, and decode to reconstruct the masked features.
Loss is scaled cosine error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import torch
from torch import Tensor, nn

from oko.models.pretrain.base import BasePretrainTask

if TYPE_CHECKING:
    from oko.config import PretrainConfig
    from oko.models.backbones.base import BaseBackbone


class HeteroGraphMAE(BasePretrainTask):
    """Heterogeneous GraphMAE with per-type decoders.

    Masks ``mask_ratio`` fraction of nodes per type, encodes the visible
    nodes via the backbone, then decodes to reconstruct the original
    features of the masked nodes.
    """

    def __init__(
        self,
        backbone: BaseBackbone,
        config: PretrainConfig,
        metadata: tuple[list[str], list[tuple[str, str, str]]],
    ) -> None:
        super().__init__(backbone, config, metadata)
        hidden_dim = backbone.config.hidden_dim

        # Per-type decoders: project hidden_dim back to input feature dim
        self.decoders = nn.ModuleDict()
        for ntype, in_dim in backbone.input_dims.items():
            self.decoders[ntype] = nn.Sequential(
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, in_dim),
            )

        # Learnable mask token per type
        self.mask_tokens = nn.ParameterDict(
            {ntype: nn.Parameter(torch.zeros(1, in_dim))
             for ntype, in_dim in backbone.input_dims.items()}
        )
        for p in self.mask_tokens.values():
            nn.init.normal_(p, std=0.02)

    def _mask_features(
        self, x_dict: dict[str, Tensor]
    ) -> tuple[dict[str, Tensor], dict[str, Tensor], dict[str, Tensor]]:
        """Mask a fraction of nodes and return (masked_x, original_x, mask_bool)."""
        masked_x: dict[str, Tensor] = {}
        originals: dict[str, Tensor] = {}
        masks: dict[str, Tensor] = {}

        for ntype, x in x_dict.items():
            n = x.size(0)
            n_mask = max(1, int(n * self.config.mask_ratio))
            perm = torch.randperm(n, device=x.device)
            mask_idx = perm[:n_mask]

            mask_bool = torch.zeros(n, dtype=torch.bool, device=x.device)
            mask_bool[mask_idx] = True
            masks[ntype] = mask_bool

            originals[ntype] = x.clone()

            # Replace masked node features with mask token
            x_masked = x.clone()
            if ntype in self.mask_tokens:
                x_masked[mask_bool] = self.mask_tokens[ntype].expand(n_mask, -1)
            masked_x[ntype] = x_masked

        return masked_x, originals, masks

    def forward(
        self,
        x_dict: dict[str, Tensor],
        edge_index_dict: dict[tuple[str, str, str], Tensor],
    ) -> Tensor:
        masked_x, originals, masks = self._mask_features(x_dict)

        # Encode with masked features
        embeddings = self.backbone(masked_x, edge_index_dict)

        # Decode and compute loss only on masked positions
        loss = torch.tensor(0.0, device=next(self.parameters()).device)
        n_types = 0

        for ntype in embeddings:
            if ntype not in self.decoders or ntype not in masks:
                continue

            mask = masks[ntype]
            if not mask.any():
                continue

            decoded = self.decoders[ntype](embeddings[ntype][mask])
            target = originals[ntype][mask]

            # Scaled cosine error
            cos_sim = nn.functional.cosine_similarity(decoded, target, dim=-1)
            type_loss = (1 - cos_sim).mean()
            loss = loss + type_loss
            n_types += 1

        return loss / max(n_types, 1)
