"""Observed heating thermostat; explicit scalar requests, never a control loop."""

import math

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import (
    ATTR_AREA_ID,
    ATTR_DEVICE_ID,
    ATTR_ENTITY_ID,
    ATTR_FLOOR_ID,
    ATTR_LABEL_ID,
    ATTR_TEMPERATURE,
    UnitOfTemperature,
)

from .client.control_model import HeatingControl, ManualControl
from .const import VALUE_ID
from .entity import MachEntity

DESCRIPTION = ClimateEntityDescription(key="heating_climate", translation_key="heating_climate")


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    if HeatingControl.MODE.value in coordinator.data.control_snapshots:
        async_add_entities([MachHeatingClimate(coordinator, DESCRIPTION)])


class MachHeatingClimate(MachEntity, ClimateEntity):
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_min_temp = 5
    _attr_max_temp = 30
    _attr_target_temperature_step = 1

    @property
    def reading(self):
        return self.coordinator.data.values.get("AIR_HEATER_VALUE")

    @property
    def available(self):
        return (
            super().available
            and HeatingControl.MODE.value in self.coordinator.data.control_snapshots
        )

    @property
    def hvac_mode(self):
        if type(self.reading) is bool:
            return HVACMode.HEAT if self.reading else HVACMode.OFF
        return None

    @property
    def native_current_temperature(self):
        return self.coordinator.data.values.get(VALUE_ID)

    @property
    def native_target_temperature(self):
        return self.coordinator.data.values.get("AIR_HEATER_TEMPERATURE")

    @property
    def extra_state_attributes(self):
        return {
            **super().extra_state_attributes,
            **self.coordinator.commands.attributes_for(ManualControl.HEATER, HeatingControl.MODE),
            "target_requires": "heating_enabled_ready_and_mains_on",
        }

    async def async_set_temperature(self, **kwargs):
        # Core's climate service forwards its already-resolved target selectors too.
        selectors = {ATTR_ENTITY_ID, ATTR_DEVICE_ID, ATTR_AREA_ID, ATTR_FLOOR_ID, ATTR_LABEL_ID}
        kwargs = {key: value for key, value in kwargs.items() if key not in selectors}
        if set(kwargs) != {ATTR_TEMPERATURE}:
            raise self.coordinator.commands.error("invalid_control_value")
        value = kwargs[ATTR_TEMPERATURE]
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not 5 <= value <= 30
            or value != int(value)
        ):
            raise self.coordinator.commands.error("invalid_control_value")
        await self.coordinator.commands.set_manual(ManualControl.HEATER, int(value), climate=True)

    async def async_set_hvac_mode(self, hvac_mode):
        if hvac_mode not in (HVACMode.OFF, HVACMode.HEAT):
            raise self.coordinator.commands.error("invalid_control_value")
        await self.coordinator.commands.set_manual(
            HeatingControl.MODE, "on" if hvac_mode == HVACMode.HEAT else "off"
        )

    async def async_turn_on(self):
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self):
        await self.async_set_hvac_mode(HVACMode.OFF)
