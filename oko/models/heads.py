"""Classification head — MLP producing fraud logits."""

from __future__ import annotations

from typing import TYPE_CHECKING

import torch.nn.functional as F
from torch import Tensor, nn

if TYPE_CHECKING:
    from oko.config import HeadConfig


class ClassificationHead(nn.Module):
    """MLP classification head: hidden_dim -> hidden_dims -> 1 (logit).

    Parameters
    ----------
    input_dim : int
        Backbone output dimension.
    config : HeadConfig
    """

    def __init__(self, input_dim: int, config: HeadConfig) -> None:
        super().__init__()
        layers: list[nn.Module] = []
        prev_dim = input_dim
        for dim in config.hidden_dims:
            layers.append(nn.Linear(prev_dim, dim))
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(config.dropout))
            prev_dim = dim
        layers.append(nn.Linear(prev_dim, 1))
        self.mlp = nn.Sequential(*layers)

    def forward(self, x: Tensor) -> Tensor:
        """Return raw logits of shape (N, 1)."""
        return self.mlp(x)
