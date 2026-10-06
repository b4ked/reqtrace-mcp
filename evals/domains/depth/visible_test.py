import pytest
from depth.alarm import DepthAlarm, depth_m


@pytest.mark.verifies("DEP-001")
def test_depth_conversion():
    assert depth_m(201.843) == pytest.approx(10.0, abs=0.01)


@pytest.mark.verifies("DEP-002")
def test_surface():
    assert depth_m(101.325) == 0.0


@pytest.mark.verifies("DEP-003")
def test_raise_after_three():
    a = DepthAlarm(100)
    assert [a.update(101) for _ in range(3)] == [False, False, True]


@pytest.mark.verifies("DEP-004")
def test_clear_after_three():
    a = DepthAlarm(100)
    for _ in range(3):
        a.update(101)
    assert [a.update(99) for _ in range(3)] == [True, True, False]
