"""NPI validation (Luhn check with the 80840 card-issuer prefix)."""

from __future__ import annotations

_PREFIX = "80840"


def is_valid_npi(npi: str | int | None) -> bool:
    """Validate a 10-digit NPI via the CMS Luhn check-digit algorithm.

    The check digit is computed over the 9-digit base prefixed with 80840
    (the health-industry card-issuer prefix), per the NPI standard.
    """
    s = str(npi).strip() if npi is not None else ""
    if len(s) != 10 or not s.isdigit():
        return False
    digits = [int(c) for c in _PREFIX + s[:9]]
    total = 0
    # Double alternate digits starting from the rightmost of the base.
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    check = (10 - total % 10) % 10
    return check == int(s[9])
