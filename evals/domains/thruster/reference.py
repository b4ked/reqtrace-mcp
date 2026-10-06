"""Thruster command limiter (synthetic benchmark task)."""

import math

CMD_LIMIT = 100.0
DEADBAND = 2.0


# implements: THR-001, THR-004
def clamp(cmd: float) -> float:
    """Saturate a thruster command (percent)."""
    if math.isnan(cmd):
        return 0.0
    return max(-CMD_LIMIT, min(CMD_LIMIT, cmd))


# implements: THR-002
def apply_deadband(cmd: float) -> float:
    """Zero out very small commands."""
    return 0.0 if abs(cmd) < DEADBAND else cmd


# implements: THR-003
class RateLimiter:
    def __init__(self, max_step: float) -> None:
        self.max_step = max_step
        self.output = 0.0

    def apply(self, cmd: float) -> float:
        """Move the output towards cmd and return it."""
        delta = max(-self.max_step, min(self.max_step, cmd - self.output))
        self.output += delta
        return self.output
