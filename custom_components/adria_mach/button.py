"""Explicit vehicle light-memory save; ACK does not prove persistence."""

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription

from .equipment_entity import MachEquipmentEntity, setup_equipment
from .master_entity import MachMasterEntity, setup_master


async def async_setup_entry(hass, entry, async_add_entities):
    setup_equipment(entry, async_add_entities, "action", MachMemorySave)
    setup_master(entry, async_add_entities, MachAllLightsOff)


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
