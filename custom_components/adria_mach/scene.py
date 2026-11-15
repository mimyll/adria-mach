"""Explicit vehicle light-memory recall; the saved light levels are not known."""

from homeassistant.components.scene import Scene
from homeassistant.helpers.entity import EntityDescription

from .equipment_entity import MachEquipmentEntity, setup_equipment


async def async_setup_entry(hass, entry, async_add_entities):
    setup_equipment(entry, async_add_entities, "action", MachMemoryRecall)


class MachMemoryRecall(MachEquipmentEntity, Scene):
    def __init__(self, coordinator, control):
        super().__init__(
            coordinator,
            control,
            EntityDescription(
                key=control.value.replace("-", "_") + "_restore",
                translation_key="light_memory_restore",
            ),
        )
        self._attr_translation_placeholders = {"number": control.value.rsplit("-", 1)[1]}

    async def async_activate(self, **kwargs):
        # Transition/brightness parameters are not translated into additional writes.
        if kwargs:
            raise self.coordinator.commands.error("invalid_control_value")
        await self.request("restore")
