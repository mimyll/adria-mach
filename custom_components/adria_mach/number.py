"""Native target slider; no heater enable, mode, source or thermostat loop."""

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import UnitOfTemperature

from .client.control_model import OFF_LEVEL, ManualControl
from .entity import MachEntity
from .equipment_entity import MachEquipmentEntity, setup_equipment

DESCRIPTION = NumberEntityDescription(
    key="AIR_HEATER_TEMPERATURE",
    translation_key="heater_target_control",
    device_class=NumberDeviceClass.TEMPERATURE,
    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    if ManualControl.HEATER.value in coordinator.data.control_snapshots:
        async_add_entities([MachHeaterTarget(coordinator, DESCRIPTION)])
    setup_equipment(entry, async_add_entities, "number", MachAcTarget)


class MachHeaterTarget(MachEntity, NumberEntity):
    _attr_native_min_value = 5
    _attr_native_max_value = 30
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    @property
    def available(self):
        return (
            super().available
            and ManualControl.HEATER.value in self.coordinator.data.control_snapshots
        )

    @property
    def native_value(self):
        return self.reading

    @property
    def extra_state_attributes(self):
        return {
            **super().extra_state_attributes,
            **self.coordinator.commands.attributes_for(ManualControl.HEATER),
        }

    async def async_set_native_value(self, value):
        if type(value) not in (int, float) or not 5 <= value <= 30 or value != int(value):
            raise self.coordinator.commands.error("invalid_control_value")
        await self.coordinator.commands.set_manual(ManualControl.HEATER, int(value))


class MachAcTarget(MachEquipmentEntity, NumberEntity):
    _attr_native_min_value = 16
    _attr_native_max_value = 31
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, control):
        super().__init__(
            coordinator,
            control,
            NumberEntityDescription(
                key="ac_target",
                translation_key="ac_target",
                device_class=NumberDeviceClass.TEMPERATURE,
                native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            ),
        )

    @property
    def native_value(self):
        return self.reading if self.reading != OFF_LEVEL else None

    async def async_set_native_value(self, value):
        if type(value) not in (int, float) or not 16 <= value <= 31 or value != int(value):
            raise self.coordinator.commands.error("invalid_control_value")
        await self.request(int(value))
