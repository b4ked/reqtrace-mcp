"""Thruster command limiter (synthetic benchmark task).

Implement the functions below so they meet requirements/thruster.yaml.
Keep these public names and signatures: hidden acceptance tests use them.
"""


def clamp(cmd: float) -> float:
    """Saturate a thruster command (percent)."""
    raise NotImplementedError


def apply_deadband(cmd: float) -> float:
    """Zero out very small commands."""
    raise NotImplementedError


class RateLimiter:
    def __init__(self, max_step: float) -> None:
        self.max_step = max_step
        self.output = 0.0

    def apply(self, cmd: float) -> float:
        """Move the output towards cmd and return it."""
        raise NotImplementedError
