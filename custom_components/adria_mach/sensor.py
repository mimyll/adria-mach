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
    UnitOfLength,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
)

from .client.position import ANGLE_KEYS
from .client.telemetry import POWER_STATES, SIM_STATES
from .client.vehicle import DIMENSIONS
from .connection_health import CONNECTION_STATES, ConnectionHealthEntity
from .const import VALUE_ID
from .entity import MachEntity, async_discover_diagnostics

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

DIAGNOSTIC_SENSORS = (
    SensorEntityDescription(
        key="LTE_OPERATOR_NAME", translation_key="mobile_operator", icon="mdi:sim"
    ),
    SensorEntityDescription(
        key="LTE_COMMUNICATION_STANDARD", translation_key="mobile_technology", icon="mdi:network"
    ),
    SensorEntityDescription(
        key="LTE_REGISTRATION_STATUS", translation_key="network_registration", icon="mdi:network"
    ),
    SensorEntityDescription(
        key="LTE_SIGNAL_STRENGTH",
        translation_key="mobile_signal_quality",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:signal",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="LTE_SIM_VALUE",
        translation_key="sim_status",
        device_class=SensorDeviceClass.ENUM,
        options=[state.lower() for state in SIM_STATES],
        icon="mdi:sim",
    ),
    SensorEntityDescription(
        key="SYSTEM_POWER_REGIME",
        translation_key="device_power_mode",
        device_class=SensorDeviceClass.ENUM,
        options=[state.lower() for state in POWER_STATES],
        icon="mdi:power-sleep",
    ),
    *(
        SensorEntityDescription(key=key, translation_key=translation, icon="mdi:chip")
        for key, translation in (
            ("mach_software_version", "mach_software_version"),
            ("mach_os_release", "mach_os_release"),
            ("mach_release_channel", "mach_release_channel"),
            ("SYSTEM_IO_FIRMWARE_VERSION", "io_firmware_version"),
            ("SYSTEM_FIRMWARE_VERSION_MCU_1", "mcu_1_firmware_version"),
            ("SYSTEM_FIRMWARE_VERSION_MCU_2", "mcu_2_firmware_version"),
            ("PANEL_VERSION", "panel_firmware_version"),
        )
    ),
)

LAST_READ = SensorEntityDescription(
    key="last_successful_read",
    translation_key="last_successful_read",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
)

LEVELLING_SENSORS = tuple(
    SensorEntityDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement="°",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:angle-acute",
    )
    for key in ANGLE_KEYS
)

VEHICLE_SENSORS = (
    SensorEntityDescription(
        key="vehicle_model", translation_key="vehicle_model", icon="mdi:caravan"
    ),
    SensorEntityDescription(
        key="chassis_number",
        translation_key="chassis_number",
        icon="mdi:identifier",
        entity_registry_enabled_default=False,
    ),
    *(
        SensorEntityDescription(
            key=key,
            translation_key=key,
            device_class=SensorDeviceClass.DISTANCE,
            native_unit_of_measurement=UnitOfLength.MILLIMETERS,
        )
        for key in DIMENSIONS
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities([MachConnectionSensor(coordinator, d) for d in CONNECTION_SENSORS])
    async_add_entities(
        [
            MachSensor(coordinator, description)
            for description in SENSORS
            if description.key in coordinator.data.values
        ]
        + [MachLastReadSensor(coordinator, LAST_READ)]
        + (
            [MachCapabilitySensor(coordinator, CAPABILITIES)]
            if coordinator.data.capabilities
            else []
        )
    )
    async_discover_diagnostics(entry, DIAGNOSTIC_SENSORS, MachDiagnosticSensor, async_add_entities)
    async_discover_diagnostics(entry, LEVELLING_SENSORS, MachSensor, async_add_entities)
    async_discover_diagnostics(
        entry,
        VEHICLE_SENSORS,
        MachVehicleSensor,
        async_add_entities,
        present=lambda description: coordinator.data.vehicle.values.get(description.key)
        is not None,
    )


class MachSensor(MachEntity, SensorEntity):
    @property
    def native_value(self):
        return self.reading


class MachDiagnosticSensor(MachSensor):
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        value = self.reading
        if value is not None and self.entity_description.device_class is SensorDeviceClass.ENUM:
            return value.lower()
        return value


class MachVehicleSensor(MachDiagnosticSensor):
    @property
    def reading(self):
        return self.coordinator.data.vehicle.values.get(self.entity_description.key)


class MachLastReadSensor(MachSensor):
    @property
    def reading(self):
        return self.coordinator.data.received_at

    @property
    def available(self):
        # A failed refresh does not erase the time of the last successful receipt.
        return self.coordinator.data is not None


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


CONNECTION_SENSORS = (
    SensorEntityDescription(
        key="connection_state",
        translation_key="connection_state",
        device_class=SensorDeviceClass.ENUM,
        options=CONNECTION_STATES,
    ),
    SensorEntityDescription(
        key="last_stream_traffic",
        translation_key="last_stream_traffic",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="last_snapshot_age",
        translation_key="last_snapshot_age",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="reported_device_contact",
        translation_key="reported_device_contact",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    SensorEntityDescription(
        key="reported_device_contact_age",
        translation_key="reported_device_contact_age",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


class MachConnectionSensor(ConnectionHealthEntity, SensorEntity):
    @property
    def native_value(self):
        return self.reading
