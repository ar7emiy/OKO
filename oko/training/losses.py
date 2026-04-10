"""Loss functions for fraud classification."""

from __future__ import annotations

from typing import TYPE_CHECKING

import torch
import torch.nn.functional as F
from torch import Tensor, nn

if TYPE_CHECKING:
    from oko.config import TrainConfig


class FocalLoss(nn.Module):
    """Focal loss for class-imbalanced binary classification.

    FL(p_t) = -alpha_t * (1 - p_t)^gamma * log(p_t)

    Parameters
    ----------
    gamma : modulating factor (higher = more focus on hard examples)
    alpha : weighting factor for the positive class
    """

    def __init__(self, gamma: float = 2.0, alpha: float = 0.25) -> None:
        super().__init__()
        self.gamma = gamma
        self.alpha = alpha

    def forward(
        self, logits: Tensor, targets: Tensor, weight: Tensor | None = None
    ) -> Tensor:
        probs = torch.sigmoid(logits.squeeze(-1))
        targets = targets.float()

        # Binary focal loss
        bce = F.binary_cross_entropy_with_logits(
            logits.squeeze(-1), targets, reduction="none"
        )
        p_t = probs * targets + (1 - probs) * (1 - targets)
        focal_weight = (1 - p_t) ** self.gamma

        alpha_t = self.alpha * targets + (1 - self.alpha) * (1 - targets)
        loss = alpha_t * focal_weight * bce

        if weight is not None:
            loss = loss * weight

        return loss.mean()


class WeightedBCELoss(nn.Module):
    """Weighted binary cross-entropy loss.

    Parameters
    ----------
    pos_weight : weight for positive (fraud) samples
    """

    def __init__(self, pos_weight: float = 10.0) -> None:
        super().__init__()
        self.pos_weight = pos_weight

    def forward(
        self, logits: Tensor, targets: Tensor, weight: Tensor | None = None
    ) -> Tensor:
        targets = targets.float()
        # Per-sample positive weighting
        pw = torch.where(
            targets == 1.0,
            torch.tensor(self.pos_weight, device=logits.device),
            torch.tensor(1.0, device=logits.device),
        )
        loss = F.binary_cross_entropy_with_logits(
            logits.squeeze(-1), targets, reduction="none"
        )
        loss = loss * pw
        if weight is not None:
            loss = loss * weight
        return loss.mean()


LOSS_REGISTRY: dict[str, type[nn.Module]] = {
    "focal": FocalLoss,
    "weighted_bce": WeightedBCELoss,
}


def build_loss(config: TrainConfig) -> nn.Module:
    """Construct a loss function from config."""
    if config.loss == "focal":
        return FocalLoss(gamma=config.focal_gamma, alpha=config.focal_alpha)
    elif config.loss == "weighted_bce":
        return WeightedBCELoss(pos_weight=config.bce_pos_weight)
    else:
        raise ValueError(
            f"Unknown loss '{config.loss}'. Available: {list(LOSS_REGISTRY)}"
        )
