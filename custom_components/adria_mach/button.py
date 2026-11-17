"""Explicit vehicle light-memory save; ACK does not prove persistence."""

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .equipment_entity import MachEquipmentEntity, setup_equipment
from .master_entity import MachMasterEntity, setup_master


async def async_setup_entry(hass, entry, async_add_entities):
    setup_equipment(entry, async_add_entities, "action", MachMemorySave)
    setup_master(entry, async_add_entities, MachAllLightsOff)
    async_add_entities([MachRestart(entry.runtime_data), MachCheckUpdates(entry.runtime_data)])


class MachMemorySave(MachEquipmentEntity, ButtonEntity):
    def __init__(self, coordinator, control):
        super().__init__(
            coordinator,
            control,
            ButtonEntityDescription(
                key=control.value.replace("-", "_") + "_save",
                translation_key="light_memory_save",
            ),
        )
        self._attr_translation_placeholders = {"number": control.value.rsplit("-", 1)[1]}

    async def async_press(self):
        await self.request("save")


class MachAllLightsOff(MachMasterEntity, ButtonEntity):
    def __init__(self, coordinator):
        super().__init__(
            coordinator,
            ButtonEntityDescription(key="all_lights_off", translation_key="all_lights_off"),
        )

    async def async_press(self):
        await self.request_master("off")


class MachMaintenanceButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key):
        self.main = coordinator
        self._attr_unique_id = f"{coordinator.device_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.device_id)})

    async def async_added_to_hass(self):
        self.async_on_remove(self.main.async_add_listener(self.async_write_ha_state))
        self.async_on_remove(self.main.firmware.async_add_listener(self.async_write_ha_state))


class MachRestart(MachMaintenanceButton):
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, coordinator):
        super().__init__(coordinator, "restart")

    @property
    def available(self):
        return self.main.last_update_success and not self.main.commands.closed

    @property
    def extra_state_attributes(self):
        return self.main.maintenance.store.attributes

    async def async_press(self):
        await self.main.maintenance.async_restart()


class MachCheckUpdates(MachMaintenanceButton):
    def __init__(self, coordinator):
        super().__init__(coordinator, "check_firmware_updates")

    async def async_press(self):
        await self.main.firmware.async_request_refresh()
        if not self.main.firmware.last_update_success:
            raise self.main.commands.error("firmware_check_failed")
