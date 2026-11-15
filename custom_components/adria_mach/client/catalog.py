"""Only identifiers with observed units or unambiguous reported states."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from ..const import VALUE_ID


@dataclass(frozen=True)
class Field:
    kind: Literal["number", "binary", "enum"]
    read_only_definition: bool = True
    options: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None


FIELDS = MappingProxyType(
    {
        VALUE_ID: Field("number"),
        "OUTSIDE_MEASURED_TEMPERATURE": Field("number"),
        "OUTSIDE_MEASURED_HUMIDITY": Field("number"),
        "MEASURED_PRESSURE": Field("number"),
        "LIVING_BATTERY_VOLTAGE": Field("number"),
        "LIVING_BATTERY_CURRENT": Field("number"),
        "FRESH_WATER_LEVEL": Field("number", minimum=0, maximum=100),
        "WASTE_WATER_LEVEL": Field("number", minimum=0, maximum=100),
        "AIR_HEATER_TEMPERATURE": Field("number", False, minimum=5, maximum=30),
        "WATER_HEATER_TEMPERATURE": Field("enum", False, ("off", "normal", "boost")),
        "MAINS_SUPPLY_VALUE": Field("binary"),
        "AIR_HEATER_VALUE": Field("binary", read_only_definition=False),
        "AIR_HEATER_WORKING": Field("binary"),
        "WATER_HEATER_WORKING": Field("binary"),
        "LIVING_BATTERY_INSTALLED": Field("binary"),
        "WATER_PUMP_VALUE": Field("binary", read_only_definition=False),
        "EXTERNAL_LIGHT_VALUE": Field("binary", read_only_definition=False),
        "AUX_VALUE": Field("binary", read_only_definition=False),
    }
)
