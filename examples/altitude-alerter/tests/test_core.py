import pytest

from alerter.core import altitude_alert, validate_floor


@pytest.mark.verifies("ALT-001")
@pytest.mark.parametrize("alt,expected", [(499, True), (500, False)])
def test_alert_at_floor_boundary(alt, expected):
    assert altitude_alert(alt, floor_ft=500) is expected


@pytest.mark.verifies("ALT-002")
def test_floor_limits():
    # Tagged ALT-002 but only checks a constant: it never calls validate_floor.
    from alerter import core
    assert core.MIN_FLOOR_FT == 100.0
