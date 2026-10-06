"""Battery management controller (synthetic benchmark task).

Implement the functions below so they meet requirements/battery.yaml.
Keep these public names and signatures: hidden acceptance tests use them.
"""


def cell_fault(cell_voltages: list[float]) -> bool:
    """True if any cell voltage is out of range."""
    raise NotImplementedError


def charge_permitted(temp_c: float) -> bool:
    """True if charging is allowed at this pack temperature."""
    raise NotImplementedError


class BatteryController:
    """States: "IDLE", "CHARGING", "FAULT"."""

    def __init__(self) -> None:
        self.state = "IDLE"

    def step(self, cell_voltages: list[float], temp_c: float, charger_connected: bool) -> str:
        """Update and return the state from one set of measurements."""
        raise NotImplementedError

    def reset(self, cell_voltages: list[float]) -> None:
        """Operator reset request."""
        raise NotImplementedError
