"""Toy low-altitude alerter (synthetic example)."""

import math

MIN_FLOOR_FT = 100.0
MAX_FLOOR_FT = 2000.0


# implements: ALT-002
def validate_floor(floor_ft: float) -> float:
    if not MIN_FLOOR_FT <= floor_ft <= MAX_FLOOR_FT:
        raise ValueError(f"floor {floor_ft} ft outside {MIN_FLOOR_FT}-{MAX_FLOOR_FT} ft")
    return floor_ft


# implements: ALT-001, ALT-003
def altitude_alert(alt_ft: float, floor_ft: float = 500.0) -> bool:
    if not math.isfinite(alt_ft) or alt_ft < 0:
        return True
    return alt_ft < validate_floor(floor_ft)


def altitude_in_metres(alt_ft: float) -> float:
    return alt_ft * 0.3048
