"""Robot-arm joint limit checker (synthetic benchmark task)."""

SOFT_ZONE_DEG = 5.0
MIN_SPAN_DEG = 10.0


# implements: JNT-004
def validate_limits(lower: float, upper: float) -> None:
    """Raise ValueError if the limits are invalid."""
    if lower >= upper or (upper - lower) < MIN_SPAN_DEG:
        raise ValueError(f"invalid joint limits ({lower}, {upper})")


# implements: JNT-001, JNT-002
def check_position(angle_deg: float, lower: float, upper: float) -> str:
    """Return "OK", "WARN" or "LIMIT"."""
    validate_limits(lower, upper)
    if angle_deg < lower or angle_deg > upper:
        return "LIMIT"
    if angle_deg < lower + SOFT_ZONE_DEG or angle_deg > upper - SOFT_ZONE_DEG:
        return "WARN"
    return "OK"


# implements: JNT-003
def check_velocity(deg_per_s: float, max_speed: float) -> bool:
    """True if the joint speed is acceptable."""
    return abs(deg_per_s) <= max_speed
