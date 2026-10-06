import math

import pytest
from thruster.limiter import RateLimiter, apply_deadband, clamp


@pytest.mark.verifies("THR-001")
@pytest.mark.parametrize("cmd,out", [(150, 100), (-150, -100), (100, 100), (-100, -100),
                                     (42.5, 42.5)])
def test_clamp(cmd, out):
    assert clamp(cmd) == out


@pytest.mark.verifies("THR-002")
@pytest.mark.parametrize("cmd,out", [(1.99, 0.0), (-1.99, 0.0), (0.0, 0.0), (2.0, 2.0),
                                     (-2.0, -2.0), (50, 50)])
def test_deadband(cmd, out):
    assert apply_deadband(cmd) == out


@pytest.mark.verifies("THR-003")
def test_rate_limit_up_and_down():
    r = RateLimiter(10)
    assert [r.apply(50) for _ in range(3)] == [10, 20, 30]
    assert r.apply(-50) == 20
    r2 = RateLimiter(10)
    assert r2.apply(4) == 4


@pytest.mark.verifies("THR-004")
def test_nan_command():
    out = clamp(float("nan"))
    assert out == 0.0 and not math.isnan(out)
