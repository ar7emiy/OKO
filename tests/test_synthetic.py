"""Tests for synthetic data generation."""

import torch


def test_synthetic_generates_valid_graph(tiny_config, tiny_data):
    data = tiny_data
    assert "claim" in data.node_types
    assert "entity" in data.node_types
    assert "address" in data.node_types
    assert "npi" in data.node_types


def test_synthetic_has_features(tiny_data):
    for ntype in tiny_data.node_types:
        assert hasattr(tiny_data[ntype], "x")
        assert tiny_data[ntype].x is not None
        assert tiny_data[ntype].x.ndim == 2


def test_synthetic_has_labels(tiny_data):
    assert hasattr(tiny_data["claim"], "y")
    labels = tiny_data["claim"].y
    assert labels.shape[0] == tiny_data["claim"].num_nodes
    # Should have both fraud and non-fraud
    assert (labels == 1.0).any()
    assert (labels == 0.0).any()


def test_synthetic_has_masks(tiny_data):
    assert hasattr(tiny_data["claim"], "train_mask")
    assert hasattr(tiny_data["claim"], "val_mask")
    assert hasattr(tiny_data["claim"], "test_mask")
    total = (
        tiny_data["claim"].train_mask.sum()
        + tiny_data["claim"].val_mask.sum()
        + tiny_data["claim"].test_mask.sum()
    )
    assert total > 0


def test_synthetic_has_edges(tiny_data):
    assert len(tiny_data.edge_types) > 0
    for etype in tiny_data.edge_types:
        ei = tiny_data[etype].edge_index
        assert ei.ndim == 2
        assert ei.shape[0] == 2


def test_synthetic_has_note_embeddings(tiny_config, tiny_data):
    assert hasattr(tiny_data["claim"], "note_emb")
    assert tiny_data["claim"].note_emb.shape[1] == tiny_config.data.note_embedding_dim
