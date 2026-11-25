"""Expose the packaged, standalone Lovelace module."""

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.loader import async_get_integration

from .const import DOMAIN

RESOURCE = "/adria_mach/dashboard.js"


async def async_setup_dashboard(hass):
    """Publish only the frontend asset when HA's frontend is configured."""
    if "frontend" not in hass.config.components:
        return
    integration = await async_get_integration(hass, DOMAIN)
    path = Path(__file__).with_name("dashboard.js")
    await hass.http.async_register_static_paths(
        [StaticPathConfig(RESOURCE, str(path), cache_headers=False)]
    )
    add_extra_js_url(hass, f"{RESOURCE}?v={integration.version}")
