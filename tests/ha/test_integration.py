"""Native config flow, entry lifecycle, coordinator and sensor acceptance."""

from datetime import timedelta

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from custom_components.adria_mach.client.model import AuthenticationError, Device, MachError
from custom_components.adria_mach.const import CONF_MACH_ID, DOMAIN, VALUE_ID

CREDS = {CONF_USERNAME: "synthetic-user", CONF_PASSWORD: "synthetic-password"}


def entry_for(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Adria MACH",
        unique_id="synthetic-a",
        data={**CREDS, CONF_MACH_ID: "synthetic-a"},
    )
    entry.add_to_hass(hass)
    return entry


def temperature_state(hass):
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"synthetic-a_{VALUE_ID}")
    assert entity_id is not None
    return hass.states.get(entity_id)


async def test_native_login_creates_and_loads_entry_with_real_sensor(hass, backend):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert entry.unique_id == "synthetic-a" and entry.data == {**CREDS, CONF_MACH_ID: "synthetic-a"}
    state = temperature_state(hass)
    assert state.state == "0" and state.attributes["unit_of_measurement"] == "°C"
    assert state.attributes["device_class"] == "temperature"
    assert state.attributes["state_class"] == "measurement"
    assert "received_at" in state.attributes
    assert backend.clients[0].closed and not backend.clients[-1].closed
    duplicate = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data=CREDS
    )
    assert duplicate["reason"] == "already_configured"
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert all(client.closed for client in backend.clients)


@pytest.mark.parametrize(
    "failure,error",
    [
        (AuthenticationError("authentication_rejected"), "invalid_auth"),
        (MachError("transport_failure"), "cannot_connect"),
    ],
)
async def test_native_login_error_and_recovery(hass, backend, failure, error):
    backend.auth_error = failure
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data=CREDS
    )
    assert result["errors"] == {"base": error}
    assert backend.clients[-1].closed
    backend.auth_error = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()


async def test_zero_and_multiple_devices_require_valid_explicit_choice(hass, backend):
    backend.devices = ()
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data=CREDS
    )
    assert result["errors"] == {"base": "no_supported_devices"}
    backend.devices = (Device("synthetic-b", "B"), Device("synthetic-a", "A"))
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["step_id"] == "vehicle"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MACH_ID: "synthetic-a"}
    )
    assert result["data"][CONF_MACH_ID] == "synthetic-a"
    await hass.async_block_till_done()


async def test_reauth_cannot_switch_vehicle(hass, backend):
    entry = entry_for(hass)
    backend.devices = (Device("synthetic-other", "Other"),)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reauth", "entry_id": entry.entry_id}, data=entry.data
    )
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["errors"] == {"base": "device_not_assigned"}
    backend.devices = (Device("synthetic-a", "Same"),)
    updated = {**CREDS, CONF_PASSWORD: "synthetic-new-password"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], updated)
    assert result["reason"] == "reauth_successful"
    await hass.async_block_till_done()
    assert entry.unique_id == "synthetic-a"
    assert entry.data == {**updated, CONF_MACH_ID: "synthetic-a"}


@pytest.mark.parametrize(
    "phase,failure,expected",
    [
        ("auth", MachError("transport_failure"), config_entries.ConfigEntryState.SETUP_RETRY),
        (
            "auth",
            AuthenticationError("authentication_rejected"),
            config_entries.ConfigEntryState.SETUP_ERROR,
        ),
        ("read", MachError("transport_failure"), config_entries.ConfigEntryState.SETUP_RETRY),
        (
            "read",
            AuthenticationError("authentication_rejected"),
            config_entries.ConfigEntryState.SETUP_ERROR,
        ),
    ],
)
async def test_first_refresh_failure_closes_client_and_has_native_status(
    hass, backend, phase, failure, expected
):
    entry = entry_for(hass)
    if phase == "auth":
        backend.auth_error = failure
    else:
        backend.read_error = failure
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is expected and backend.clients[-1].closed
    assert hass.states.async_all("sensor") == []


async def test_updates_availability_poll_budget_unload_and_reload(hass, backend, freezer):
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert backend.reads == 1
    registry = er.async_get(hass)
    initial = registry.async_get(temperature_state(hass).entity_id)
    identity = (initial.entity_id, initial.unique_id, initial.device_id)
    assert initial.device_id is not None
    # HA floors loop time and its test helper adds0.5s jitter tolerance.
    freezer.tick(timedelta(seconds=298))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert backend.reads == 1
    freezer.tick(timedelta(seconds=4))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert backend.reads == 2
    backend.read_error = MachError("transport_failure")
    await entry.runtime_data.async_refresh()
    assert temperature_state(hass).state == "unavailable"
    backend.read_error = None
    backend.temperature = None
    await entry.runtime_data.async_refresh()
    assert temperature_state(hass).state == "unavailable"
    backend.temperature = 12
    await entry.runtime_data.async_refresh()
    assert temperature_state(hass).state == "12"
    assert await hass.config_entries.async_unload(entry.entry_id)
    reads = backend.reads
    freezer.tick(timedelta(seconds=602))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert backend.reads == reads and backend.clients[-1].closed
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert temperature_state(hass).state == "12" and backend.reads == reads + 1
    reloaded = registry.async_get(temperature_state(hass).entity_id)
    assert (reloaded.entity_id, reloaded.unique_id, reloaded.device_id) == identity


async def test_native_verified_catalog_metadata_translation_and_shared_availability(hass, backend):
    hass.config.language = "fi"
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    # Independent expected contract: domain, state, unit, device class, state class.
    expected = {
        VALUE_ID: ("sensor", "0", "°C", "temperature", "measurement"),
        "OUTSIDE_MEASURED_TEMPERATURE": ("sensor", "-3", "°C", "temperature", "measurement"),
        "OUTSIDE_MEASURED_HUMIDITY": ("sensor", "81", "%", "humidity", "measurement"),
        "MEASURED_PRESSURE": ("sensor", "997", "hPa", "atmospheric_pressure", "measurement"),
        "LIVING_BATTERY_VOLTAGE": ("sensor", "12.7", "V", "voltage", "measurement"),
        "LIVING_BATTERY_CURRENT": ("sensor", "-0.35", "A", "current", "measurement"),
        "FRESH_WATER_LEVEL": ("sensor", "0", "%", None, "measurement"),
        "WASTE_WATER_LEVEL": ("sensor", "42", "%", None, "measurement"),
        "AIR_HEATER_TEMPERATURE": ("sensor", "19", "°C", "temperature", None),
        "WATER_HEATER_TEMPERATURE": ("sensor", "normal", None, "enum", None),
        "MAINS_SUPPLY_VALUE": ("binary_sensor", "on", None, "power", None),
        "AIR_HEATER_VALUE": ("binary_sensor", "off", None, None, None),
        "AIR_HEATER_WORKING": ("binary_sensor", "on", None, None, None),
        "WATER_HEATER_WORKING": ("binary_sensor", "off", None, None, None),
        "LIVING_BATTERY_INSTALLED": ("binary_sensor", "on", None, None, None),
        "WATER_PUMP_VALUE": ("binary_sensor", "off", None, None, None),
        "EXTERNAL_LIGHT_VALUE": ("binary_sensor", "on", None, None, None),
        "AUX_VALUE": ("binary_sensor", "off", None, None, None),
    }
    registry = er.async_get(hass)
    registered = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert {e.unique_id.removeprefix("synthetic-a_") for e in registered} == expected.keys() | {
        "last_successful_read",
        "restart",
        "check_firmware_updates",
        "firmware",
    }
    assert len({e.device_id for e in registered}) == 1 and backend.reads == 1

    def state_for(key):
        entity_id = registry.async_get_entity_id(expected[key][0], DOMAIN, f"synthetic-a_{key}")
        return hass.states.get(entity_id)

    for key, (domain, value, unit, device_class, state_class) in expected.items():
        state = state_for(key)
        assert state.domain == domain and state.state == value
        assert state.attributes.get("unit_of_measurement") == unit
        assert state.attributes.get("device_class") == device_class
        assert state.attributes.get("state_class") == state_class
        assert set(state.attributes) <= {
            "friendly_name",
            "unit_of_measurement",
            "device_class",
            "state_class",
            "received_at",
            "options",
            "icon",
        }
    assert state_for("OUTSIDE_MEASURED_TEMPERATURE").name == "Adria MACH Ulkolämpötila"
    assert state_for("AIR_HEATER_WORKING").name == "Adria MACH Lämmittimen toimintavalmius"
    assert state_for("WATER_HEATER_TEMPERATURE").attributes["options"] == ["off", "normal", "boost"]
    translations = await async_get_translations(hass, "fi", "entity", {DOMAIN})
    assert (
        translations["component.adria_mach.entity.sensor.water_heater_mode.state.normal"]
        == "Normaali"
    )

    invalid = ("OUTSIDE_MEASURED_TEMPERATURE", "WATER_HEATER_TEMPERATURE", "MAINS_SUPPLY_VALUE")
    saved = dict(backend.readings)
    for key in invalid:
        backend.readings[key] = None
    backend.readings.pop("OUTSIDE_MEASURED_TEMPERATURE")
    await entry.runtime_data.async_refresh()
    assert backend.reads == 2
    for key in invalid:
        assert state_for(key).state == "unavailable"
    assert state_for("WASTE_WATER_LEVEL").state == "42"
    assert state_for("AIR_HEATER_VALUE").state == "off"
    backend.readings = saved
    await entry.runtime_data.async_refresh()
    for key in invalid:
        assert state_for(key).state == expected[key][1]


@pytest.mark.parametrize("disabled", [None, er.RegistryEntryDisabler.USER])
async def test_upgrade_preserves_existing_living_registration_and_user_settings(
    hass, backend, disabled
):
    entry = entry_for(hass)
    area = ar.async_get(hass).async_create("Synthetic caravan")
    devices = dr.async_get(hass)
    device = devices.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, "synthetic-a")}, name="Adria MACH"
    )
    devices.async_update_device(device.id, area_id=area.id, name_by_user="Owner caravan")
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"synthetic-a_{VALUE_ID}",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="owner_living",
        disabled_by=disabled,
    )
    registry.async_update_entity(
        old.entity_id, name="Owner temperature", icon="mdi:thermometer", area_id=area.id
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    current = registry.async_get(old.entity_id)
    assert (
        current.unique_id,
        current.device_id,
        current.area_id,
        current.name,
        current.icon,
        current.disabled_by,
    ) == (old.unique_id, device.id, area.id, "Owner temperature", "mdi:thermometer", disabled)
    assert devices.async_get(device.id).area_id == area.id
    assert devices.async_get(device.id).name_by_user == "Owner caravan"
    registered = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert len(registered) == 22 and {e.device_id for e in registered} == {device.id}
    assert len([e for e in registered if e.unique_id == old.unique_id]) == 1
    assert (hass.states.get(old.entity_id) is None) == (disabled is not None)


async def test_initially_unsupported_optional_field_is_not_created(hass, backend):
    backend.readings.pop("AUX_VALUE")
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("binary_sensor", DOMAIN, "synthetic-a_AUX_VALUE") is None
    assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == 21
    assert temperature_state(hass).state == "0"


async def test_native_diagnostics_are_additive_and_share_reads(hass, backend, diagnostic_snapshot):
    from homeassistant.const import EntityCategory

    from custom_components.adria_mach.diagnostics import async_get_config_entry_diagnostics

    backend.readings.update(LTE_SIGNAL_STRENGTH=None, LTE_VALUE=None)
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, "synthetic-a_LTE_SIGNAL_STRENGTH") is None
    assert registry.async_get_entity_id("binary_sensor", DOMAIN, "synthetic-a_LTE_VALUE") is None
    old = {
        e.entity_id: (e.unique_id, e.device_id)
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    original = temperature_state(hass).entity_id
    registry.async_update_entity(original, name="Owner room", icon="mdi:home")
    backend.readings = dict(diagnostic_snapshot["normalized"])
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    expected = {
        "LTE_VALUE": ("binary_sensor", "on", None, None),
        "USER_ALLOWS_ROAMING": ("binary_sensor", "off", None, None),
        "LTE_OPERATOR_NAME": ("sensor", "Example Mobile", None, None),
        "LTE_COMMUNICATION_STANDARD": ("sensor", "4G", None, None),
        "LTE_REGISTRATION_STATUS": ("sensor", "ROAMING", None, None),
        "LTE_SIGNAL_STRENGTH": ("sensor", "73", "%", None),
        "LTE_SIM_VALUE": ("sensor", "sim_ready", None, "enum"),
        "SYSTEM_POWER_REGIME": ("sensor", "sleep", None, "enum"),
        "SYSTEM_IO_FIRMWARE_VERSION": ("sensor", "03.004.005", None, None),
        "SYSTEM_FIRMWARE_VERSION_MCU_1": ("sensor", "2.3-beta", None, None),
        "mach_software_version": ("sensor", "9.8.7 2030-01-02", None, None),
        "mach_os_release": ("sensor", "2030-01-02", None, None),
        "mach_release_channel": ("sensor", "PRODUCTION", None, None),
    }
    for key, (domain, value, unit, device_class) in expected.items():
        entity_id = registry.async_get_entity_id(domain, DOMAIN, "synthetic-a_" + key)
        record = registry.async_get(entity_id)
        state = hass.states.get(entity_id)
        assert record.entity_category is EntityCategory.DIAGNOSTIC
        assert record.device_id == old[original][1]
        assert (
            state.state,
            state.attributes.get("unit_of_measurement"),
            state.attributes.get("device_class"),
        ) == (value, unit, device_class)
        if device_class == "enum":
            assert value in state.attributes["options"]
    translations = await async_get_translations(hass, "en", "entity", {DOMAIN})
    assert translations["component.adria_mach.entity.sensor.sim_status.state.sim_ready"] == "Ready"
    assert (
        translations["component.adria_mach.entity.sensor.device_power_mode.state.sleep"] == "Sleep"
    )
    assert registry.async_get_entity_id("sensor", DOMAIN, "synthetic-a_PANEL_VERSION") is None
    assert backend.reads == 2
    assert {
        k: (registry.async_get(k).unique_id, registry.async_get(k).device_id) for k in old
    } == old
    assert registry.async_get(original).name == "Owner room"
    assert registry.async_get(original).icon == "mdi:home"
    timestamp = registry.async_get_entity_id("sensor", DOMAIN, "synthetic-a_last_successful_read")
    last_read = hass.states.get(timestamp).state
    assert hass.states.get(timestamp).attributes["device_class"] == "timestamp"
    backend.read_error = MachError("transport_failure")
    await entry.runtime_data.async_refresh()
    assert hass.states.get(timestamp).state == last_read
    backend.read_error = None
    backend.readings["LTE_SIGNAL_STRENGTH"] = None
    await entry.runtime_data.async_refresh()
    signal = registry.async_get_entity_id("sensor", DOMAIN, "synthetic-a_LTE_SIGNAL_STRENGTH")
    assert hass.states.get(signal).state == "unavailable"
    assert temperature_state(hass).state == "0"
    backend.readings["LTE_SIGNAL_STRENGTH"] = 54
    await entry.runtime_data.async_refresh()
    assert hass.states.get(signal).state == "54"
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["device_diagnostics"]["mach_software_version"] == "9.8.7 2030-01-02"
    assert report["source_sample_at"] is None
    count = len(er.async_entries_for_config_entry(registry, entry.entry_id))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == count
    assert registry.async_get(original).name == "Owner room"
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert all(c.closed for c in backend.clients)


async def test_native_position_lifecycle_preserves_identity_and_private_location(hass, backend):
    import json

    from custom_components.adria_mach.client.position import Location
    from custom_components.adria_mach.diagnostics import async_get_config_entry_diagnostics

    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("device_tracker", DOMAIN, "synthetic-a_location") is None
    original = temperature_state(hass).entity_id
    registry.async_update_entity(original, name="Owner room", icon="mdi:home")
    old = {
        e.entity_id: (e.unique_id, e.device_id)
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    options = dict(entry.options)
    backend.readings.update(levelling_pitch=-10.0, levelling_roll=20.0)
    backend.location = Location(10.125, -20.25)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert backend.reads == 2  # One shared snapshot, no tracker or angle-specific request.
    for key, expected in (("levelling_pitch", "-10.0"), ("levelling_roll", "20.0")):
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, "synthetic-a_" + key)
        state = hass.states.get(entity_id)
        assert state.state == expected
        assert state.attributes["unit_of_measurement"] == "°"
        assert state.attributes["state_class"] == "measurement"
        assert registry.async_get(entity_id).device_id == old[original][1]
    tracker = registry.async_get_entity_id("device_tracker", DOMAIN, "synthetic-a_location")
    assert registry.async_get(tracker).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(tracker) is None
    registry.async_update_entity(tracker, disabled_by=None)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(tracker)
    assert state.attributes["latitude"] == 10.125
    assert state.attributes["longitude"] == -20.25
    assert state.attributes["source_type"] == "gps"
    assert state.state == "not_home"
    backend.location = None
    await entry.runtime_data.async_refresh()
    assert hass.states.get(tracker).state == "unavailable"
    assert hass.states.get(tracker).attributes.get("latitude") is None
    assert hass.states.get(tracker).attributes.get("longitude") is None
    backend.location = Location(11.125, -21.25)
    await entry.runtime_data.async_refresh()
    backend.read_error = MachError("transport_failure")
    await entry.runtime_data.async_refresh()
    assert hass.states.get(tracker).state == "unavailable"
    assert hass.states.get(tracker).attributes.get("latitude") is None
    backend.read_error = None
    await entry.runtime_data.async_refresh()
    assert hass.states.get(tracker).attributes["latitude"] == 11.125
    report = json.dumps(await async_get_config_entry_diagnostics(hass, entry), default=str)
    assert all(value not in report for value in ("10.125", "-20.25", "11.125", "-21.25"))
    count = len(er.async_entries_for_config_entry(registry, entry.entry_id))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == count
    assert registry.async_get_entity_id("device_tracker", DOMAIN, "synthetic-a_location") == tracker
    assert {
        key: (registry.async_get(key).unique_id, registry.async_get(key).device_id) for key in old
    } == old
    assert registry.async_get(original).name == "Owner room"
    assert registry.async_get(original).icon == "mdi:home"
    assert dict(entry.options) == options
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert all(client.closed for client in backend.clients)


async def test_native_vehicle_information_is_private_additive_and_read_only(
    hass, backend, vehicle_snapshot
):
    import json

    from homeassistant.const import EntityCategory

    from custom_components.adria_mach.client.position import Location
    from custom_components.adria_mach.client.vehicle import VehicleInfo, vehicle_from
    from custom_components.adria_mach.diagnostics import async_get_config_entry_diagnostics

    vehicle_snapshot["configuration"]["system"]["vehicle"]["chassis"]["number"] = (
        "*000-TEST-CHASSIS*"
    )
    backend.location = Location(10.125, -20.25)
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    tracker = registry.async_get_entity_id("device_tracker", DOMAIN, "synthetic-a_location")
    registry.async_update_entity(tracker, disabled_by=None)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    old_entity = temperature_state(hass).entity_id
    registry.async_update_entity(old_entity, name="Owner room", icon="mdi:home")
    old = {
        e.entity_id: (e.unique_id, e.device_id, e.disabled_by, e.name, e.icon)
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    options = dict(entry.options)
    device = dr.async_get(hass).async_get(registry.async_get(old_entity).device_id)
    device_before = (device.id, device.model, device.serial_number, device.identifiers)
    reads = backend.reads
    backend.vehicle = vehicle_from(vehicle_snapshot["configuration"])
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert backend.reads == reads + 1
    entities = {
        key: registry.async_get_entity_id("sensor", DOMAIN, "synthetic-a_" + key)
        for key in backend.vehicle.values
    }
    chassis = entities["chassis_number"]
    assert registry.async_get(chassis).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(chassis) is None
    registry.async_update_entity(chassis, disabled_by=None)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    for key, entity_id in entities.items():
        state = hass.states.get(entity_id)
        assert registry.async_get(entity_id).entity_category is EntityCategory.DIAGNOSTIC
        assert registry.async_get(entity_id).device_id == device.id
        assert state.state == str(backend.vehicle.values[key])
        assert "state_class" not in state.attributes
        numeric = key not in ("vehicle_model", "chassis_number")
        assert state.attributes.get("device_class") == ("distance" if numeric else None)
        assert state.attributes.get("unit_of_measurement") == ("mm" if numeric else None)
    assert "000-TEST-CHASSIS" not in json.dumps(
        await async_get_config_entry_diagnostics(hass, entry), default=str
    )
    assert all(
        "000-TEST-CHASSIS" not in json.dumps(hass.states.get(e).attributes, default=str)
        for e in old
    )
    backend.vehicle = VehicleInfo({"vehicle_model": "Example 701"})
    await entry.runtime_data.async_refresh()
    assert hass.states.get(chassis).state == "unavailable"
    assert hass.states.get(entities["vehicle_length"]).state == "unavailable"
    assert hass.states.get(entities["vehicle_model"]).state == "Example 701"
    backend.read_error = MachError("transport_failure")
    await entry.runtime_data.async_refresh()
    assert hass.states.get(entities["vehicle_model"]).state == "unavailable"
    backend.read_error = None
    backend.vehicle = vehicle_from(vehicle_snapshot["configuration"])
    await entry.runtime_data.async_refresh()
    assert hass.states.get(chassis).state == "*000-TEST-CHASSIS*"
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == len(old) + 6
    assert {
        e: (
            registry.async_get(e).unique_id,
            registry.async_get(e).device_id,
            registry.async_get(e).disabled_by,
            registry.async_get(e).name,
            registry.async_get(e).icon,
        )
        for e in old
    } == old
    device = dr.async_get(hass).async_get(device.id)
    assert (device.id, device.model, device.serial_number, device.identifiers) == device_before
    assert dict(entry.options) == options
    assert hass.states.get(tracker).attributes["latitude"] == 10.125
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert all(client.closed for client in backend.clients)


async def test_stored_renewal_credentials_and_native_failure_handling_preserve_identity(
    hass, backend
):
    entry = entry_for(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    client = backend.clients[-1]
    registry = er.async_get(hass)
    initial = registry.async_get(temperature_state(hass).entity_id)
    identity = (initial.entity_id, initial.unique_id, initial.device_id)
    options = dict(entry.options)
    assert client.renewal_device == "synthetic-a"
    assert client.renewal_credentials() == ("synthetic-user", "synthetic-password")
    # Callback reads the current entry rather than retaining a stale password copy.
    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_PASSWORD: "updated-secret"}
    )
    assert client.renewal_credentials() == ("synthetic-user", "updated-secret")
    coordinator = entry.runtime_data
    backend.read_error = MachError("session_renewal_deferred")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert temperature_state(hass).state == "unavailable"
    assert not hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    backend.read_error = None
    backend.temperature = 11
    await coordinator.async_refresh()
    assert temperature_state(hass).state == "11"
    current = registry.async_get(initial.entity_id)
    assert (current.entity_id, current.unique_id, current.device_id) == identity
    assert entry.options == options and entry.state is config_entries.ConfigEntryState.LOADED
    backend.read_error = AuthenticationError("authentication_rejected")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1 and flows[0]["context"]["source"] == "reauth"
