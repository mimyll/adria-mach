"""Finite equipment power switches; state always comes from a service read."""

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription

from .client.operational import EquipmentControl
from .equipment_entity import MachEquipmentEntity, setup_equipment
from .light import PendingLightDisplay


async def async_setup_entry(hass, entry, async_add_entities):
    setup_equipment(entry, async_add_entities, "switch", MachEquipmentSwitch)


class MachEquipmentSwitch(PendingLightDisplay, MachEquipmentEntity, SwitchEntity):
    def __init__(self, coordinator, control):
        key = getattr(control, "entity_key", control.value.replace("-", "_"))
        super().__init__(
            coordinator,
            control,
            SwitchEntityDescription(
                key=key,
                translation_key=key,
            ),
        )

    @property
    def request_control(self):
        return self.control if self.control is EquipmentControl.AUX else None

    @property
    def reported_is_on(self):
        return self.reading == "on" if self.reading is not None else None

    async def async_turn_on(self, **kwargs):
        await self.request("on")

    async def async_turn_off(self, **kwargs):
        await self.request("off")
