"""Mock only the external MACH client; retain actual HA lifecycle and entities."""

from datetime import UTC, datetime

import pytest

import custom_components.adria_mach as integration
from custom_components.adria_mach import config_flow
from custom_components.adria_mach.client.model import Device, Measurement
from custom_components.adria_mach.const import VALUE_ID


@pytest.fixture
def backend(monkeypatch, full_snapshot):
    class Backend:
        devices = (Device("synthetic-a", "Vehicle A"),)
        auth_error = None
        read_error = None
        temperature = 0
        clients = []
        reads = 0

    state = Backend()
    state.clients = []
    state.readings = full_snapshot["normalized"]
    state.control_snapshots = {}
    state.capabilities = None
    state.location = None
    from custom_components.adria_mach.client.vehicle import VehicleInfo

    state.vehicle = VehicleInfo()

    class Client:
        def __init__(self):
            self.closed = False
            state.clients.append(self)

        def configure_session_renewal(self, device_id, credentials):
            self.renewal_device = device_id
            self.renewal_credentials = credentials

        async def authenticate(self, username, password):
            if state.auth_error:
                raise state.auth_error
            return state.devices

        async def read(self, device_id):
            assert device_id == "synthetic-a"
            state.reads += 1
            if state.read_error:
                raise state.read_error
            readings = {**state.readings, VALUE_ID: state.temperature}
            return Measurement(
                readings,
                datetime.now(UTC),
                state.control_snapshots,
                state.capabilities,
                state.location,
                state.vehicle,
            )

        async def close(self):
            self.closed = True

    monkeypatch.setattr(integration, "create_client", lambda hass: Client())
    monkeypatch.setattr(config_flow, "create_client", lambda hass: Client())
    return state
