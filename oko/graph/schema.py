"""Node/edge type constants and HeteroData schema validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from torch_geometric.data import HeteroData

    from oko.config import GraphSchemaConfig

# Default canonical types
DEFAULT_NODE_TYPES: list[str] = ["claim", "entity", "address", "npi"]

DEFAULT_EDGE_TYPES: list[tuple[str, str, str]] = [
    ("entity", "files", "claim"),
    ("entity", "located_at", "address"),
    ("entity", "has_npi", "npi"),
    ("claim", "serviced_at", "address"),
    ("entity", "associated_with", "entity"),
    ("npi", "appears_on", "claim"),
]


def validate_schema(config: GraphSchemaConfig, data: HeteroData) -> list[str]:
    """Check that a HeteroData object matches the expected schema.

    Returns a list of warning messages (empty if valid).
    """
    warnings: list[str] = []
    expected_node_types = set(config.node_types)
    actual_node_types = set(data.node_types)

    missing_nodes = expected_node_types - actual_node_types
    if missing_nodes:
        warnings.append(f"Missing node types in data: {missing_nodes}")

    expected_edges = {tuple(e) for e in config.edge_types}
    actual_edges = set(data.edge_types)
    # Only check forward edges — reverse edges added by ToUndirected are fine
    missing_edges = expected_edges - actual_edges
    if missing_edges:
        warnings.append(f"Missing edge types in data: {missing_edges}")

    # Verify every node type has features
    for ntype in actual_node_types & expected_node_types:
        if not hasattr(data[ntype], "x") or data[ntype].x is None:
            warnings.append(f"Node type '{ntype}' has no feature tensor (.x)")

    return warnings
