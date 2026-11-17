"""Adria MACH monitoring and narrowly bounded owner-operated test controls."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import CONF_MACH_ID, DOMAIN


def CONFIG_SCHEMA(config):
    """Defer HA imports so the protocol package stays independently testable."""
    from homeassistant.helpers import config_validation as cv

    return cv.config_entry_only_config_schema(DOMAIN)(config)


async def async_setup(hass, config):
    from .services import async_setup_services

    async_setup_services(hass)
    return True


if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .coordinator import MachCoordinator

    type MachConfigEntry = ConfigEntry[MachCoordinator]


def create_client(hass):
    """Keep cookie isolation while reusing HA's verified TLS connector."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from .client import MachClient

    return MachClient(connector=async_get_clientsession(hass).connector, persistent=True)


async def async_setup_entry(hass: HomeAssistant, entry: MachConfigEntry) -> bool:
    from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
    from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

    from .client import AuthenticationError, MachError
    from .coordinator import MachCoordinator

    client = create_client(hass)
    ready = False
    coordinator = None
    try:
        try:
            devices = await client.authenticate(
                entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
            )
            if entry.data[CONF_MACH_ID] not in {device.id for device in devices}:
                raise ConfigEntryAuthFailed("device_not_assigned")
        except AuthenticationError:
            raise ConfigEntryAuthFailed("authentication_rejected") from None
        except MachError:
            raise ConfigEntryNotReady("cannot_connect") from None
        client.configure_session_renewal(
            entry.data[CONF_MACH_ID],
            lambda: (entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]),
        )
        coordinator = MachCoordinator(hass, entry, client)
        entry.runtime_data = coordinator
        await coordinator.async_config_entry_first_refresh()
        await coordinator.commands.setup()
        await coordinator.maintenance.setup()
        from .maintenance import FirmwareCoordinator

        coordinator.firmware = FirmwareCoordinator(coordinator, entry)
        await coordinator.firmware.async_refresh()
        await hass.config_entries.async_forward_entry_setups(
            entry,
            [
                Platform.SENSOR,
                Platform.DEVICE_TRACKER,
                Platform.BINARY_SENSOR,
                Platform.LIGHT,
                Platform.NUMBER,
                Platform.WATER_HEATER,
                Platform.CLIMATE,
                Platform.SWITCH,
                Platform.SELECT,
                Platform.BUTTON,
                Platform.SCENE,
                Platform.UPDATE,
            ],
        )
        entry.async_on_unload(coordinator.async_close)
        ready = True
        return True
    finally:
        if not ready:
            if coordinator:
                await coordinator.async_close()
            else:
                await client.close()


async def async_unload_entry(hass: HomeAssistant, entry: MachConfigEntry) -> bool:
    from homeassistant.const import Platform

    await entry.runtime_data.commands.close()
    return await hass.config_entries.async_unload_platforms(
        entry,
        [
            Platform.SENSOR,
            Platform.DEVICE_TRACKER,
            Platform.BINARY_SENSOR,
            Platform.LIGHT,
            Platform.NUMBER,
            Platform.WATER_HEATER,
            Platform.CLIMATE,
            Platform.SWITCH,
            Platform.SELECT,
            Platform.BUTTON,
            Platform.SCENE,
            Platform.UPDATE,
        ],
    )
