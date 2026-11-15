"""Validated vehicle position; coordinates stay outside general telemetry and exports."""

import math
from dataclasses import dataclass

AXES = tuple(f"ACCELERATION_{axis}" for axis in "XYZ")
OFFSETS = tuple(f"{key}_ZERO_POSITION_OFFSET" for key in AXES)
GPS_IDS = ("GPS_LATITUDE", "GPS_LONGITUDE")
POSITION_IDS = frozenset((*AXES, *OFFSETS, *GPS_IDS))
ANGLE_KEYS = ("levelling_pitch", "levelling_roll")
_SENTINELS = (-9007199254740991, -9223372036854776000, 5e-324)


@dataclass(frozen=True, repr=False)
class Location:
    latitude: float
    longitude: float


def _supported(configuration, key, *, calibration=False):
    definitions = [
        row
        for row in configuration.get("values", [])
        if isinstance(row, dict) and row.get("id") == key
    ]
    if len(definitions) != 1:
        return False
    config = definitions[0].get("config")
    if (
        not isinstance(config, dict)
        or config.get("id") != key
        or config.get("type") not in ("integer", "float")
        or type(config.get("writable")) is not bool
        or (config["writable"] and not calibration)
        or config.get("hasState") is False
    ):
        return False
    return True


def levelling_supported(configuration):
    """Describe schema eligibility independently of temporary sample validity."""
    present = {
        row.get("id")
        for row in configuration.get("values", [])
        if isinstance(row, dict) and row.get("id") in OFFSETS
    }
    return all(_supported(configuration, key) for key in AXES) and (
        not present or all(_supported(configuration, key, calibration=True) for key in OFFSETS)
    )


def _number(configuration, values, key, *, calibration=False):
    if not _supported(configuration, key, calibration=calibration):
        return None
    rows = [
        row
        for row in values.get("values", [])
        if isinstance(row, dict) and row.get("device") == key
    ]
    if len(rows) != 1:
        return None
    value = rows[0].get("status")
    if type(value) not in (int, float) or value in _SENTINELS:
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except OverflowError:
        return None


def location_from(configuration, values):
    """Return one complete pair from this snapshot, never a retained partial fix."""
    latitude, longitude = (_number(configuration, values, key) for key in GPS_IDS)
    if (
        latitude is None
        or longitude is None
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
        or latitude == 0
        or longitude == 0
    ):
        return None
    return Location(latitude, longitude)


def _angle(component, other_a, other_b):
    return math.degrees(math.atan2(component, math.hypot(other_a, other_b)))


class Levelling:
    """FULL-device mounting interpretation, latched per calibration context.

    Use the latest complete snapshot without the web screen's animation smoothing.
    The client owns this context and replaces it for another session or vehicle.
    """

    def __init__(self):
        self._calibration = None
        self._vertical = None

    def readings(self, configuration, values):
        if not any(
            isinstance(row, dict) and row.get("id") in AXES
            for row in configuration.get("values", [])
        ):
            return {}
        unavailable = dict.fromkeys(ANGLE_KEYS)
        raw = tuple(_number(configuration, values, key) for key in AXES)
        if any(value is None for value in raw):
            return unavailable
        norm = math.hypot(*raw)
        if not math.isfinite(norm) or norm == 0:
            return unavailable
        present = {
            row.get("id")
            for row in configuration.get("values", [])
            if isinstance(row, dict) and row.get("id") in OFFSETS
        }
        calibration = (0.0, 0.0, 0.0)
        if present:
            reported = tuple(
                _number(configuration, values, key, calibration=True) for key in OFFSETS
            )
            if any(value is None for value in reported):
                return unavailable
            calibration = (-reported[0], -reported[1], 1.0 - reported[2])
        context = (bool(present), calibration)
        vertical = self._vertical
        if vertical is None or self._calibration != context:
            vertical = (
                abs(_angle(raw[0], raw[1], raw[2])) >= 70
                or abs(_angle(raw[1], raw[0], raw[2])) >= 70
            )
        x, y, z = raw
        dx, dy, dz = calibration
        corrected = (y + dx, -(z + dy), x + dz) if vertical else (y + dy, x + dx, z + dz)
        norm = math.hypot(*corrected)
        if not math.isfinite(norm) or norm == 0:
            return unavailable
        self._vertical, self._calibration = vertical, context
        a, b, c = corrected
        return {
            ANGLE_KEYS[0]: -_angle(a, b, c),
            ANGLE_KEYS[1]: _angle(b, a, c),
        }
