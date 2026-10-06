import pytest
from depth.alarm import DepthAlarm, depth_m


@pytest.mark.verifies("DEP-001")
@pytest.mark.parametrize("p,d", [(201.843, 10.0), (603.915, 50.0), (1106.505, 100.0)])
def test_depth_conversion(p, d):
    assert depth_m(p) == pytest.approx(d, abs=0.01)


@pytest.mark.verifies("DEP-002")
@pytest.mark.parametrize("p", [101.325, 90.0, 0.0])
def test_surface_clamp(p):
    assert depth_m(p) == 0.0


def feed(alarm, samples):
    return [alarm.update(s) for s in samples]


@pytest.mark.verifies("DEP-003")
def test_debounce_raise():
    assert feed(DepthAlarm(100), [101, 101, 101]) == [False, False, True]
    assert feed(DepthAlarm(100), [101, 101, 99, 101]) == [False, False, False, False]
    assert feed(DepthAlarm(100), [100, 100, 100]) == [False, False, False]


@pytest.mark.verifies("DEP-004")
def test_debounce_clear():
    a = DepthAlarm(100)
    feed(a, [101, 101, 101])
    assert feed(a, [99, 99, 99]) == [True, True, False]
    feed(a, [101, 101, 101])
    assert feed(a, [99, 99, 101, 99]) == [True, True, True, True]
    b = DepthAlarm(100)
    feed(b, [101, 101, 101])
    assert feed(b, [100, 100, 100]) == [True, True, False]
