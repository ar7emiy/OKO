"""Tests for pretraining tasks."""

import torch
from dataclasses import replace

from oko.models.backbones import build_backbone
from oko.models.pretrain import build_pretrain_task
from oko.training.pipeline import _compute_input_dims


def test_dgi_loss_computes(tiny_config, tiny_data):
    metadata = tiny_data.metadata()
    input_dims = _compute_input_dims(tiny_data, tiny_config)
    backbone = build_backbone(metadata, tiny_config.backbone, input_dims)
    task = build_pretrain_task(backbone, tiny_config.pretrain, metadata)

    x_dict = {ntype: tiny_data[ntype].x for ntype in tiny_data.node_types}
    # Add projected embeddings where available
    from oko.models.scorer import NoteProjection
    proj = NoteProjection(tiny_config.data.note_embedding_dim, tiny_config.data.projection_dim)
    for ntype in tiny_data.node_types:
        if hasattr(tiny_data[ntype], "note_emb") and tiny_data[ntype].note_emb is not None:
            projected = proj(tiny_data[ntype].note_emb)
            x_dict[ntype] = torch.cat([x_dict[ntype], projected], dim=-1)

    loss = task(x_dict, tiny_data.edge_index_dict)
    assert loss.dim() == 0  # scalar
    assert not torch.isnan(loss)


def test_graphmae_loss_computes(tiny_config, tiny_data):
    config = replace(tiny_config, pretrain=replace(tiny_config.pretrain, strategy="graphmae"))
    metadata = tiny_data.metadata()
    input_dims = _compute_input_dims(tiny_data, config)
    backbone = build_backbone(metadata, config.backbone, input_dims)
    task = build_pretrain_task(backbone, config.pretrain, metadata)

    x_dict = {ntype: tiny_data[ntype].x for ntype in tiny_data.node_types}
    from oko.models.scorer import NoteProjection
    proj = NoteProjection(config.data.note_embedding_dim, config.data.projection_dim)
    for ntype in tiny_data.node_types:
        if hasattr(tiny_data[ntype], "note_emb") and tiny_data[ntype].note_emb is not None:
            projected = proj(tiny_data[ntype].note_emb)
            x_dict[ntype] = torch.cat([x_dict[ntype], projected], dim=-1)

    loss = task(x_dict, tiny_data.edge_index_dict)
    assert loss.dim() == 0
    assert not torch.isnan(loss)


def test_pretrain_registry():
    from oko.models.pretrain import PRETRAIN_REGISTRY
    assert "dgi" in PRETRAIN_REGISTRY
    assert "graphmae" in PRETRAIN_REGISTRY
