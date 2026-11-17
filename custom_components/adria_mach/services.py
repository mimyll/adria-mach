"""Native read-only diagnostic action; no generic transport or actuator service."""

import probatio as vol
from homeassistant.const import ATTR_CONFIG_ENTRY_ID
from homeassistant.core import SupportsResponse, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service

from .const import DOMAIN


@callback
def async_setup_services(hass):
    async def acknowledge_restart(call):
        entry = service.async_get_config_entry(hass, DOMAIN, call.data[ATTR_CONFIG_ENTRY_ID])
        return await entry.runtime_data.maintenance.async_acknowledge(call.data["request_id"])

    service.async_register_admin_service(
        hass,
        DOMAIN,
        "acknowledge_restart",
        acknowledge_restart,
        schema=vol.Schema(
            {
                vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
                vol.Required("request_id"): vol.Match(r"^[a-f0-9]{32}$"),
                vol.Required("confirm"): vol.All(bool, vol.In([True])),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    async def probe_connection(call):
        entry = service.async_get_config_entry(hass, DOMAIN, call.data[ATTR_CONFIG_ENTRY_ID])
        return await entry.runtime_data.async_connection_probe()

    async def test_session_renewal(call):
        entry = service.async_get_config_entry(hass, DOMAIN, call.data[ATTR_CONFIG_ENTRY_ID])
        return await entry.runtime_data.async_test_session_renewal()

    service.async_register_admin_service(
        hass,
        DOMAIN,
        "test_session_renewal",
        test_session_renewal,
        schema=vol.Schema(
            {
                vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
                vol.Required("confirm"): vol.All(bool, vol.In([True])),
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    service.async_register_admin_service(
        hass,
        DOMAIN,
        "probe_connection",
        probe_connection,
        schema=vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string}),
        supports_response=SupportsResponse.ONLY,
    )
