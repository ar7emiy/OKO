"""Supervised fine-tuning loop with early stopping."""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING

import torch
from sklearn.metrics import roc_auc_score
from torch_geometric.data import HeteroData

from oko.training.losses import build_loss

if TYPE_CHECKING:
    from oko.config import TrainConfig
    from oko.models.scorer import FraudScorer

logger = logging.getLogger(__name__)


class FinetuneRunner:
    """Supervised fine-tuning on labeled claim nodes.

    Parameters
    ----------
    scorer : FraudScorer
    config : TrainConfig
    device : str
    """

    def __init__(
        self,
        scorer: FraudScorer,
        config: TrainConfig,
        device: str = "cpu",
    ) -> None:
        self.scorer = scorer
        self.config = config
        self.device = device

    def run(self, data: HeteroData) -> FraudScorer:
        """Train the scorer and return the best checkpoint."""
        data = data.to(self.device)
        self.scorer = self.scorer.to(self.device)
        target = self.scorer.target_node_type

        criterion = build_loss(self.config).to(self.device)
        optimizer = torch.optim.Adam(
            self.scorer.parameters(),
            lr=self.config.lr,
            weight_decay=self.config.weight_decay,
        )

        train_mask = data[target].train_mask
        val_mask = data[target].val_mask
        labels = data[target].y
        sample_weights = getattr(data[target], "sample_weight", None)

        # Apply downweight ratio to sample weights
        if sample_weights is not None and self.config.downweight_ratio != 1.0:
            sample_weights = sample_weights * self.config.downweight_ratio

        best_val_auc = 0.0
        best_state = None
        patience_counter = 0

        for epoch in range(1, self.config.epochs + 1):
            # --- Train ---
            self.scorer.train()
            optimizer.zero_grad()
            logits = self.scorer(data)

            train_logits = logits[train_mask]
            train_labels = labels[train_mask]
            train_weights = sample_weights[train_mask] if sample_weights is not None else None

            # Skip if no valid labels
            valid = ~torch.isnan(train_labels)
            if valid.sum() == 0:
                logger.warning("No valid training labels at epoch %d", epoch)
                continue

            loss = criterion(
                train_logits[valid], train_labels[valid],
                weight=train_weights[valid] if train_weights is not None else None,
            )
            loss.backward()
            optimizer.step()

            # --- Validate ---
            self.scorer.eval()
            with torch.no_grad():
                val_logits = self.scorer(data)[val_mask]
                val_labels = labels[val_mask]
                valid_val = ~torch.isnan(val_labels)

                if valid_val.sum() >= 2:
                    val_probs = torch.sigmoid(val_logits[valid_val].squeeze(-1)).cpu().numpy()
                    val_y = val_labels[valid_val].cpu().numpy()
                    # AUC needs both classes
                    if len(set(val_y)) > 1:
                        val_auc = roc_auc_score(val_y, val_probs)
                    else:
                        val_auc = 0.0
                else:
                    val_auc = 0.0

            if epoch % 5 == 0 or epoch == 1:
                logger.info(
                    "Finetune epoch %d/%d  loss=%.4f  val_auc=%.4f",
                    epoch, self.config.epochs, loss.item(), val_auc,
                )

            # Early stopping on validation AUC
            if val_auc > best_val_auc + 1e-4:
                best_val_auc = val_auc
                best_state = copy.deepcopy(self.scorer.state_dict())
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= self.config.patience:
                    logger.info("Finetune early stop at epoch %d (best val_auc=%.4f)", epoch, best_val_auc)
                    break

        if best_state is not None:
            self.scorer.load_state_dict(best_state)
        return self.scorer
