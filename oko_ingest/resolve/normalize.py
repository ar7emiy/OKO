"""Deterministic, Windows-friendly normalization for blocking/canonical keys.

Pure functions only — no I/O, no global state — so they are trivially
unit-testable and reproducible (docs/data-sourcing-engine.md §3.4 stage 2).

Three normalizers, each producing a *blocking/canonical key*, never a stored
display value (the survivorship layer keeps original strings as provenance):

- :func:`normalize_address` -> canonical address key. Uses ``usaddress`` (CRF
  tagger; installs from a prebuilt ``cp313`` wheel on Windows — no C build,
  unlike libpostal/pypostal which the spec explicitly forbids here). The tagged
  components are folded to USPS-style abbreviations so surface variants
  ("STE 100", "Suite #100", "Street"/"St") collapse to one key. A regex
  fallback covers strings ``usaddress`` cannot tag.
- :func:`normalize_org_name` -> org blocking key (legal-suffix stripping).
- :func:`normalize_person_name` -> person blocking key.

Determinism: identical input -> identical output, no randomness, no network.
"""

from __future__ import annotations

import re

try:  # prebuilt cp313 wheel on Windows; see module docstring
    import usaddress

    _HAVE_USADDRESS = True
except Exception:  # pragma: no cover - exercised only where the wheel is absent
    _HAVE_USADDRESS = False


# --- shared helpers ---------------------------------------------------------

_WS_RE = re.compile(r"\s+")
_NON_ALNUM_SPACE_RE = re.compile(r"[^A-Z0-9 ]")


def _squash(text: str) -> str:
    """Upper-case, strip punctuation to spaces, collapse whitespace."""
    up = text.upper()
    up = _NON_ALNUM_SPACE_RE.sub(" ", up)
    return _WS_RE.sub(" ", up).strip()


# --- address ----------------------------------------------------------------

# USPS Pub-28 style canonicalization of street-type and unit-type words.
_STREET_TYPE_MAP = {
    "STREET": "ST", "ST": "ST",
    "AVENUE": "AVE", "AVE": "AVE", "AV": "AVE",
    "BOULEVARD": "BLVD", "BLVD": "BLVD",
    "ROAD": "RD", "RD": "RD",
    "DRIVE": "DR", "DR": "DR",
    "LANE": "LN", "LN": "LN",
    "COURT": "CT", "CT": "CT",
    "PLACE": "PL", "PL": "PL",
    "CIRCLE": "CIR", "CIR": "CIR",
    "HIGHWAY": "HWY", "HWY": "HWY",
    "PARKWAY": "PKWY", "PKWY": "PKWY",
    "TERRACE": "TER", "TER": "TER",
    "TRAIL": "TRL", "TRL": "TRL",
    "SUITE": "STE", "STE": "STE",
    "APARTMENT": "APT", "APT": "APT",
    "UNIT": "UNIT",
    "BUILDING": "BLDG", "BLDG": "BLDG",
    "FLOOR": "FL", "FL": "FL",
    "ROOM": "RM", "RM": "RM",
    "NUMBER": "", "NO": "", "NUM": "",
}

_DIRECTION_MAP = {
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
    "NORTHEAST": "NE", "NORTHWEST": "NW",
    "SOUTHEAST": "SE", "SOUTHWEST": "SW",
    "N": "N", "S": "S", "E": "E", "W": "W",
    "NE": "NE", "NW": "NW", "SE": "SE", "SW": "SW",
}


def _canon_token(tok: str) -> str:
    """Fold one address token to its canonical abbreviation."""
    t = tok.strip().upper().replace("#", "")
    if not t:
        return ""
    if t in _STREET_TYPE_MAP:
        return _STREET_TYPE_MAP[t]
    if t in _DIRECTION_MAP:
        return _DIRECTION_MAP[t]
    return t


def _canon_component(value: str) -> str:
    cleaned = _squash(value.replace("#", " "))
    toks = [_canon_token(t) for t in cleaned.split(" ")]
    return " ".join(t for t in toks if t)


def _zip5(value: str) -> str:
    digits = re.sub(r"\D", "", value or "")
    return digits[:5]


def normalize_address(
    line1: str | None,
    city: str | None = None,
    state: str | None = None,
    zip_code: str | None = None,
) -> str:
    """Return a canonical address key, or ``""`` for an empty street line.

    The key is a pipe-joined tuple of normalized components:
    ``"<street> <unit> | <city> | <state> | <zip5>"``. ZIP+4 is reduced to
    ZIP5 so the key is stable across vintages that vary the +4. Surface
    variants of the same address collapse to one key by design.
    """
    line1 = (line1 or "").strip()
    if not line1:
        return ""

    street_part = ""
    unit_part = ""
    parsed_city = ""
    parsed_state = ""
    parsed_zip = ""

    if _HAVE_USADDRESS:
        try:
            tagged, _ = usaddress.tag(line1)
        except Exception:
            tagged = {}
        street_fields = [
            "AddressNumber",
            "StreetNamePreDirectional",
            "StreetName",
            "StreetNamePostType",
            "StreetNamePostDirectional",
        ]
        unit_fields = ["OccupancyType", "OccupancyIdentifier"]
        street_part = _canon_component(
            " ".join(tagged.get(f, "") for f in street_fields)
        )
        unit_part = _canon_component(
            " ".join(tagged.get(f, "") for f in unit_fields)
        )
        parsed_city = _canon_component(tagged.get("PlaceName", ""))
        parsed_state = _canon_component(tagged.get("StateName", ""))
        parsed_zip = _zip5(tagged.get("ZipCode", ""))

    # Fallback / fill: when usaddress is unavailable or failed to split unit.
    if not street_part:
        street_part = _canon_component(line1)

    city_part = parsed_city or _canon_component(city or "")
    state_part = parsed_state or _canon_component(state or "")
    zip_part = parsed_zip or _zip5(zip_code or "")

    street = (street_part + (" " + unit_part if unit_part else "")).strip()
    return f"{street} | {city_part} | {state_part} | {zip_part}"


# --- organization name ------------------------------------------------------

# Legal-entity suffixes stripped to form a blocking key (never the stored name).
_ORG_SUFFIXES = {
    "LLC", "LLP", "LP", "LTD", "INC", "INCORPORATED", "CORP", "CORPORATION",
    "CO", "COMPANY", "PC", "PA", "PLLC", "PLC", "PC", "GROUP", "GRP",
    "ASSOCIATES", "ASSOC", "ASSN", "FOUNDATION", "TRUST", "DBA",
}

# Token-level expansions for common medical abbreviations (blocking only).
_ORG_TOKEN_MAP = {
    "MED": "MEDICAL",
    "CTR": "CENTER",
    "CTRS": "CENTERS",
    "HOSP": "HOSPITAL",
    "SVCS": "SERVICES",
    "SVC": "SERVICE",
    "HLTH": "HEALTH",
    "PHARM": "PHARMACY",
    "LABS": "LAB",
    "LABORATORY": "LAB",
    "LABORATORIES": "LAB",
}


def normalize_org_name(name: str | None) -> str:
    """Return an organization blocking key (suffix-stripped, expanded)."""
    if not name:
        return ""
    squashed = _squash(name)
    if not squashed:
        return ""
    toks = squashed.split(" ")
    toks = [_ORG_TOKEN_MAP.get(t, t) for t in toks]
    # Drop trailing legal suffixes (repeatedly: "FOO MEDICAL INC LLC").
    while toks and toks[-1] in _ORG_SUFFIXES:
        toks.pop()
    if not toks:  # name was nothing but suffixes; keep them for a stable key
        toks = squashed.split(" ")
    return " ".join(toks)


# --- person name ------------------------------------------------------------

_NAME_SUFFIXES = {"JR", "SR", "II", "III", "IV", "MD", "DO", "DDS", "PHD", "RN", "NP"}


def normalize_person_name(
    first: str | None,
    last: str | None,
    middle: str | None = None,
) -> str:
    """Return a person blocking key: ``"<LAST> <FIRST> <MIDDLE_INITIAL>"``.

    Honorific/degree suffixes are dropped; the middle name is reduced to its
    initial so "Robert J" and "Robert James" block together.
    """
    first_s = _squash(first or "")
    last_s = _squash(last or "")
    middle_s = _squash(middle or "")

    last_toks = [t for t in last_s.split(" ") if t and t not in _NAME_SUFFIXES]
    first_toks = [t for t in first_s.split(" ") if t and t not in _NAME_SUFFIXES]

    last_key = " ".join(last_toks)
    first_key = first_toks[0] if first_toks else ""
    middle_init = ""
    if middle_s:
        middle_init = middle_s[0]
    elif len(first_toks) > 1:
        middle_init = first_toks[1][0]

    parts = [p for p in (last_key, first_key, middle_init) if p]
    return " ".join(parts)
