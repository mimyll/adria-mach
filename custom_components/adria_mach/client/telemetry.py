"""Allowlisted network and installed-version telemetry; no remote configuration retained."""

import math
import re
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType


@dataclass(frozen=True)
class DiagnosticField:
    kind: str
    types: tuple[str, ...] = ("string",)
    writable: bool = False
    options: tuple[str, ...] = ()


SIM_STATES = (
    "SIM_READY",
    "INCORRECT_PASSWORD",
    "NETWORK_REGISTRATION_FAILED",
    "INCORRECT_APN",
    "INCORRECT_PDP_AUTHENTICATION",
    "SIM_PIN",
    "SIM_PIN2",
    "SIM_PUK",
    "SIM_PUK2",
    "PH_SIM_PIN",
    "PH_FSIM_PIN",
    "PH_FSIM_PUK",
    "PH_NET_PIN",
    "PH_NET_PUK",
    "PH_NETSUB_PIN",
    "PH_NETSUB_PUK",
    "PH_SP_PIN",
    "PH_SP_PUK",
    "PH_CORP_PIN",
    "PH_CORP_PUK",
    "SIM_NOT_INSERTED",
)
POWER_STATES = ("ON", "SLEEP", "HIBERNATION", "CHARGING", "SHUTDOWN")
DIAGNOSTIC_FIELDS = MappingProxyType(
    {
        "LTE_VALUE": DiagnosticField("binary", ("categorical",), True),
        "USER_ALLOWS_ROAMING": DiagnosticField("binary", ("categorical",), True),
        "LTE_OPERATOR_NAME": DiagnosticField("operator"),
        "LTE_COMMUNICATION_STANDARD": DiagnosticField("status"),
        "LTE_REGISTRATION_STATUS": DiagnosticField("status"),
        "LTE_SIGNAL_STRENGTH": DiagnosticField("signal", ("integer", "float")),
        "LTE_SIM_VALUE": DiagnosticField("enum", ("string", "categorical"), options=SIM_STATES),
        "SYSTEM_POWER_REGIME": DiagnosticField("power", ("categorical",), options=POWER_STATES),
        **{
            key: DiagnosticField("version")
            for key in (
                "SYSTEM_IO_FIRMWARE_VERSION",
                "SYSTEM_FIRMWARE_VERSION_MCU_1",
                "SYSTEM_FIRMWARE_VERSION_MCU_2",
                "PANEL_VERSION",
            )
        },
    }
)
METADATA = MappingProxyType(
    {
        "mach_software_version": ("version", "version"),
        "mach_os_release": ("osReleaseDate", "date"),
        "mach_release_channel": ("releaseType", "status"),
    }
)
DIAGNOSTIC_KEYS = frozenset(DIAGNOSTIC_FIELDS) | frozenset(METADATA)


def _value(value, field):
    if field.kind == "signal":
        if type(value) not in (int, float):
            return None
        # The vendor displays nonpositive/sentinel values as no reading, not 0%.
        return value if 0 < value <= 100 and math.isfinite(value) else None
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    if field.kind == "binary":
        return {"on": True, "off": False}.get(value)
    if field.kind in ("enum", "power"):
        candidate = value.upper() if field.kind == "power" else value
        return candidate if candidate in field.options else None
    if field.kind == "date":
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            return None
        try:
            date.fromisoformat(value)
        except ValueError:
            return None
        return value
    patterns = {
        "operator": r"[\w][\w .&()+/-]{0,63}",
        "status": r"[A-Za-z0-9][A-Za-z0-9 _+./-]{0,47}",
        "version": r"(?=.*[0-9])[A-Za-z0-9][A-Za-z0-9 ._()+/-]{0,95}",
    }
    return value if re.fullmatch(patterns[field.kind], value) else None


def diagnostic_readings(configuration, values):
    """Validate each optional field independently; definitions never grant write access."""
    result = {}
    for key, field in DIAGNOSTIC_FIELDS.items():
        definitions = [
            r for r in configuration["values"] if isinstance(r, dict) and r.get("id") == key
        ]
        if len(definitions) != 1:
            continue
        config = definitions[0].get("config")
        if (
            not isinstance(config, dict)
            or config.get("id") != key
            or config.get("type") not in field.types
            or (
                type(config.get("writable")) is not bool
                and not (field.writable and config.get("writable") is None)
            )
            or (config.get("writable") is True and not field.writable)
            or config.get("hasState") is False
        ):
            continue
        rows = [r for r in values["values"] if isinstance(r, dict) and r.get("device") == key]
        result[key] = _value(rows[0].get("status"), field) if len(rows) == 1 else None
    for key, (source, kind) in METADATA.items():
        value = _value(configuration.get(source), DiagnosticField(kind))
        if value is not None:
            result[key] = value
    return result
