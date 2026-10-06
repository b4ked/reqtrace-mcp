"""Battery management controller (synthetic benchmark task)."""

CELL_MAX_V = 4.20
CELL_MIN_V = 3.00
CHARGE_MIN_C = 0.0
CHARGE_MAX_C = 45.0


# implements: BMS-001, BMS-002
def cell_fault(cell_voltages: list[float]) -> bool:
    """True if any cell voltage is out of range."""
    return any(v > CELL_MAX_V or v < CELL_MIN_V for v in cell_voltages)


# implements: BMS-003
def charge_permitted(temp_c: float) -> bool:
    """True if charging is allowed at this pack temperature."""
    return CHARGE_MIN_C <= temp_c <= CHARGE_MAX_C


# implements: BMS-004, BMS-005
class BatteryController:
    """States: "IDLE", "CHARGING", "FAULT"."""

    def __init__(self) -> None:
        self.state = "IDLE"

    def step(self, cell_voltages: list[float], temp_c: float, charger_connected: bool) -> str:
        """Update and return the state from one set of measurements."""
        if cell_fault(cell_voltages):
            self.state = "FAULT"
        elif self.state != "FAULT":
            self.state = "CHARGING" if charger_connected and charge_permitted(temp_c) else "IDLE"
        return self.state

    def reset(self, cell_voltages: list[float]) -> None:
        """Operator reset request."""
        if self.state == "FAULT" and not cell_fault(cell_voltages):
            self.state = "IDLE"
