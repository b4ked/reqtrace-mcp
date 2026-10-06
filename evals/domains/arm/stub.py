"""Robot-arm joint limit checker (synthetic benchmark task).

Implement the functions below so they meet requirements/arm.yaml.
Keep these public names and signatures: hidden acceptance tests use them.
"""


def validate_limits(lower: float, upper: float) -> None:
    """Raise ValueError if the limits are invalid."""
    raise NotImplementedError


def check_position(angle_deg: float, lower: float, upper: float) -> str:
    """Return "OK", "WARN" or "LIMIT"."""
    raise NotImplementedError


def check_velocity(deg_per_s: float, max_speed: float) -> bool:
    """True if the joint speed is acceptable."""
    raise NotImplementedError
