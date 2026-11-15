"""Read-only vehicle specifications, kept outside general telemetry and diagnostics."""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

DIMENSIONS = {
    "vehicle_height": "B11",
    "vehicle_length": "B13",
    "vehicle_length_with_towbar": "B12",
    "vehicle_width": "B15",
}


@dataclass(frozen=True, repr=False)
class VehicleInfo:
    values: Mapping[str, str | float | None] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


def _text(value, *, chassis=False):
    if not isinstance(value, str):
        return None
    pattern = r"[A-Za-z0-9][A-Za-z0-9 -]{0,63}" if chassis else r"[\w .()+/-]{1,100}"
    if not re.fullmatch(pattern, value) or not value.strip():
        return None
    return value.strip()


def _dimension(value):
    if isinstance(value, str):
        if len(value) > 32 or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
            return None
        value = float(value)
    if type(value) not in (int, float) or value == 5e-324:
        return None
    try:
        return float(value) if math.isfinite(value) and value > 0 else None
    except OverflowError:
        return None


def vehicle_from(configuration):
    """Project only the six reviewed fields from this complete configuration."""
    system = configuration.get("system")
    source = system.get("vehicle") if isinstance(system, dict) else None
    if not isinstance(source, dict):
        return VehicleInfo()
    chassis = source.get("chassis")
    result = {
        "vehicle_model": _text(source.get("model")),
        "chassis_number": _text(chassis.get("number"), chassis=True)
        if isinstance(chassis, dict)
        else None,
    }
    equipment = source.get("equipment")
    equipment = equipment if isinstance(equipment, list) else []
    for key, equipment_key in DIMENSIONS.items():
        matches = [
            row for row in equipment if isinstance(row, dict) and row.get("key") == equipment_key
        ]
        result[key] = _dimension(matches[0].get("value")) if len(matches) == 1 else None
    return VehicleInfo(result)
