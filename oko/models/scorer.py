"""FraudScorer — top-level model composing backbone + projection + head."""

from __future__ import annotations

from typing import TYPE_CHECKING

import torch
from torch import Tensor, nn
from torch_geometric.data import HeteroData

from oko.models.backbones import build_backbone
from oko.models.heads import ClassificationHead

if TYPE_CHECKING:
    from oko.config import ScoringConfig
    from oko.models.backbones.base import BaseBackbone


class NoteProjection(nn.Module):
    """Linear projection for high-dimensional note embeddings."""

    def __init__(self, input_dim: int, output_dim: int) -> None:
        super().__init__()
        self.linear = nn.Linear(input_dim, output_dim)
        self.norm = nn.LayerNorm(output_dim)

    def forward(self, x: Tensor) -> Tensor:
        return self.norm(self.linear(x))


class FraudScorer(nn.Module):
    """Full scoring model: note projection + GNN backbone + classification head.

    Parameters
    ----------
    metadata : tuple of (node_types, edge_types)
    config : ScoringConfig
    input_dims : dict mapping node_type -> raw structured feature dimension
        (before note embedding concatenation)
    """

    def __init__(
        self,
        metadata: tuple[list[str], list[tuple[str, str, str]]],
        config: ScoringConfig,
        input_dims: dict[str, int],
    ) -> None:
        super().__init__()
        self.config = config
        self.target_node_type = "claim"
        self._raw_input_dims = input_dims.copy()

        # Note embedding projection (768 -> projection_dim)
        self.note_projection = NoteProjection(
            config.data.note_embedding_dim, config.data.projection_dim
        )

        # Backbone input dims: structured features + projected embedding where applicable
        backbone_input_dims = {}
        for ntype, dim in input_dims.items():
            backbone_input_dims[ntype] = dim  # will be updated dynamically
        self._backbone_input_dims = backbone_input_dims

        # Backbone
        self.backbone = build_backbone(metadata, config.backbone, backbone_input_dims)

        # Classification head on target node type
        self.head = ClassificationHead(config.backbone.hidden_dim, config.head)

    def _prepare_features(self, data: HeteroData) -> dict[str, Tensor]:
        """Concatenate structured features with projected note embeddings."""
        x_dict: dict[str, Tensor] = {}
        for ntype in data.node_types:
            parts: list[Tensor] = []
            if hasattr(data[ntype], "x") and data[ntype].x is not None:
                parts.append(data[ntype].x)
            if hasattr(data[ntype], "note_emb") and data[ntype].note_emb is not None:
                projected = self.note_projection(data[ntype].note_emb)
                parts.append(projected)
            if parts:
                x_dict[ntype] = torch.cat(parts, dim=-1)
        return x_dict

    def forward(self, data: HeteroData) -> Tensor:
        """Produce fraud logits for the target node type.

        Returns
        -------
        Tensor of shape (num_target_nodes, 1) — raw logits.
        """
        x_dict = self._prepare_features(data)
        embeddings = self.backbone(x_dict, data.edge_index_dict)
        target_emb = embeddings[self.target_node_type]
        return self.head(target_emb)

    def get_embeddings(self, data: HeteroData) -> dict[str, Tensor]:
        """Return backbone embeddings (for downstream explanation engine)."""
        x_dict = self._prepare_features(data)
        return self.backbone(x_dict, data.edge_index_dict)

    def predict_proba(self, data: HeteroData) -> Tensor:
        """Return fraud probabilities in [0, 1]."""
        logits = self.forward(data)
        return torch.sigmoid(logits).squeeze(-1)
