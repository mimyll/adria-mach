"""Shared stable identity and availability for one normalized snapshot field."""

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MachCoordinator


def async_discover_diagnostics(
    entry, descriptions, entity_type, async_add_entities, *, present=None
):
    """Add optional diagnostics on the first valid shared snapshot, once per platform."""
    coordinator = entry.runtime_data
    seen = set()

    @callback
    def discover():
        if not coordinator.last_update_success:
            return
        new = [
            d
            for d in descriptions
            if d.key not in seen
            and (
                present(d)
                if present is not None
                else coordinator.data.values.get(d.key) is not None
            )
        ]
        seen.update(d.key for d in new)
        if new:
            async_add_entities([entity_type(coordinator, d) for d in new])

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class MachEntity(CoordinatorEntity[MachCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator, description):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            name="Adria MACH",
            manufacturer="Adria",
            model="MACH PLUS",
        )

    @property
    def reading(self):
        return self.coordinator.data.values.get(self.entity_description.key)

    @property
    def available(self) -> bool:
        return super().available and self.reading is not None

    @property
    def extra_state_attributes(self):
        return {"received_at": self.coordinator.data.received_at.isoformat()}
