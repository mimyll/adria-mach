"""Small normalized model; no Home Assistant dependency."""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

from ..const import VALUE_ID
from .catalog import FIELDS, Field
from .position import Levelling, Location
from .telemetry import diagnostic_readings


class MachError(Exception):
    """A fixed local error code, never remote text or an exception chain."""


class AuthenticationError(MachError):
    """The remote session or credentials were rejected."""


@dataclass(frozen=True, repr=False)
class Device:
    id: str
    name: str


@dataclass(frozen=True)
class Measurement:
    values: Mapping[str, int | float | str | bool | None]
    received_at: datetime
    control_snapshots: Mapping[str, Any] = field(default_factory=dict, repr=False)
    capabilities: Any = field(default=None, repr=False)
    location: Location | None = field(default=None, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        object.__setattr__(
            self, "control_snapshots", MappingProxyType(dict(self.control_snapshots))
        )

    @property
    def temperature(self):
        """Preserve the initial reference's meaning, with one source of truth."""
        return self.values.get(VALUE_ID)


def assigned_devices(data: Any) -> tuple[Device, ...]:
    if not isinstance(data, list):
        raise MachError("invalid_discovery")
    devices = []
    seen = set()
    for row in data:
        if not isinstance(row, dict):
            raise MachError("invalid_discovery")
        device_id = row.get("machId")
        if not isinstance(device_id, str) or not 1 <= len(device_id) <= 256 or device_id in seen:
            raise MachError("invalid_discovery")
        seen.add(device_id)
        # FULL is the only device type verified with the owner's portal.
        if row.get("type") != "FULL":
            continue
        name = row.get("name")
        name = name[:100] if isinstance(name, str) and name.strip() else "Adria MACH"
        devices.append(Device(device_id, name))
    return tuple(devices)


def temperature_from(configuration: Any, values: Any) -> int | float | None:
    return readings_from(configuration, values)[VALUE_ID]


def _supported(definitions, key: str, field: Field) -> bool:
    rows = [row for row in definitions if isinstance(row, dict) and row.get("id") == key]
    if len(rows) != 1 or not isinstance(config := rows[0].get("config"), dict):
        return False
    expected_types = ("integer", "float") if field.kind == "number" else ("categorical",)
    return (
        config.get("id") == key
        and config.get("type") in expected_types
        and (not field.read_only_definition or config.get("writable") is False)
    )


def _reading(rows, key: str, field: Field):
    matches = [row for row in rows if isinstance(row, dict) and row.get("device") == key]
    if len(matches) != 1:
        return None
    value = matches[0].get("status")
    if field.kind == "number":
        if type(value) not in (int, float) or value == -9007199254740991:
            return None
        try:
            if not math.isfinite(value):
                return None
        except OverflowError:
            return None
        if field.minimum is not None and value < field.minimum:
            return None
        if field.maximum is not None and value > field.maximum:
            return None
        return value
    if not isinstance(value, str):
        return None
    if field.kind == "binary":
        return {"on": True, "off": False}.get(value)
    return value if value in field.options else None


def readings_from(
    configuration: Any, values: Any, levelling=None
) -> dict[str, int | float | str | bool | None]:
    """Project a full response onto supported known fields; never retain raw context."""
    if not isinstance(configuration, dict) or not isinstance(values, dict):
        raise MachError("invalid_measurement")
    definitions, rows = configuration.get("values"), values.get("values")
    if not isinstance(definitions, list) or not isinstance(rows, list):
        raise MachError("invalid_measurement")
    if not _supported(definitions, VALUE_ID, FIELDS[VALUE_ID]):
        raise MachError("unsupported_temperature")
    return (
        {
            key: _reading(rows, key, field)
            for key, field in FIELDS.items()
            if _supported(definitions, key, field)
        }
        | diagnostic_readings(configuration, values)
        | (levelling or Levelling()).readings(configuration, values)
    )
