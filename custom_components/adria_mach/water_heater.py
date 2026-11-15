"""Verified water-heating modes without invented temperatures or power actions."""

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityDescription,
    WaterHeaterEntityFeature,
)
from homeassistant.const import UnitOfTemperature

from .client.control_model import WATER_MODES, WaterControl
from .entity import MachEntity

DESCRIPTION = WaterHeaterEntityDescription(
    key="WATER_HEATER_TEMPERATURE", translation_key="water_heater_control"
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    if WaterControl.MODE.value in coordinator.data.control_snapshots:
        async_add_entities([MachWaterHeater(coordinator, DESCRIPTION)])


class MachWaterHeater(MachEntity, WaterHeaterEntity):
    _attr_supported_features = WaterHeaterEntityFeature.OPERATION_MODE
    _attr_operation_list = list(WATER_MODES)
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS

    @property
    def available(self):
        return (
            super().available and WaterControl.MODE.value in self.coordinator.data.control_snapshots
        )

    @property
    def current_operation(self):
        return self.reading

    @property
    def capability_attributes(self):
        # Core's generic numeric defaults are not verified water-temperature limits.
        return {"operation_list": self.operation_list}

    @property
    def extra_state_attributes(self):
        return {
            **super().extra_state_attributes,
            **self.coordinator.commands.attributes_for(WaterControl.MODE),
        }

    async def async_set_operation_mode(self, operation_mode):
        await self.coordinator.commands.set_manual(WaterControl.MODE, operation_mode)
