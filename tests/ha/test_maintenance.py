"""Native maintenance entities, shared admission and cancellation with synthetic devices."""

import asyncio
import threading
from dataclasses import replace
from datetime import timedelta

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant.common import MockConfigEntry

from custom_components.adria_mach import maintenance
from custom_components.adria_mach.client.control_model import ManualControl
from custom_components.adria_mach.client.model import MachError
from custom_components.adria_mach.const import DOMAIN


@pytest.fixture
def hass_config_dir(tmp_path):
    return str(tmp_path)


@pytest.fixture
async def native_maintenance(hass, backend):
    backend.readings.update(mach_software_version="1.9.0", mach_release_channel="PRODUCTION")
    backend.firmware_latest = "1.10.0"
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
    return entry


def entity_id(hass, domain, key):
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, "synthetic-a_" + key)


async def test_native_firmware_numeric_identity_no_install_and_isolated_failure(
    hass,
    backend,
    native_maintenance,
):
    entry = native_maintenance
    main = entry.runtime_data
    registry = er.async_get(hass)
    update = entity_id(hass, "update", "firmware")
    state = hass.states.get(update)
    assert state.state == "on"
    assert state.attributes["installed_version"] == "1.9.0"
    assert state.attributes["latest_version"] == "1.10.0"
    assert state.attributes["supported_features"] == 0
    assert (
        len(
            {
                registry.async_get(entity_id(hass, d, k)).device_id
                for d, k in (
                    ("update", "firmware"),
                    ("button", "restart"),
                    ("button", "check_firmware_updates"),
                    ("sensor", "LIVING_MEASURED_TEMPERATURE"),
                )
            }
        )
        == 1
    )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call("update", "install", {"entity_id": update}, blocking=True)
    assert len(backend.firmware_calls) == 1
    await main.firmware.async_request_refresh()
    assert len(backend.firmware_calls) == 1
    backend.firmware_error = MachError("firmware_check_failed")
    main.firmware.next_check = 0
    await main.firmware.async_refresh()
    assert not main.firmware.last_update_success and main.last_update_success
    await hass.async_block_till_done()
    assert hass.states.get(update).state == "unavailable"
    session = main.firmware.client.session
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert session.closed and main.firmware.closed


@pytest.mark.parametrize(
    "reservation", ["task", "probe_task", "session_test", "pending", "blocked"]
)
async def test_restart_rejects_existing_reservations_without_intent(
    hass,
    native_maintenance,
    reservation,
):
    main = native_maintenance.runtime_data
    commands = main.commands
    if reservation in {"task", "probe_task"}:
        setattr(commands, reservation, asyncio.current_task())
    elif reservation == "pending":
        commands.journal.state["pending"] = {"case": "synthetic"}
    else:
        setattr(commands, reservation, True)
    try:
        with pytest.raises(HomeAssistantError):
            await main.maintenance.async_restart()
        assert main.maintenance.store.events == []
    finally:
        if reservation in {"task", "probe_task"}:
            setattr(commands, reservation, None)
        elif reservation == "pending":
            commands.journal.state["pending"] = None
        else:
            setattr(commands, reservation, False)


async def test_restart_unknown_blocks_all_controls_across_reload_and_exact_local_ack(
    hass,
    backend,
    native_maintenance,
    monkeypatch,
):
    entry = native_maintenance
    main = entry.runtime_data
    calls = []

    async def uncertain(client, device, persist, publish):
        calls.append(True)
        await persist()
        raise MachError("transport_failure")

    monkeypatch.setattr(maintenance, "restart", uncertain)
    journal = main.commands.directory / "state.json"
    before = journal.read_bytes() if journal.exists() else None
    with pytest.raises(HomeAssistantError):
        await main.maintenance.async_restart()
    request = main.maintenance.store.events[-1]["id"]
    assert main.commands.restart_unresolved and not main.commands.can_resynchronize
    with pytest.raises(HomeAssistantError):
        await main.commands.set_manual(ManualControl.GROUP_1, 20)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    main = entry.runtime_data
    assert main.commands.restart_unresolved
    with pytest.raises(HomeAssistantError):
        await main.maintenance.async_restart()
    with pytest.raises(HomeAssistantError):
        await main.maintenance.async_acknowledge("b" * 32)
    assert await main.maintenance.async_acknowledge(request) == {
        "outcome": "owner_acknowledged",
        "physical_confirmation": "not_recorded",
    }
    assert not main.commands.restart_unresolved
    with pytest.raises(HomeAssistantError):
        await main.maintenance.async_acknowledge(request)
    assert len(calls) == 1
    assert (journal.read_bytes() if journal.exists() else None) == before
    assert [r["event"] for r in main.maintenance.store.events] == [
        "requested",
        "owner_acknowledged",
    ]


async def test_restart_cancellation_joins_only_one_durable_completion(
    hass,
    native_maintenance,
    monkeypatch,
):
    main = native_maintenance.runtime_data
    entered, release = threading.Event(), threading.Event()

    async def accepted(client, device, persist, publish):
        await persist()
        return "accepted_unconfirmed"

    monkeypatch.setattr(maintenance, "restart", accepted)
    store = main.maintenance.store
    original = store.append
    appends = []

    def delayed(event, request):
        appends.append(event)
        if event == "accepted_unconfirmed":
            entered.set()
            release.wait(5)
        original(event, request)

    monkeypatch.setattr(store, "append", delayed)
    task = asyncio.create_task(main.maintenance.async_restart())
    try:
        assert await hass.async_add_executor_job(entered.wait, 3)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert main.commands.task is task
        with pytest.raises(HomeAssistantError):
            await main.commands.set_manual(ManualControl.GROUP_1, 20)
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert appends == ["requested", "accepted_unconfirmed"]
    assert main.commands.task is None and not main.commands.io_jobs
    assert main.commands.restart_unresolved
    assert store.attributes["restart_outcome"] == "accepted_unconfirmed"


async def test_firmware_refreshes_stale_metadata_and_missing_version_remains_unknown(
    hass,
    backend,
    native_maintenance,
):
    main = native_maintenance.runtime_data
    before = len(backend.firmware_calls)
    main.data = replace(main.data, received_at=main.data.received_at - timedelta(minutes=2))
    main.firmware.next_check = 0
    await main.firmware.async_refresh()
    assert main.firmware.last_update_success and main.last_update_success
    assert len(backend.firmware_calls) == before + 1
    main.data = replace(main.data, values={"mach_release_channel": "PRODUCTION"})
    main.firmware.next_check = 0
    await main.firmware.async_refresh()
    assert not main.firmware.last_update_success and main.last_update_success
    assert len(backend.firmware_calls) == before + 1


async def test_local_ack_service_requires_admin_and_confirmation(
    hass,
    native_maintenance,
    hass_read_only_user,
):
    import probatio as vol
    from homeassistant.core import Context

    main = native_maintenance.runtime_data
    request_id = "c" * 32
    await main.commands.io(main.maintenance.store.append, "requested", request_id)
    main.commands.restart_unresolved = True
    data = {
        "config_entry_id": native_maintenance.entry_id,
        "request_id": request_id,
        "confirm": True,
    }
    for bad in ({k: v for k, v in data.items() if k != "confirm"}, {**data, "confirm": False}):
        with pytest.raises((vol.Invalid, HomeAssistantError)):
            await hass.services.async_call(
                DOMAIN, "acknowledge_restart", bad, blocking=True, return_response=True
            )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "acknowledge_restart",
            data,
            blocking=True,
            return_response=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    assert main.commands.restart_unresolved
    result = await hass.services.async_call(
        DOMAIN, "acknowledge_restart", data, blocking=True, return_response=True
    )
    assert result["outcome"] == "owner_acknowledged" and not main.commands.restart_unresolved


async def test_unload_cancels_owned_firmware_read_and_closes_isolated_session(
    hass,
    native_maintenance,
    monkeypatch,
):
    main = native_maintenance.runtime_data
    entered = asyncio.Event()

    async def hanging(*args):
        entered.set()
        await asyncio.Future()

    monkeypatch.setattr(main.firmware.client, "check", hanging)
    main.firmware.next_check = 0
    task = asyncio.create_task(main.firmware.async_refresh())
    await entered.wait()
    assert await hass.config_entries.async_unload(native_maintenance.entry_id)
    assert task.done() and main.firmware.client.session.closed
    assert main.commands.closed and not main.commands.io_jobs
