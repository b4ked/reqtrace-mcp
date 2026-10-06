import pytest
from arm.limits import check_position, check_velocity, validate_limits


@pytest.mark.verifies("JNT-001")
def test_outside_limits():
    assert check_position(100.01, 0, 100) == "LIMIT"
    assert check_position(-0.01, 0, 100) == "LIMIT"
    assert check_position(100, 0, 100) != "LIMIT"


@pytest.mark.verifies("JNT-002")
@pytest.mark.parametrize("angle,expected", [(4.99, "WARN"), (5.0, "OK"), (95.0, "OK"),
                                            (95.01, "WARN")])
def test_soft_zone(angle, expected):
    assert check_position(angle, 0, 100) == expected


@pytest.mark.verifies("JNT-003")
def test_speed():
    assert check_velocity(30, 30)
    assert not check_velocity(30.1, 30)
    assert not check_velocity(-30.1, 30)


@pytest.mark.verifies("JNT-004")
def test_invalid_limits():
    validate_limits(0, 10)
    with pytest.raises(ValueError):
        validate_limits(0, 9.9)
    with pytest.raises(ValueError):
        validate_limits(10, 0)
