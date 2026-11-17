"""Native firmware availability, explicitly without installation support."""

from homeassistant.components.update import UpdateDeviceClass, UpdateEntity, UpdateEntityFeature
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client.firmware import version_key
from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([MachFirmware(entry.runtime_data)])


class MachFirmware(CoordinatorEntity, UpdateEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "firmware"
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_supported_features = UpdateEntityFeature(0)

    def __init__(self, main):
        super().__init__(main.firmware)
        self._attr_unique_id = f"{main.device_id}_firmware"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, main.device_id)})

    @property
    def installed_version(self):
        return self.coordinator.data.installed if self.coordinator.data else None

    @property
    def latest_version(self):
        return self.coordinator.data.latest if self.coordinator.data else None

    def version_is_newer(self, latest_version, installed_version):
        return version_key(latest_version) > version_key(installed_version)

    @property
    def extra_state_attributes(self):
        return {"checked_at": self.coordinator.checked_at, "installation_supported": False}

    async def async_update(self):
        await self.coordinator.async_request_refresh()
