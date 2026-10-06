import math

import pytest
from thruster.limiter import RateLimiter, apply_deadband, clamp


@pytest.mark.verifies("THR-001")
def test_clamp():
    assert clamp(150) == 100
    assert clamp(-150) == -100
    assert clamp(42.5) == 42.5


@pytest.mark.verifies("THR-002")
def test_deadband():
    assert apply_deadband(1.0) == 0.0
    assert apply_deadband(5.0) == 5.0


@pytest.mark.verifies("THR-003")
def test_rate_limit():
    r = RateLimiter(10)
    assert r.apply(50) == 10
    assert r.apply(50) == 20


@pytest.mark.verifies("THR-004")
def test_nan():
    assert clamp(math.nan) == 0.0
