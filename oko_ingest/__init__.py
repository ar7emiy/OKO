"""OKO ingest: Tier-1 bulk ingestion for the reference graph (M1).

Pulls public bulk datasets (NPPES, LEIE, SAM exclusions, PECOS), validates
them against pandera schemas, and stages them as immutable snapshot-dated
Parquet partitions queryable via DuckDB.

Design: docs/data-sourcing-engine.md. The scoring engine (`oko/`) never
imports this package; the only hand-off is the staged Parquet store.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
