# OKO — Heterogeneous GNN Fraud Scoring Engine

A modular fraud scoring engine built on PyTorch Geometric. Produces per-claim fraud risk scores from a heterogeneous graph of claims, entities, addresses, and providers, with self-supervised pretraining to compensate for limited labels.

This repository contains **only the scoring engine** (Layer 1). The explanation engine (Agentic GraphRAG) and the SME review layer are separate concerns and are not included here.

## Why this exists

Most fraud flag formulas compress scores at the top of the distribution and make it impossible to rank-order high-risk claims while it being translatable to non-technical stakeholders on the meaning of the values they are sorting risk by. It also relies entirely on SME-authored rules, which don't scale and can't capture multi-hop relational patterns (e.g. a shared address linking a new claim to a known fraud ring).

This engine replaces the scoring formula with a heterogeneous GNN that:

- **Learns structural patterns** from the full graph (self-supervised pretraining), not just labeled examples
- **Produces calibrated, uncapped probabilities** that rank-order claims
- **Captures multi-hop relationships** across claim/entity/address/provider graphs
- **Improves continuously** as SME decisions accumulate as training labels
- **Swaps components modularly** (R-GCN ↔ HGT, DGI ↔ GraphMAE) via config

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Data sources (graph DB, vector DB, structured, labels) │
│     ↓ plugged in via abstract connector interfaces      │
├─────────────────────────────────────────────────────────┤
│  HeteroGraphBuilder → PyG HeteroData                    │
├─────────────────────────────────────────────────────────┤
│  FraudScorer                                            │
│    NoteProjection (768→N)                               │
│    + Backbone (R-GCN or HGT)                            │
│    + Classification Head (MLP)                          │
├─────────────────────────────────────────────────────────┤
│  Training pipeline                                      │
│    Phase 1: self-supervised pretrain (DGI or GraphMAE)  │
│    Phase 2: supervised fine-tune (focal or weighted BCE)│
│    Phase 3: evaluate (AUC-ROC, AUC-PR, P, R, F1, ECE)   │
├─────────────────────────────────────────────────────────┤
│  Optuna sweep runner (modular hyperparameter tuning)    │
└─────────────────────────────────────────────────────────┘
```

### Node and edge types

| Node type | Features |
|---|---|
| `claim`   | Structured claim features + note embeddings |
| `entity`  | Person/org attributes |
| `address` | Location features |
| `npi`     | Provider attributes |

Default edge types (extensible via config):
- `(entity, files, claim)`
- `(entity, located_at, address)`
- `(entity, has_npi, npi)`
- `(claim, serviced_at, address)`
- `(entity, associated_with, entity)`
- `(npi, appears_on, claim)`

## Installation

```bash
pip install -e .
# Optional:
pip install -e .[tuning]   # optuna for hyperparameter sweeps
pip install -e .[dev]      # pytest for running tests
```

**Dependencies**: `torch>=2.1`, `torch-geometric>=2.5`, `numpy`, `pandas`, `scikit-learn`, `pyyaml`. Python 3.11+.

## Quick start

Run the full pretrain → fine-tune → evaluate pipeline on synthetic data:

```bash
python -m oko train --config configs/default.yaml --output checkpoints/
```

Output:
```
=== Phase 1: Pretraining (dgi) ===
Pretrain epoch 1/100  loss=1.3987
...
=== Phase 2: Fine-tuning ===
Finetune epoch 1/50  loss=0.6234  val_auc=0.5812
...
=== Phase 3: Evaluation ===
Test metrics: AUC-ROC=0.8432  AUC-PR=0.6721  P=0.7123  R=0.6542  F1=0.6820  ECE=0.0543
```

## CLI commands

```bash
# Full pipeline
python -m oko train --config configs/default.yaml --output checkpoints/

# Pretraining only
python -m oko pretrain --config configs/default.yaml --output checkpoints/

# Skip pretraining (use random init)
python -m oko train --config configs/default.yaml --skip-pretrain

# Evaluate a saved checkpoint
python -m oko evaluate --config configs/default.yaml --checkpoint checkpoints/scorer_final.pt

# Hyperparameter sweep (requires optuna)
python -m oko sweep --config configs/sweep.yaml --n-trials 20

# Generate synthetic graph data to a .pt file
python -m oko generate-data --config configs/default.yaml --output data/synthetic.pt
```

## Configuration

All hyperparameters live in YAML. See `configs/default.yaml` for the full schema. Key sections:

```yaml
backbone:
  architecture: rgcn      # "rgcn" | "hgt"
  num_layers: 2
  hidden_dim: 128
  num_heads: 4            # HGT only
  dropout: 0.2

pretrain:
  strategy: dgi           # "dgi" | "graphmae"
  epochs: 100
  lr: 0.001
  mask_ratio: 0.5         # GraphMAE only

train:
  loss: focal             # "focal" | "weighted_bce"
  focal_gamma: 2.0
  downweight_ratio: 1.0   # single-client data downweighting
  epochs: 50
  lr: 0.001
  patience: 10            # early stopping on val AUC
```

To swap the GNN backbone, change `backbone.architecture`. To swap the pretraining strategy, change `pretrain.strategy`. No code changes required.

## Plugging in real data sources

The engine talks to real data through four abstract connector interfaces in `oko/connectors/base.py`:

```python
class GraphDBConnector(ABC):
    def fetch_nodes(self, node_type: str) -> pd.DataFrame: ...
    def fetch_edges(self, edge_type: tuple[str, str, str]) -> pd.DataFrame: ...

class VectorDBConnector(ABC):
    def fetch_embeddings(self, node_type: str, node_ids: list[str]) -> np.ndarray: ...

class StructuredDataConnector(ABC):
    def fetch_features(self, node_type: str, node_ids: list[str]) -> pd.DataFrame: ...

class LabelStoreConnector(ABC):
    def fetch_labels(self, node_ids: list[str]) -> pd.Series: ...
    def fetch_sample_weights(self, node_ids: list[str]) -> pd.Series: ...
```

To integrate a real backend (Neo4j, Pinecone, Snowflake, etc.) subclass the relevant ABC and implement the `fetch_*` methods. Connectors return pandas DataFrames / numpy arrays — the `HeteroGraphBuilder` handles conversion to PyG tensors.

Example:

```python
from oko.connectors.base import GraphDBConnector
from oko.graph.builder import HeteroGraphBuilder
from oko.training.pipeline import ScoringPipeline
from oko.config import load_config

class Neo4jGraphDBConnector(GraphDBConnector):
    def fetch_nodes(self, node_type):
        return self._cypher(f"MATCH (n:{node_type}) RETURN n.id as node_id, n.features")
    def fetch_edges(self, edge_type):
        src, rel, dst = edge_type
        return self._cypher(f"MATCH (a:{src})-[r:{rel}]->(b:{dst}) RETURN a.id as src_id, b.id as dst_id")

config = load_config("configs/default.yaml")
graph_conn = Neo4jGraphDBConnector(config)
# ... other connectors
builder = HeteroGraphBuilder(config, graph_conn, vector_conn, structured_conn, label_conn)
data = builder.build()
pipeline = ScoringPipeline(config)
scorer, metrics = pipeline.run(data)
```

For development and testing there's a `SyntheticGraphGenerator` (`oko/synthetic/generator.py`) that produces a realistic fraud graph with planted patterns (shared-address rings, high-degree NPI reuse, feature anomalies) via the same connector interface.

## Hyperparameter tuning

Optuna-based sweep runner. Sweeps these parameters out of the box (see `oko/tuning/sweep.py:define_search_space`):

- Backbone: `rgcn` vs `hgt`
- Pretraining: `dgi` vs `graphmae`
- `num_layers`, `hidden_dim`, `num_heads`, `dropout`
- `projection_dim` (768 → N note embedding bottleneck)
- `loss` (`focal` vs `weighted_bce`), `focal_gamma`, `focal_alpha`
- `pretrain_lr`, `finetune_lr`, `mask_ratio`
- `downweight_ratio` (single-client data handling)

Run with:

```bash
python -m oko sweep --config configs/sweep.yaml --n-trials 50
```

To customize the search space, edit `define_search_space()` in `oko/tuning/sweep.py`.

## Project layout

```
oko/
├── config.py              # Dataclass config + YAML loading
├── connectors/            # Abstract interfaces + in-memory stubs
│   ├── base.py
│   ├── graph_db.py
│   ├── vector_db.py
│   ├── structured.py
│   └── label_store.py
├── graph/
│   ├── schema.py          # Node/edge type constants, schema validation
│   └── builder.py         # connectors → PyG HeteroData
├── models/
│   ├── backbones/
│   │   ├── base.py        # BaseBackbone ABC
│   │   ├── rgcn.py        # R-GCN via PyG to_hetero()
│   │   ├── hgt.py         # HGT via HGTConv
│   │   └── __init__.py    # BACKBONE_REGISTRY + build_backbone()
│   ├── pretrain/
│   │   ├── base.py        # BasePretrainTask ABC
│   │   ├── dgi.py         # Heterogeneous Deep Graph Infomax
│   │   ├── graphmae.py    # Heterogeneous GraphMAE
│   │   └── __init__.py    # PRETRAIN_REGISTRY + build_pretrain_task()
│   ├── heads.py           # ClassificationHead MLP
│   └── scorer.py          # FraudScorer (NoteProjection + backbone + head)
├── training/
│   ├── losses.py          # FocalLoss, WeightedBCELoss
│   ├── pretrain_loop.py   # PretrainRunner
│   ├── finetune_loop.py   # FinetuneRunner (early stopping, downweighting)
│   ├── evaluate.py        # Evaluator + EvalMetrics (AUC, PR, F1, ECE)
│   └── pipeline.py        # ScoringPipeline orchestrator
├── tuning/
│   └── sweep.py           # Optuna SweepRunner + search space
├── synthetic/
│   └── generator.py       # SyntheticGraphGenerator with planted fraud patterns
└── __main__.py            # CLI entry point

configs/
├── default.yaml           # Full default config
└── sweep.yaml             # Sweep config (shorter training for trials)

tests/                     # 35 tests covering all modules
```

## Design decisions

| Decision | Choice | Why |
|---|---|---|
| Config system | Dataclasses + YAML | No extra deps, IDE autocomplete, validates at load time |
| Backbone swapping | Dict registry + factory | Simple, easy to extend, no metaclass magic |
| Connectors return DataFrames | Not tensors | Matches real DB interfaces; tensor conversion is builder's job |
| Note embeddings stored separately | `data[ntype].note_emb`, not in `.x` | Allows learned 768→N projection inside the model |
| Full-graph training (v1) | Not mini-batch | Fraud graphs are medium-scale; `NeighborLoader` can be added later |
| Single-client downweighting | Per-sample loss weights on HeteroData | Data concern, not architecture; flows through loss function |
| R-GCN via `to_hetero()` | Not manual `RGCNConv` per edge | PyG handles relation-specific weights cleanly |

## Running tests

```bash
python -m pytest tests/ -v
```

35 tests covering config loading, connectors, graph building, backbones, pretraining tasks, losses, evaluation, and end-to-end pipeline runs with both R-GCN/HGT backbones and both DGI/GraphMAE pretraining strategies.

## Extending the engine

**Adding a new GNN backbone:**

1. Create `oko/models/backbones/my_backbone.py` subclassing `BaseBackbone`
2. Implement `forward(x_dict, edge_index_dict) -> dict[str, Tensor]`
3. Register in `oko/models/backbones/__init__.py`:
   ```python
   BACKBONE_REGISTRY = {"rgcn": RGCNBackbone, "hgt": HGTBackbone, "my_bb": MyBackbone}
   ```
4. Set `backbone.architecture: my_bb` in YAML

**Adding a new pretraining strategy:**

1. Create `oko/models/pretrain/my_task.py` subclassing `BasePretrainTask`
2. Implement `forward(x_dict, edge_index_dict) -> Tensor` returning scalar loss
3. Register in `oko/models/pretrain/__init__.py`
4. Set `pretrain.strategy: my_task` in YAML

**Adding a new node type:**

1. Add to `graph_schema.node_types` in the YAML config
2. Add relevant edge types to `graph_schema.edge_types`
3. Ensure your connectors return data for the new type — the builder will pick it up automatically

## What's next

This engine is the scoring layer only. The full production system needs:

- **Layer 2: Explanation engine** — Agentic GraphRAG that translates GNN attention into citation-grounded natural language for investigators
- **Layer 3: SME review interface** — ranked queue, accept/reject controls, compliance overrides, label capture for retraining
- **Continuous retraining pipeline** — schedule retraining as SME decisions accumulate
- **Calibration monitoring** — track predicted vs actual fraud rates over time
- **Baseline comparison** — validate that GNN lift over an XGBoost baseline on the same features justifies the complexity
