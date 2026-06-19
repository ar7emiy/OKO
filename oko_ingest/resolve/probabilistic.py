"""Stage 3-4 probabilistic resolution — EXTENSION POINT (not implemented).

This is the documented seam for the probabilistic pass described in
docs/data-sourcing-engine.md §3.4 stages 3 (Fellegi-Sunter via Splink on the
DuckDB backend) and 4 (banding + connected-components clustering, with the
ambiguous middle band routed to review).

It is deliberately a stub:

- It needs **real data** to tune (EM training, term-frequency adjustments,
  blocking-rule selection) — synthetic fixtures cannot calibrate it.
- **Splink** install on py3.13/Windows is uncertain, so it is not a dependency
  of this milestone (M2 deterministic core).

Intended contract when implemented:

    def resolve_probabilistic(
        result: ResolutionResult,          # Stage-1 clusters to extend
        records: pd.DataFrame,             # candidate records with blocking keys
        *,
        match_threshold: float = 0.99,     # auto-merge ceiling (§3.4 stage 4)
        reject_threshold: float = 0.01,    # auto-reject floor
    ) -> ResolutionResult: ...

It must:
1. Build blocking keys via :mod:`oko_ingest.resolve.normalize`
   (ZIP5+name-metaphone, street-number+surname, cleaned-org-token).
2. Score pairs with Splink's Fellegi-Sunter model.
3. ``union`` auto-match pairs into the existing :class:`UnionFind`, leaving the
   gray band for human/LLM adjudication (never auto-merged here).
4. Preserve provenance as non-destructive ``same_as`` edges (§3.4 stage 5),
   never lossy merges.

Until then, callers run deterministic resolution only.
"""

from __future__ import annotations

from oko_ingest.resolve.deterministic import ResolutionResult


def resolve_probabilistic(*args, **kwargs) -> ResolutionResult:  # noqa: D401
    """Not implemented — see module docstring and §3.4 stages 3-4."""
    raise NotImplementedError(
        "Probabilistic resolution (Splink Fellegi-Sunter) is out of scope for "
        "M2; it requires real data to tune. See oko_ingest/resolve/probabilistic.py "
        "and docs/data-sourcing-engine.md §3.4 stages 3-4."
    )
