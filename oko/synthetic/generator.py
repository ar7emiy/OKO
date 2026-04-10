"""Synthetic fraud graph generator for development and testing.

Plants realistic fraud patterns into a heterogeneous graph:
- Shared-address rings (multiple entities at same address filing claims)
- High-degree NPI reuse (one NPI on many claims from different entities)
- Feature anomalies (fraudulent claims get skewed distributions)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from torch_geometric.data import HeteroData

from oko.config import ScoringConfig
from oko.connectors.graph_db import InMemoryGraphDBConnector
from oko.connectors.label_store import InMemoryLabelStoreConnector
from oko.connectors.structured import InMemoryStructuredDataConnector
from oko.connectors.vector_db import InMemoryVectorDBConnector
from oko.graph.builder import HeteroGraphBuilder


class SyntheticGraphGenerator:
    """Generate a synthetic heterogeneous fraud graph.

    Parameters
    ----------
    config : ScoringConfig
        Controls graph size, fraud ratio, embedding dimensions, etc.
    """

    def __init__(self, config: ScoringConfig) -> None:
        self.config = config
        self.rng = np.random.RandomState(config.seed)

    def generate(self) -> HeteroData:
        """Generate a complete HeteroData graph via the connector → builder path."""
        connectors = self.generate_connectors()
        builder = HeteroGraphBuilder(self.config, *connectors)
        return builder.build()

    def generate_connectors(
        self,
    ) -> tuple[
        InMemoryGraphDBConnector,
        InMemoryVectorDBConnector,
        InMemoryStructuredDataConnector,
        InMemoryLabelStoreConnector,
    ]:
        """Generate populated in-memory connectors."""
        cfg = self.config.data
        n_claims = cfg.synthetic_num_claims
        n_entities = cfg.synthetic_num_entities
        n_addresses = cfg.synthetic_num_addresses
        n_npis = cfg.synthetic_num_npis
        fraud_ratio = cfg.synthetic_fraud_ratio

        # --- Node IDs ---
        claim_ids = [f"CLM-{i:06d}" for i in range(n_claims)]
        entity_ids = [f"ENT-{i:06d}" for i in range(n_entities)]
        address_ids = [f"ADDR-{i:06d}" for i in range(n_addresses)]
        npi_ids = [f"NPI-{i:06d}" for i in range(n_npis)]

        # --- Fraud labels ---
        n_fraud = int(n_claims * fraud_ratio)
        labels = np.zeros(n_claims)
        fraud_indices = self.rng.choice(n_claims, size=n_fraud, replace=False)
        labels[fraud_indices] = 1.0

        # --- Structured features per node type ---
        # Claims: 10 features (flags, amounts, dates encoded as floats)
        claim_feats = self.rng.randn(n_claims, 10).astype(np.float32)
        # Fraudulent claims get shifted features (higher amounts, unusual patterns)
        claim_feats[fraud_indices] += self.rng.uniform(1.0, 3.0, size=(n_fraud, 10))

        entity_feats = self.rng.randn(n_entities, 5).astype(np.float32)
        address_feats = self.rng.randn(n_addresses, 3).astype(np.float32)
        npi_feats = self.rng.randn(n_npis, 4).astype(np.float32)

        # --- Note embeddings (only for claims) ---
        emb_dim = cfg.note_embedding_dim
        claim_embeddings: dict[str, np.ndarray] = {}
        for i, cid in enumerate(claim_ids):
            emb = self.rng.randn(emb_dim).astype(np.float32) * 0.1
            if labels[i] == 1.0:
                # Fraud claims cluster in embedding space
                emb[:emb_dim // 4] += 1.5
            claim_embeddings[cid] = emb

        # --- Edges ---
        # 1. entity -> claim: each claim has 1-3 entities
        entity_claim_src, entity_claim_dst = [], []
        for ci, cid in enumerate(claim_ids):
            n_ents = self.rng.randint(1, 4)
            ents = self.rng.choice(n_entities, size=n_ents, replace=False)
            for ei in ents:
                entity_claim_src.append(entity_ids[ei])
                entity_claim_dst.append(cid)

        # 2. entity -> address: each entity has 1-2 addresses
        entity_addr_src, entity_addr_dst = [], []
        for ei, eid in enumerate(entity_ids):
            n_addrs = self.rng.randint(1, 3)
            addrs = self.rng.choice(n_addresses, size=n_addrs, replace=False)
            for ai in addrs:
                entity_addr_src.append(eid)
                entity_addr_dst.append(address_ids[ai])

        # 3. entity -> npi: ~30% of entities have an NPI link
        entity_npi_src, entity_npi_dst = [], []
        for ei in range(n_entities):
            if self.rng.random() < 0.3:
                npi_idx = self.rng.randint(0, n_npis)
                entity_npi_src.append(entity_ids[ei])
                entity_npi_dst.append(npi_ids[npi_idx])

        # 4. claim -> address: each claim has a service location
        claim_addr_src, claim_addr_dst = [], []
        for ci in range(n_claims):
            ai = self.rng.randint(0, n_addresses)
            claim_addr_src.append(claim_ids[ci])
            claim_addr_dst.append(address_ids[ai])

        # 5. npi -> claim: each NPI appears on some claims
        npi_claim_src, npi_claim_dst = [], []
        for ni in range(n_npis):
            n_claims_for_npi = self.rng.randint(1, max(2, n_claims // n_npis * 2))
            claims_for_npi = self.rng.choice(n_claims, size=n_claims_for_npi, replace=False)
            for ci in claims_for_npi:
                npi_claim_src.append(npi_ids[ni])
                npi_claim_dst.append(claim_ids[ci])

        # 6. entity -> entity: co-occurrence (sparse)
        entity_entity_src, entity_entity_dst = [], []
        n_co = min(n_entities, n_claims // 2)
        for _ in range(n_co):
            e1, e2 = self.rng.choice(n_entities, size=2, replace=False)
            entity_entity_src.append(entity_ids[e1])
            entity_entity_dst.append(entity_ids[e2])

        # --- FRAUD PATTERNS: shared-address rings ---
        n_rings = max(1, n_fraud // 5)
        for _ in range(n_rings):
            ring_addr = address_ids[self.rng.randint(0, n_addresses)]
            ring_entities = self.rng.choice(
                [entity_ids[fi] for fi in fraud_indices[:n_entities] if fi < n_entities]
                or entity_ids[:3],
                size=min(3, n_fraud),
                replace=True,
            )
            for eid in ring_entities:
                entity_addr_src.append(eid)
                entity_addr_dst.append(ring_addr)

        # --- FRAUD PATTERNS: high-degree NPI reuse ---
        if n_fraud > 2:
            fraud_npi = npi_ids[self.rng.randint(0, n_npis)]
            for fi in fraud_indices[:min(10, n_fraud)]:
                npi_claim_src.append(fraud_npi)
                npi_claim_dst.append(claim_ids[fi])

        # --- Assemble connectors ---
        nodes = {
            "claim": pd.DataFrame({"node_id": claim_ids}),
            "entity": pd.DataFrame({"node_id": entity_ids}),
            "address": pd.DataFrame({"node_id": address_ids}),
            "npi": pd.DataFrame({"node_id": npi_ids}),
        }
        edges = {
            ("entity", "files", "claim"): pd.DataFrame(
                {"src_id": entity_claim_src, "dst_id": entity_claim_dst}
            ),
            ("entity", "located_at", "address"): pd.DataFrame(
                {"src_id": entity_addr_src, "dst_id": entity_addr_dst}
            ),
            ("entity", "has_npi", "npi"): pd.DataFrame(
                {"src_id": entity_npi_src, "dst_id": entity_npi_dst}
            ),
            ("claim", "serviced_at", "address"): pd.DataFrame(
                {"src_id": claim_addr_src, "dst_id": claim_addr_dst}
            ),
            ("entity", "associated_with", "entity"): pd.DataFrame(
                {"src_id": entity_entity_src, "dst_id": entity_entity_dst}
            ),
            ("npi", "appears_on", "claim"): pd.DataFrame(
                {"src_id": npi_claim_src, "dst_id": npi_claim_dst}
            ),
        }

        graph_conn = InMemoryGraphDBConnector(self.config, nodes=nodes, edges=edges)

        features = {
            "claim": pd.DataFrame(
                claim_feats,
                index=claim_ids,
                columns=[f"feat_{i}" for i in range(10)],
            ),
            "entity": pd.DataFrame(
                entity_feats,
                index=entity_ids,
                columns=[f"feat_{i}" for i in range(5)],
            ),
            "address": pd.DataFrame(
                address_feats,
                index=address_ids,
                columns=[f"feat_{i}" for i in range(3)],
            ),
            "npi": pd.DataFrame(
                npi_feats,
                index=npi_ids,
                columns=[f"feat_{i}" for i in range(4)],
            ),
        }
        structured_conn = InMemoryStructuredDataConnector(self.config, features=features)

        vector_conn = InMemoryVectorDBConnector(
            self.config, embeddings={"claim": claim_embeddings}
        )

        label_series = pd.Series(labels, index=claim_ids)
        weight_series = pd.Series(np.ones(n_claims), index=claim_ids)
        label_conn = InMemoryLabelStoreConnector(
            self.config, labels=label_series, sample_weights=weight_series
        )

        return graph_conn, vector_conn, structured_conn, label_conn
