"""Actual HA native-service/state/registry wiring; synthetic backend only."""

import asyncio
import json
import threading
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from homeassistant.components.water_heater import WaterHeaterEntityFeature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_translations
from pytest_homeassistant.common import MockConfigEntry

from custom_components.adria_mach.client.capabilities import inventory
from custom_components.adria_mach.client.control_model import (
    OFF_LEVEL,
    Case,
    ControlError,
    HeatingControl,
    ManualControl,
    Snapshot,
    WaterControl,
)
from custom_components.adria_mach.client.journal import Journal
from custom_components.adria_mach.client.master import MasterControl
from custom_components.adria_mach.client.operational import (
    CURRENT_CONTROLS,
    AcControl,
    EquipmentControl,
)
from custom_components.adria_mach.client.outside import OutsideControl
from custom_components.adria_mach.const import DOMAIN
from custom_components.adria_mach.diagnostics import async_get_config_entry_diagnostics


@pytest.fixture
def hass_config_dir(tmp_path):
    """Exercise real journal IO in an existing isolated HA configuration root."""
    return str(tmp_path)


@pytest.fixture
async def native_controls(hass, backend, monkeypatch, request):
    cases = (Case.LIGHT, Case.HEATER) + getattr(request, "param", ())
    for case in cases:
        water = case is WaterControl.MODE
        backend.control_snapshots[case.value] = Snapshot(
            {case.key: "normal" if water else case.baseline},
            {},
            datetime.now(UTC).isoformat(),
            asyncio.get_running_loop().time(),
        )
        backend.readings[case.key] = "normal" if water else 15 if case is Case.HEATER else False
    manual_snapshots(backend)
    backend.control_snapshots[OutsideControl.BINARY.value] = backend.control_snapshots[
        Case.LIGHT.value
    ]
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Adria MACH",
        unique_id="synthetic-a",
        data={
            "username": "synthetic-user",
            "password": "synthetic-password",
            "mach_id": "synthetic-a",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    backend.commands = []
    backend.command_error = None
    backend.fail_once = False
    backend.gate = None
    backend.gates = None
    backend.command_entered = None
    backend.entered = asyncio.Event()

    async def scripted_command(
        self,
        device,
        case,
        target,
        restore,
        persist,
        progress,
        publish,
        expected_context=None,
        *,
        climate=False,
        resume=None,
        unsent_deadline=None,
    ):
        manual = isinstance(
            case,
            (
                ManualControl,
                WaterControl,
                HeatingControl,
                OutsideControl,
                EquipmentControl,
                AcControl,
                MasterControl,
            ),
        )
        if resume is not None:
            publish(await self.read(device))
            await resume()
        before = backend.control_snapshots[case.value]
        if manual:
            current = before.observed[case.key]
            if target is None:
                target = 50 if current == OFF_LEVEL else current
            if target == current and not isinstance(case, MasterControl):
                progress("unchanged", None)
                return await self.read(device), False
        await persist(case, target if manual else restore)
        backend.commands.append((case, target, restore))
        progress("requested", None)
        progress(
            "candidate_positive",
            {"http_status": 200, "application_status": 200, "positive_candidate": True},
        )
        backend.entered.set()
        if backend.command_entered:
            backend.command_entered[len(backend.commands) - 1].set()
        if backend.gate:
            await backend.gate.wait()
        if backend.gates:
            await backend.gates[len(backend.commands) - 1].wait()
        if backend.command_error:
            error = backend.command_error
            if backend.fail_once:
                backend.command_error = None
            raise error
        heater = case in (Case.HEATER, ManualControl.HEATER)
        backend.readings[case.key] = (
            target == "on"
            if case in (HeatingControl.MODE, OutsideControl.BINARY)
            else target
            if heater or case is WaterControl.MODE
            else (target != OFF_LEVEL if manual else target == case.target)
        )
        backend.control_snapshots[case.value] = replace(
            before,
            observed={
                case.key: None if isinstance(case, EquipmentControl) and case.action else target
            },
        )
        if isinstance(case, ManualControl):
            backend.control_snapshots[case.legacy_case.value] = backend.control_snapshots[
                case.value
            ]
        elif not manual:
            manual_snapshots(backend)
            if case is Case.LIGHT:
                backend.control_snapshots[OutsideControl.BINARY.value] = backend.control_snapshots[
                    case.value
                ]
        observed = await self.read(device)
        publish(observed)
        progress(
            "service_observed",
            {"http_status": 200, "application_status": 200, "positive_candidate": True},
        )
        return observed, True

    monkeypatch.setattr(type(backend.clients[-1]), "command", scripted_command, raising=False)
    registry = er.async_get(hass)
    light = registry.async_get_entity_id("light", DOMAIN, "synthetic-a_" + Case.LIGHT.key)
    number = registry.async_get_entity_id("number", DOMAIN, "synthetic-a_" + Case.HEATER.key)
    assert light and number
    return entry, backend, light, number


async def action(hass, domain, service, entity, **data):
    await hass.services.async_call(domain, service, {"entity_id": entity, **data}, blocking=True)
    await hass.async_block_till_done()


def manual_snapshots(backend):
    for control in ManualControl:
        if control.legacy_case.value in backend.control_snapshots:
            backend.control_snapshots[control.value] = backend.control_snapshots[
                control.legacy_case.value
            ]


async def test_native_entities_routine_outside_and_full_target_slider(hass, native_controls):
    entry, backend, light, number = native_controls
    registered = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(registered) == 24 and len({e.device_id for e in registered}) == 1
    assert not backend.commands
    assert hass.states.get(light).attributes["supported_color_modes"] == ["onoff"]
    n = hass.states.get(number)
    assert (n.attributes["min"], n.attributes["max"], n.attributes["step"]) == (5, 30, 1)
    assert n.attributes["mode"] == "slider"
    assert n.attributes["unit_of_measurement"] == "°C"
    assert not hasattr(entry.runtime_data.commands, "reset")
    await action(hass, "light", "turn_on", light)
    assert hass.states.get(light).state == "on"
    assert hass.states.get(light).attributes["physical_confirmation"] == "not_recorded"
    await action(hass, "light", "turn_off", light)
    await action(hass, "number", "set_value", number, value=5.0)
    assert hass.states.get(number).state == "5"
    assert type(backend.commands[-1][1]) is int
    await action(hass, "number", "set_value", number, value=30.0)
    await action(hass, "number", "set_value", number, value=15.0)
    assert backend.commands == [
        (OutsideControl.BINARY, "on", False),
        (OutsideControl.BINARY, "off", False),
        (ManualControl.HEATER, 5, False),
        (ManualControl.HEATER, 30, False),
        (ManualControl.HEATER, 15, False),
    ]
    ids = {(e.domain, e.unique_id): e.entity_id for e in registered}
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert ids == {
        (e.domain, e.unique_id): e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }
    await action(hass, "light", "turn_on", light)
    assert backend.commands[-1] == (OutsideControl.BINARY, "on", False)
    assert len(backend.commands) == 6
    await action(hass, "number", "set_value", number, value=22)
    assert backend.commands[-1] == (ManualControl.HEATER, 22, False)


@pytest.mark.parametrize("native_controls", [(Case.GROUP_1, Case.GROUP_2)], indirect=True)
async def test_native_onoff_option_preserves_identity_history_and_other_settings(
    hass, native_controls
):
    from homeassistant.data_entry_flow import InvalidData

    from custom_components.adria_mach.const import CONF_ONOFF_LIGHTS

    entry, backend, _, _ = native_controls
    hass.config_entries.async_update_entry(entry, options={"owner_setting": "retained"})
    registry = er.async_get(hass)

    def identity_and_settings():
        return {
            e.entity_id: (
                e.unique_id,
                e.device_id,
                e.area_id,
                e.name,
                e.icon,
                e.disabled_by,
                e.hidden_by,
                dict(e.options),
            )
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        }

    before = identity_and_settings()
    data = dict(entry.data)
    path = entry.runtime_data.commands.directory / "state.json"
    # Persist a valid old unknown. Options/reload must not settle or alter it.
    await entry.runtime_data.commands.io(
        entry.runtime_data.commands.journal.intent_manual, ManualControl.GROUP_1, 10
    )
    history = path.read_bytes()
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] == "form"
    assert flow["data_schema"]({CONF_ONOFF_LIGHTS: []}) == {
        CONF_ONOFF_LIGHTS: [],
        "identified_equipment": [],
    }
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            flow["flow_id"], {CONF_ONOFF_LIGHTS: ["heater"]}
        )
    invalid = await hass.config_entries.options.async_configure(
        flow["flow_id"], {CONF_ONOFF_LIGHTS: [Case.GROUP_1.value, Case.GROUP_1.value]}
    )
    assert invalid["errors"] == {"base": "invalid_light_selection"}
    result = await hass.config_entries.options.async_configure(
        flow["flow_id"], {CONF_ONOFF_LIGHTS: [Case.GROUP_1.value]}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert identity_and_settings() == before and dict(entry.data) == data
    assert entry.options == {
        "owner_setting": "retained",
        CONF_ONOFF_LIGHTS: [Case.GROUP_1.value],
        "identified_equipment": [],
    }
    assert path.read_bytes() == history and not backend.commands
    group = registry.async_get_entity_id("light", DOMAIN, "synthetic-a_" + Case.GROUP_1.key)
    other = registry.async_get_entity_id("light", DOMAIN, "synthetic-a_" + Case.GROUP_2.key)
    assert hass.states.get(group).attributes["supported_color_modes"] == ["onoff"]
    assert hass.states.get(group).attributes.get("brightness") is None
    assert hass.states.get(other).attributes["supported_color_modes"] == ["brightness"]
    await action(hass, "light", "turn_on", group, brightness=51)
    assert backend.commands[-1] == (ManualControl.GROUP_1, 50, False)
    assert hass.states.get(group).state == "on"
    assert hass.states.get(group).attributes.get("brightness") is None
    await action(hass, "light", "turn_on", group)  # Already ON remains idempotent.
    assert len(backend.commands) == 1
    await action(hass, "light", "turn_on", group, brightness=0)
    assert backend.commands[-1] == (ManualControl.GROUP_1, OFF_LEVEL, False)
    await action(hass, "light", "turn_on", other, brightness=51)
    assert backend.commands[-1] == (ManualControl.GROUP_2, 10, False)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    await hass.config_entries.options.async_configure(flow["flow_id"], {CONF_ONOFF_LIGHTS: []})
    await hass.async_block_till_done()
    assert hass.states.get(group).attributes["supported_color_modes"] == ["brightness"]
    assert identity_and_settings() == before and entry.options["owner_setting"] == "retained"


async def test_known_legacy_restore_is_distinct_from_uncertainty(hass, native_controls):
    entry, backend, light, number = native_controls
    manager = entry.runtime_data.commands
    await manager.set(Case.LIGHT, "on")
    assert manager.restoration_required and not manager.blocked
    assert manager.attributes["control_lock_reason"] == "legacy_restoration_required"
    with pytest.raises(HomeAssistantError) as error:
        await action(hass, "number", "set_value", number, value=22)
    assert error.value.translation_key == "legacy_restore_required"
    assert len(backend.commands) == 1
    await action(hass, "light", "turn_off", light)
    assert not manager.restoration_required and not manager.blocked
    assert Case.LIGHT.value in manager.journal.state["completed"]
    await action(hass, "light", "turn_on", light)
    await action(hass, "number", "set_value", number, value=22)
    assert backend.commands[-2:] == [
        (OutsideControl.BINARY, "on", False),
        (ManualControl.HEATER, 22, False),
    ]


async def test_read_probe_preserves_unknown_journal_entities_and_settings(hass, native_controls):
    entry, backend, light, _ = native_controls
    backend.command_error = ControlError("synthetic_failure")
    with pytest.raises(HomeAssistantError):
        await action(hass, "light", "turn_on", light)
    manager = entry.runtime_data.commands
    assert manager.blocked
    path = manager.directory / "state.json"
    before = path.read_bytes()
    registry = er.async_get(hass)
    entities = dict(registry.entities)
    settings = (dict(entry.data), dict(entry.options))
    count = len(backend.commands)
    backend.temperature = 7
    report = await hass.services.async_call(
        "adria_mach",
        "probe_connection",
        {"config_entry_id": entry.entry_id},
        blocking=True,
        return_response=True,
    )
    assert report["outcome"] == "completed" and len(report["reads"]) == 2
    assert manager.blocked and manager.status == "unknown"
    assert path.read_bytes() == before and len(backend.commands) == count
    assert (
        dict(registry.entities) == entities and (dict(entry.data), dict(entry.options)) == settings
    )
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["connection_probe"] == report
    assert diagnostics["ack_diagnostics"] == {"classification": "not_recorded"}
    assert "synthetic" not in json.dumps(report) + json.dumps(diagnostics)
    assert entry.runtime_data.data.values["LIVING_MEASURED_TEMPERATURE"] == 7
    foreign = MockConfigEntry(domain="synthetic_other", data={})
    foreign.add_to_hass(hass)
    for entry_id in ("missing", foreign.entry_id):
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                "adria_mach",
                "probe_connection",
                {"config_entry_id": entry_id},
                blocking=True,
                return_response=True,
            )
    assert await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "adria_mach",
            "probe_connection",
            {"config_entry_id": entry.entry_id},
            blocking=True,
            return_response=True,
        )


async def test_read_probe_excludes_commands_checks_admin_and_is_joined_on_unload(
    hass, native_controls, monkeypatch, hass_read_only_user
):
    from homeassistant.core import Context

    entry, backend, light, _ = native_controls
    viewer = hass_read_only_user
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "adria_mach",
            "probe_connection",
            {"config_entry_id": entry.entry_id},
            blocking=True,
            return_response=True,
            context=Context(user_id=viewer.id),
        )
    entered = asyncio.Event()

    async def held_read(device):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(entry.runtime_data.client, "read", held_read)
    pending = asyncio.create_task(
        hass.services.async_call(
            "adria_mach",
            "probe_connection",
            {"config_entry_id": entry.entry_id},
            blocking=True,
            return_response=True,
        )
    )
    await asyncio.wait_for(entered.wait(), 2)
    queued = asyncio.create_task(action(hass, "light", "turn_on", light))
    await asyncio.sleep(0)
    assert not queued.done()
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "adria_mach",
            "probe_connection",
            {"config_entry_id": entry.entry_id},
            blocking=True,
            return_response=True,
        )
    assert not backend.commands and entry.runtime_data.commands.journal.state["pending"] is None
    coordinator = entry.runtime_data
    assert await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(asyncio.CancelledError):
        await pending
    with pytest.raises((asyncio.CancelledError, HomeAssistantError)):
        await queued
    assert coordinator.commands.probe_task is None
    assert coordinator.last_connection_probe["outcome"] == "cancelled"


async def test_same_outside_identity_uses_numeric_observation_not_binary_alias(
    hass, native_controls
):
    entry, backend, light, number = native_controls
    registry = er.async_get(hass)
    prior = registry.async_get(light)
    registry.async_update_entity(light, name="Owner outside", icon="mdi:lamp")
    del backend.control_snapshots[OutsideControl.BINARY.value]
    control = OutsideControl.LIS112
    backend.control_snapshots[control.value] = Snapshot(
        {control.key: 25}, {}, datetime.now(UTC).isoformat(), asyncio.get_running_loop().time()
    )
    backend.readings[Case.LIGHT.key] = False
    entry.runtime_data.async_set_updated_data(await backend.clients[-1].read("synthetic-a"))
    await hass.async_block_till_done()
    observed = hass.states.get(light)
    assert observed.state == "on" and observed.attributes["brightness"] == 128
    assert observed.attributes["supported_color_modes"] == ["brightness"]
    assert observed.attributes["color_mode"] == "brightness"
    await action(hass, "light", "turn_on", light, brightness=128)
    await action(hass, "light", "turn_off", light)
    await action(hass, "number", "set_value", number, value=22)
    assert backend.commands == [
        (control, 26, False),
        (control, OFF_LEVEL, False),
        (ManualControl.HEATER, 22, False),
    ]
    assert entry.runtime_data.commands.journal.state["pending"] is None
    current = registry.async_get(light)
    assert current.unique_id == prior.unique_id and current.device_id == prior.device_id
    assert current.name == "Owner outside" and current.icon == "mdi:lamp"
    del backend.control_snapshots[control.value]
    entry.runtime_data.async_set_updated_data(await backend.clients[-1].read("synthetic-a"))
    await hass.async_block_till_done()
    assert hass.states.get(light).state == "unavailable"
    assert hass.states.get(light).attributes["supported_color_modes"] == ["onoff"]


@pytest.mark.parametrize("value", [5.5, 4, 31, float("nan")])
async def test_native_number_rejects_unapproved_values_without_truncation(
    hass, native_controls, value
):
    _, backend, _, number = native_controls
    with pytest.raises((HomeAssistantError, ValueError)):
        await action(hass, "number", "set_value", number, value=value)
    assert not backend.commands


async def test_candidate_is_not_observed_and_parallel_request_waits_in_order(hass, native_controls):
    entry, backend, light, number = native_controls
    backend.gate = asyncio.Event()
    request = asyncio.create_task(action(hass, "light", "turn_on", light))
    await asyncio.wait_for(backend.entered.wait(), 2)
    assert hass.states.get(light).state == "on"
    assert hass.states.get(light).attributes["reported_state"] == "off"
    assert hass.states.get(light).attributes["display_state_source"] == "requested"
    assert entry.runtime_data.data.values[Case.LIGHT.key] is False
    entry.runtime_data.async_set_updated_data(await entry.runtime_data.client.read("synthetic-a"))
    assert hass.states.get(light).state == "on"  # Old baseline cannot bounce the display.
    assert hass.states.get(light).attributes["command_outcome"] == "candidate_positive"
    reads = backend.reads
    with pytest.raises(HomeAssistantError) as probe_error:
        await hass.services.async_call(
            "adria_mach",
            "probe_connection",
            {"config_entry_id": entry.entry_id},
            blocking=True,
            return_response=True,
        )
    assert probe_error.value.translation_key == "probe_busy" and backend.reads == reads
    queued = asyncio.create_task(
        hass.services.async_call(
            "number", "set_value", {"entity_id": number, "value": 16}, blocking=True
        )
    )
    await asyncio.sleep(0)
    assert not queued.done() and len(backend.commands) == 1
    backend.gate.set()
    await request
    await queued
    assert backend.commands[-1] == (ManualControl.HEATER, 16, False)
    assert hass.states.get(light).state == "on"
    assert hass.states.get(light).attributes["reported_state"] == "on"
    assert hass.states.get(light).attributes["display_state_source"] == "reported"
    assert not hass.states.get(light).attributes["request_pending"]
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "native_controls", [(Case.GROUP_1, Case.GROUP_2, Case.GROUP_3)], indirect=True
)
async def test_light_queue_serializes_fanout_and_coalesces_unsent_slider(hass, native_controls):
    entry, backend, _, number = native_controls
    manager = entry.runtime_data.commands
    backend.gate = asyncio.Event()
    first = asyncio.create_task(manager.set_manual(ManualControl.GROUP_1, 10))
    await asyncio.wait_for(backend.entered.wait(), 2)
    second = asyncio.create_task(manager.set_manual(ManualControl.GROUP_2, 10, coalesce=True))
    await asyncio.sleep(0)
    third = asyncio.create_task(manager.set_manual(ManualControl.GROUP_3, 10))
    await asyncio.sleep(0)
    original_expiry = manager.lights.pending[0].expires
    replacement = asyncio.create_task(manager.set_manual(ManualControl.GROUP_2, 30, coalesce=True))
    await second
    entity = er.async_get(hass).async_get_entity_id(
        "light", DOMAIN, "synthetic-a_" + Case.GROUP_2.key
    )
    assert hass.states.get(entity).state == "on"
    assert hass.states.get(entity).attributes["brightness"] == 153
    assert hass.states.get(entity).attributes["reported_state"] == "off"
    assert hass.states.get(entity).attributes["request_pending"]
    assert manager.lights.pending[0].expires == original_expiry
    assert len(backend.commands) == 1
    equipment = asyncio.create_task(
        hass.services.async_call(
            "number", "set_value", {"entity_id": number, "value": 22}, blocking=True
        )
    )
    await asyncio.sleep(0)
    backend.gate.set()
    await asyncio.gather(first, third, replacement, equipment)
    assert backend.commands == [
        (ManualControl.GROUP_1, 10, False),
        (ManualControl.GROUP_2, 30, False),
        (ManualControl.GROUP_3, 10, False),
        (ManualControl.HEATER, 22, False),
    ]
    assert not manager.lights.pending and manager.lights.worker is None


@pytest.mark.parametrize("native_controls", [(Case.GROUP_1, Case.GROUP_2)], indirect=True)
async def test_unknown_retains_queued_off_and_sibling_after_fresh_resync(hass, native_controls):
    entry, backend, _, _ = native_controls
    manager = entry.runtime_data.commands
    backend.gate = asyncio.Event()
    backend.command_error = ControlError("synthetic_failure")
    backend.fail_once = True
    first = asyncio.create_task(manager.set_manual(ManualControl.GROUP_1, 10))
    await asyncio.wait_for(backend.entered.wait(), 2)
    off = asyncio.create_task(manager.set_manual(ManualControl.GROUP_1, OFF_LEVEL))
    sibling = asyncio.create_task(manager.set_manual(ManualControl.GROUP_2, 10))
    await asyncio.sleep(0)
    backend.gate.set()
    results = await asyncio.gather(first, off, sibling, return_exceptions=True)
    assert isinstance(results[0], HomeAssistantError) and results[1:] == [None, None]
    assert len(backend.commands) == 2 and not manager.blocked
    assert not manager.lights.pending
    backend.command_error = None
    await manager.set_manual(ManualControl.GROUP_2, 10)
    assert len(backend.commands) == 2 and manager.historical_unknown and not manager.thermal_hold


@pytest.mark.parametrize(
    "native_controls", [(Case.GROUP_1, Case.GROUP_2, Case.GROUP_3)], indirect=True
)
async def test_light_queue_expiry_capacity_and_cancel_never_dispatch(
    hass, native_controls, monkeypatch
):
    from custom_components.adria_mach.client import light_queue

    entry, backend, _, _ = native_controls
    manager = entry.runtime_data.commands
    monkeypatch.setattr(light_queue, "CAPACITY", 1)
    backend.gate = asyncio.Event()
    first = asyncio.create_task(manager.set_manual(ManualControl.GROUP_1, 10))
    await asyncio.wait_for(backend.entered.wait(), 2)
    second = asyncio.create_task(manager.set_manual(ManualControl.GROUP_2, 10))
    await asyncio.sleep(0)
    with pytest.raises(HomeAssistantError):
        await manager.set_manual(ManualControl.GROUP_3, 10)
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second
    assert not manager.lights.pending
    monkeypatch.setattr(light_queue, "WAIT_SECONDS", 0.01)
    expired = asyncio.create_task(manager.set_manual(ManualControl.GROUP_2, 10))
    with pytest.raises(HomeAssistantError):
        await asyncio.wait_for(expired, 0.1)
    assert not first.done() and not manager.lights.pending
    backend.gate.set()
    await first
    assert len(backend.commands) == 1


@pytest.mark.parametrize("phase", ["intent", "resume"])
@pytest.mark.parametrize("native_controls", [(Case.GROUP_1, Case.GROUP_2)], indirect=True)
async def test_cancelled_light_keeps_writer_until_late_io_finishes(
    hass, native_controls, monkeypatch, phase
):
    entry, backend, _, _ = native_controls
    manager = entry.runtime_data.commands
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    if phase == "resume":
        await manager.io(manager.journal.intent_manual, ManualControl.GROUP_1, 20)
        manager.blocked = True
    function = getattr(manager.journal, "intent_manual" if phase == "intent" else "resume_manual")

    def held(*args):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5)
        return function(*args)

    monkeypatch.setattr(manager.journal, function.__name__, held)
    caller = asyncio.create_task(manager.set_manual(ManualControl.GROUP_1, 10))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        worker = manager.lights.worker
        assert worker is not None and manager.task is worker and manager.io_jobs
        queued = asyncio.create_task(manager.set_manual(ManualControl.GROUP_2, 10))
        await asyncio.sleep(0)
        worker.cancel()  # Repeated cancellation cannot release the executor fence.
        await asyncio.sleep(0)
        assert manager.lights.worker is worker and manager.task is worker
        assert not backend.commands
        release.set()
        await asyncio.gather(worker, return_exceptions=True)
        with pytest.raises(HomeAssistantError):
            await queued
        assert not manager.io_jobs and manager.task is None
        # A later explicit call uses a new preflight, never the cancelled target.
        await manager.set_manual(ManualControl.GROUP_2, 10)
        assert backend.commands == [(ManualControl.GROUP_2, 10, False)]
        assert manager.historical_unknown and not manager.thermal_hold
    finally:
        release.set()


@pytest.mark.parametrize("native_controls", [(), (Case.GROUP_1,)], indirect=True)
async def test_unknown_light_resumes_only_after_new_action_and_preserves_history(
    hass, native_controls
):
    entry, backend, light, number = native_controls
    backend.command_error = ControlError("synthetic_failure")
    with pytest.raises(HomeAssistantError):
        await action(hass, "light", "turn_on", light)
    assert hass.states.get(light).state == "off"
    assert hass.states.get(light).attributes["previous_command_unknown"] is True
    old = (entry.runtime_data.commands.directory / "state.json").read_bytes()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.commands.blocked
    await entry.runtime_data.async_refresh()
    assert (
        len([s for s in hass.states.async_all() if s.entity_id.startswith("sensor.adria_mach")])
        >= 10
    )
    backend.command_error = None
    await action(hass, "light", "turn_off", light)  # Fresh no-op does not settle the old ON.
    manager = entry.runtime_data.commands
    archives = list(manager.directory.glob("unknown-light-*"))
    assert len(archives) == 1 and archives[0].read_bytes() == old
    assert manager.historical_unknown and not manager.blocked and not manager.thermal_hold
    await action(hass, "number", "set_value", number, value=16)
    assert manager.historical_unknown
    group = er.async_get(hass).async_get_entity_id(
        "light", DOMAIN, "synthetic-a_" + Case.GROUP_1.key
    )
    if group:
        await action(hass, "light", "turn_on", group)
        assert len(backend.commands) == 3
    else:
        assert len(backend.commands) == 2


async def test_unload_waits_for_cancelled_executor_intent_and_keeps_restart_closed(
    hass, native_controls
):
    entry, _, _, _ = native_controls
    manager = entry.runtime_data.commands
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def delayed():
        loop.call_soon_threadsafe(started.set)
        assert release.wait(5)
        manager.journal.intent(Case.LIGHT, restore=False)

    task = asyncio.create_task(manager.io(delayed))
    try:
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        closing = asyncio.create_task(manager.close())
        await asyncio.sleep(0)
        assert not closing.done()
        closing.cancel()
        await asyncio.sleep(0)
        assert not closing.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert not manager.io_jobs and manager.journal.fd is None
        with pytest.raises(ControlError):
            with Journal(manager.directory):
                pytest.fail("late IO lost its pending interlock")
    finally:
        release.set()


async def test_native_dimming_keeps_registry_and_reports_observed_levels(hass, native_controls):
    entry, backend, light, _ = native_controls
    registry = er.async_get(hass)
    registry.async_update_entity(light, name="Owner lamp", icon="mdi:lamp")
    prior = {
        e.entity_id: (
            e.unique_id,
            e.device_id,
            e.name,
            e.icon,
            e.area_id,
            e.disabled_by,
            e.hidden_by,
        )
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    for case in Case:
        if case.individual_light:
            backend.control_snapshots[case.value] = Snapshot(
                {case.key: case.baseline},
                {},
                datetime.now(UTC).isoformat(),
                asyncio.get_running_loop().time(),
            )
            backend.readings[case.key] = False
    manual_snapshots(backend)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    registered = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert len(registered) == 32 and not backend.commands
    full_identity = {
        e.entity_id: (
            e.unique_id,
            e.device_id,
            e.name,
            e.icon,
            e.area_id,
            e.disabled_by,
            e.hidden_by,
        )
        for e in registered
    }
    assert len({e.device_id for e in registered}) == 1
    assert prior == {
        e.entity_id: (
            e.unique_id,
            e.device_id,
            e.name,
            e.icon,
            e.area_id,
            e.disabled_by,
            e.hidden_by,
        )
        for e in registered
        if e.entity_id in prior
    }
    groups = {
        case: registry.async_get_entity_id("light", DOMAIN, "synthetic-a_" + case.key)
        for case in Case
        if case.individual_light
    }
    assert all(groups.values())
    for entity in groups.values():
        assert hass.states.get(entity).state == "off"
        assert hass.states.get(entity).attributes["supported_color_modes"] == ["brightness"]
    # HA converts percentages and clamps brightness steps before the adapter quantizes.
    await action(hass, "light", "turn_on", groups[Case.GROUP_1], brightness_pct=50)
    assert hass.states.get(groups[Case.GROUP_1]).attributes["brightness"] == 133
    await action(hass, "light", "turn_on", groups[Case.GROUP_1], brightness_step=10000)
    assert hass.states.get(groups[Case.GROUP_1]).attributes["brightness"] == 255
    await action(hass, "light", "turn_on", groups[Case.GROUP_1], brightness=0)
    assert backend.commands == [
        (ManualControl.GROUP_1, 26, False),
        (ManualControl.GROUP_1, 50, False),
        (ManualControl.GROUP_1, Case.GROUP_1.baseline, False),
    ]
    await action(hass, "light", "turn_on", groups[Case.GROUP_1], brightness=16)
    assert backend.commands[-1] == (ManualControl.GROUP_1, 4, False)
    # Bare ON preserves the fresh existing level, rather than sending another command.
    await action(hass, "light", "turn_on", groups[Case.GROUP_1])
    assert len(backend.commands) == 4
    odd = replace(backend.control_snapshots[Case.GROUP_1.value], observed={Case.GROUP_1.key: 3})
    backend.control_snapshots[Case.GROUP_1.value] = odd
    backend.control_snapshots[ManualControl.GROUP_1.value] = odd
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(groups[Case.GROUP_1]).attributes["brightness"] == 15
    await action(hass, "light", "turn_on", groups[Case.GROUP_1])
    assert len(backend.commands) == 4
    await action(hass, "light", "turn_on", groups[Case.GROUP_8])
    await action(hass, "light", "turn_off", groups[Case.GROUP_8])
    assert len(backend.commands) == 6
    backend.control_snapshots.pop(Case.GROUP_2.value)
    backend.control_snapshots.pop(ManualControl.GROUP_2.value)
    backend.readings.pop(Case.GROUP_2.key)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(groups[Case.GROUP_2]).state == "unavailable"
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert full_identity == {
        e.entity_id: (
            e.unique_id,
            e.device_id,
            e.name,
            e.icon,
            e.area_id,
            e.disabled_by,
            e.hidden_by,
        )
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    for case in (Case.GROUP_1, Case.GROUP_8):
        await action(hass, "light", "turn_on", groups[case], brightness=1)
    assert len(backend.commands) == 8


@pytest.mark.parametrize("native_controls", [(Case.GROUP_1, Case.GROUP_8)], indirect=True)
async def test_new_group_uncertainty_keeps_native_waiter_and_retains_history(hass, native_controls):
    entry, backend, old_light, number = native_controls
    registry = er.async_get(hass)
    group = registry.async_get_entity_id("light", DOMAIN, "synthetic-a_" + Case.GROUP_1.key)
    other = registry.async_get_entity_id("light", DOMAIN, "synthetic-a_" + Case.GROUP_8.key)
    backend.gate = asyncio.Event()
    backend.command_error = ControlError("synthetic_failure")
    backend.fail_once = True
    pending = asyncio.create_task(action(hass, "light", "turn_on", group))
    await asyncio.wait_for(backend.entered.wait(), 2)
    assert hass.states.get(group).state == "on"
    assert hass.states.get(group).attributes["reported_state"] == "off"
    assert hass.states.get(group).attributes.get("brightness") is None
    waiting = asyncio.create_task(
        hass.services.async_call("light", "turn_on", {"entity_id": other}, blocking=True)
    )
    await asyncio.sleep(0)
    assert not waiting.done()
    backend.gate.set()
    with pytest.raises(HomeAssistantError):
        await pending
    await waiting
    assert hass.states.get(group).state == "off"
    assert not hass.states.get(group).attributes["request_pending"]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    assert len(backend.commands) == 2
    backend.command_error = None
    await action(hass, "light", "turn_on", other)
    assert len(backend.commands) == 2
    assert backend.commands[-1][0] is ManualControl.GROUP_8
    assert hass.states.get(old_light).attributes["previous_command_unknown"] is True
    await action(hass, "number", "set_value", number, value=16)
    assert len(backend.commands) == 3
    assert hass.states.get("sensor.adria_mach_living_temperature").state != "unavailable"


@pytest.mark.parametrize("native_controls", [(Case.GROUP_1,)], indirect=True)
async def test_unload_cancels_manual_request_without_clearing_pending(hass, native_controls):
    entry, backend, _, number = native_controls
    manager = entry.runtime_data.commands
    group = er.async_get(hass).async_get_entity_id(
        "light", DOMAIN, "synthetic-a_" + Case.GROUP_1.key
    )
    backend.gate = asyncio.Event()
    pending = asyncio.create_task(action(hass, "light", "turn_on", group, brightness_pct=50))
    await asyncio.wait_for(backend.entered.wait(), 2)
    assert await hass.config_entries.async_unload(entry.entry_id)
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not manager.io_jobs
    assert manager.journal.fd is None
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.commands.blocked
    assert hass.states.get(group).state == "off"
    assert not hass.states.get(group).attributes["request_pending"]
    assert hass.states.get(group).attributes["display_state_source"] == "reported"
    backend.gate.set()
    await action(hass, "number", "set_value", number, value=22)
    assert len(backend.commands) == 2
    assert entry.runtime_data.commands.historical_unknown


async def test_unload_waits_for_known_manual_completion_and_does_not_replay(
    hass, native_controls, monkeypatch
):
    entry, backend, _, number = native_controls
    manager = entry.runtime_data.commands
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    complete = manager.journal.complete_manual

    def delayed_complete(*args):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(5)
        return complete(*args)

    monkeypatch.setattr(manager.journal, "complete_manual", delayed_complete)
    request = asyncio.create_task(action(hass, "number", "set_value", number, value=22))
    try:
        await asyncio.wait_for(started.wait(), 2)
        control_task = manager.task
        cancelled_twice = asyncio.Event()
        cancel = control_task.cancel

        def observe_cancel(*args, **kwargs):
            result = cancel(*args, **kwargs)
            if control_task.cancelling() >= 2:
                cancelled_twice.set()
            return result

        monkeypatch.setattr(control_task, "cancel", observe_cancel)
        control_task.cancel()  # First caller cancellation while finalization is held.
        await asyncio.sleep(0)
        closing = asyncio.create_task(hass.config_entries.async_unload(entry.entry_id))
        await asyncio.wait_for(cancelled_twice.wait(), 2)
        assert not closing.done() and manager.journal.fd is not None
        release.set()
        assert await closing
        with pytest.raises(asyncio.CancelledError):
            await request
        assert manager.status == "service_observed" and not manager.blocked
        assert not manager.io_jobs and manager.journal.fd is None
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert len(backend.commands) == 1
        assert entry.runtime_data.commands.journal.state["last_manual"]["target"] == 22
        assert not entry.runtime_data.commands.blocked
        await action(hass, "number", "set_value", number, value=23)
        assert len(backend.commands) == 2
    finally:
        release.set()


@pytest.mark.parametrize(
    "native_controls", [tuple(c for c in Case if c.individual_light)], indirect=True
)
async def test_water_mode_only_native_services_preserve_existing_twenty_eight(
    hass, native_controls
):
    entry, backend, light, _ = native_controls
    registry = er.async_get(hass)
    registry.async_update_entity(light, name="Owner lamp", icon="mdi:lamp")

    def identities():
        return {
            e.entity_id: (
                e.unique_id,
                e.device_id,
                e.name,
                e.icon,
                e.area_id,
                e.disabled_by,
                e.hidden_by,
                e.options,
            )
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        }

    before = identities()
    assert len(before) == 32
    backend.control_snapshots[WaterControl.MODE.value] = Snapshot(
        {WaterControl.MODE.key: "normal"},
        {},
        datetime.now(UTC).isoformat(),
        asyncio.get_running_loop().time(),
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    water = registry.async_get_entity_id(
        "water_heater", DOMAIN, "synthetic-a_" + WaterControl.MODE.key
    )
    assert water and len(identities()) == 33
    assert before == {key: value for key, value in identities().items() if key in before}
    state = hass.states.get(water)
    assert state.state == "normal" and state.attributes["operation_list"] == [
        "off",
        "normal",
        "boost",
    ]
    assert state.attributes["supported_features"] == WaterHeaterEntityFeature.OPERATION_MODE
    assert "min_temp" not in state.attributes and "max_temp" not in state.attributes
    assert state.attributes.get("current_temperature") is None
    assert state.attributes.get("temperature") is None
    assert not backend.commands
    for language, normal, boost in [("en", "Normal", "Boost"), ("fi", "Normaali", "Tehostus")]:
        translations = await async_get_translations(hass, language, "entity", {DOMAIN})
        prefix = "component.adria_mach.entity.water_heater.water_heater_control.state."
        assert translations[prefix + "normal"] == normal
        assert translations[prefix + "boost"] == boost
    for service, data in [
        ("set_operation_mode", {"operation_mode": "eco"}),
        ("set_temperature", {"temperature": 60}),
        ("set_away_mode", {"away_mode": True}),
        ("turn_on", {}),
        ("turn_off", {}),
    ]:
        with pytest.raises(HomeAssistantError):
            await action(hass, "water_heater", service, water, **data)
    assert not backend.commands
    for mode in ("off", "boost", "normal", "normal"):
        await action(hass, "water_heater", "set_operation_mode", water, operation_mode=mode)
        assert hass.states.get(water).state == mode
    assert backend.commands == [
        (WaterControl.MODE, mode, False) for mode in ("off", "boost", "normal")
    ]
    assert entry.runtime_data.commands.journal.state["last_water"]["target"] == "normal"
    assert entry.runtime_data.commands.journal.state["last_manual"] is None
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(backend.commands) == 3
    assert before == {key: value for key, value in identities().items() if key in before}
    assert len(identities()) == 33


@pytest.mark.parametrize("native_controls", [(WaterControl.MODE,)], indirect=True)
@pytest.mark.parametrize("failed", ["water", "number"])
async def test_water_and_existing_controls_share_uncertainty_after_reload(
    hass, native_controls, failed
):
    entry, backend, light, number = native_controls
    water = er.async_get(hass).async_get_entity_id(
        "water_heater", DOMAIN, "synthetic-a_" + WaterControl.MODE.key
    )
    backend.command_error = ControlError("synthetic_failure")
    with pytest.raises(HomeAssistantError):
        if failed == "water":
            await action(hass, "water_heater", "set_operation_mode", water, operation_mode="boost")
        else:
            await action(hass, "number", "set_value", number, value=16)
    assert hass.states.get(water).state == "normal"
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.commands.blocked
    old = (entry.runtime_data.commands.directory / "state.json").read_bytes()
    backend.command_error = None
    for domain, service, entity, data in [
        ("water_heater", "set_operation_mode", water, {"operation_mode": "off"}),
        ("number", "set_value", number, {"value": 22}),
        ("light", "turn_on", light, {}),
    ]:
        await action(hass, domain, service, entity, **data)
    assert len(backend.commands) == 4
    assert any(
        p.read_bytes() == old
        for p in entry.runtime_data.commands.directory.glob("unknown-manual-*")
    )


async def add_native_climate(hass, entry, backend, full_snapshot):
    backend.control_snapshots[HeatingControl.MODE.value] = Snapshot(
        {HeatingControl.MODE.key: "on"},
        {},
        datetime.now(UTC).isoformat(),
        asyncio.get_running_loop().time(),
    )
    backend.readings[HeatingControl.MODE.key] = True
    backend.capabilities = inventory(
        full_snapshot["configuration"], full_snapshot["values"], full_snapshot["normalized"], {}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    return registry.async_get_entity_id("climate", DOMAIN, "synthetic-a_heating_climate")


@pytest.mark.parametrize(
    "native_controls",
    [tuple(c for c in Case if c.individual_light) + (WaterControl.MODE,)],
    indirect=True,
)
async def test_climate_and_inventory_preserve_all_twenty_nine(hass, native_controls, full_snapshot):
    entry, backend, light, number = native_controls
    registry = er.async_get(hass)
    registry.async_update_entity(
        light, name="Owner lamp", icon="mdi:lamp", hidden_by=er.RegistryEntryHider.USER
    )

    def identities():
        return {
            e.entity_id: (
                e.unique_id,
                e.device_id,
                e.name,
                e.icon,
                e.area_id,
                e.disabled_by,
                e.hidden_by,
                e.options,
                e.labels,
                e.aliases,
            )
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        }

    before = identities()
    assert len(before) == 33
    configuration = (dict(entry.data), dict(entry.options))
    climate = await add_native_climate(hass, entry, backend, full_snapshot)
    assert climate and len(identities()) == 35
    assert before == {k: v for k, v in identities().items() if k in before}
    assert configuration == (dict(entry.data), dict(entry.options))
    state = hass.states.get(climate)
    assert state.state == "heat"
    assert state.attributes["hvac_modes"] == ["off", "heat"]
    assert state.attributes["min_temp"] == 5 and state.attributes["max_temp"] == 30
    assert state.attributes["target_temp_step"] == 1
    assert state.attributes["current_temperature"] == 0 and state.attributes["temperature"] == 15
    assert state.attributes["temperature_unit"] == "°C"
    assert state.attributes.get("hvac_action") is None
    assert not backend.commands
    for language, label in (("fi", "Lämmitys"), ("en", "Heating")):
        translations = await async_get_translations(hass, language, "entity", {DOMAIN})
        assert translations["component.adria_mach.entity.climate.heating_climate.name"] == label
    for service, data in [
        ("set_hvac_mode", {"hvac_mode": "cool"}),
        ("set_temperature", {"temperature": 22, "hvac_mode": "heat"}),
        ("set_temperature", {"temperature": 5.5}),
        ("set_temperature", {"temperature": float("nan")}),
        ("set_temperature", {"temperature": 31}),
        ("set_fan_mode", {"fan_mode": "auto"}),
    ]:
        with pytest.raises((HomeAssistantError, ValueError)):
            await action(hass, "climate", service, climate, **data)
    assert not backend.commands
    await action(hass, "climate", "turn_off", climate)
    assert hass.states.get(climate).state == "off"
    await action(hass, "climate", "set_hvac_mode", climate, hvac_mode="heat")
    await action(hass, "climate", "set_temperature", climate, temperature=22)
    assert hass.states.get(number).state == "22"
    await action(hass, "number", "set_value", number, value=23)
    assert hass.states.get(climate).attributes["temperature"] == 23
    assert backend.commands == [
        (HeatingControl.MODE, "off", False),
        (HeatingControl.MODE, "on", False),
        (ManualControl.HEATER, 22, False),
        (ManualControl.HEATER, 23, False),
    ]
    summary = registry.async_get_entity_id("sensor", DOMAIN, "synthetic-a_capability_inventory")
    assert registry.async_get(summary).entity_category.value == "diagnostic"
    assert hass.states.get(summary).state == "18"
    saved = json.dumps(entry.runtime_data.commands.journal.state, sort_keys=True)
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["capabilities"]["summary"]["configured_definitions"] == 18
    assert "synthetic-a" not in json.dumps(diagnostics) and "synthetic-password" not in json.dumps(
        diagnostics
    )
    assert saved == json.dumps(entry.runtime_data.commands.journal.state, sort_keys=True)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(backend.commands) == 4
    assert before == {k: v for k, v in identities().items() if k in before}


@pytest.mark.parametrize("failed", ["climate", "number"])
async def test_climate_and_existing_controls_share_unknown_interlock(
    hass, native_controls, full_snapshot, failed
):
    entry, backend, light, number = native_controls
    climate = await add_native_climate(hass, entry, backend, full_snapshot)
    backend.command_error = ControlError("synthetic_failure")
    with pytest.raises(HomeAssistantError):
        if failed == "climate":
            await action(hass, "climate", "turn_off", climate)
        else:
            await action(hass, "number", "set_value", number, value=22)
    assert hass.states.get(climate).state == "heat"
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    old = (entry.runtime_data.commands.directory / "state.json").read_bytes()
    backend.command_error = None
    for domain, service, entity, data in [
        ("climate", "turn_off", climate, {}),
        ("number", "set_value", number, {"value": 22}),
        ("light", "turn_on", light, {}),
    ]:
        await action(hass, domain, service, entity, **data)
    assert len(backend.commands) == 4
    assert any(
        p.read_bytes() == old
        for p in entry.runtime_data.commands.directory.glob("unknown-manual-*")
    )


async def test_native_equipment_surfaces_preserve_existing_and_gate_optional(hass, native_controls):
    entry, backend, _, _ = native_controls
    registry = er.async_get(hass)
    old = {
        e.entity_id: e.unique_id
        for e in registry.entities.values()
        if e.config_entry_id == entry.entry_id
    }
    for control in CURRENT_CONTROLS:
        backend.control_snapshots[control.value] = Snapshot(
            {
                control.key: None
                if control.action
                else 20
                if control is AcControl.TARGET
                else control.choices[0]
            },
            {},
            datetime.now(UTC).isoformat(),
            asyncio.get_running_loop().time(),
            control.choices,
        )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    def entity(domain, key):
        value = registry.async_get_entity_id(domain, DOMAIN, "synthetic-a_" + key)
        assert value
        return value

    pump = entity("switch", "water_pump")
    source = entity("select", "heating_source")
    level = entity("select", "fridge_level")
    save = entity("button", "light_memory_1_save")
    recall = entity("scene", "light_memory_1_restore")
    assert not registry.async_get_entity_id("switch", DOMAIN, "synthetic-a_aux_output")
    assert not registry.async_get_entity_id("switch", DOMAIN, "synthetic-a_ac_power")
    assert not backend.commands  # Discovery/reload is read-only.
    assert hass.states.get(level).attributes["options"] == ["one", "two", "three", "four", "five"]
    assert "unit_of_measurement" not in hass.states.get(level).attributes
    await action(hass, "switch", "turn_on", pump)
    await action(hass, "select", "select_option", source, option="gas")
    await action(hass, "select", "select_option", level, option="five")
    await action(hass, "button", "press", save)
    assert entry.runtime_data.commands.status == "acknowledged_unconfirmed"
    assert (
        entry.runtime_data.commands.journal.state["last_equipment"]["outcome"]
        == "acknowledged_unconfirmed"
    )
    await action(hass, "scene", "turn_on", recall)
    assert backend.commands[-1] == (EquipmentControl.MEMORY_1, "restore", False)
    assert (
        backend.control_snapshots[EquipmentControl.MEMORY_1.value].observed[
            EquipmentControl.MEMORY_1.key
        ]
        is None
    )
    before = len(backend.commands)
    hass.config_entries.async_update_entry(
        entry,
        options={**entry.options, "identified_equipment": ["aux", "alde", "air_conditioning"]},
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert len(backend.commands) == before
    ac_power = entity("switch", "ac_power")
    ac_mode = entity("select", "ac_mode")
    target = entity("number", "ac_target")
    fan = entity("select", "ac_fan")
    assert hass.states.get(ac_mode).attributes["options"] == ["off", "fan", "cool", "heat", "auto"]
    assert hass.states.get(fan).attributes["options"] == ["low", "mid", "high"]
    assert hass.states.get(ac_mode).state == "off"
    await action(hass, "switch", "turn_on", ac_power)
    await action(hass, "select", "select_option", ac_mode, option="heat")
    await action(hass, "number", "set_value", target, value=22)
    assert backend.commands[-3:] == [
        (AcControl.POWER, "on", False),
        (AcControl.MODE, "heat", False),
        (AcControl.TARGET, 22, False),
    ]
    await action(hass, "select", "select_option", fan, option="mid")
    assert backend.commands[-1] == (AcControl.FAN, "mid", False)
    assert old == {key: registry.async_get(key).unique_id for key in old}


async def test_ordered_equipment_requests_do_not_coalesce(hass, native_controls):
    entry, backend, _, number = native_controls
    backend.gate = asyncio.Event()
    first = asyncio.create_task(action(hass, "number", "set_value", number, value=16))
    await asyncio.wait_for(backend.entered.wait(), 2)
    second = asyncio.create_task(action(hass, "number", "set_value", number, value=20))
    third = asyncio.create_task(action(hass, "number", "set_value", number, value=22))
    await asyncio.sleep(0)
    assert len(backend.commands) == 1
    backend.gate.set()
    await asyncio.gather(first, second, third)
    assert [target for _, target, _ in backend.commands] == [16, 20, 22]
    assert not entry.runtime_data.commands.lights.pending


@pytest.mark.parametrize("native_controls", [(Case.GROUP_1,)], indirect=True)
async def test_native_master_and_explicit_all_off_use_one_route_and_preserve_other_states(
    hass, native_controls
):
    entry, backend, _, _ = native_controls
    registry = er.async_get(hass)
    before = {
        e.entity_id: e.unique_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    backend.control_snapshots[MasterControl.GROUP.value] = Snapshot(
        {MasterControl.GROUP.key: "off"},
        {},
        datetime.now(UTC).isoformat(),
        asyncio.get_running_loop().time(),
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    master = registry.async_get_entity_id("light", DOMAIN, "synthetic-a_light_master")
    button = registry.async_get_entity_id("button", DOMAIN, "synthetic-a_all_lights_off")
    group = registry.async_get_entity_id("light", DOMAIN, "synthetic-a_" + Case.GROUP_1.key)
    assert master and button and hass.states.get(master).state == "off"
    assert not backend.commands
    await action(hass, "light", "turn_off", master)
    await action(hass, "button", "press", button)
    assert backend.commands == [(MasterControl.GROUP, "off", False)] * 2
    assert hass.states.get(group).state == "off"
    backend.gate = asyncio.Event()
    backend.entered.clear()
    first = asyncio.create_task(action(hass, "light", "turn_on", master))
    await asyncio.wait_for(backend.entered.wait(), 2)
    second = asyncio.create_task(
        hass.services.async_call(
            "light", "turn_on", {"entity_id": group, "brightness": 51}, blocking=True
        )
    )
    third = asyncio.create_task(
        hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    )
    await asyncio.sleep(0)
    assert hass.states.get(master).state == "off"
    assert hass.states.get(master).attributes["request_pending"]
    assert hass.states.get(master).attributes["display_state_source"] == "requested"
    assert hass.states.get(group).attributes["reported_state"] == "off"
    backend.gate.set()
    await asyncio.gather(first, second, third)
    assert backend.commands[-3:] == [
        (MasterControl.GROUP, "on", False),
        (ManualControl.GROUP_1, 10, False),
        (MasterControl.GROUP, "off", False),
    ]
    assert hass.states.get(master).state == "off"
    assert (
        hass.states.get(group).state == "on"
    )  # Never fabricate a child observation from master OFF.
    assert hass.states.get(master).attributes["all_physical_lamps_observed"] is False
    assert before == {k: registry.async_get(k).unique_id for k in before}


@pytest.mark.parametrize("native_controls", [(Case.GROUP_1, Case.GROUP_2)], indirect=True)
async def test_native_clicks_stay_ordered_and_feedback_belongs_to_each_control(
    hass, native_controls
):
    entry, backend, outside, _ = native_controls
    manager = entry.runtime_data.commands
    registry = er.async_get(hass)
    group = registry.async_get_entity_id("light", DOMAIN, "synthetic-a_" + Case.GROUP_1.key)
    other = registry.async_get_entity_id("light", DOMAIN, "synthetic-a_" + Case.GROUP_2.key)
    backend.gates = [asyncio.Event() for _ in range(3)]
    backend.command_entered = [asyncio.Event() for _ in range(3)]
    first = asyncio.create_task(
        hass.services.async_call(
            "light",
            "toggle",
            {"entity_id": group},
            blocking=True,
        )
    )
    await asyncio.wait_for(backend.entered.wait(), 2)
    off = asyncio.create_task(
        hass.services.async_call(
            "light",
            "toggle",
            {"entity_id": group},
            blocking=True,
        )
    )
    sibling = asyncio.create_task(
        hass.services.async_call(
            "light",
            "turn_on",
            {"entity_id": other},
            blocking=True,
        )
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert len(manager.lights.pending) == 2
    assert manager.attributes_for(ManualControl.GROUP_1)["pending_target"] == OFF_LEVEL
    assert manager.attributes_for(ManualControl.GROUP_1)["command_outcome"] == "queued"
    assert manager.attributes_for(ManualControl.GROUP_2)["command_outcome"] == "queued"
    assert hass.states.get(outside).attributes["command_outcome"] == "idle"
    # A's earlier completion must not overwrite the newer OFF token.
    manager._feedback(ManualControl.GROUP_1, 1, outcome="service_observed")
    assert manager.attributes_for(ManualControl.GROUP_1)["command_outcome"] == "queued"
    assert hass.states.get(group).state == "off"
    assert hass.states.get(group).attributes["reported_state"] == "off"
    backend.gates[0].set()
    await asyncio.wait_for(backend.command_entered[1].wait(), 2)
    assert hass.states.get(group).state == "off"
    assert hass.states.get(group).attributes["reported_state"] == "on"
    assert hass.states.get(group).attributes["display_state_source"] == "requested"
    backend.gates[1].set()
    backend.gates[2].set()
    await asyncio.wait_for(asyncio.gather(first, off, sibling), 3)
    assert backend.commands == [
        (ManualControl.GROUP_1, 50, False),
        (ManualControl.GROUP_1, OFF_LEVEL, False),
        (ManualControl.GROUP_2, 50, False),
    ]
    assert manager.attributes_for(ManualControl.GROUP_1)["last_requested_value"] == OFF_LEVEL
    assert manager.attributes_for(ManualControl.GROUP_2)["last_requested_value"] == 50
    assert hass.states.get(outside).attributes["last_requested_value"] is None


@pytest.mark.parametrize("native_controls", [(Case.GROUP_1, Case.GROUP_2)], indirect=True)
@pytest.mark.parametrize(
    "kind", ["onoff", "dimmer", "outside-binary", "outside-numeric", "master", "aux"]
)
async def test_pending_light_display_keeps_native_toggle_and_separate_reported_state(
    hass,
    native_controls,
    kind,
):
    entry, backend, outside, _ = native_controls
    registry = er.async_get(hass)
    domain, data = "light", {}
    if kind == "onoff":
        control = ManualControl.GROUP_1
        key = Case.GROUP_1.key
        hass.config_entries.async_update_entry(
            entry, options={"onoff_lights": [Case.GROUP_1.value]}
        )
    elif kind == "dimmer":
        control, key, data = ManualControl.GROUP_2, Case.GROUP_2.key, {"brightness": 153}
    elif kind == "outside-binary":
        control, key = OutsideControl.BINARY, Case.LIGHT.key
    elif kind == "outside-numeric":
        control, key, data = OutsideControl.LIS112, Case.LIGHT.key, {"brightness": 153}
        del backend.control_snapshots[OutsideControl.BINARY.value]
        backend.control_snapshots[control.value] = Snapshot(
            {control.key: OFF_LEVEL},
            {},
            datetime.now(UTC).isoformat(),
            asyncio.get_running_loop().time(),
        )
    else:
        control = MasterControl.GROUP if kind == "master" else EquipmentControl.AUX
        key = "light_master" if kind == "master" else "aux_output"
        if kind == "aux":
            domain = "switch"
            hass.config_entries.async_update_entry(entry, options={"identified_equipment": ["aux"]})
        backend.control_snapshots[control.value] = Snapshot(
            {control.key: "off"},
            {},
            datetime.now(UTC).isoformat(),
            asyncio.get_running_loop().time(),
        )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    entity = registry.async_get_entity_id(domain, DOMAIN, "synthetic-a_" + key)
    assert entity and hass.states.get(entity).state == "off"
    backend.gate = asyncio.Event()
    request = asyncio.create_task(
        hass.services.async_call(
            domain,
            "turn_on",
            {"entity_id": entity, **data},
            blocking=True,
        )
    )
    await asyncio.wait_for(backend.entered.wait(), 2)
    state = hass.states.get(entity)
    assert state.state == "on" and state.attributes["reported_state"] == "off"
    assert state.attributes["display_state_source"] == "requested"
    assert state.attributes["request_pending"] and not state.attributes.get("assumed_state", False)
    assert backend.control_snapshots[control.value].observed[control.key] in ("off", OFF_LEVEL)
    if data:
        assert state.attributes["brightness"] == 153
        assert state.attributes["reported_brightness"] is None
    entry.runtime_data.async_set_updated_data(await backend.clients[-1].read("synthetic-a"))
    assert hass.states.get(entity).state == "on"
    entry.runtime_data.async_set_update_error(HomeAssistantError("synthetic_unavailable"))
    assert hass.states.get(entity).state == "unavailable"
    entry.runtime_data.async_set_updated_data(await backend.clients[-1].read("synthetic-a"))
    assert hass.states.get(entity).state == "on"
    if kind not in ("outside-binary", "outside-numeric"):
        assert hass.states.get(outside).state == "off"
    backend.gate.set()
    await request
    state = hass.states.get(entity)
    assert state.state == "on" and state.attributes["reported_state"] == "on"
    assert not state.attributes["request_pending"]
    assert state.attributes["display_state_source"] == "reported"
    assert len(backend.commands) == 1


@pytest.mark.parametrize("native_controls", [(Case.GROUP_2,)], indirect=True)
@pytest.mark.parametrize("termination", ["rejected", "cancelled", "expired"])
async def test_ended_newer_light_request_keeps_older_active_display(
    hass,
    native_controls,
    monkeypatch,
    termination,
):
    from custom_components.adria_mach.client import light_queue

    entry, backend, _, _ = native_controls
    manager = entry.runtime_data.commands
    entity = er.async_get(hass).async_get_entity_id(
        "light", DOMAIN, "synthetic-a_" + Case.GROUP_2.key
    )
    backend.gate = asyncio.Event()
    first = asyncio.create_task(manager.set_manual(ManualControl.GROUP_2, 10))
    await asyncio.wait_for(backend.entered.wait(), 2)
    if termination == "rejected":
        monkeypatch.setattr(light_queue, "CAPACITY", 0)
        with pytest.raises(HomeAssistantError):
            await manager.set_manual(ManualControl.GROUP_2, OFF_LEVEL)
    else:
        if termination == "expired":
            monkeypatch.setattr(light_queue, "WAIT_SECONDS", 0.01)
        second = asyncio.create_task(manager.set_manual(ManualControl.GROUP_2, OFF_LEVEL))
        await asyncio.sleep(0)
        assert hass.states.get(entity).state == "off"
        if termination == "cancelled":
            second.cancel()
            with pytest.raises(asyncio.CancelledError):
                await second
        else:
            with pytest.raises(HomeAssistantError):
                await asyncio.wait_for(second, 0.2)
    state = hass.states.get(entity)
    assert state.state == "on" and state.attributes["brightness"] == 51
    assert state.attributes["reported_state"] == "off" and state.attributes["request_pending"]
    assert manager.pending_for(ManualControl.GROUP_2).target[0] == 10
    backend.gate.set()
    await first
    assert len(backend.commands) == 1 and not manager.pending_for(ManualControl.GROUP_2)


async def test_session_renewal_action_requires_admin_confirmation_and_preserves_history(
    hass, native_controls, monkeypatch, hass_read_only_user
):
    import probatio as vol
    from homeassistant.core import Context

    entry, backend, light, _ = native_controls
    coordinator = entry.runtime_data
    calls = []

    async def diagnostic(device, report):
        calls.append(device)
        report.update(
            baseline_read_completed=True,
            owned_cookies_cleared=True,
            authentication_rejection_observed=True,
            authentication_rejection_status=401,
            automatic_login_attempts=1,
            device_discoveries=1,
            automatic_renewals=1,
            configured_vehicle_verified=True,
            fresh_read_completed=True,
        )
        return await coordinator.client.read(device)

    monkeypatch.setattr(coordinator.client, "test_session_renewal", diagnostic, raising=False)
    data = {"config_entry_id": entry.entry_id, "confirm": True}
    for bad in ({"config_entry_id": entry.entry_id}, {**data, "confirm": False}):
        with pytest.raises((vol.Invalid, HomeAssistantError)):
            await hass.services.async_call(
                DOMAIN, "test_session_renewal", bad, blocking=True, return_response=True
            )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "test_session_renewal",
            data,
            blocking=True,
            return_response=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    assert not calls
    backend.command_error = ControlError("synthetic_failure")
    with pytest.raises(HomeAssistantError):
        await action(hass, "light", "turn_on", light)
    manager = coordinator.commands
    history = (manager.directory / "state.json").read_bytes()
    registry = dict(er.async_get(hass).entities)
    before = len(backend.commands)
    result = await hass.services.async_call(
        DOMAIN, "test_session_renewal", data, blocking=True, return_response=True
    )
    assert result["outcome"] == "completed" and calls == ["synthetic-a"]
    assert manager.blocked and (manager.directory / "state.json").read_bytes() == history
    assert len(backend.commands) == before and dict(er.async_get(hass).entities) == registry
    assert manager.probe_task is None and not manager.session_test
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["session_renewal_test"] == result and "synthetic" not in json.dumps(result)


@pytest.mark.parametrize("phase", ["baseline", "cookies_cleared", "timeout"])
async def test_session_renewal_reservation_rejects_controls_and_is_cancelled_on_unload(
    hass, native_controls, monkeypatch, phase
):
    from custom_components.adria_mach import connection_probe

    entry, backend, light, _ = native_controls
    coordinator = entry.runtime_data
    manager = coordinator.commands
    entered = asyncio.Event()

    async def held(device, report):
        report["owned_cookies_cleared"] = phase != "baseline"
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(coordinator.client, "test_session_renewal", held, raising=False)
    if phase == "timeout":
        monkeypatch.setattr(connection_probe, "SESSION_TEST_SECONDS", 0.02)
    data = {"config_entry_id": entry.entry_id, "confirm": True}
    task = asyncio.create_task(
        hass.services.async_call(
            DOMAIN, "test_session_renewal", data, blocking=True, return_response=True
        )
    )
    await asyncio.wait_for(entered.wait(), 2)
    before = dict(manager.feedback)
    for request in (
        action(hass, "light", "turn_on", light),
        manager.set(Case.LIGHT, "on"),
        hass.services.async_call(
            DOMAIN, "test_session_renewal", data, blocking=True, return_response=True
        ),
    ):
        with pytest.raises(HomeAssistantError) as error:
            await request
        assert error.value.translation_key == "probe_busy"
    assert manager.feedback == before and not manager.lights.pending and not backend.commands
    assert manager.journal.state["pending"] is None
    if phase == "timeout":
        with pytest.raises(HomeAssistantError):
            await task
        assert coordinator.last_session_renewal_test["outcome"] == "timed_out"
    else:
        assert await hass.config_entries.async_unload(entry.entry_id)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert coordinator.last_session_renewal_test["outcome"] == "cancelled"
    assert manager.probe_task is None and not manager.session_test
    assert not backend.commands


async def test_session_renewal_refuses_existing_command_queue_or_probe(hass, native_controls):
    entry, backend, _, _ = native_controls
    manager = entry.runtime_data.commands
    data = {"config_entry_id": entry.entry_id, "confirm": True}
    for owner, attribute, value in (
        (manager, "task", object()),
        (manager, "probe_task", object()),
        (manager.lights, "worker", object()),
    ):
        setattr(owner, attribute, value)
        try:
            with pytest.raises(HomeAssistantError) as error:
                await hass.services.async_call(
                    DOMAIN, "test_session_renewal", data, blocking=True, return_response=True
                )
            assert error.value.translation_key == "probe_busy"
        finally:
            setattr(owner, attribute, None)
        assert not manager.session_test and not backend.commands
