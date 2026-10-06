import pytest
from battery.bms import BatteryController, cell_fault, charge_permitted

OK = [3.7, 3.8, 3.9]


@pytest.mark.verifies("BMS-001")
def test_overvoltage_boundary():
    assert cell_fault([4.20, 3.70]) is False
    assert cell_fault([4.21, 3.70]) is True
    assert cell_fault([3.7, 3.7, 4.25]) is True


@pytest.mark.verifies("BMS-002")
def test_undervoltage_boundary():
    assert cell_fault([3.00]) is False
    assert cell_fault([2.99]) is True
    assert cell_fault([3.7, 2.5]) is True


@pytest.mark.verifies("BMS-003")
@pytest.mark.parametrize("temp,ok", [(-0.1, False), (0.0, True), (25, True), (45.0, True),
                                     (45.1, False)])
def test_charge_window(temp, ok):
    assert charge_permitted(temp) is ok


@pytest.mark.verifies("BMS-004")
def test_charging_state():
    c = BatteryController()
    assert c.step(OK, 25, True) == "CHARGING"
    assert c.step(OK, 25, False) == "IDLE"
    assert c.step(OK, 50, True) == "IDLE"
    assert c.step(OK, -5, True) == "IDLE"
    assert c.state == "IDLE"


@pytest.mark.verifies("BMS-005")
def test_fault_latches_until_valid_reset():
    c = BatteryController()
    assert c.step([4.3, 3.7], 25, True) == "FAULT"
    assert c.step(OK, 25, True) == "FAULT"
    c.reset([4.3, 3.7])
    assert c.state == "FAULT"
    c.reset(OK)
    assert c.state == "IDLE"
    assert c.step(OK, 25, True) == "CHARGING"
