"""Only normalized technical inventory, never entries, registries or raw responses."""

from .client.operational import CURRENT_CONTROLS
from .const import UPDATE_SECONDS


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    report = coordinator.data.capabilities
    return {
        "capabilities": report.export() if report else None,
        "received_at": coordinator.data.received_at.isoformat(),
        "source_sample_at": None,
        "update_seconds": UPDATE_SECONDS,
        "last_update_success": coordinator.last_update_success,
        "controls_blocked": coordinator.commands.blocked,
        "onoff_light_overrides": sorted(coordinator.onoff_lights),
        "identified_equipment": sorted(coordinator.equipment),
        "withheld_equipment": sorted(
            set(("aux", "alde", "air_conditioning")) - coordinator.equipment
        ),
        "protocol_eligible_equipment_controls": sorted(
            c.value for c in CURRENT_CONTROLS if c.value in coordinator.data.control_snapshots
        ),
        "last_command_duration_ms": coordinator.commands.last_duration_ms,
        "ack_diagnostics": (coordinator.commands.ack or {}).get("diagnostics")
        or {"classification": "not_recorded"},
        "connection_probe": coordinator.last_connection_probe,
        "live_connection": coordinator.client.live.facts()
        if getattr(coordinator.client, "live", None) is not None
        else None,
        "physical_confirmation": "not_recorded",
    }
