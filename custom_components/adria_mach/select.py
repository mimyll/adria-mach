"""Actual finite categories, including refrigerator levels without invented temperatures."""

from homeassistant.components.select import SelectEntity, SelectEntityDescription

from .equipment_entity import MachEquipmentEntity, setup_equipment


async def async_setup_entry(hass, entry, async_add_entities):
    setup_equipment(entry, async_add_entities, "select", MachEquipmentSelect)


class MachEquipmentSelect(MachEquipmentEntity, SelectEntity):
    def __init__(self, coordinator, control):
        key = getattr(control, "entity_key", control.value.replace("-", "_"))
        super().__init__(
            coordinator, control, SelectEntityDescription(key=key, translation_key=key)
        )

    @property
    def options(self):
        return list(self.snapshot.choices) if self.snapshot else []

    @property
    def current_option(self):
        return self.reading if self.reading in self.options else None

    @property
    def extra_state_attributes(self):
        return {**super().extra_state_attributes, "observed_setting": self.reading}

    async def async_select_option(self, option):
        await self.request(option)
