"""Entity-resolution and reference-graph-construction layer (M2).

Stage-1 deterministic resolution + canonical graph construction + normalization
(docs/data-sourcing-engine.md §3.4, §5.2). The probabilistic stage (§3.4 stages
3-4) is a documented stub in :mod:`oko_ingest.resolve.probabilistic`.
"""

from oko_ingest.resolve.deterministic import (
    ResolutionResult,
    resolve_deterministic,
)
from oko_ingest.resolve.graph import ReferenceGraph, build_reference_graph
from oko_ingest.resolve.normalize import (
    normalize_address,
    normalize_org_name,
    normalize_person_name,
)

__all__ = [
    "ResolutionResult",
    "resolve_deterministic",
    "ReferenceGraph",
    "build_reference_graph",
    "normalize_address",
    "normalize_org_name",
    "normalize_person_name",
]
