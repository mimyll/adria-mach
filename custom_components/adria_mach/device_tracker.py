"""Optional native vehicle location, excluded from general diagnostics."""

from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.helpers.entity import EntityDescription

from .entity import MachEntity, async_discover_diagnostics

LOCATION = EntityDescription(
    key="location",
    translation_key="location",
    entity_registry_enabled_default=False,
    icon="mdi:caravan",
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_discover_diagnostics(
        entry,
        (LOCATION,),
        MachLocation,
        async_add_entities,
        present=lambda description: entry.runtime_data.data.location is not None,
    )


class MachLocation(MachEntity, TrackerEntity):
    @property
    def reading(self):
        return self.coordinator.data.location

    @property
    def latitude(self):
        return self.reading.latitude if self.available else None

    @property
    def longitude(self):
        return self.reading.longitude if self.available else None
