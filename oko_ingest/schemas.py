"""Pandera schemas for staged tables.

Every staged table is validated before it is written. Note the privacy gate
(docs/data-sourcing-engine.md §1 #7): SSN and DOB columns are dropped at
parse time and never reach staging, so no schema below carries them.
"""

from __future__ import annotations

import pandas as pd

try:  # pandera >= 0.24 namespaced the pandas API
    import pandera.pandas as pa
except ImportError:  # pragma: no cover
    import pandera as pa

# Parsers emit pandas "string" dtype with real pd.NA (never object-with-None,
# which coercion would stringify); all columns coerce to schema dtypes.
_NPI_CHECK = pa.Check.str_matches(r"^\d{10}$")
_STR = pa.Column(str, nullable=True, coerce=True)
_DATE = pa.Column("datetime64[ns]", nullable=True, coerce=True)

NPPES_SCHEMA = pa.DataFrameSchema(
    {
        "npi": pa.Column(str, checks=_NPI_CHECK, nullable=False, coerce=True),
        "entity_type": pa.Column(
            "Int64", checks=pa.Check.isin([1, 2]), nullable=True, coerce=True
        ),
        "org_name": _STR,
        "last_name": _STR,
        "first_name": _STR,
        "taxonomy_code": _STR,
        "address_1": _STR,
        "city": _STR,
        "state": _STR,
        "zip": _STR,
        "enumeration_date": _DATE,
        "last_update_date": _DATE,
        "deactivation_date": _DATE,
        "is_deactivated": pa.Column(bool, coerce=True),
    },
    unique=["npi"],
    strict=True,
)

LEIE_SCHEMA = pa.DataFrameSchema(
    {
        "last_name": _STR,
        "first_name": _STR,
        "mid_name": _STR,
        "bus_name": _STR,
        "general": _STR,
        "specialty": _STR,
        "npi": pa.Column(str, checks=_NPI_CHECK, nullable=True, coerce=True),
        "address": _STR,
        "city": _STR,
        "state": _STR,
        "zip": _STR,
        "excl_type": pa.Column(str, nullable=False, coerce=True),
        "excl_date": pa.Column("datetime64[ns]", nullable=False, coerce=True),
        "rein_date": _DATE,
        "waiver_date": _DATE,
    },
    strict=True,
)

SAM_EXCLUSIONS_SCHEMA = pa.DataFrameSchema(
    {
        "classification": _STR,
        "name": pa.Column(str, nullable=False, coerce=True),
        "uei": _STR,
        "cage": _STR,
        "exclusion_type": _STR,
        "exclusion_program": _STR,
        "excluding_agency": _STR,
        "activation_date": _DATE,
        "termination_date": _DATE,
        "city": _STR,
        "state": _STR,
        "zip": _STR,
    },
    strict=True,
)

PECOS_ENROLLMENT_SCHEMA = pa.DataFrameSchema(
    {
        "enrollment_id": pa.Column(str, nullable=False, coerce=True),
        "npi": pa.Column(str, checks=_NPI_CHECK, nullable=False, coerce=True),
        "provider_type": _STR,
        "state": _STR,
        "org_name": _STR,
        "first_name": _STR,
        "last_name": _STR,
    },
    strict=True,
)

PECOS_REASSIGNMENT_SCHEMA = pa.DataFrameSchema(
    {
        "reassigning_enrollment_id": pa.Column(str, nullable=False, coerce=True),
        "receiving_enrollment_id": pa.Column(str, nullable=False, coerce=True),
    },
    strict=True,
)

TABLE_SCHEMAS: dict[str, pa.DataFrameSchema] = {
    "nppes": NPPES_SCHEMA,
    "leie": LEIE_SCHEMA,
    "sam_exclusions": SAM_EXCLUSIONS_SCHEMA,
    "pecos_enrollment": PECOS_ENROLLMENT_SCHEMA,
    "pecos_reassignment": PECOS_REASSIGNMENT_SCHEMA,
}


def validate(table: str, df: pd.DataFrame) -> pd.DataFrame:
    """Validate (and coerce) a staged table; raises pandera.errors.SchemaError."""
    return TABLE_SCHEMAS[table].validate(df)
