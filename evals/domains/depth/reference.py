"""ROV depth alarm (synthetic benchmark task)."""

SURFACE_KPA = 101.325
KPA_PER_M = 1025.0 * 9.80665 / 1000.0
SAMPLES = 3


# implements: DEP-001, DEP-002
def depth_m(pressure_kpa: float) -> float:
    """Depth in metres of seawater from absolute pressure in kPa."""
    if pressure_kpa <= SURFACE_KPA:
        return 0.0
    return (pressure_kpa - SURFACE_KPA) / KPA_PER_M


# implements: DEP-003, DEP-004
class DepthAlarm:
    def __init__(self, max_depth_m: float) -> None:
        self.max_depth_m = max_depth_m
        self.active = False
        self._deep = 0
        self._shallow = 0

    def update(self, depth: float) -> bool:
        """Feed one depth sample; return whether the alarm is active."""
        if depth > self.max_depth_m:
            self._deep += 1
            self._shallow = 0
            if self._deep >= SAMPLES:
                self.active = True
        else:
            self._shallow += 1
            self._deep = 0
            if self._shallow >= SAMPLES:
                self.active = False
        return self.active
