"""Evaluation metrics for fraud scoring."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from torch_geometric.data import HeteroData

from oko.models.scorer import FraudScorer


@dataclass
class EvalMetrics:
    auc_roc: float
    auc_pr: float
    precision: float
    recall: float
    f1: float
    calibration_error: float  # expected calibration error

    def __str__(self) -> str:
        return (
            f"AUC-ROC={self.auc_roc:.4f}  AUC-PR={self.auc_pr:.4f}  "
            f"P={self.precision:.4f}  R={self.recall:.4f}  F1={self.f1:.4f}  "
            f"ECE={self.calibration_error:.4f}"
        )


def _expected_calibration_error(
    y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10
) -> float:
    """Compute binned Expected Calibration Error."""
    bin_edges = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    total = len(y_true)
    if total == 0:
        return 0.0

    for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
        mask = (y_prob >= lo) & (y_prob < hi)
        count = mask.sum()
        if count == 0:
            continue
        avg_conf = y_prob[mask].mean()
        avg_acc = y_true[mask].mean()
        ece += (count / total) * abs(avg_conf - avg_acc)
    return ece


class Evaluator:
    """Compute evaluation metrics on a subset of the graph.

    Parameters
    ----------
    device : str
    threshold : float
        Classification threshold for precision/recall/F1.
    """

    def __init__(self, device: str = "cpu", threshold: float = 0.5) -> None:
        self.device = device
        self.threshold = threshold

    def evaluate(
        self,
        scorer: FraudScorer,
        data: HeteroData,
        mask: torch.Tensor,
    ) -> EvalMetrics:
        """Evaluate the scorer on nodes selected by mask."""
        data = data.to(self.device)
        scorer = scorer.to(self.device)
        scorer.eval()
        target = scorer.target_node_type

        with torch.no_grad():
            logits = scorer(data)
            probs = torch.sigmoid(logits.squeeze(-1))

        labels = data[target].y
        probs_masked = probs[mask].cpu().numpy()
        labels_masked = labels[mask].cpu().numpy()

        # Filter out NaN labels
        valid = ~np.isnan(labels_masked)
        probs_masked = probs_masked[valid]
        labels_masked = labels_masked[valid]

        if len(labels_masked) < 2 or len(set(labels_masked)) < 2:
            return EvalMetrics(
                auc_roc=0.0, auc_pr=0.0, precision=0.0,
                recall=0.0, f1=0.0, calibration_error=0.0,
            )

        preds = (probs_masked >= self.threshold).astype(int)
        labels_int = labels_masked.astype(int)

        return EvalMetrics(
            auc_roc=roc_auc_score(labels_int, probs_masked),
            auc_pr=average_precision_score(labels_int, probs_masked),
            precision=precision_score(labels_int, preds, zero_division=0),
            recall=recall_score(labels_int, preds, zero_division=0),
            f1=f1_score(labels_int, preds, zero_division=0),
            calibration_error=_expected_calibration_error(labels_int, probs_masked),
        )
