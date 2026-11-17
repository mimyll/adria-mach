"""Network-free connection diagnostics with an independent age clock."""

import logging
from datetime import UTC, datetime, timedelta

from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN

CONNECTION_STATES = [
    "unknown",
    "disconnected",
    "connecting",
    "ready",
    "reconnecting",
    "checking",
    "authentication_required",
    "rate_limited",
    "closed",
]
LOGGER = logging.getLogger(__name__)


def age(value, now):
    return max(0, int((now - value).total_seconds())) if value is not None else None


class ConnectionHealthCoordinator(DataUpdateCoordinator):
    def __init__(self, main, entry):
        super().__init__(
            main.hass,
            LOGGER,
            name="MACH connection health",
            config_entry=entry,
            update_interval=timedelta(seconds=30),
        )
        self.main = main
        self.closed = False

    def snapshot(self):
        main = self.main
        live = getattr(main.client, "live", None)
        facts = live.facts() if live is not None else {}
        now = datetime.now(UTC)
        measurement = getattr(main, "data", None)
        contact = live.metadata.last_contact if live is not None else None
        traffic = live.last_traffic_at if live is not None else None
        idle = facts.get("stream_idle_seconds")
        stream_ok = bool(facts.get("connection_ready")) and (
            idle is not None and idle < facts["stream_inactivity_budget_seconds"]
        )
        status = facts.get("connection_state", "unknown")
        if status == "ready" and not stream_ok:
            status = "checking"
        return {
            **facts,
            "connection_state": status if status in CONNECTION_STATES else "unknown",
            "event_stream_connected": bool(facts.get("connection_ready"))
            if live is not None
            else None,
            "last_stream_traffic": traffic,
            "last_snapshot_age": age(measurement.received_at, now) if measurement else None,
            "reported_device_contact": contact,
            "reported_device_contact_age": age(contact, now),
            "last_read_successful": main.last_update_success,
        }

    def changed(self):
        if not self.closed:
            self.async_set_updated_data(self.snapshot())

    async def _async_update_data(self):
        return self.snapshot()

    async def async_close(self):
        self.closed = True
        await self.async_shutdown()


class ConnectionHealthEntity(CoordinatorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, main, description):
        super().__init__(main.health)
        self.entity_description = description
        self._attr_unique_id = f"{main.device_id}_{description.key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, main.device_id)})

    @property
    def available(self):
        # These diagnostics must explain telemetry failures, not disappear with them.
        return not self.coordinator.closed and self.coordinator.data is not None

    @property
    def reading(self):
        return self.coordinator.data.get(self.entity_description.key)

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        return {
            key: data.get(key)
            for key in (
                "last_read_successful",
                "connection_generation",
                "connection_handshakes",
                "recovery_attempts",
                "successful_recoveries",
                "last_recovery_at",
                "last_recovery_reason",
                "last_connection_error",
                "stream_inactivity_budget_seconds",
            )
        } | {
            "snapshot_age_scope": "home_assistant_receipt",
            "contact_age_scope": "reported_device_contact_not_sample_time",
            "physical_confirmation": "not_recorded",
        }
