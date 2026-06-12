"""Source registry: one module per Tier-1 bulk dataset."""

from oko_ingest.sources.base import BulkSource
from oko_ingest.sources.leie import LEIESource
from oko_ingest.sources.nppes import NPPESSource
from oko_ingest.sources.pecos import PECOSSource
from oko_ingest.sources.sam import SAMExclusionsSource

SOURCE_REGISTRY: dict[str, type[BulkSource]] = {
    "nppes": NPPESSource,
    "leie": LEIESource,
    "sam": SAMExclusionsSource,
    "pecos": PECOSSource,
}

__all__ = ["BulkSource", "SOURCE_REGISTRY"]
