"""Reported states only, with no actuator actions or running inference."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory

from .connection_health import ConnectionHealthEntity
from .entity import MachEntity, async_discover_diagnostics

BINARY_SENSORS = (
    BinarySensorEntityDescription(
        key="MAINS_SUPPLY_VALUE",
        translation_key="mains_supply",
        device_class=BinarySensorDeviceClass.POWER,
    ),
    BinarySensorEntityDescription(
        key="AIR_HEATER_VALUE", translation_key="heater_enabled", icon="mdi:radiator"
    ),
    BinarySensorEntityDescription(
        key="AIR_HEATER_WORKING", translation_key="heater_operational", icon="mdi:radiator"
    ),
    BinarySensorEntityDescription(
        key="WATER_HEATER_WORKING",
        translation_key="water_heater_operational",
        icon="mdi:water-boiler",
    ),
    BinarySensorEntityDescription(
        key="LIVING_BATTERY_INSTALLED", translation_key="battery_installed", icon="mdi:car-battery"
    ),
    BinarySensorEntityDescription(
        key="WATER_PUMP_VALUE", translation_key="water_pump_enabled", icon="mdi:water-pump"
    ),
    BinarySensorEntityDescription(
        key="EXTERNAL_LIGHT_VALUE", translation_key="outside_light", icon="mdi:lightbulb"
    ),
    BinarySensorEntityDescription(
        key="AUX_VALUE", translation_key="aux_enabled", icon="mdi:power-socket"
    ),
)

DIAGNOSTIC_BINARY_SENSORS = (
    BinarySensorEntityDescription(
        key="LTE_VALUE",
        translation_key="lte_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:network",
    ),
    BinarySensorEntityDescription(
        key="USER_ALLOWS_ROAMING",
        translation_key="roaming_permitted",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:network",
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities([MachConnectionBinary(coordinator, d) for d in CONNECTION_BINARY_SENSORS])
    async_add_entities(
        [
            MachBinarySensor(coordinator, description)
            for description in BINARY_SENSORS
            if description.key in coordinator.data.values
        ]
    )
    async_discover_diagnostics(
        entry, DIAGNOSTIC_BINARY_SENSORS, MachBinarySensor, async_add_entities
    )


class MachBinarySensor(MachEntity, BinarySensorEntity):
    @property
    def is_on(self) -> bool | None:
        return self.reading


CONNECTION_BINARY_SENSORS = (
    BinarySensorEntityDescription(
        key="event_stream_connected",
        translation_key="event_stream_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    BinarySensorEntityDescription(
        key="reported_device_connected",
        translation_key="reported_device_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
    ),
    BinarySensorEntityDescription(
        key="reported_cache_initialized",
        translation_key="reported_cache_initialized",
    ),
)


class MachConnectionBinary(ConnectionHealthEntity, BinarySensorEntity):
    @property
    def is_on(self):
        return self.reading
