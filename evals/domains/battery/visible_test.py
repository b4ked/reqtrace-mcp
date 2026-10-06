import pytest
from battery.bms import BatteryController, cell_fault, charge_permitted

OK = [3.7, 3.8]


@pytest.mark.verifies("BMS-001")
def test_overvoltage():
    assert not cell_fault([4.20, 3.70])
    assert cell_fault([4.21, 3.70])


@pytest.mark.verifies("BMS-002")
def test_undervoltage():
    assert not cell_fault([3.00])
    assert cell_fault([2.99])


@pytest.mark.verifies("BMS-003")
@pytest.mark.parametrize("temp,ok", [(-0.1, False), (0.0, True), (45.0, True), (45.1, False)])
def test_charge_window(temp, ok):
    assert charge_permitted(temp) is ok


@pytest.mark.verifies("BMS-004")
def test_charging_state():
    c = BatteryController()
    assert c.step(OK, 25, True) == "CHARGING"
    assert c.step(OK, 25, False) == "IDLE"
    assert c.step(OK, 50, True) == "IDLE"


@pytest.mark.verifies("BMS-005")
def test_fault_latching():
    c = BatteryController()
    assert c.step([4.3], 25, True) == "FAULT"
    assert c.step(OK, 25, True) == "FAULT"
    c.reset([4.3])
    assert c.state == "FAULT"
    c.reset(OK)
    assert c.state == "IDLE"
