import pytest
from arm.limits import check_position, check_velocity, validate_limits


@pytest.mark.verifies("JNT-001")
@pytest.mark.parametrize("angle,expected", [(100.01, "LIMIT"), (-0.01, "LIMIT"), (250, "LIMIT")])
def test_hard_limit(angle, expected):
    assert check_position(angle, 0, 100) == expected


@pytest.mark.verifies("JNT-001")
def test_limit_value_itself_is_not_limit():
    assert check_position(100, 0, 100) != "LIMIT"
    assert check_position(0, 0, 100) != "LIMIT"


@pytest.mark.verifies("JNT-002")
@pytest.mark.parametrize("angle,expected", [(4.99, "WARN"), (5.0, "OK"), (50, "OK"),
                                            (95.0, "OK"), (95.01, "WARN"), (100, "WARN"),
                                            (0, "WARN")])
def test_soft_zone(angle, expected):
    assert check_position(angle, 0, 100) == expected


@pytest.mark.verifies("JNT-003")
@pytest.mark.parametrize("speed,ok", [(30, True), (-30, True), (30.1, False), (-30.1, False)])
def test_speed(speed, ok):
    assert check_velocity(speed, 30) is ok


@pytest.mark.verifies("JNT-004")
def test_limit_validation():
    validate_limits(0, 10)
    for lo, hi in [(0, 9.9), (10, 0), (5, 5)]:
        with pytest.raises(ValueError):
            validate_limits(lo, hi)
    with pytest.raises(ValueError):
        check_position(1, 0, 5)
