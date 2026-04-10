"""Pretraining loop for self-supervised GNN pretraining."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import torch
from torch_geometric.data import HeteroData

if TYPE_CHECKING:
    from oko.config import PretrainConfig, ScoringConfig
    from oko.models.backbones.base import BaseBackbone
    from oko.models.pretrain.base import BasePretrainTask
    from oko.models.scorer import NoteProjection

logger = logging.getLogger(__name__)


class PretrainRunner:
    """Run self-supervised pretraining and return the trained backbone.

    Parameters
    ----------
    pretrain_task : BasePretrainTask
        DGI or GraphMAE task wrapping the backbone.
    config : PretrainConfig
    device : str
    note_projection : NoteProjection, optional
        If provided, trains the note projection jointly.
    """

    def __init__(
        self,
        pretrain_task: BasePretrainTask,
        config: PretrainConfig,
        device: str = "cpu",
        note_projection: NoteProjection | None = None,
    ) -> None:
        self.task = pretrain_task
        self.config = config
        self.device = device
        self.note_projection = note_projection

    def _prepare_features(self, data: HeteroData) -> dict[str, torch.Tensor]:
        """Build x_dict, projecting note embeddings if present."""
        x_dict: dict[str, torch.Tensor] = {}
        for ntype in data.node_types:
            parts: list[torch.Tensor] = []
            if hasattr(data[ntype], "x") and data[ntype].x is not None:
                parts.append(data[ntype].x)
            if (
                self.note_projection is not None
                and hasattr(data[ntype], "note_emb")
                and data[ntype].note_emb is not None
            ):
                parts.append(self.note_projection(data[ntype].note_emb))
            if parts:
                x_dict[ntype] = torch.cat(parts, dim=-1)
        return x_dict

    def run(self, data: HeteroData) -> BaseBackbone:
        """Train and return the backbone with learned weights."""
        data = data.to(self.device)
        self.task = self.task.to(self.device)
        if self.note_projection is not None:
            self.note_projection = self.note_projection.to(self.device)

        params = list(self.task.parameters())
        if self.note_projection is not None:
            params += list(self.note_projection.parameters())
        optimizer = torch.optim.Adam(
            params, lr=self.config.lr, weight_decay=self.config.weight_decay
        )

        best_loss = float("inf")
        patience_counter = 0

        self.task.train()
        for epoch in range(1, self.config.epochs + 1):
            optimizer.zero_grad()
            x_dict = self._prepare_features(data)
            loss = self.task(x_dict, data.edge_index_dict)
            loss.backward()
            optimizer.step()

            loss_val = loss.item()
            if epoch % 10 == 0 or epoch == 1:
                logger.info("Pretrain epoch %d/%d  loss=%.4f", epoch, self.config.epochs, loss_val)

            # Early stopping on training loss plateau
            if loss_val < best_loss - 1e-4:
                best_loss = loss_val
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= self.config.patience:
                    logger.info("Pretrain early stop at epoch %d", epoch)
                    break

        return self.task.backbone
