"""ROV depth alarm (synthetic benchmark task).

Implement the functions below so they meet requirements/depth.yaml.
Keep these public names and signatures: hidden acceptance tests use them.
"""


def depth_m(pressure_kpa: float) -> float:
    """Depth in metres of seawater from absolute pressure in kPa."""
    raise NotImplementedError


class DepthAlarm:
    def __init__(self, max_depth_m: float) -> None:
        self.max_depth_m = max_depth_m
        self.active = False

    def update(self, depth: float) -> bool:
        """Feed one depth sample; return whether the alarm is active."""
        raise NotImplementedError
