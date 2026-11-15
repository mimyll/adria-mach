"""Reusable local HTTP transport boundary; no public service access."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from aiohttp import web


@pytest.fixture
def full_snapshot():
    return json.loads((Path(__file__).parent / "fixtures" / "monitoring.json").read_text())


@pytest.fixture
def diagnostic_snapshot(full_snapshot):
    """Synthetic data: keep the historical monitoring fixture unchanged."""
    full_snapshot = deepcopy(full_snapshot)
    fields = {
        "LTE_VALUE": ("categorical", True, "on", True),
        "USER_ALLOWS_ROAMING": ("categorical", True, "off", False),
        "LTE_OPERATOR_NAME": ("string", False, "Example Mobile", "Example Mobile"),
        "LTE_COMMUNICATION_STANDARD": ("string", False, "4G", "4G"),
        "LTE_REGISTRATION_STATUS": ("string", False, "ROAMING", "ROAMING"),
        "LTE_SIGNAL_STRENGTH": ("integer", False, 73, 73),
        "LTE_SIM_VALUE": ("string", False, "SIM_READY", "SIM_READY"),
        "SYSTEM_POWER_REGIME": ("categorical", False, "sleep", "SLEEP"),
        "SYSTEM_IO_FIRMWARE_VERSION": ("string", False, "03.004.005", "03.004.005"),
        "SYSTEM_FIRMWARE_VERSION_MCU_1": ("string", False, "2.3-beta", "2.3-beta"),
    }
    full_snapshot["configuration"].update(
        version="9.8.7 2030-01-02", osReleaseDate="2030-01-02", releaseType="PRODUCTION"
    )
    for key, (kind, writable, value, normalized) in fields.items():
        full_snapshot["configuration"]["values"].append(
            {"id": key, "config": {"id": key, "type": kind, "writable": writable}}
        )
        full_snapshot["values"]["values"].append({"device": key, "status": value})
        full_snapshot["normalized"][key] = normalized
    full_snapshot["normalized"].update(
        mach_software_version="9.8.7 2030-01-02",
        mach_os_release="2030-01-02",
        mach_release_channel="PRODUCTION",
    )
    return full_snapshot


@pytest.fixture
def position_snapshot(diagnostic_snapshot):
    """Synthetic offshore coordinates and independent acceleration vectors."""
    data = deepcopy(diagnostic_snapshot)
    for key, value in {
        "ACCELERATION_X": 0.0,
        "ACCELERATION_Y": 0.0,
        "ACCELERATION_Z": 1.0,
        "GPS_LATITUDE": 10.125,
        "GPS_LONGITUDE": -20.25,
    }.items():
        data["configuration"]["values"].append(
            {"id": key, "config": {"id": key, "type": "float", "writable": False}}
        )
        data["values"]["values"].append({"device": key, "status": value})
    return data


@pytest.fixture
async def loopback():
    runners = []

    async def start(handler):
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        runners.append(runner)
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        return "http://127.0.0.1:" + str(runner.addresses[0][1])

    yield start
    for runner in reversed(runners):
        await runner.cleanup()
