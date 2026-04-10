"""Tests for graph schema and builder."""

from oko.graph.schema import validate_schema


def test_validate_schema_passes(tiny_config, tiny_data):
    warnings = validate_schema(tiny_config.graph_schema, tiny_data)
    # No missing node types
    missing_nodes = [w for w in warnings if "Missing node types" in w]
    assert len(missing_nodes) == 0


def test_builder_creates_edge_index(tiny_data):
    # At least the forward edges should exist
    found_types = set(tiny_data.edge_types)
    assert len(found_types) > 0
    # ToUndirected should have added reverse edges
    assert len(found_types) > 6  # 6 forward + reverses
