"""Finite equipment contracts; configuration presence is not installed hardware proof."""

import hashlib
import json
from datetime import UTC, datetime
from enum import Enum


class EquipmentControl(Enum):
    HEATING_SOURCE = "heating-source"
    HEATING_PRIORITY = "heating-priority"
    FRIDGE_POWER = "fridge-power"
    FRIDGE_SOURCE = "fridge-source"
    FRIDGE_AUTO = "fridge-auto"
    FRIDGE_LEVEL = "fridge-level"
    FRIDGE_FRAME = "fridge-frame"
    PUMP = "water-pump"
    AUX = "aux-output"
    ALDE = "alde-panel"
    AC_POWER = "ac-power"
    AC_MODE = "ac-mode"
    AC_TARGET = "ac-target"
    AC_FAN = "ac-fan"
    MEMORY_1 = "light-memory-1"
    MEMORY_2 = "light-memory-2"
    MEMORY_3 = "light-memory-3"
    MEMORY_4 = "light-memory-4"

    @property
    def key(self):
        return SPECS[self][0]

    @property
    def choices(self):
        return SPECS[self][1]

    @property
    def family(self):
        return SPECS[self][2]

    @property
    def domain(self):
        return SPECS[self][3]

    @property
    def equipment(self):
        return {"aux": "aux", "alde": "alde", "ac": "air_conditioning"}.get(self.family)

    @property
    def action(self):
        return self.family == "memory"

    @property
    def seconds(self):
        return 60


ONOFF = ("off", "on")
SPECS = {
    EquipmentControl.HEATING_SOURCE: (
        "ENERGY_SOURCE",
        ("off", "gas", "el1", "el2", "el3", "el1_and_gas", "el2_and_gas", "el3_and_gas"),
        "heating",
        "select",
    ),
    EquipmentControl.HEATING_PRIORITY: (
        "ENERGY_SOURCE_PRIORITY_SETTING",
        ("electricity", "gas"),
        "heating",
        "select",
    ),
    EquipmentControl.FRIDGE_POWER: ("FRIDGE_VALUE", ONOFF, "fridge", "switch"),
    EquipmentControl.FRIDGE_SOURCE: (
        "FRIDGE_POWER_MODE",
        ("auto", "gas", "ac", "dc"),
        "fridge",
        "select",
    ),
    EquipmentControl.FRIDGE_AUTO: ("FRIDGE_AUTOMATIC_MODE", ONOFF, "fridge", "switch"),
    EquipmentControl.FRIDGE_LEVEL: (
        "FRIDGE_ACTUAL_SETTING_VALUE",
        ("one", "two", "three", "four", "five"),
        "fridge",
        "select",
    ),
    EquipmentControl.FRIDGE_FRAME: ("FRIDGE_FRAME_HEATER_VALUE", ONOFF, "fridge", "switch"),
    EquipmentControl.PUMP: ("WATER_PUMP_VALUE", ONOFF, "pump", "switch"),
    EquipmentControl.AUX: ("AUX_VALUE", ONOFF, "aux", "switch"),
    EquipmentControl.ALDE: ("ALDE_PANEL_VALUE", ONOFF, "alde", "switch"),
    EquipmentControl.AC_POWER: ("AIR_CONDITION_VALUE", ONOFF, "ac", "switch"),
    EquipmentControl.AC_MODE: (
        "AIR_CONDITION_MODE",
        ("cool", "heat", "fan", "dry", "dehumidify", "auto"),
        "ac",
        "select",
    ),
    EquipmentControl.AC_TARGET: ("AIR_CONDITION_TEMPERATURE", (), "ac", "number"),
    EquipmentControl.AC_FAN: (
        "AIR_CONDITION_FAN_MODE",
        ("auto", "low", "medium", "high"),
        "ac",
        "select",
    ),
    **{
        c: (f"LIGHT_SYSTEM_MEMORY_{n}", ("save", "restore"), "memory", "action")
        for n, c in enumerate(
            (
                EquipmentControl.MEMORY_1,
                EquipmentControl.MEMORY_2,
                EquipmentControl.MEMORY_3,
                EquipmentControl.MEMORY_4,
            ),
            1,
        )
    },
}
EQUIPMENT_SCOPE_HASH = hashlib.sha256(
    json.dumps(
        {
            "revision": 1,
            "controls": {c.value: SPECS[c] for c in EquipmentControl},
            "ac_target": [16, 31, 1],
            "memory_outcome": "acknowledged_unconfirmed",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()


class AcControl(Enum):
    """Verified AC categories, separate from the immutable earlier equipment scope."""

    POWER = "ac-power-v2"
    MODE = "ac-mode-v2"
    TARGET = "ac-target-v2"
    FAN = "ac-fan-v2"

    @property
    def key(self):
        return AC_SPECS[self][0]

    @property
    def choices(self):
        return AC_SPECS[self][1]

    @property
    def domain(self):
        return AC_SPECS[self][2]

    @property
    def entity_key(self):
        return self.value.removesuffix("-v2").replace("-", "_")

    @property
    def family(self):
        return "ac"

    @property
    def equipment(self):
        return "air_conditioning"

    @property
    def action(self):
        return False

    @property
    def seconds(self):
        return 60


AC_SPECS = {
    AcControl.POWER: ("AIR_CONDITION_VALUE", ONOFF, "switch"),
    AcControl.MODE: ("AIR_CONDITION_MODE", ("off", "fan", "cool", "heat", "auto"), "select"),
    AcControl.TARGET: ("AIR_CONDITION_TEMPERATURE", (), "number"),
    AcControl.FAN: ("AIR_CONDITION_FAN_MODE", ("low", "mid", "high"), "select"),
}
AC_SCOPE_HASH = hashlib.sha256(
    json.dumps(
        {
            "revision": "verified-ac-2",
            "controls": {c.value: AC_SPECS[c] for c in AcControl},
            "target": [16, 31, 1],
            "off_state": True,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
).hexdigest()
CURRENT_CONTROLS = tuple(c for c in EquipmentControl if c.family != "ac") + tuple(AcControl)


def validate_equipment(control, target):
    from .control_model import ControlError

    if not isinstance(control, (EquipmentControl, AcControl)):
        raise ControlError("command_rejected")
    if control.key == "AIR_CONDITION_TEMPERATURE":
        valid = type(target) is int and 16 <= target <= 31
    else:
        valid = type(target) is str and target in control.choices
    if not valid:
        raise ControlError("command_rejected")


def equipment_snapshot(configuration, values, device_id, control, now):
    """Validate one sibling independently, with a stable family context for readback."""
    from .control_model import ControlError, Snapshot, _one

    if not isinstance(configuration, dict) or configuration.get("machId") != device_id:
        raise ControlError("vehicle_identity_mismatch")
    definitions = configuration.get("values")
    rows = values.get("values") if isinstance(values, dict) else None
    if not isinstance(definitions, list) or not isinstance(rows, list):
        raise ControlError("invalid_snapshot")
    config = _one(definitions, control.key, "id").get("config")
    if (
        not isinstance(config, dict)
        or config.get("id") != control.key
        or config.get("writable", True) is not True
        or config.get("hasState", not control.action) is not (not control.action)
    ):
        raise ControlError("unsupported_command_definition")
    choices = ()
    if control.key == "AIR_CONDITION_TEMPERATURE":
        if (
            config.get("type") != "integer"
            or config.get("range") != [16, 31]
            or any(type(v) is not int for v in config.get("range", []))
            or type(config.get("step", 1)) is not int
            or config.get("step", 1) != 1
            or config.get("offState") is not True
            or config.get("dividend", 1) != 1
        ):
            raise ControlError("unsupported_command_definition")
    else:
        raw = config.get("categories")
        ids = (
            tuple(c.get("id") if isinstance(c, dict) else c for c in raw)
            if isinstance(raw, list)
            else ()
        )
        if (
            config.get("type") != "categorical"
            or not ids
            or any(type(c) is not str for c in ids)
            or (control is not AcControl.FAN and any(c not in control.choices for c in ids))
            or len(set(ids)) != len(ids)
            or (control.domain == "switch" and set(ids) != set(ONOFF))
            or (
                control.action
                and (set(ids) != {"save", "restore"} or config.get("showActions") is not True)
            )
        ):
            raise ControlError("unsupported_command_definition")
        choices = tuple(c for c in control.choices if c in ids)
        if not choices:
            raise ControlError("unsupported_command_definition")

    observed, context = {}, {}

    def read(key, allowed=None):
        value = _one(rows, key, "device").get("status")
        if allowed is not None:
            if type(value) is not str or value not in allowed:
                raise ControlError("invalid_equipment_context")
        elif not (type(value) is int and -9007199254740991 <= value <= 100):
            raise ControlError("invalid_equipment_context")
        return value

    ready = {
        "heating": "AIR_HEATER_WORKING",
        "alde": "AIR_HEATER_WORKING",
        "fridge": "FRIDGE_WORKING",
        "ac": "AC_WORKING",
    }.get(control.family)
    if ready:
        context[ready] = read(ready, ONOFF)
        if context[ready] != "on":
            raise ControlError("equipment_not_ready")
    siblings = tuple(c for c in CURRENT_CONTROLS if c.family == control.family)
    if control.family in ("heating", "alde"):
        siblings = (EquipmentControl.HEATING_SOURCE, EquipmentControl.HEATING_PRIORITY)
        for key, allowed in (
            ("AIR_HEATER_VALUE", ONOFF),
            ("WATER_HEATER_TEMPERATURE", ("off", "normal", "boost")),
        ):
            context[key] = read(key, allowed)
    for sibling in siblings:
        if sibling is control or sibling.action:
            continue
        # Optional siblings are compared when present; malformed duplicates fail closed.
        if any(isinstance(r, dict) and r.get("device") == sibling.key for r in rows):
            context[sibling.key] = read(sibling.key, sibling.choices or None)
    if control.family == "ac":
        context["AUTOMATIC_CLIMATE_CONTROL_SETTING"] = read(
            "AUTOMATIC_CLIMATE_CONTROL_SETTING", ONOFF
        )
        mode = read("AIR_CONDITION_MODE", AcControl.MODE.choices)
        if (
            control.key in ("AIR_CONDITION_MODE", "AIR_CONDITION_FAN_MODE")
            and context["AUTOMATIC_CLIMATE_CONTROL_SETTING"] != "off"
        ):
            raise ControlError("automatic_climate_active_or_unknown")
        if control.key == "AIR_CONDITION_FAN_MODE":
            if mode in ("auto", "dry", "dehumidify"):
                raise ControlError("manual_fan_unavailable")
            defs = {item["id"]: item for item in raw if isinstance(item, dict)}
            allowed = []
            for choice in choices:
                definition = defs.get(choice, {})
                if not isinstance(definition, dict):
                    continue
                blocker = definition.get("isBlockedBy")
                if blocker is None:
                    allowed.append(choice)
                elif (
                    isinstance(blocker, dict)
                    and blocker.get("valueId") == "AIR_CONDITION_MODE"
                    and isinstance(blocker.get("keys"), list)
                    and mode not in blocker["keys"]
                ):
                    allowed.append(choice)
            choices = tuple(allowed)
            if not choices:
                raise ControlError("manual_fan_unavailable")
        if control.key == "AIR_CONDITION_TEMPERATURE" and (
            mode in ("fan", "dehumidify") or context["AUTOMATIC_CLIMATE_CONTROL_SETTING"] != "off"
        ):
            raise ControlError("manual_target_unavailable")
    if control.action:
        observed[control.key] = None  # Action keywords are never enduring observed state.
    else:
        target = read(control.key, control.choices or None)
        if control.key == "AIR_CONDITION_TEMPERATURE":
            # The off sentinel is an observation, never an implicit power command.
            if target != -9007199254740991 and not 16 <= target <= 31:
                raise ControlError("invalid_target_readback")
        elif target not in ids:
            raise ControlError("invalid_target_readback")
        observed[control.key] = target
    return Snapshot(observed, context, datetime.now(UTC).isoformat(), now, choices)
