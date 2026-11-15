"""Single snapshot/poll owner for one assigned vehicle."""

import asyncio
import logging
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
        self.last_connection_probe = None
        if getattr(client, "live", None) is not None:
            client.live.listener = self.async_set_updated_data
            client.live.error_listener = self._live_error

    def _live_error(self, error):
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

    async def async_close(self):
        try:
            await self.commands.close()
        finally:
            await self.client.close()

    async def _async_update_data(self) -> Measurement:
        try:
            return await self.client.read(self.device_id)
        except AuthenticationError:
            raise ConfigEntryAuthFailed("authentication_rejected") from None
        except MachError:
            raise UpdateFailed("cannot_read_states") from None
