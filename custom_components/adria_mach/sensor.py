"""Verified numeric measurements and read-only reported settings."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPressure,
    UnitOfTemperature,
)

from .const import VALUE_ID
from .entity import MachEntity

SENSORS = (
    SensorEntityDescription(
        key=VALUE_ID,
        translation_key="living_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="OUTSIDE_MEASURED_TEMPERATURE",
        translation_key="outside_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="OUTSIDE_MEASURED_HUMIDITY",
        translation_key="outside_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="MEASURED_PRESSURE",
        translation_key="pressure",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="LIVING_BATTERY_VOLTAGE",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    SensorEntityDescription(
        key="LIVING_BATTERY_CURRENT",
        translation_key="battery_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    SensorEntityDescription(
        key="FRESH_WATER_LEVEL",
        translation_key="fresh_water_level",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:water",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="WASTE_WATER_LEVEL",
        translation_key="waste_water_level",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:water-off",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="AIR_HEATER_TEMPERATURE",
        translation_key="heater_target",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="WATER_HEATER_TEMPERATURE",
        translation_key="water_heater_mode",
        device_class=SensorDeviceClass.ENUM,
        options=["off", "normal", "boost"],
        icon="mdi:water-boiler",
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        [
            MachSensor(coordinator, description)
            for description in SENSORS
            if description.key in coordinator.data.values
        ]
        + (
            [MachCapabilitySensor(coordinator, CAPABILITIES)]
            if coordinator.data.capabilities
            else []
        )
    )


class MachSensor(MachEntity, SensorEntity):
    @property
    def native_value(self):
        return self.reading


CAPABILITIES = SensorEntityDescription(
    key="capability_inventory",
    translation_key="capability_inventory",
    entity_category=EntityCategory.DIAGNOSTIC,
    icon="mdi:format-list-checks",
)


class MachCapabilitySensor(MachEntity, SensorEntity):
    @property
    def reading(self):
        report = self.coordinator.data.capabilities
        return len(report.definitions) if report else None

    @property
    def native_value(self):
        return self.reading

    @property
    def extra_state_attributes(self):
        report = self.coordinator.data.capabilities
        return {**super().extra_state_attributes, **(report.summary if report else {})}
