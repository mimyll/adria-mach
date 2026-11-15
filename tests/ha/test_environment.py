"""Exercise the exact core fixture before integration-specific tests."""

import os
from importlib.metadata import version


async def test_target_environment(hass):
    assert version("homeassistant") == os.environ.get("EXPECTED_HA_VERSION", "2026.11.0")
    assert hass.config_entries is not None
