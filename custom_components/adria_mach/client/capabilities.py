"""Descriptive, allowlisted configuration inventory. This never grants write authority."""

from collections import Counter
from dataclasses import asdict, dataclass

from .catalog import FIELDS
from .control_model import Case, HeatingControl, ManualControl, WaterControl
from .master import MasterControl
from .operational import CURRENT_CONTROLS, EquipmentControl
from .outside import OutsideControl
from .telemetry import DIAGNOSTIC_FIELDS

# Reviewed public technical symbols, not a lexical test of untrusted identifiers.
# Source and predicates: technical-capability-audit-2026-11-13/digests/public-catalog-r1.md.
CANDIDATES = (
    frozenset(FIELDS)
    | frozenset(DIAGNOSTIC_FIELDS)
    | frozenset(
        """
    AIR_HEATER_MODE AIR_HEATER_VENTILATION_SPEED WANTED_TEMPERATURE_BED BED_HEATER_WORKING
    ENERGY_SOURCE ENERGY_SOURCE_GAS_VALUE HEATING_POWER_SETTING HEATING_DIESEL_POWER_SETTING
    ENERGY_SOURCE_PRIORITY_SETTING ALDE_PANEL_VALUE AUTOMATIC_CLIMATE_CONTROL_SETTING
    AUTOMATIC_CLIMATE_CONTROL_RANGE ACC_WORKING HEATER_NOTIFICATION
    WATER_HEATER_MEASURED_TEMPERATURE WATER_HEATER_ENERGY_SOURCE WATER_NOTIFICATION
    AIR_CONDITION_VALUE AIR_CONDITION_TEMPERATURE AIR_CONDITION_MODE AIR_CONDITION_FAN_MODE
    AIR_CONDITION_SLEEP_MODE AIR_CONDITION_COMPRESSOR_VALUE AIR_CONDITION_LIGHT_VALUE
    AC_WORKING AIR_CONDITIONING_NOTIFICATION FRIDGE_VALUE FRIDGE_USER_MODE FRIDGE_POWER_MODE
    FRIDGE_AUTOMATIC_MODE FRIDGE_NIGHT_MODE FRIDGE_ACTUAL_SETTING_VALUE
    FRIDGE_ACTUAL_FREEZER_SETTING_VALUE FRIDGE_FRAME_HEATER_VALUE FRIDGE_FAN_1_VALUE
    FRIDGE_FAN_2_VALUE FRIDGE_ICEMAKER_VALUE FRIDGE_BUZZER_VALUE FRIDGE_COMPRESSOR_VALUE
    FRIDGE_CONDENSER_FAN_VALUE FRIDGE_WORKING FRIDGE_NOTIFICATION AMPLIFIER_VALUE STAIR_STATE
    INTERNAL_LIGHT_VALUE FUNCTIONAL_LIGHT_VALUE LIGHT_SYSTEM_MAIN_BUTTON
    LIGHT_SYSTEM_SWITCH_OFF_BUTTON LIGHT_GROUP_INTERNAL_LIGHTS
    LIGHT_GROUP_EXTERNAL_LIGHTS_BRIGHTNESS LIGHT_GROUP_1_VALUE PANEL_VALUE
    SOLAR_PANEL_POWER SOLAR_PANEL_CURRENT SOLAR_PANEL_POWER_STATE SOLAR_PANEL_CHARGING_PHASE
    SOLAR_PANEL_WORKING ENGINE_RELAY_VALUE BLACK_WATER_LEVEL FRESH_WATER_LEVEL_P
    WASTE_WATER_LEVEL_P REGISTERED_GAS_SENSOR REGISTERED_GAS_SENSOR_BACKUP
    GAS_BOTTLE_LEVEL GAS_BOTTLE_LEVEL_BACKUP ACTUAL_TEMPERATURE_BED_SENSOR
    LIVING_MEASURED_HUMIDITY CARBON_DIOXIDE_VALUE CARBON_DIOXIDE_ALARM_VALUE
    LTE_VALUE LTE_SIGNAL_STRENGTH LTE_REGISTRATION_STATUS USER_ALLOWS_ROAMING
    MACH_CONNECTION SYSTEM_POWER_REGIME PWR_RGM_CHNG_UTC MACHEND_DISCONNECT_UTC
    SYSTEM_PENDING_VALUE_IDS GPS_LATITUDE GPS_LONGITUDE ACCELERATION_X ACCELERATION_Y
    ACCELERATION_Z ACCELERATION_X_ZERO_POSITION_OFFSET ACCELERATION_Y_ZERO_POSITION_OFFSET
    ACCELERATION_Z_ZERO_POSITION_OFFSET TIRE_TEMPERATURE_LIMIT ROOF_STATE_VALUE
    ROOF_STATE_INFO_VALUE SYSTEM_CAMERA_1_CONNECTED SYSTEM_CAMERA_2_CONNECTED
    """.split()
    )
    | frozenset(
        f"LIGHT_GROUP_{n}_{suffix}" for n in range(1, 17) for suffix in ("BRIGHTNESS", "BUTTON")
    )
    | frozenset(f"LIGHT_SYSTEM_MEMORY_{n}" for n in range(1, 17))
    | frozenset(f"DIGITAL_OUTPUT_CONTROL_{n}" for n in range(1, 7))
    | frozenset(f"ROOM_{n}_MEASURED_TEMPERATURE" for n in range(1, 11))
    | frozenset(
        f"ROOM_{n}_{suffix}"
        for n in range(1, 6)
        for suffix in ("MEASURED_HUMIDITY", "CARBON_DIOXIDE_VALUE")
    )
    | frozenset(
        f"TIRE_{n}_{suffix}"
        for n in range(1, 7)
        for suffix in ("ADDRESS", "PRESSURE", "TEMPERATURE", "VOLTAGE", "UPDATE_TIME")
    )
    | frozenset(
        f"AXLE_{n}_PRESSURE_LIMIT_{suffix}" for n in range(1, 4) for suffix in ("LOW", "HIGH")
    )
    | frozenset(
        f"{prefix}_BATTERY_{suffix}"
        for prefix in ("CAR", "LIVING", "ADDITIONAL_LIVING")
        for suffix in ("VOLTAGE", "SOC", "SOH", "CURRENT", "CAPACITY", "TEMPERATURE")
    )
    | frozenset(
        f"BLUETOOTH_BATTERY_{n}_{suffix}"
        for n in (1, 2)
        for suffix in (
            "ADDRESS",
            "SOC",
            "STATUS",
            "VOLTAGE",
            "CURRENT",
            "REMAINING_CAPACITY",
            "FULL_CAPACITY",
            "TEMPERATURE",
            "SOH",
            "DISCHARGE_TIME",
            "UPDATE_TIME",
            "CONNECTED",
            "NAME",
        )
    )
)
EXCLUDED = frozenset(
    k
    for k in CANDIDATES
    if k.startswith("GPS_") or (k.endswith(("_ADDRESS", "_NAME")) and k != "LTE_OPERATOR_NAME")
) | {"SYSTEM_PENDING_VALUE_IDS"}
UNITS = {
    "LIVING_MEASURED_TEMPERATURE": "°C",
    "OUTSIDE_MEASURED_TEMPERATURE": "°C",
    "AIR_HEATER_TEMPERATURE": "°C",
    "AIR_CONDITION_TEMPERATURE": "°C",
    "OUTSIDE_MEASURED_HUMIDITY": "%",
    "MEASURED_PRESSURE": "hPa",
    "LIVING_BATTERY_VOLTAGE": "V",
    "LIVING_BATTERY_CURRENT": "A",
    "FRESH_WATER_LEVEL": "%",
    "WASTE_WATER_LEVEL": "%",
    "LTE_SIGNAL_STRENGTH": "%",
}
RANGES = {"AIR_HEATER_TEMPERATURE": (5, 30)} | {
    c.key: (1, 50) for c in (*Case, *OutsideControl) if c.individual_light
}
RANGES[EquipmentControl.AC_TARGET.key] = (16, 31)
CATEGORIES = {k: ("off", "on") for k, f in FIELDS.items() if f.kind == "binary"} | {
    "WATER_HEATER_TEMPERATURE": ("off", "normal", "boost"),
    "ENERGY_SOURCE": (
        "off",
        "gas",
        "el1",
        "el2",
        "el3",
        "el1_and_gas",
        "el2_and_gas",
        "el3_and_gas",
    ),
    "ENERGY_SOURCE_PRIORITY_SETTING": ("electricity", "gas"),
}
CATEGORIES.update({c.key: c.choices for c in CURRENT_CONTROLS if c.choices})
CATEGORIES.update({c.key: ("off", "on") for c in MasterControl})
READ_DOMAINS = {
    k: ("binary_sensor",) if f.kind == "binary" else ("sensor",) for k, f in FIELDS.items()
}
READ_DOMAINS.update(
    {
        k: ("binary_sensor",) if f.kind == "binary" else ("sensor",)
        for k, f in DIAGNOSTIC_FIELDS.items()
    }
)
WRITE_CONTROLS = (
    {
        OutsideControl.BINARY.key: ((OutsideControl.BINARY.value, "light", "manual_outside"),),
        ManualControl.HEATER.key: (
            (ManualControl.HEATER.value, "number", "manual_target"),
            (ManualControl.HEATER.value, "climate", "manual_target_context"),
        ),
        WaterControl.MODE.key: ((WaterControl.MODE.value, "water_heater", "manual_mode"),),
        HeatingControl.MODE.key: ((HeatingControl.MODE.value, "climate", "manual_heat_off"),),
    }
    | {
        c.key: ((c.value, "light", "manual_brightness"),)
        for c in ManualControl
        if c is not ManualControl.HEATER
    }
    | {
        c.key: ((c.value, "light", "manual_outside_brightness"),)
        for c in OutsideControl
        if c.individual_light
    }
)
WRITE_CONTROLS.update(
    {
        c.key: (
            (c.value, "button", "acknowledged_unconfirmed"),
            (c.value, "scene", "acknowledged_unconfirmed"),
        )
        if c.action
        else ((c.value, c.domain, "manual_equipment"),)
        for c in CURRENT_CONTROLS
    }
)
WRITE_CONTROLS.update(
    {
        c.key: (
            (c.value, "light", "reported_master_setting_only"),
            (c.value, "button", "explicit_master_off"),
        )
        for c in MasterControl
    }
)


@dataclass(frozen=True)
class Capability:
    index: int
    identifier: str | None
    disposition: str
    reason: str
    definition_type: str
    writable: bool | None
    has_state: bool | None
    native_domains: tuple[str, ...] = ()
    read_available: bool = False
    control_available: bool = False
    command_policies: tuple[str, ...] = ()
    unit: str | None = None
    verified_range: tuple[int, int] | None = None
    verified_step: int | None = None
    categories: tuple[str, ...] = ()
    off_sentinel: str = "not_verified"
    predicates: str = "not_verified_for_optional_equipment"


@dataclass(frozen=True)
class Inventory:
    definitions: tuple[Capability, ...]
    absent_candidates: tuple[str, ...]

    @property
    def summary(self):
        counts = Counter(c.disposition for c in self.definitions)
        return {"configured_definitions": len(self.definitions), **dict(sorted(counts.items()))}

    def export(self):
        return {
            "summary": self.summary,
            "definitions": [asdict(c) for c in self.definitions],
            "absent_reviewed_candidates": list(self.absent_candidates),
            "source_sample_at": None,
            "presence_means": "configured_affordance_not_hardware_or_physical_confirmation",
            "write_authority": "none_inventory_is_descriptive",
        }


def inventory(configuration, values, readings, controls, identified_equipment=()):
    """One disposition per input row; no arbitrary strings or current values escape."""
    definitions = configuration.get("values", [])
    rows = values.get("values", [])
    identifiers = [d.get("id") if isinstance(d, dict) else None for d in definitions]
    counts = Counter(k for k in identifiers if type(k) is str and k in CANDIDATES)
    result = []
    for index, definition in enumerate(definitions):
        raw = definition.get("id") if isinstance(definition, dict) else None
        key = raw if type(raw) is str and raw in CANDIDATES else None
        config = definition.get("config") if isinstance(definition, dict) else None
        config = config if isinstance(config, dict) else {}
        kind = config.get("type")
        kind = (
            kind
            if type(kind) is str and kind in ("integer", "float", "categorical", "string")
            else "unknown"
        )
        disposition, reason = "unsupported", "implementation_not_reviewed"
        if key is None:
            disposition, reason = "unsupported", "unknown_identifier_redacted"
            kind, config = "unknown", {}
        elif key in EXCLUDED:
            disposition, reason = "excluded", "privacy_or_administrative_data"
            kind, config = "unknown", {}
        elif counts[key] != 1:
            reason = "duplicate_definition"
        elif config.get("id") != key or kind == "unknown":
            reason = "invalid_definition"
        elif key in readings or key in WRITE_CONTROLS:
            disposition, reason = "implemented", "reviewed_native_mapping"
        matches = [r for r in rows if isinstance(r, dict) and r.get("device") == key] if key else []
        if (
            disposition == "implemented"
            and key not in readings
            and not any(c in controls for c, _, _ in WRITE_CONTROLS.get(key, ()))
        ):
            disposition, reason = "unsupported", "definition_or_context_not_eligible"
        read = disposition == "implemented" and readings.get(key) is not None
        commands = WRITE_CONTROLS.get(key, ()) if disposition == "implemented" else ()
        optional = next((c.equipment for c in CURRENT_CONTROLS if c.key == key), None)
        if disposition == "implemented" and optional and optional not in identified_equipment:
            commands = ()
            reason = "owner_equipment_identification_required"
            if key not in readings:
                disposition = "unsupported"
        available = tuple(
            (domain, policy)
            for c, domain, policy in commands
            if c in controls and (domain != "climate" or HeatingControl.MODE.value in controls)
        )
        domains = set(
            READ_DOMAINS.get(key, ()) if key in readings and disposition == "implemented" else ()
        )
        domains.update(d for d, _ in available)
        known_categories = CATEGORIES.get(key, ())
        raw_categories = config.get("categories")
        ids = (
            tuple(c.get("id") if isinstance(c, dict) else c for c in raw_categories)
            if isinstance(raw_categories, list)
            else ()
        )
        categories = tuple(c for c in known_categories if c in ids)
        verified_range = RANGES.get(key)
        if config.get("range") != list(verified_range or ()) or any(
            type(v) is not int for v in config.get("range", [])
        ):
            verified_range = None
        temperature = key in ("AIR_HEATER_TEMPERATURE", "AIR_CONDITION_TEMPERATURE")
        expected_step = 1 if temperature else 2
        step = config.get("step", 1 if temperature else None)
        verified_step = (
            expected_step
            if verified_range and type(step) is int and step == expected_step
            else None
        )
        result.append(
            Capability(
                index,
                key,
                disposition,
                reason,
                kind,
                config.get("writable") if type(config.get("writable")) is bool else None,
                config.get("hasState") if type(config.get("hasState")) is bool else None,
                tuple(sorted(domains)),
                read and len(matches) == 1,
                bool(available),
                tuple(sorted({p for _, p in available})),
                UNITS.get(key),
                verified_range,
                verified_step,
                categories,
                "-9007199254740991"
                if verified_range
                and key != "AIR_HEATER_TEMPERATURE"
                and config.get("offState") is True
                else "not_verified",
                "fresh_schema_and_state_context_checked"
                if available
                else "not_verified_for_optional_equipment",
            )
        )
    return Inventory(tuple(result), tuple(sorted(CANDIDATES - set(counts))))
