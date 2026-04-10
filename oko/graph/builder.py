"""Build a PyG HeteroData object from connector data sources."""

from __future__ import annotations

import numpy as np
import torch
from torch_geometric.data import HeteroData
from torch_geometric import transforms as T

from oko.config import ScoringConfig
from oko.connectors.base import (
    GraphDBConnector,
    LabelStoreConnector,
    StructuredDataConnector,
    VectorDBConnector,
)


class HeteroGraphBuilder:
    """Converts connector outputs into a single PyG HeteroData graph.

    Parameters
    ----------
    config : ScoringConfig
    graph_conn : GraphDBConnector
    vector_conn : VectorDBConnector
    structured_conn : StructuredDataConnector
    label_conn : LabelStoreConnector
    """

    def __init__(
        self,
        config: ScoringConfig,
        graph_conn: GraphDBConnector,
        vector_conn: VectorDBConnector,
        structured_conn: StructuredDataConnector,
        label_conn: LabelStoreConnector,
    ) -> None:
        self.config = config
        self.graph_conn = graph_conn
        self.vector_conn = vector_conn
        self.structured_conn = structured_conn
        self.label_conn = label_conn

    def build(self) -> HeteroData:
        """Construct the full heterogeneous graph."""
        data = HeteroData()
        id_maps: dict[str, dict[str, int]] = {}

        # --- 1. Nodes: features + embeddings ---
        for ntype in self.config.graph_schema.node_types:
            nodes_df = self.graph_conn.fetch_nodes(ntype)
            if nodes_df.empty:
                continue

            node_ids = nodes_df["node_id"].tolist()
            id_map = {nid: idx for idx, nid in enumerate(node_ids)}
            id_maps[ntype] = id_map

            # Structured features
            feat_df = self.structured_conn.fetch_features(ntype, node_ids)
            if feat_df.empty or feat_df.shape[1] == 0:
                # Fallback: use graph-DB attributes (columns after node_id)
                attr_cols = [c for c in nodes_df.columns if c != "node_id"]
                if attr_cols:
                    feat_tensor = torch.tensor(
                        nodes_df[attr_cols].values.astype(np.float32)
                    )
                else:
                    feat_tensor = torch.zeros(len(node_ids), 1)
            else:
                feat_tensor = torch.tensor(feat_df.values.astype(np.float32))

            data[ntype].x = feat_tensor
            data[ntype].num_nodes = len(node_ids)

            # Note embeddings (stored separately for learned projection)
            embs = self.vector_conn.fetch_embeddings(ntype, node_ids)
            if embs.any():
                data[ntype].note_emb = torch.tensor(embs)

        # --- 2. Edges ---
        for edge_type in self.config.graph_schema.edge_type_tuples:
            src_type, rel, dst_type = edge_type
            if src_type not in id_maps or dst_type not in id_maps:
                continue

            edges_df = self.graph_conn.fetch_edges(edge_type)
            if edges_df.empty:
                continue

            src_map = id_maps[src_type]
            dst_map = id_maps[dst_type]

            # Filter edges to only include known node IDs
            valid = edges_df["src_id"].isin(src_map) & edges_df["dst_id"].isin(dst_map)
            edges_df = edges_df[valid]
            if edges_df.empty:
                continue

            src_idx = torch.tensor(
                [src_map[s] for s in edges_df["src_id"]], dtype=torch.long
            )
            dst_idx = torch.tensor(
                [dst_map[d] for d in edges_df["dst_id"]], dtype=torch.long
            )
            data[src_type, rel, dst_type].edge_index = torch.stack([src_idx, dst_idx])

        # --- 3. Labels + sample weights (on target node type: claim) ---
        target = "claim"
        if target in id_maps:
            node_ids = list(id_maps[target].keys())
            labels = self.label_conn.fetch_labels(node_ids)
            weights = self.label_conn.fetch_sample_weights(node_ids)

            label_tensor = torch.tensor(labels.values.astype(np.float32))
            weight_tensor = torch.tensor(weights.values.astype(np.float32))

            data[target].y = label_tensor
            data[target].sample_weight = weight_tensor

            # --- 4. Train / val / test masks ---
            self._create_masks(data, target, labels)

        # --- 5. Add reverse edges for message passing ---
        data = T.ToUndirected()(data)

        return data

    def _create_masks(
        self,
        data: HeteroData,
        target: str,
        labels: "pd.Series",
    ) -> None:
        """Create stratified train/val/test masks on labeled nodes."""
        import pandas as pd

        n = data[target].num_nodes
        train_mask = torch.zeros(n, dtype=torch.bool)
        val_mask = torch.zeros(n, dtype=torch.bool)
        test_mask = torch.zeros(n, dtype=torch.bool)

        # Only split labeled nodes
        labeled_idx = [i for i, v in enumerate(labels.values) if not pd.isna(v)]
        if not labeled_idx:
            data[target].train_mask = train_mask
            data[target].val_mask = val_mask
            data[target].test_mask = test_mask
            return

        rng = np.random.RandomState(self.config.seed)
        rng.shuffle(labeled_idx)

        n_labeled = len(labeled_idx)
        n_train = int(n_labeled * self.config.data.train_ratio)
        n_val = int(n_labeled * self.config.data.val_ratio)

        train_idx = labeled_idx[:n_train]
        val_idx = labeled_idx[n_train : n_train + n_val]
        test_idx = labeled_idx[n_train + n_val :]

        train_mask[train_idx] = True
        val_mask[val_idx] = True
        test_mask[test_idx] = True

        data[target].train_mask = train_mask
        data[target].val_mask = val_mask
        data[target].test_mask = test_mask
