# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

OKO is a heterogeneous GNN fraud scoring engine built on PyTorch Geometric. It scores `claim` nodes for fraud risk on a graph of claims, entities, addresses, and providers (NPIs), using self-supervised pretraining followed by supervised fine-tuning. This repo contains only the scoring engine (Layer 1) — the explanation engine and SME review layer are out of scope.

## Commands

```bash
pip install -e .            # install (Python 3.11+; torch, torch-geometric required)
pip install -e .[dev]       # pytest
pip install -e .[tuning]    # optuna, needed only for `sweep`

pip install -e .[ingest]    # httpx, tenacity, pyarrow, duckdb, pandera (oko_ingest only)

python -m pytest tests/ -v                          # all tests
python -m pytest tests/test_training.py -v          # one file
python -m pytest tests/test_training.py::test_name  # one test
python -m pytest tests/test_ingest.py -v            # ingestion tests (no torch needed)

# Ingestion CLI (see oko_ingest/__main__.py)
python -m oko_ingest pull --source leie --data-dir data/staging
python -m oko_ingest pull --source nppes --data-dir data/staging \
    --from-file monthly.csv --from-file weekly.csv --snapshot-date 2026-06-01
python -m oko_ingest vintages --data-dir data/staging

# CLI (see oko/__main__.py)
python -m oko train --config configs/default.yaml --output checkpoints/
python -m oko train --config configs/default.yaml --skip-pretrain
python -m oko pretrain --config configs/default.yaml --output checkpoints/
python -m oko evaluate --config configs/default.yaml --checkpoint checkpoints/scorer_final.pt
python -m oko sweep --config configs/sweep.yaml --n-trials 20
python -m oko generate-data --config configs/default.yaml --output data/synthetic.pt
```

There is no linter configured. Tests run on CPU with small synthetic graphs (see `tiny_config` / `tiny_data` fixtures in `tests/conftest.py`).

## Architecture

Data flow: **connectors → `HeteroGraphBuilder` → PyG `HeteroData` → `ScoringPipeline` (pretrain → fine-tune → evaluate)**.

- `oko/config.py` — everything is configured via nested dataclasses (`ScoringConfig`) hydrated from YAML by `load_config()`. Unknown YAML keys are silently dropped. Behavior changes (backbone, pretrain strategy, loss) should be config-driven, not hardcoded.
- `oko/connectors/` — four ABCs in `base.py` (`GraphDBConnector`, `VectorDBConnector`, `StructuredDataConnector`, `LabelStoreConnector`) returning pandas DataFrames / numpy arrays. In-memory stub implementations live in the sibling modules. Real backends (Neo4j, Pinecone, etc.) are integrated by subclassing these ABCs; tensor conversion is exclusively the builder's job.
- `oko/graph/builder.py` — builds `HeteroData`: maps string node IDs to indices, filters edges to known nodes, attaches labels/sample weights/stratified train-val-test masks to the `claim` node type, and applies `T.ToUndirected()` to add reverse edges for message passing.
- `oko/models/` — `FraudScorer` (`scorer.py`) composes `NoteProjection` + backbone + `ClassificationHead`. Its target node type is hardcoded to `"claim"`. Backbones and pretrain tasks are selected via dict registries with factory functions (`BACKBONE_REGISTRY` in `models/backbones/__init__.py`, `PRETRAIN_REGISTRY` in `models/pretrain/__init__.py`); to add one, subclass the base ABC and add an entry to the registry, then reference it by name in YAML.
- `oko/training/` — `ScoringPipeline` (`pipeline.py`) orchestrates the three phases and transfers pretrained backbone weights into the fresh `FraudScorer`. `PretrainRunner` / `FinetuneRunner` are the loops (fine-tuning has early stopping on val AUC and per-sample downweighting); `losses.py` has `FocalLoss` / `WeightedBCELoss`; `evaluate.py` computes AUC-ROC, AUC-PR, P/R/F1, ECE.
- `oko/synthetic/generator.py` — `SyntheticGraphGenerator` builds dev/test graphs with planted fraud patterns (shared-address rings, NPI reuse, feature anomalies), going through the same connector → builder path as real data.
- `oko/tuning/sweep.py` — Optuna sweep; the search space is `define_search_space()`.
- `oko_ingest/` — separate package (never imported by `oko/`) that bulk-ingests public datasets (NPPES, LEIE, SAM exclusions, PECOS) into an append-only `SnapshotStore` of snapshot-dated Parquet partitions queryable via DuckDB (`staging.py`). Sources subclass `BulkSource` (`sources/base.py`) and are registered in `SOURCE_REGISTRY`; staged tables are validated by pandera schemas (`schemas.py`). Snapshots are immutable — vintage retention backs as-of graph reconstruction (see `docs/`). Parsers emit pandas `"string"` dtype with `pd.NA` (never object-with-None). Design docs live in `docs/`.

## Key conventions

- **Note embeddings are stored separately** as `data[ntype].note_emb`, never concatenated into `.x` at build time. The model concatenates `.x` with the learned 768→`projection_dim` projection at forward time (`FraudScorer._prepare_features`). Preserve this split when touching feature handling.
- **Training is full-graph** (no mini-batching / `NeighborLoader`) — a deliberate v1 choice.
- Per-sample loss weights (`data["claim"].sample_weight`) implement single-client downweighting; this flows through the loss functions, not the architecture.
- R-GCN is built via PyG `to_hetero()`, not manual per-relation `RGCNConv`.
- Reproducibility comes from `config.seed`; default device is CPU.
