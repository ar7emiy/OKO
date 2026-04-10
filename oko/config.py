"""Dataclass-based configuration with YAML loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class GraphSchemaConfig:
    node_types: list[str] = field(
        default_factory=lambda: ["claim", "entity", "address", "npi"]
    )
    edge_types: list[list[str]] = field(
        default_factory=lambda: [
            ["entity", "files", "claim"],
            ["entity", "located_at", "address"],
            ["entity", "has_npi", "npi"],
            ["claim", "serviced_at", "address"],
            ["entity", "associated_with", "entity"],
            ["npi", "appears_on", "claim"],
        ]
    )
    attribute_node_types: list[str] = field(default_factory=list)

    @property
    def edge_type_tuples(self) -> list[tuple[str, str, str]]:
        return [tuple(e) for e in self.edge_types]


@dataclass
class DataConfig:
    note_embedding_dim: int = 768
    projection_dim: int = 64
    synthetic_num_claims: int = 2000
    synthetic_num_entities: int = 1500
    synthetic_num_addresses: int = 500
    synthetic_num_npis: int = 200
    synthetic_fraud_ratio: float = 0.05
    train_ratio: float = 0.6
    val_ratio: float = 0.2
    test_ratio: float = 0.2


@dataclass
class BackboneConfig:
    architecture: str = "rgcn"  # "rgcn" | "hgt"
    num_layers: int = 2
    hidden_dim: int = 128
    num_heads: int = 4  # HGT only
    dropout: float = 0.2


@dataclass
class PretrainConfig:
    strategy: str = "dgi"  # "dgi" | "graphmae"
    epochs: int = 100
    lr: float = 1e-3
    weight_decay: float = 1e-5
    mask_ratio: float = 0.5  # GraphMAE only
    patience: int = 20


@dataclass
class HeadConfig:
    hidden_dims: list[int] = field(default_factory=lambda: [64])
    dropout: float = 0.3


@dataclass
class TrainConfig:
    loss: str = "focal"  # "focal" | "weighted_bce"
    focal_gamma: float = 2.0
    focal_alpha: float = 0.25
    bce_pos_weight: float = 10.0
    downweight_ratio: float = 1.0  # single-client downweighting
    epochs: int = 50
    lr: float = 1e-3
    weight_decay: float = 1e-4
    patience: int = 10  # early stopping


@dataclass
class SweepConfig:
    n_trials: int = 50
    metric: str = "auc_roc"
    direction: str = "maximize"


@dataclass
class ScoringConfig:
    graph_schema: GraphSchemaConfig = field(default_factory=GraphSchemaConfig)
    data: DataConfig = field(default_factory=DataConfig)
    backbone: BackboneConfig = field(default_factory=BackboneConfig)
    pretrain: PretrainConfig = field(default_factory=PretrainConfig)
    head: HeadConfig = field(default_factory=HeadConfig)
    train: TrainConfig = field(default_factory=TrainConfig)
    sweep: SweepConfig = field(default_factory=SweepConfig)
    seed: int = 42
    device: str = "cpu"


def _dict_to_dataclass(cls: type, data: dict[str, Any]) -> Any:
    """Recursively convert a dict to nested dataclasses."""
    if not isinstance(data, dict):
        return data
    fieldtypes = {f.name: f.type for f in cls.__dataclass_fields__.values()}
    kwargs = {}
    for key, value in data.items():
        if key not in fieldtypes:
            continue
        ft = fieldtypes[key]
        # Resolve string type annotations to actual classes
        if isinstance(ft, str):
            ft = globals().get(ft, ft)
        if isinstance(ft, type) and hasattr(ft, "__dataclass_fields__") and isinstance(value, dict):
            kwargs[key] = _dict_to_dataclass(ft, value)
        else:
            kwargs[key] = value
    return cls(**kwargs)


# Map of field name -> dataclass type for nested config hydration
_NESTED_TYPES = {
    "graph_schema": GraphSchemaConfig,
    "data": DataConfig,
    "backbone": BackboneConfig,
    "pretrain": PretrainConfig,
    "head": HeadConfig,
    "train": TrainConfig,
    "sweep": SweepConfig,
}


def load_config(path: str | Path) -> ScoringConfig:
    """Load a ScoringConfig from a YAML file."""
    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    kwargs = {}
    for key, value in raw.items():
        if key in _NESTED_TYPES and isinstance(value, dict):
            kwargs[key] = _dict_to_dataclass(_NESTED_TYPES[key], value)
        else:
            kwargs[key] = value
    return ScoringConfig(**kwargs)


def config_to_dict(config: ScoringConfig) -> dict[str, Any]:
    """Serialize a ScoringConfig to a plain dict (for YAML export)."""
    from dataclasses import asdict
    return asdict(config)


def save_config(config: ScoringConfig, path: str | Path) -> None:
    """Save a ScoringConfig to a YAML file."""
    with open(path, "w") as f:
        yaml.dump(config_to_dict(config), f, default_flow_style=False, sort_keys=False)
