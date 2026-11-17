"""Single snapshot/poll owner for one assigned vehicle."""

import asyncio
import logging
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import timedelta

from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import AuthenticationError, MachError, Measurement
from .const import (
    CONF_EQUIPMENT,
    CONF_MACH_ID,
    CONF_ONOFF_LIGHTS,
    DOMAIN,
    EQUIPMENT_OPTIONS,
    LIGHT_OPTIONS,
    UPDATE_SECONDS,
)

LOGGER = logging.getLogger(__name__)


class MachCoordinator(DataUpdateCoordinator[Measurement]):
    def __init__(self, hass, entry, client):
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=UPDATE_SECONDS),
        )
        self.client = client
        self.device_id = entry.data[CONF_MACH_ID]
        identified = entry.options.get(CONF_EQUIPMENT, [])
        self.equipment = (
            frozenset(
                item for item in identified if type(item) is str and item in EQUIPMENT_OPTIONS
            )
            if type(identified) is list
            else frozenset()
        )
        self.client.identified_equipment = self.equipment
        selected = entry.options.get(CONF_ONOFF_LIGHTS, [])
        self.onoff_lights = (
            frozenset(item for item in selected if type(item) is str and item in LIGHT_OPTIONS)
            if type(selected) is list
            else frozenset()
        )
        from .command_manager import CommandManager

        self.commands = CommandManager(hass, self, entry)
        from .maintenance import Maintenance

        self.maintenance = Maintenance(self)
        self.firmware = None
        from .connection_health import ConnectionHealthCoordinator

        self.health = ConnectionHealthCoordinator(self, entry)
        client.recovery_admission = self._recovery_admission
        self.last_connection_probe = None
        self.last_session_renewal_test = None
        if getattr(client, "live", None) is not None:
            client.live.listener = self._live_update
            client.live.error_listener = self._live_error
            client.live.state_listener = self.health.changed

    def _live_update(self, snapshot):
        if not self.commands.session_test:
            self.async_set_updated_data(snapshot)
            self.health.changed()

    def _live_error(self, error):
        if self.commands.session_test:
            return
        self._authentication_error(error)

    def _authentication_error(self, error):
        self.async_set_update_error(UpdateFailed("authentication_rejected"))
        if isinstance(error, AuthenticationError):
            self.config_entry.async_start_reauth(self.hass)

    async def async_connection_probe(self):
        from .connection_probe import run_probe

        if (
            self.commands.closed
            or self.commands.task
            or self.commands.probe_task
            or self.commands.lights.worker
        ):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="probe_busy")
        self.commands.probe_task = asyncio.current_task()
        try:
            report = await run_probe(self)
            if report["outcome"] not in ("completed", "recovered"):
                raise HomeAssistantError(translation_domain=DOMAIN, translation_key="probe_failed")
            return deepcopy(report)
        finally:
            self.commands.probe_task = None

    @asynccontextmanager
    async def _recovery_admission(self):
        commands = self.commands
        if (
            commands.closed
            or commands.task
            or commands.probe_task
            or commands.session_test
            or commands.lights.worker
            or commands.lights.pending
            or commands.io_jobs
        ):
            yield False
            return
        # The watchdog creates a finite task per attempt; manual requests may await this slot.
        task = asyncio.current_task()
        commands.probe_task = task
        try:
            yield True
        finally:
            if commands.probe_task is task:
                commands.probe_task = None

    async def async_close(self):
        try:
            await self.commands.close()
        finally:
            try:
                if getattr(self.client, "live", None) is not None:
                    self.client.live.state_listener = None
                await self.health.async_close()
                if self.firmware is not None:
                    await self.firmware.async_close()
            finally:
                await self.client.close()

    async def async_test_session_renewal(self):
        from .connection_probe import run_session_renewal_test

        commands = self.commands
        if (
            commands.closed
            or commands.task
            or commands.probe_task
            or commands.lights.worker
            or commands.lights.pending
            or commands.io_jobs
        ):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="probe_busy")
        commands.session_test = True
        commands.probe_task = asyncio.current_task()
        try:
            report = await run_session_renewal_test(self)
            if report["outcome"] not in ("completed", "not_reproduced"):
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="session_test_failed"
                )
            return deepcopy(report)
        finally:
            report = self.last_session_renewal_test
            if report and report["owned_cookies_cleared"]:
                if report["outcome"] == "authentication_required":
                    self._authentication_error(AuthenticationError("authentication_rejected"))
                elif report["outcome"] not in ("completed", "not_reproduced"):
                    self.async_set_update_error(UpdateFailed("session_test_incomplete"))
            commands.probe_task = None
            commands.session_test = False

    async def _async_update_data(self) -> Measurement:
        try:
            return await self.client.read(self.device_id)
        except AuthenticationError:
            raise ConfigEntryAuthFailed("authentication_rejected") from None
        except MachError:
            raise UpdateFailed("cannot_read_states") from None
