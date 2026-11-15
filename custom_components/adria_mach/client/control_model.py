"""Fixed experimental scope and allowlisted observations, independent of HA."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from .master import MASTER_SCOPE_HASH, MasterControl, master_route
from .model import MachError
from .operational import (
    AC_SCOPE_HASH,
    EQUIPMENT_SCOPE_HASH,
    AcControl,
    EquipmentControl,
    validate_equipment,
)
from .outside import OUTSIDE_SCOPE_HASH, OutsideControl, outside_route

PLAN_HASH = "4cbff894c45f7d3c34a5b99a21042383d35fde3fb3305c8658225378a03d82bb"
OFF_LEVEL = -9007199254740991
# Canonical JSON: revision individual-lights-1, groups1..8, on50, off sentinel, one cycle each.
LIGHTING_SCOPE_HASH = "956ad8f0b5fa356aec16a9e0e17c0633bf4f880ad593eea97e6a91e1dff2ac1a"
MANUAL_SCOPE_HASH = "47b0cf76d4866ded39b50ff91d9b94bbff753a1809c61537b6dde49c6cc89695"
WATER_SCOPE_HASH = "8c9b46e0cb3f8b733e8e42d0ac96565fa3438e819964e1d65d6b7284431d0a1f"
WATER_MODES = ("off", "normal", "boost")
HEATING_SCOPE_HASH = "a499e4fc7c47523b10a7fb23d408242d30c768762e50c657fd2f4bf78567011d"


class ControlError(MachError):
    """Only locally chosen codes cross this boundary."""


class Case(Enum):
    LIGHT = "outside-light"
    HEATER = "heater-target"
    GROUP_1 = "light-group-1"
    GROUP_2 = "light-group-2"
    GROUP_3 = "light-group-3"
    GROUP_4 = "light-group-4"
    GROUP_5 = "light-group-5"
    GROUP_6 = "light-group-6"
    GROUP_7 = "light-group-7"
    GROUP_8 = "light-group-8"

    @property
    def individual_light(self):
        return self not in (Case.LIGHT, Case.HEATER)

    @property
    def key(self):
        if self.individual_light:
            return f"LIGHT_GROUP_{self.value.rsplit('-', 1)[1]}_BRIGHTNESS"
        return "EXTERNAL_LIGHT_VALUE" if self is Case.LIGHT else "AIR_HEATER_TEMPERATURE"

    @property
    def baseline(self):
        if self.individual_light:
            return OFF_LEVEL
        return "off" if self is Case.LIGHT else 15

    @property
    def target(self):
        if self.individual_light:
            return 50
        return "on" if self is Case.LIGHT else 16

    @property
    def seconds(self):
        return 60 if self is Case.HEATER else 30


class ManualControl(Enum):
    GROUP_1 = "manual-light-group-1"
    GROUP_2 = "manual-light-group-2"
    GROUP_3 = "manual-light-group-3"
    GROUP_4 = "manual-light-group-4"
    GROUP_5 = "manual-light-group-5"
    GROUP_6 = "manual-light-group-6"
    GROUP_7 = "manual-light-group-7"
    GROUP_8 = "manual-light-group-8"
    HEATER = "manual-heater-target"

    @property
    def legacy_case(self):
        return Case(self.value.removeprefix("manual-"))

    @property
    def key(self):
        return self.legacy_case.key

    @property
    def seconds(self):
        return self.legacy_case.seconds


class WaterControl(Enum):
    MODE = "water-heater-mode"

    @property
    def key(self):
        return "WATER_HEATER_TEMPERATURE"

    @property
    def seconds(self):
        return 60

    @property
    def individual_light(self):
        return False


class HeatingControl(Enum):
    MODE = "heating-mode"

    @property
    def key(self):
        return "AIR_HEATER_VALUE"

    @property
    def seconds(self):
        return 60

    @property
    def individual_light(self):
        return False


def manual_scope(control):
    if isinstance(control, AcControl):
        return AC_SCOPE_HASH
    if isinstance(control, MasterControl):
        return MASTER_SCOPE_HASH
    if isinstance(control, EquipmentControl):
        return EQUIPMENT_SCOPE_HASH
    if isinstance(control, OutsideControl):
        return OUTSIDE_SCOPE_HASH
    if isinstance(control, HeatingControl):
        return HEATING_SCOPE_HASH
    if isinstance(control, WaterControl):
        return WATER_SCOPE_HASH
    if isinstance(control, ManualControl):
        return MANUAL_SCOPE_HASH
    raise ControlError("command_rejected")


def validate_manual(control, target, *, allow_default_on=False):
    if isinstance(control, MasterControl):
        if type(target) is not str or target not in ("off", "on"):
            raise ControlError("command_rejected")
        return
    if isinstance(control, (EquipmentControl, AcControl)):
        validate_equipment(control, target)
        return
    if control is OutsideControl.BINARY:
        if type(target) is not str or target not in ("off", "on"):
            raise ControlError("command_rejected")
        return
    if isinstance(control, OutsideControl):
        if target is None and allow_default_on:
            return
        if type(target) is not int or not (
            target == OFF_LEVEL or (2 <= target <= 50 and target % 2 == 0)
        ):
            raise ControlError("command_rejected")
        return
    if isinstance(control, HeatingControl):
        if type(target) is not str or target not in ("off", "on"):
            raise ControlError("command_rejected")
        return
    if isinstance(control, WaterControl):
        if type(target) is not str or target not in WATER_MODES:
            raise ControlError("command_rejected")
        return
    if not isinstance(control, ManualControl):
        raise ControlError("command_rejected")
    if target is None and allow_default_on and control is not ManualControl.HEATER:
        return
    if type(target) is not int:
        raise ControlError("command_rejected")
    if control is ManualControl.HEATER:
        valid = 5 <= target <= 30
    else:
        valid = target == OFF_LEVEL or (2 <= target <= 50 and target % 2 == 0)
    if not valid:
        raise ControlError("command_rejected")


def brightness_to_level(value):
    """Match progress0..50/step2; positive half-up, never implicit off."""
    if type(value) is not int or not 0 <= value <= 255:
        raise ControlError("invalid_brightness")
    if value == 0:
        return OFF_LEVEL
    return max(2, min(50, 2 * ((value * 50 + 255) // 510)))


def level_to_brightness(level):
    """Retain odd observed levels; this is UI scaling, not physical light output."""
    if type(level) is not int:
        raise ControlError("invalid_target_readback")
    if level == OFF_LEVEL:
        return None
    if type(level) is not int or not 1 <= level <= 50:
        raise ControlError("invalid_target_readback")
    return (level * 255 + 25) // 50


def manual_command(control, target):
    validate_manual(control, target)
    return {
        "type": "ui-req",
        "payload": {
            "type": "device",
            "content": {
                "method": "setValue",
                "request": [{"valueId": control.key, "value": target}],
            },
        },
    }


def command(case: Case, *, restore: bool) -> dict[str, Any]:
    """No generic identifier, value, URL or RPC argument is exposed."""
    if not isinstance(case, Case) or type(restore) is not bool:
        raise ControlError("command_rejected")
    return {
        "type": "ui-req",
        "payload": {
            "type": "device",
            "content": {
                "method": "setValue",
                "request": [
                    {"valueId": case.key, "value": case.baseline if restore else case.target}
                ],
            },
        },
    }


def _one(rows, key, id_key):
    matches = [r for r in rows if isinstance(r, dict) and r.get(id_key) == key]
    if len(matches) != 1:
        raise ControlError("ambiguous_snapshot")
    return matches[0]


CONTEXT_KEYS = (
    "ENERGY_SOURCE",
    "ENERGY_SOURCE_PRIORITY_SETTING",
    "ENERGY_SOURCE_GAS_VALUE",
    "HEATING_POWER_SETTING",
    "HEATING_DIESEL_POWER_SETTING",
    "AIR_HEATER_VALUE",
    "AIR_HEATER_WORKING",
    "WATER_HEATER_TEMPERATURE",
    "MAINS_SUPPLY_VALUE",
)
ENUMS = {
    "INTERNAL_LIGHT_VALUE": {"off", "on"},
    "LIGHT_GROUP_INTERNAL_LIGHTS": {"off", "on"},
    "EXTERNAL_LIGHT_VALUE": {"off", "on"},
    "AIR_HEATER_VALUE": {"off", "on"},
    "AIR_HEATER_WORKING": {"off", "on"},
    "WATER_HEATER_WORKING": {"off", "on"},
    "MAINS_SUPPLY_VALUE": {"off", "on"},
    "WATER_HEATER_TEMPERATURE": {"off", "normal", "boost"},
}


@dataclass(frozen=True, repr=False)
class Snapshot:
    observed: dict
    context: dict  # Compared in memory; raw energy enums never exported.
    received_at: str
    monotonic_at: float
    choices: tuple = ()


def snapshot(
    configuration,
    values,
    device_id: str,
    case: Case | WaterControl | HeatingControl | OutsideControl,
    now: float,
) -> Snapshot:
    if not isinstance(configuration, dict) or configuration.get("machId") != device_id:
        raise ControlError("vehicle_identity_mismatch")
    definitions = configuration.get("values")
    rows = values.get("values") if isinstance(values, dict) else None
    if not isinstance(definitions, list) or not isinstance(rows, list):
        raise ControlError("invalid_snapshot")
    config = _one(definitions, case.key, "id").get("config")
    if not isinstance(config, dict) or config.get("id") != case.key:
        raise ControlError("unsupported_command_definition")
    if "writable" in config and config["writable"] is not True:
        raise ControlError("command_not_writable")
    if "hasState" in config and config["hasState"] is not True:
        raise ControlError("unsupported_command_definition")
    categorical = isinstance(case, MasterControl) or case in (
        Case.LIGHT,
        WaterControl.MODE,
        HeatingControl.MODE,
        OutsideControl.BINARY,
    )
    route = (
        master_route(configuration)
        if isinstance(case, MasterControl)
        else outside_route(configuration)
        if isinstance(case, OutsideControl)
        else None
    )
    if isinstance(case, MasterControl) and (route is None or route[0] is not case):
        raise ControlError("master_route_unverified")
    if isinstance(case, OutsideControl) and (route is None or route[0] is not case):
        raise ControlError("outside_route_unverified")
    if categorical:
        categories = config.get("categories")
        expected = ENUMS[case.key]
        if not isinstance(categories, list) or len(categories) != len(expected):
            raise ControlError("unsupported_command_definition")
        ids = [c.get("id") if isinstance(c, dict) else c for c in categories]
        if (
            config.get("type") != "categorical"
            or any(type(c) is not str for c in ids)
            or set(ids) != expected
        ):
            raise ControlError("unsupported_command_definition")
    elif case.individual_light:
        if (
            config.get("type") != "integer"
            or config.get("offState") is not True
            or config.get("range") != [1, 50]
            or any(type(v) is not int for v in config.get("range", []))
            or type(config.get("step")) is not int
            or config["step"] != 2
            or (
                "dividend" in config
                and (type(config["dividend"]) is not int or config["dividend"] != 1)
            )
        ):
            raise ControlError("unsupported_command_definition")
    elif (
        config.get("type") != "integer"
        or config.get("offState") is not False
        or config.get("range") != [5, 30]
        or any(type(v) is not int for v in config.get("range", []))
        or ("step" in config and (type(config["step"]) is not int or config["step"] != 1))
    ):
        raise ControlError("unsupported_command_definition")
    observed = {}
    for key, options in ENUMS.items():
        matches = [r for r in rows if isinstance(r, dict) and r.get("device") == key]
        if len(matches) == 1 and isinstance(v := matches[0].get("status"), str) and v in options:
            observed[key] = v
    target = _one(rows, case.key, "device").get("status")
    if categorical:
        if not isinstance(target, str) or target not in ENUMS[case.key]:
            raise ControlError("invalid_target_readback")
    elif case.individual_light:
        if type(target) is not int or not (target == OFF_LEVEL or 1 <= target <= 50):
            raise ControlError("invalid_target_readback")
    elif type(target) is not int or not 5 <= target <= 30:
        raise ControlError("invalid_target_readback")
    observed[case.key] = target
    for key in ("LIVING_MEASURED_TEMPERATURE", "OUTSIDE_MEASURED_TEMPERATURE"):
        matches = [r for r in rows if isinstance(r, dict) and r.get("device") == key]
        if len(matches) == 1:
            v = matches[0].get("status")
            if type(v) in (int, float) and abs(v) < 1_000_000 and math.isfinite(v):
                observed[key] = v
    context = dict(route[1]) if route else {}
    if case is HeatingControl.MODE:
        # Until a separate mode contract is reviewed, do not label ventilation as heat.
        if any(
            isinstance(d, dict) and d.get("id") == "AIR_HEATER_MODE" for d in definitions
        ) or any(isinstance(r, dict) and r.get("device") == "AIR_HEATER_MODE" for r in rows):
            raise ControlError("unsupported_heater_mode")
        acc = "AUTOMATIC_CLIMATE_CONTROL_SETTING"
        if any(isinstance(d, dict) and d.get("id") == acc for d in definitions) or any(
            isinstance(r, dict) and r.get("device") == acc for r in rows
        ):
            acc_config = _one(definitions, acc, "id").get("config")
            if (
                not isinstance(acc_config, dict)
                or acc_config.get("id") != acc
                or acc_config.get("type") != "categorical"
                or _one(rows, acc, "device").get("status") != "off"
            ):
                raise ControlError("automatic_climate_active_or_unknown")
            context[acc] = "off"
        # Reuse the old target schema checks without widening the old target scope.
        target_config = _one(definitions, "AIR_HEATER_TEMPERATURE", "id").get("config")
        if (
            not isinstance(target_config, dict)
            or target_config.get("id") != "AIR_HEATER_TEMPERATURE"
            or target_config.get("type") != "integer"
            or target_config.get("offState") is not False
            or target_config.get("range") != [5, 30]
            or any(type(v) is not int for v in target_config.get("range", []))
            or ("writable" in target_config and target_config["writable"] is not True)
            or ("hasState" in target_config and target_config["hasState"] is not True)
            or (
                "step" in target_config
                and (type(target_config["step"]) is not int or target_config["step"] != 1)
            )
        ):
            raise ControlError("unsupported_command_definition")
    if case in (Case.HEATER, WaterControl.MODE, HeatingControl.MODE):
        water = case is WaterControl.MODE
        heating = case is HeatingControl.MODE
        required = (
            {"ENERGY_SOURCE", "ENERGY_SOURCE_PRIORITY_SETTING", "WATER_HEATER_WORKING"}
            if water
            else {
                "ENERGY_SOURCE",
                "ENERGY_SOURCE_PRIORITY_SETTING",
                "AIR_HEATER_VALUE",
                "AIR_HEATER_WORKING",
                "WATER_HEATER_TEMPERATURE",
                "MAINS_SUPPLY_VALUE",
            }
        )
        keys = tuple(k for k in CONTEXT_KEYS if k != case.key)
        if water:
            keys += ("WATER_HEATER_WORKING", "AIR_HEATER_TEMPERATURE")
        elif heating:
            required = required - {case.key} | {"AIR_HEATER_TEMPERATURE"}
            keys += ("AIR_HEATER_TEMPERATURE",)
        for key in keys:
            matches = [r for r in rows if isinstance(r, dict) and r.get("device") == key]
            if not matches and key not in required:
                continue
            value = _one(rows, key, "device").get("status")
            if not (
                (isinstance(value, str) and 0 < len(value) <= 100)
                or (type(value) in (int, float) and abs(value) < 1_000_000 and math.isfinite(value))
            ):
                raise ControlError("invalid_heater_context")
            if (water or heating) and (
                (key in ENUMS and key not in observed)
                or (
                    key == "AIR_HEATER_TEMPERATURE"
                    and (type(value) is not int or not 5 <= value <= 30)
                )
            ):
                raise ControlError("invalid_heater_context")
            context[key] = value
        if water:
            if observed.get("WATER_HEATER_WORKING") != "on":
                raise ControlError("water_heater_not_ready")
        elif any(
            observed.get(k) != "on"
            for k in (
                ("AIR_HEATER_WORKING", "MAINS_SUPPLY_VALUE")
                if heating
                else ("AIR_HEATER_VALUE", "AIR_HEATER_WORKING", "MAINS_SUPPLY_VALUE")
            )
        ):
            raise ControlError("heater_not_ready")
        if not water and "WATER_HEATER_TEMPERATURE" not in observed:
            raise ControlError("invalid_heater_context")
    return Snapshot(observed, context, datetime.now(UTC).isoformat(), now)


def positive_candidate(result: Any) -> bool:
    """Proposed experiment policy, NOT a service-verified acceptance contract."""
    if not isinstance(result, dict) or type(result.get("status")) is not int:
        return False
    payload = result.get("payload")
    successes = payload.get("successes") if isinstance(payload, dict) else None
    return (
        set(result) == {"status", "payload"}
        and isinstance(payload, dict)
        and set(payload) == {"successes"}
        and 200 <= result["status"] < 300
        and isinstance(successes, list)
        and len(successes) == 1
        and successes[0] is True
    )
