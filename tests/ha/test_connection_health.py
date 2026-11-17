"""Native health visibility and age clocks with a synthetic external backend."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from custom_components.adria_mach.client.health import ConnectionMetadata
from custom_components.adria_mach.client.model import MachError
from custom_components.adria_mach.const import DOMAIN
from custom_components.adria_mach.diagnostics import async_get_config_entry_diagnostics

HEALTH_IDS = {
    "connection_state": "sensor",
    "last_stream_traffic": "sensor",
    "last_snapshot_age": "sensor",
    "reported_device_contact": "sensor",
    "reported_device_contact_age": "sensor",
    "event_stream_connected": "binary_sensor",
    "reported_device_connected": "binary_sensor",
    "reported_cache_initialized": "binary_sensor",
}


@pytest.fixture
def hass_config_dir(tmp_path):
    return str(tmp_path)


def health_state(hass, key):
    entity = er.async_get(hass).async_get_entity_id(HEALTH_IDS[key], DOMAIN, "synthetic-a_" + key)
    return hass.states.get(entity)


async def setup_health(hass, backend):
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


async def test_age_remains_visible_and_advances_during_telemetry_failure(hass, backend, freezer):
    entry = await setup_health(hass, backend)
    main = entry.runtime_data
    assert health_state(hass, "reported_device_contact_age").state == "unknown"
    assert health_state(hass, "last_snapshot_age").state == "0"
    backend.read_error = MachError("transport_failure")
    await main.async_refresh()
    before = backend.reads
    freezer.tick(timedelta(seconds=31))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert health_state(hass, "last_snapshot_age").state == "31"
    assert health_state(hass, "reported_device_contact_age").state == "unknown"
    assert backend.reads == before and not main.last_update_success
    assert health_state(hass, "connection_state").state != "unavailable"
    backend.read_error = None
    await main.async_refresh()
    await main.health.async_refresh()
    await hass.async_block_till_done()
    assert health_state(hass, "last_snapshot_age").state == "0"
    assert health_state(hass, "reported_device_contact_age").state == "unknown"


async def test_health_source_contact_and_receipt_are_separate_and_safe(hass, backend):
    entry = await setup_health(hass, backend)
    main = entry.runtime_data
    metadata = ConnectionMetadata()
    stamp = int((datetime.now(UTC) - timedelta(hours=1)).timestamp() * 1000)
    metadata.observe(
        {
            "type": "bcknd-msg",
            "payload": {
                "type": "mach-conn",
                "payload": {
                    "connected": True,
                    "initialized": False,
                    "lastContactUTC": stamp,
                    "vehicleId": "SYNTHETIC_PRIVATE_CANARY",
                    "location": "SYNTHETIC_PRIVATE_CANARY",
                },
            },
        }
    )

    class Link:
        last_traffic_at = datetime.now(UTC)
        state_listener = None
        idle = 2

        def facts(self):
            return {
                "connection_state": "ready",
                "connection_ready": True,
                "stream_idle_seconds": self.idle,
                "stream_inactivity_budget_seconds": 600,
                **metadata.facts(),
            }

    link = Link()
    link.metadata = metadata
    main.client.live = link
    await main.health.async_refresh()
    await hass.async_block_till_done()
    assert health_state(hass, "event_stream_connected").state == "on"
    assert health_state(hass, "reported_device_connected").state == "on"
    assert health_state(hass, "reported_cache_initialized").state == "off"
    assert health_state(hass, "last_snapshot_age").state == "0"
    assert 3599 <= int(health_state(hass, "reported_device_contact_age").state) <= 3601
    link.idle = 601
    await main.health.async_refresh()
    await hass.async_block_till_done()
    assert health_state(hass, "connection_state").state == "checking"
    # Silence prompts renewal; the still-open transport is not falsely reported disconnected.
    assert health_state(hass, "event_stream_connected").state == "on"
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert report["source_sample_at"] is None
    assert report["connection_health"]["device_sample_at"] is None
    assert "SYNTHETIC_PRIVATE_CANARY" not in json.dumps(report)
    for key in HEALTH_IDS:
        assert "SYNTHETIC_PRIVATE_CANARY" not in json.dumps(health_state(hass, key).attributes)


async def test_health_clock_unload_and_existing_identity_preservation(hass, backend, freezer):
    entry = await setup_health(hass, backend)
    registry = er.async_get(hass)
    previous = {
        e.entity_id: (e.id, e.unique_id, e.device_id)
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    age_id = health_state(hass, "last_snapshot_age").entity_id
    registry.async_update_entity(age_id, name="Owner age", icon="mdi:timer")
    old_health = entry.runtime_data.health
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert old_health.closed
    assert all(
        (
            registry.async_get(eid).id,
            registry.async_get(eid).unique_id,
            registry.async_get(eid).device_id,
        )
        == values
        for eid, values in previous.items()
    )
    assert registry.async_get(age_id).name == "Owner age"
    assert registry.async_get(age_id).icon == "mdi:timer"
    main = entry.runtime_data
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert main.health.closed
    reads = backend.reads
    freezer.tick(timedelta(minutes=15))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert backend.reads == reads


async def test_recovery_admission_is_finite_and_cancellation_releases_slot(hass, backend):
    entry = await setup_health(hass, backend)
    main = entry.runtime_data
    entered = asyncio.Event()

    async def recover():
        async with main._recovery_admission() as admitted:
            assert admitted
            entered.set()
            await asyncio.Future()

    task = asyncio.create_task(recover())
    await entered.wait()
    assert main.commands.probe_task is task
    async with main._recovery_admission() as admitted:
        assert not admitted
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert main.commands.probe_task is None
    main.commands.session_test = True
    async with main._recovery_admission() as admitted:
        assert not admitted
    main.commands.session_test = False
    future = asyncio.get_running_loop().create_future()
    main.commands.io_jobs.add(future)
    try:
        async with main._recovery_admission() as admitted:
            assert not admitted
    finally:
        main.commands.io_jobs.discard(future)
        future.cancel()
