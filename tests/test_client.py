"""Production parser and actual HTTP transport, with synthetic account data."""

import asyncio
import math
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp import web

from custom_components.adria_mach import client as portal
from custom_components.adria_mach.client.model import (
    assigned_devices,
    readings_from,
    temperature_from,
)
from custom_components.adria_mach.connection_probe import run_probe
from custom_components.adria_mach.const import VALUE_ID

CONFIGURATION = {
    "machId": "synthetic-a",
    "values": [
        {
            "id": VALUE_ID,
            "config": {
                "id": VALUE_ID,
                "type": "integer",
                "writable": False,
            },
        }
    ],
}
VALUES = {"values": [{"device": VALUE_ID, "status": 0}]}
READY = (
    b'data: {"type":"bcknd-msg","payload":{"type":"mach-conn",'
    b'"payload":{"connected":true}}}\r\n\r\n'
)
DEVICES = [{"machId": "synthetic-a", "type": "FULL", "name": "Synthetic vehicle"}]


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, 0),
        (15.5, 15.5),
        (None, None),
        (True, None),
        (float("nan"), None),
        (float("inf"), None),
        (-9007199254740991, None),
    ],
)
def test_numeric_measurement_is_truthful(value, expected):
    assert (
        temperature_from(CONFIGURATION, {"values": [{"device": VALUE_ID, "status": value}]})
        == expected
    )


@pytest.mark.parametrize("change", ["missing", "duplicate", "mismatch", "writable", "type"])
def test_definition_must_be_unambiguous_and_verified(change):
    config = deepcopy(CONFIGURATION)
    if change == "missing":
        config["values"] = []
    elif change == "duplicate":
        config["values"] *= 2
    else:
        config["values"][0]["config"][
            {"mismatch": "id", "writable": "writable", "type": "type"}[change]
        ] = "bad"
    with pytest.raises(portal.MachError, match="^unsupported_temperature$"):
        temperature_from(config, VALUES)


def test_missing_or_duplicate_rows_are_unavailable_and_discovery_is_strict():
    for rows in ([], VALUES["values"] * 2, [{"device": VALUE_ID}]):
        assert temperature_from(CONFIGURATION, {"values": rows}) is None
    assert assigned_devices([{"machId": "other", "type": "UNKNOWN"}]) == ()
    with pytest.raises(portal.MachError):
        assigned_devices(DEVICES * 2)


@pytest.fixture
async def scenario(loopback, monkeypatch, full_snapshot):
    calls = []
    responses = []
    configuration = full_snapshot["configuration"]
    stream_open = asyncio.Event()
    stream_done = asyncio.Event()
    release = asyncio.Event()

    async def handler(request):
        path = request.path
        body = await request.json() if request.method == "POST" else None
        calls.append((request.method, path, body))
        if path == "/api/login/login":
            response = web.Response()
            response.set_cookie("test_session", "synthetic-cookie", httponly=True)
            return response
        assert request.cookies.get("test_session") == "synthetic-cookie"
        if path == "/api/user/listMyDevices":
            return web.json_response(DEVICES)
        if path == "/api/control/initHandshake":
            assert body == {"machId": "synthetic-a"}
            return web.json_response({"granted": True})
        if path == "/api/control/events":
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            stream_open.set()
            # Exercise framing across arbitrary network chunks.
            for chunk in (READY[:7], READY[7:55], READY[55:]):
                await response.write(chunk)
            await release.wait()
            stream_done.set()
            return response
        assert path == "/api/control/req" and stream_open.is_set() and not stream_done.is_set()
        assert len(responses) == 1 and not responses[0].closed
        assert body["type"] == "ui-req" and body["payload"]["type"] == "device"
        method = body["payload"]["content"]["method"]
        assert method in ("getMachConfiguration", "getValuesAll")
        return web.json_response(
            {
                "status": 200,
                "payload": configuration
                if method == "getMachConfiguration"
                else full_snapshot["values"],
            }
        )

    url = await loopback(handler)
    # localhost cookies use the real safe jar; only the fixed origin is patched.
    monkeypatch.setattr(portal, "BASE_URL", url.replace("127.0.0.1", "localhost"))
    yield calls, responses, configuration
    release.set()


def observe_stream(client, responses, monkeypatch):
    original_get = client._session.get

    @asynccontextmanager
    async def observe(url, **kwargs):
        async with original_get(url, **kwargs) as response:
            responses.append(response)
            yield response

    monkeypatch.setattr(client._session, "get", observe)


async def test_complete_reader_only_reads_assigned_vehicle_and_keeps_stream_open(
    scenario, monkeypatch, full_snapshot, vehicle_snapshot
):
    full_snapshot["configuration"]["system"] = vehicle_snapshot["configuration"]["system"]
    calls, responses, _ = scenario
    client = portal.MachClient()
    observe_stream(client, responses, monkeypatch)
    try:
        devices = await client.authenticate("synthetic-user", "synthetic-password")
        assert [device.id for device in devices] == ["synthetic-a"]
        with pytest.raises(portal.MachError, match="^device_not_assigned$"):
            await client.read("unassigned")
        result = await client.read(devices[0].id)
        assert responses[0].closed
        assert result.temperature == 0
        assert result.values["OUTSIDE_MEASURED_TEMPERATURE"] == -3
        assert result.values["WASTE_WATER_LEVEL"] == 42
        assert result.values["WATER_HEATER_TEMPERATURE"] == "normal"
        assert result.values["AIR_HEATER_VALUE"] is False
        assert len(result.values) == 18
        assert result.received_at.tzinfo is not None
        assert result.vehicle.values["vehicle_model"] == "Example 700 (Test)"
        assert result.vehicle.values["vehicle_length_with_towbar"] == 8543.5
        assert [(method, path) for method, path, _ in calls] == [
            ("POST", "/api/login/login"),
            ("POST", "/api/user/listMyDevices"),
            ("POST", "/api/control/initHandshake"),
            ("GET", "/api/control/events"),
            ("POST", "/api/control/req"),
            ("POST", "/api/control/req"),
        ]
        assert calls[0][2] == {
            "auth": {"username": "synthetic-user", "password": "synthetic-password"}
        }
        with pytest.raises(portal.MachError, match="operation_rejected"):
            await client._device_read("setValue")
        assert len(calls) == 6
    finally:
        await client.close()
    assert client._session.closed


def test_full_snapshot_projects_only_verified_contract(full_snapshot):
    config, values = full_snapshot["configuration"], full_snapshot["values"]
    for key in (
        "LIVING_BATTERY_SOC",
        "LIVING_BATTERY_SOC_P",
        "INTERNAL_LIGHT_VALUE",
        "SECRET_CONTEXT",
    ):
        config["values"].append(
            {"id": key, "config": {"id": key, "type": "integer", "writable": False}}
        )
        values["values"].append({"device": key, "status": 77, "secret": "PRIVATE"})
    config["token"] = "PRIVATE"
    actual = readings_from(config, values)
    assert actual == full_snapshot["normalized"]
    assert "PRIVATE" not in repr(actual)


@pytest.mark.parametrize(
    "key", ["OUTSIDE_MEASURED_TEMPERATURE", "MAINS_SUPPLY_VALUE", "WATER_HEATER_TEMPERATURE"]
)
@pytest.mark.parametrize(
    "change",
    [
        "missing_definition",
        "duplicate_definition",
        "mismatched_definition",
        "wrong_type",
        "missing_value",
        "duplicate_value",
        "invalid_value",
    ],
)
def test_bad_optional_field_does_not_invalidate_siblings(full_snapshot, key, change):
    config, values = full_snapshot["configuration"], full_snapshot["values"]
    definition = next(row for row in config["values"] if row["id"] == key)
    row = next(row for row in values["values"] if row["device"] == key)
    if change == "missing_definition":
        config["values"].remove(definition)
    elif change == "duplicate_definition":
        config["values"].append(deepcopy(definition))
    elif change == "mismatched_definition":
        definition["config"]["id"] = "other"
    elif change == "wrong_type":
        definition["config"]["type"] = "other"
    elif change == "missing_value":
        values["values"].remove(row)
    elif change == "duplicate_value":
        values["values"].append(deepcopy(row))
    else:
        row["status"] = "unexpected"
    expected = full_snapshot["normalized"]
    if change.endswith("definition") or change == "wrong_type":
        expected.pop(key)
    else:
        expected[key] = None
    assert readings_from(config, values) == expected


@pytest.mark.parametrize("mode", ["off", "boost", "normal", "unknown", True])
def test_mode_tokens_are_exact_without_truthiness(full_snapshot, mode):
    row = next(
        row
        for row in full_snapshot["values"]["values"]
        if row["device"] == "WATER_HEATER_TEMPERATURE"
    )
    row["status"] = mode
    result = readings_from(full_snapshot["configuration"], full_snapshot["values"])
    assert result["WATER_HEATER_TEMPERATURE"] == (
        mode if mode in ("off", "normal", "boost") else None
    )


def test_only_observed_range_contracts_are_applied(full_snapshot):
    for key, minimum, maximum in (
        ("FRESH_WATER_LEVEL", 0, 100),
        ("WASTE_WATER_LEVEL", 0, 100),
        ("AIR_HEATER_TEMPERATURE", 5, 30),
    ):
        row = next(row for row in full_snapshot["values"]["values"] if row["device"] == key)
        for value in (minimum, maximum, minimum - 1, maximum + 1):
            row["status"] = value
            result = readings_from(full_snapshot["configuration"], full_snapshot["values"])
            assert result[key] == (value if minimum <= value <= maximum else None)
    assert result["LIVING_BATTERY_CURRENT"] == -0.35


@pytest.mark.parametrize("identity", [None, "synthetic-other"])
async def test_reader_rejects_missing_or_different_configuration_identity(
    scenario, monkeypatch, identity
):
    calls, responses, configuration = scenario
    configuration["machId"] = identity
    client = portal.MachClient()
    observe_stream(client, responses, monkeypatch)
    try:
        await client.authenticate("synthetic-user", "synthetic-password")
        with pytest.raises(portal.MachError, match="^vehicle_identity_mismatch$"):
            await client.read("synthetic-a")
        assert responses[0].closed
        assert len(calls) == 5
        assert calls[-1][2]["payload"]["content"]["method"] == "getMachConfiguration"
    finally:
        await client.close()


@pytest.mark.parametrize("stream", [False, True])
async def test_redirect_never_forwards_credentials_or_cookies(loopback, monkeypatch, stream):
    forwarded = []

    async def destination(request):
        forwarded.append(request.path)
        return web.Response()

    target = await loopback(destination)

    async def handler(request):
        raise web.HTTPTemporaryRedirect(target)

    monkeypatch.setattr(portal, "BASE_URL", await loopback(handler))
    client = portal.MachClient()
    try:
        with pytest.raises(portal.MachError, match="^redirect_rejected$"):
            if stream:
                async with client._connected_events():
                    pytest.fail("redirect reached device reads")
            else:
                await client.authenticate("synthetic-secret", "synthetic-secret")
    finally:
        await client.close()
    assert forwarded == []


@pytest.mark.parametrize(
    "status,body,error",
    [
        (401, "PRIVATE", portal.AuthenticationError),
        (503, "PRIVATE", portal.MachError),
        (200, "PRIVATE", portal.MachError),
    ],
)
async def test_safe_remote_failures_are_not_retried(
    loopback, monkeypatch, caplog, status, body, error
):
    calls = []

    async def handler(request):
        calls.append(request.path)
        return web.Response(status=status, text=body)

    monkeypatch.setattr(portal, "BASE_URL", await loopback(handler))
    client = portal.MachClient()
    try:
        with pytest.raises(error) as raised:
            await client.authenticate("synthetic", "synthetic")
        assert "PRIVATE" not in str(raised.value) + caplog.text
        assert raised.value.__suppress_context__ or status != 200
    finally:
        await client.close()
    assert len(calls) == 1 and client._session.closed


async def test_body_bound_and_sse_readiness_bounds(loopback, monkeypatch):
    async def handler(request):
        return web.Response(body=b"x" * (portal.MAX_BODY_BYTES + 1))

    monkeypatch.setattr(portal, "BASE_URL", await loopback(handler))
    client = portal.MachClient()
    try:
        with pytest.raises(portal.MachError, match="^body_too_large$"):
            await client.authenticate("synthetic", "synthetic")
    finally:
        await client.close()

    class Chunks:
        def __init__(self, chunks):
            self.chunks = chunks

        async def iter_chunked(self, size):
            for chunk in self.chunks:
                yield chunk

    with pytest.raises(portal.MachError, match="^event_too_large$"):
        await portal.wait_connected(Chunks([b"x" * (portal.MAX_EVENT_BYTES + 1)]))
    monkeypatch.setattr(portal, "MAX_INITIAL_STREAM_BYTES", 50)
    with pytest.raises(portal.MachError, match="^initial_stream_too_large$"):
        await portal.wait_connected(Chunks([b": ignored\n\n"] * 6))
    monkeypatch.setattr(portal, "MAX_INITIAL_STREAM_BYTES", 262_144)
    with pytest.raises(portal.MachError, match="^device_not_connected$"):
        await portal.wait_connected(Chunks([READY.replace(b"true", b"false")]))


async def test_stream_deadline_cancellation_and_shared_connector_cleanup(loopback, monkeypatch):
    entered = asyncio.Queue()
    release = asyncio.Event()

    async def handler(request):
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await entered.put(True)
        await release.wait()
        return response

    monkeypatch.setattr(portal, "BASE_URL", await loopback(handler))
    monkeypatch.setattr(portal, "READINESS_SECONDS", 0.05)
    async with aiohttp.ClientSession() as unrelated:
        client = portal.MachClient(connector=unrelated.connector)
        try:
            with pytest.raises(portal.MachError, match="^transport_failure$"):
                async with client._connected_events():
                    pytest.fail("not ready")
            await entered.get()
            monkeypatch.setattr(portal, "READINESS_SECONDS", 15)

            async def wait():
                async with client._connected_events():
                    pytest.fail("not ready")

            task = asyncio.create_task(wait())
            await entered.get()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            await client.close()
            release.set()
        assert client._session.closed and not unrelated.closed and not unrelated.connector.closed


@pytest.mark.parametrize("mode", ["ok", "timeout", "auth", "rate", "identity"])
async def test_connection_probe_reopens_then_reads_without_writes(
    loopback, monkeypatch, full_snapshot, mode
):
    from custom_components.adria_mach import connection_probe

    release = asyncio.Event()
    responses, methods, snapshots = [], [], []
    streams = 0

    async def handler(request):
        nonlocal streams
        if request.path == "/api/control/events":
            streams += 1
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            if mode != "timeout" or streams > 1:
                await response.write(READY)
            await release.wait()
            return response
        body = await request.json()
        if request.path == "/api/login/login":
            return web.Response()
        if request.path == "/api/user/listMyDevices":
            return web.json_response(DEVICES)
        if request.path == "/api/control/initHandshake":
            if mode in ("auth", "rate"):
                return web.Response(status=401 if mode == "auth" else 429)
            return web.json_response({"granted": True})
        method = body["payload"]["content"]["method"]
        methods.append(method)
        assert method in ("getMachConfiguration", "getValuesAll")
        payload = deepcopy(
            full_snapshot["configuration" if method == "getMachConfiguration" else "values"]
        )
        if method == "getMachConfiguration" and mode == "identity":
            payload["machId"] = "synthetic-wrong"
        if method == "getValuesAll":
            for row in payload["values"]:
                if row["device"] == VALUE_ID:
                    row["status"] = streams
        return web.json_response({"status": 200, "payload": payload})

    monkeypatch.setattr(portal, "BASE_URL", await loopback(handler))
    monkeypatch.setattr(connection_probe, "CYCLE_SECONDS", 0.15)
    monkeypatch.setattr(connection_probe, "PROBE_SECONDS", 0.5)
    client = portal.MachClient()
    original = client._session.get

    @asynccontextmanager
    async def observe(url, **kwargs):
        assert not responses or responses[-1].closed
        async with original(url, **kwargs) as response:
            responses.append(response)
            yield response

    monkeypatch.setattr(client._session, "get", observe)
    coordinator = SimpleNamespace(
        client=client, device_id="synthetic-a", async_set_updated_data=snapshots.append
    )
    try:
        await client.authenticate("synthetic-user", "synthetic-password")
        report = await run_probe(coordinator)
        expected = "completed" if mode == "ok" else "recovered" if mode == "timeout" else None
        if expected:
            assert report["outcome"] == expected and streams == 2
            assert snapshots[-1].values[VALUE_ID] == 2
            assert methods.count("getMachConfiguration") == len(snapshots)
            assert methods.count("getValuesAll") == len(snapshots)
            if mode == "timeout":
                assert report["reads"][0]["outcome"] == "timed_out"
        else:
            assert len(report["reads"]) == 1 and not snapshots
        assert all(response.closed for response in responses)
        assert report["initial_readiness_only"] and not report["push_or_delivery_proven"]
        assert "synthetic" not in str(report)
    finally:
        release.set()
        await client.close()


async def test_connection_probe_deadline_includes_lock_wait_and_cancellation(monkeypatch):
    from custom_components.adria_mach import connection_probe

    monkeypatch.setattr(connection_probe, "CYCLE_SECONDS", 0.02)
    monkeypatch.setattr(connection_probe, "PROBE_SECONDS", 0.07)
    client = portal.MachClient()
    coordinator = SimpleNamespace(client=client, device_id="synthetic-a")
    await client._lock.acquire()
    try:
        report = await asyncio.wait_for(run_probe(coordinator), 0.2)
        assert [item["outcome"] for item in report["reads"]] == ["timed_out", "timed_out"]
        task = asyncio.create_task(run_probe(coordinator))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert coordinator.last_connection_probe["outcome"] == "cancelled"
    finally:
        client._lock.release()
        await client.close()


@pytest.fixture
async def live_wire(loopback, monkeypatch, full_snapshot):
    """Actual owned SSE and RPC transport; no manufacturer connection."""
    import json

    from custom_components.adria_mach.client import live

    state = SimpleNamespace(
        calls=[],
        streams=[],
        values=deepcopy(full_snapshot["values"]),
        status=200,
        app_status=200,
        rpc_entered=asyncio.Event(),
        rpc_release=None,
        during_read=None,
        configuration=full_snapshot["configuration"],
    )

    async def handler(request):
        path = request.path
        body = await request.json() if request.method == "POST" else None
        if path == "/api/login/login":
            return web.Response()
        if path == "/api/user/listMyDevices":
            return web.json_response(DEVICES)
        if path == "/api/control/initHandshake":
            state.calls.append("handshake")
            return web.json_response({"granted": True})
        if path == "/api/control/events":
            state.calls.append("stream")
            queue = asyncio.Queue()
            state.streams.append(queue)
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            await response.write(READY)
            while True:
                event = await queue.get()
                if event is None:
                    return response
                try:
                    await response.write(b"data: " + json.dumps(event).encode() + b"\n\n")
                except ConnectionResetError:
                    return response
        assert path == "/api/control/req"
        method = body["payload"]["content"]["method"]
        state.calls.append(method)
        assert method in ("getMachConfiguration", "getValuesAll")
        if state.status != 200:
            return web.Response(status=state.status, headers={"Retry-After": "1"})
        if method == "getMachConfiguration":
            return web.json_response(
                {
                    "status": state.app_status,
                    "payload": state.configuration,
                }
            )
        data = deepcopy(state.values)
        if state.rpc_release is not None:
            state.rpc_entered.set()
            await state.rpc_release.wait()
        if state.during_read:
            state.during_read()
            state.during_read = None
        return web.json_response({"status": 200, "payload": data})

    url = await loopback(handler)
    monkeypatch.setattr(portal, "BASE_URL", url)
    monkeypatch.setattr(live, "BASE_URL", url)
    monkeypatch.setattr(live, "REFRESH_DELAY", 0.005)
    monkeypatch.setattr(live, "RECONNECT_DELAYS", (0.005, 0.01))
    yield state
    for queue in state.streams:
        queue.put_nowait(None)


async def eventually(predicate):
    async with asyncio.timeout(2):
        while not predicate():  # noqa: ASYNC110 -- bounded observation of real wire completion
            await asyncio.sleep(0.005)


def value_event(value, *, key=VALUE_ID):
    return {
        "type": "mach-msg",
        "payload": {
            "type": "values",
            "values": [
                {"valueId": key, "value": value},
            ],
        },
    }


def set_temperature(state, value):
    next(row for row in state.values["values"] if row["device"] == VALUE_ID)["status"] = value


async def test_live_reuses_epoch_invalidates_with_full_read_and_closes_borrowed_connector(
    live_wire,
    position_snapshot,
):
    state = live_wire
    state.configuration = position_snapshot["configuration"]
    state.values = position_snapshot["values"]
    connector = aiohttp.TCPConnector()
    client = portal.MachClient(connector, persistent=True)
    published = []
    client.live.listener = published.append
    try:
        await client.authenticate("synthetic-user", "synthetic-password")
        await client.read("synthetic-a")
        await client.read("synthetic-a")
        assert state.calls.count("handshake") == state.calls.count("stream") == 1
        for _ in range(10):
            state.streams[0].put_nowait(value_event(0))
        state.streams[0].put_nowait(value_event(42, key="UNVERIFIED_ID"))
        await asyncio.sleep(0.03)
        assert not published
        set_temperature(state, 7)
        for _ in range(10):
            state.streams[0].put_nowait(value_event(7))
        await eventually(lambda: published)
        assert published[-1].temperature == 7
        await eventually(lambda: client.live.maintenance is None)
        count = state.calls.count("getValuesAll")
        for _ in range(5):
            state.streams[0].put_nowait(value_event(7))
        await asyncio.sleep(0.03)
        assert state.calls.count("getValuesAll") == count
        row = next(r for r in state.values["values"] if r["device"] == "LTE_SIGNAL_STRENGTH")
        row["status"] = 61
        state.streams[0].put_nowait(value_event(99, key="LTE_SIGNAL_STRENGTH"))
        await eventually(lambda: published[-1].values.get("LTE_SIGNAL_STRENGTH") == 61)
        assert published[-1].values["mach_software_version"] == "9.8.7 2030-01-02"
        await eventually(lambda: client.live.maintenance is None)
        count = state.calls.count("getValuesAll")
        state.streams[0].put_nowait(value_event(61, key="LTE_SIGNAL_STRENGTH"))
        await asyncio.sleep(0.03)
        assert state.calls.count("getValuesAll") == count
        row = next(r for r in state.values["values"] if r["device"] == "GPS_LONGITUDE")
        row["status"] = -21.75
        state.streams[0].put_nowait(value_event(42.75, key="GPS_LONGITUDE"))
        await eventually(lambda: published[-1].location.longitude == -21.75)
        row = next(r for r in state.values["values"] if r["device"] == "ACCELERATION_Y")
        row["status"] = math.tan(math.radians(10))
        state.streams[0].put_nowait(value_event(-0.9, key="ACCELERATION_Y"))
        await eventually(lambda: published[-1].values["levelling_pitch"] == pytest.approx(-10))
        assert "GPS_LONGITUDE" not in published[-1].values
        assert state.calls.count("handshake") == state.calls.count("stream") == 1
        assert set(state.calls) <= {"handshake", "stream", "getMachConfiguration", "getValuesAll"}
    finally:
        await client.close()
        borrowed_connector_open = not connector.closed
        await connector.close()
    assert borrowed_connector_open
    assert client.live.pump is None and client.live.maintenance is None


async def test_live_invalidation_during_snapshot_is_not_lost_and_disconnect_resynchronizes(
    live_wire,
):
    state = live_wire
    client = portal.MachClient(persistent=True)
    published = []
    client.live.listener = published.append
    try:
        await client.authenticate("synthetic-user", "synthetic-password")
        await client.read("synthetic-a")
        state.rpc_release = asyncio.Event()
        set_temperature(state, 1)
        state.streams[0].put_nowait(value_event(1))
        await asyncio.wait_for(state.rpc_entered.wait(), 2)
        set_temperature(state, 2)
        state.streams[0].put_nowait(value_event(2))
        await eventually(lambda: client.live.invalidations >= 2)
        state.rpc_release.set()
        await eventually(lambda: len(published) >= 2)
        assert [m.temperature for m in published[:2]] == [1, 2]
        state.streams[0].put_nowait(None)
        await eventually(lambda: state.calls.count("handshake") == 2 and len(published) >= 3)
        assert client.live.facts()["connection_ready"]
        assert set(state.calls) <= {"handshake", "stream", "getMachConfiguration", "getValuesAll"}
    finally:
        await client.close()


@pytest.mark.parametrize("status", [401, 403, 429])
@pytest.mark.parametrize("application", [False, True])
async def test_live_auth_and_retry_after_gate_network_without_automatic_write(
    live_wire,
    status,
    application,
):
    state = live_wire
    client = portal.MachClient(persistent=True)
    try:
        await client.authenticate("synthetic-user", "synthetic-password")
        await client.read("synthetic-a")
        if application:
            state.app_status = status
        else:
            state.status = status
        with pytest.raises(portal.MachError):
            await client.read("synthetic-a")
        before = len(state.calls)
        with pytest.raises(portal.MachError):
            await client.read("synthetic-a")
        assert len(state.calls) == before
        if status == 429:
            assert 0 < client.rate_wait <= (30 if application else 1)
    finally:
        await client.close()


async def test_live_transient_rpc_failure_returns_to_ready_after_verified_refresh(live_wire):
    state = live_wire
    client = portal.MachClient(persistent=True)
    published = []
    client.live.listener = published.append
    try:
        await client.authenticate("synthetic-user", "synthetic-password")
        await client.read("synthetic-a")
        state.status = 500
        state.streams[0].put_nowait(value_event(2))
        await eventually(lambda: state.calls.count("getMachConfiguration") >= 2)
        state.status = 200
        await eventually(lambda: published)
        assert client.live.facts()["connection_state"] == "ready"
        assert state.calls.count("handshake") == 1
    finally:
        await client.close()


async def test_live_cancelled_readiness_joins_owned_stream(loopback, monkeypatch):
    from custom_components.adria_mach.client import live

    release = asyncio.Event()
    opened = asyncio.Event()

    async def handler(request):
        if request.path.endswith("initHandshake"):
            return web.json_response({"granted": True})
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        opened.set()
        await release.wait()
        return response

    url = await loopback(handler)
    monkeypatch.setattr(portal, "BASE_URL", url)
    monkeypatch.setattr(live, "BASE_URL", url)
    client = portal.MachClient(persistent=True)
    try:
        task = asyncio.create_task(client.live.ensure("synthetic-a"))
        await asyncio.wait_for(opened.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client.live.pump is None and not client.live.ready.is_set()
    finally:
        release.set()
        await client.close()


def test_diagnostic_projection_preserves_versions_and_excludes_private_fields(diagnostic_snapshot):
    import json

    from custom_components.adria_mach.client.capabilities import inventory

    config, values = diagnostic_snapshot["configuration"], diagnostic_snapshot["values"]
    for key in (
        "LTE_SIM_APN_VALUE",
        "LTE_SIM_ID_VALUE",
        "LTE_SIM_PASSWORD_VALUE",
        "LTE_SIM_PIN_VALUE",
        "GPS_LATITUDE",
        "UNKNOWN_PRIVATE_FIELD",
    ):
        config["values"].append(
            {
                "id": key,
                "config": {
                    "id": key,
                    "type": "string",
                    "writable": False,
                    "label": "PRIVATE_MARKER",
                },
            }
        )
        values["values"].append({"device": key, "status": "PRIVATE_MARKER"})
    config["private_extra"] = "PRIVATE_MARKER"
    actual = readings_from(config, values)
    assert actual == diagnostic_snapshot["normalized"]
    assert "PRIVATE_MARKER" not in json.dumps(actual)
    report = inventory(config, values, actual, {})
    assert "PRIVATE_MARKER" not in json.dumps(report.export())
    operator = next(r for r in report.definitions if r.identifier == "LTE_OPERATOR_NAME")
    assert operator.disposition == "implemented" and operator.native_domains == ("sensor",)
    assert not operator.control_available


@pytest.mark.parametrize(
    "value", [0, -1, -9007199254740991, True, float("nan"), float("inf"), 101, "73", None, 10**500]
)
def test_invalid_signal_is_not_a_zero_or_connection_claim(diagnostic_snapshot, value):
    values = diagnostic_snapshot["values"]
    next(r for r in values["values"] if r["device"] == "LTE_SIGNAL_STRENGTH")["status"] = value
    result = readings_from(diagnostic_snapshot["configuration"], values)
    assert result["LTE_SIGNAL_STRENGTH"] is None
    assert result[VALUE_ID] == 0


@pytest.mark.parametrize(
    "change",
    [
        "absent",
        "duplicate",
        "mismatch",
        "type",
        "writable",
        "no_state",
        "missing_row",
        "duplicate_row",
    ],
)
def test_optional_diagnostic_schema_and_row_failures_are_isolated(diagnostic_snapshot, change):
    config, values = diagnostic_snapshot["configuration"], diagnostic_snapshot["values"]
    key = "SYSTEM_IO_FIRMWARE_VERSION"
    definition = next(r for r in config["values"] if r["id"] == key)
    row = next(r for r in values["values"] if r["device"] == key)
    if change == "absent":
        config["values"].remove(definition)
    elif change == "duplicate":
        config["values"].append(deepcopy(definition))
    elif change == "missing_row":
        values["values"].remove(row)
    elif change == "duplicate_row":
        values["values"].append(deepcopy(row))
    else:
        field, value = {
            "mismatch": ("id", "OTHER"),
            "type": ("type", "integer"),
            "writable": ("writable", True),
            "no_state": ("hasState", False),
        }[change]
        definition["config"][field] = value
    result = readings_from(config, values)
    assert result.get(key) is None and result["LTE_SIGNAL_STRENGTH"] == 73
    assert "SYSTEM_FIRMWARE_VERSION_MCU_2" not in result and "PANEL_VERSION" not in result


@pytest.mark.parametrize(
    "key,value",
    [
        ("LTE_OPERATOR_NAME", "Example\nSECRET"),
        ("LTE_OPERATOR_NAME", "x" * 65),
        ("LTE_OPERATOR_NAME", "user@example.invalid"),
        ("LTE_VALUE", True),
        ("LTE_SIM_VALUE", "UNVERIFIED_STATE"),
        ("SYSTEM_POWER_REGIME", "UNVERIFIED_MODE"),
        ("SYSTEM_IO_FIRMWARE_VERSION", "unknown"),
        ("SYSTEM_IO_FIRMWARE_VERSION", "x" * 97),
        ("LTE_REGISTRATION_STATUS", "<private>"),
    ],
)
def test_invalid_diagnostic_text_does_not_escape(diagnostic_snapshot, key, value):
    config, values = diagnostic_snapshot["configuration"], diagnostic_snapshot["values"]
    next(r for r in values["values"] if r["device"] == key)["status"] = value
    actual = readings_from(config, values)
    assert actual[key] is None and actual[VALUE_ID] == 0


def test_missing_and_malformed_metadata_never_invent_versions(diagnostic_snapshot):
    config, values = diagnostic_snapshot["configuration"], diagnostic_snapshot["values"]
    config.pop("version")
    config["osReleaseDate"] = "2030-02-30"
    config["releaseType"] = "PRIVATE\nMARKER"
    actual = readings_from(config, values)
    assert not {"mach_software_version", "mach_os_release", "mach_release_channel"} & actual.keys()
    assert actual["SYSTEM_IO_FIRMWARE_VERSION"] == "03.004.005"


@pytest.mark.parametrize("metadata", ["missing", None, False, True, "invalid"])
def test_lte_readonly_projection_accepts_optional_writability(diagnostic_snapshot, metadata):
    config, values = diagnostic_snapshot["configuration"], diagnostic_snapshot["values"]
    for key in ("LTE_VALUE", "USER_ALLOWS_ROAMING"):
        definition = next(r["config"] for r in config["values"] if r["id"] == key)
        if metadata == "missing":
            definition.pop("writable")
        else:
            definition["writable"] = metadata
    actual = readings_from(config, values)
    if metadata == "invalid":
        assert "LTE_VALUE" not in actual and "USER_ALLOWS_ROAMING" not in actual
    else:
        assert actual["LTE_VALUE"] is True and actual["USER_ALLOWS_ROAMING"] is False


def set_position(data, **updates):
    for key, value in updates.items():
        next(row for row in data["values"]["values"] if row["device"] == key)["status"] = value


async def test_vehicle_metadata_mapping_privacy_and_snapshot_replacement(vehicle_snapshot):
    from dataclasses import FrozenInstanceError

    from custom_components.adria_mach.client.vehicle import VehicleInfo

    config, values = vehicle_snapshot["configuration"], vehicle_snapshot["values"]
    expected = {
        "vehicle_model": "Example 700 (Test)",
        "chassis_number": "000-TEST-CHASSIS",
        "vehicle_height": 2710,
        "vehicle_length": 7123,
        "vehicle_length_with_towbar": 8543.5,
        "vehicle_width": 2310.25,
    }
    result = portal.MachClient.measurement(config, values, "synthetic-a")
    assert dict(result.vehicle.values) == expected
    assert result.temperature == 0 and result.location is not None
    assert result.values["levelling_pitch"] == 0
    assert not set(expected) & result.values.keys()
    assert "000-TEST-CHASSIS" not in repr(result) + repr(result.vehicle)
    copy = VehicleInfo(expected)
    expected["chassis_number"] = "CHANGED"
    assert copy.values["chassis_number"] == "000-TEST-CHASSIS"
    with pytest.raises(TypeError):
        copy.values["chassis_number"] = "CHANGED"
    with pytest.raises(FrozenInstanceError):
        copy.values = {}
    config["system"]["vehicle"]["equipment"] = []
    config["system"]["vehicle"]["chassis"] = {"id": "DO-NOT-USE"}
    missing = portal.MachClient.measurement(config, values, "synthetic-a")
    assert missing.vehicle.values["chassis_number"] is None
    assert missing.vehicle.values["vehicle_length"] is None  # No properties fallback.
    assert missing.vehicle.values["vehicle_model"] == "Example 700 (Test)"
    config["system"]["vehicle"]["equipment"] = [{"key": "B13", "value": "7000"}]
    assert (
        portal.MachClient.measurement(config, values, "synthetic-a").vehicle.values[
            "vehicle_length"
        ]
        == 7000
    )


@pytest.mark.parametrize(
    "invalid",
    [
        True,
        None,
        0,
        -1,
        math.nan,
        math.inf,
        -9007199254740991,
        5e-324,
        10**400,
        "2710 mm",
        "1e3",
        "1,5",
        " 1",
        "1\n",
        [],
        {},
        "9" * 400,
    ],
)
def test_vehicle_dimension_rejects_invalid_values_without_hiding_siblings(
    vehicle_snapshot, invalid
):
    from custom_components.adria_mach.client.vehicle import vehicle_from

    config = vehicle_snapshot["configuration"]
    config["system"]["vehicle"]["equipment"][0]["value"] = invalid
    actual = vehicle_from(config).values
    assert actual["vehicle_height"] is None
    assert actual["vehicle_width"] == 2310.25


@pytest.mark.parametrize("bad_path", ["system", "vehicle", "chassis", "equipment", "duplicate"])
async def test_vehicle_malformed_optional_groups_are_isolated(vehicle_snapshot, bad_path):
    config, values = vehicle_snapshot["configuration"], vehicle_snapshot["values"]
    if bad_path == "system":
        config["system"] = []
    elif bad_path == "vehicle":
        config["system"]["vehicle"] = "invalid"
    elif bad_path == "duplicate":
        config["system"]["vehicle"]["equipment"].append({"key": "B11", "value": "2710"})
    else:
        config["system"]["vehicle"][bad_path] = "invalid"
    result = portal.MachClient.measurement(config, values, "synthetic-a")
    assert result.temperature == 0 and result.location is not None
    assert result.values["levelling_roll"] == 0
    if bad_path in ("system", "vehicle"):
        assert not result.vehicle.values
    elif bad_path == "chassis":
        assert result.vehicle.values["chassis_number"] is None
        assert result.vehicle.values["vehicle_height"] == 2710
    else:
        assert result.vehicle.values["vehicle_height"] is None
        assert result.vehicle.values["chassis_number"] == "000-TEST-CHASSIS"


@pytest.mark.parametrize(
    "invalid", [None, 123, "", " ", "x" * 101, "Bad\ntext", "<private>", "Bad\x00text"]
)
def test_vehicle_text_rejects_invalid_data(vehicle_snapshot, invalid):
    from custom_components.adria_mach.client.vehicle import vehicle_from

    config = vehicle_snapshot["configuration"]
    config["system"]["vehicle"]["model"] = invalid
    config["system"]["vehicle"]["chassis"]["number"] = invalid
    actual = vehicle_from(config).values
    assert actual["vehicle_model"] is None and actual["chassis_number"] is None
    assert actual["vehicle_height"] == 2710


@pytest.mark.parametrize(
    "vector,expected",
    [
        ((0, math.tan(math.radians(10)), 1), (-10, 0)),
        ((math.tan(math.radians(-20)), 0, 1), (0, -20)),
        ((1, 0, 0), (0, 0)),
    ],
)
def test_levelling_axes_and_signs(position_snapshot, vector, expected):
    from custom_components.adria_mach.client.position import ANGLE_KEYS, AXES, Levelling

    set_position(position_snapshot, **dict(zip(AXES, vector, strict=True)))
    actual = Levelling().readings(position_snapshot["configuration"], position_snapshot["values"])
    assert tuple(actual[k] for k in ANGLE_KEYS) == pytest.approx(expected)


async def test_levelling_calibration_and_mounting_context(position_snapshot):
    from custom_components.adria_mach.client.position import AXES, OFFSETS, Levelling

    config, values = position_snapshot["configuration"], position_snapshot["values"]
    levelling = Levelling()
    assert levelling.readings(config, values)["levelling_roll"] == 0
    set_position(position_snapshot, ACCELERATION_X=1, ACCELERATION_Z=0)
    assert levelling.readings(config, values)["levelling_roll"] == 90  # Latched horizontal.
    assert Levelling().readings(config, values)["levelling_roll"] == 0  # Fresh vertical.
    for key, value in zip(OFFSETS, (0, 0, 1), strict=True):
        config["values"].append(
            {"id": key, "config": {"id": key, "type": "float", "writable": True}}
        )
        values["values"].append({"device": key, "status": value})
    assert levelling.readings(config, values)["levelling_roll"] == 0  # Calibration reset.
    for key, value in zip(OFFSETS, (0.1, 0.2, 0.9), strict=True):
        set_position(position_snapshot, **{key: value})
    set_position(position_snapshot, **dict(zip(AXES, (0.1, 0.2, 0.9), strict=True)))
    assert tuple(levelling.readings(config, values).values()) == pytest.approx((0, 0))
    client = portal.MachClient()
    first = client._observed(config, values, "synthetic-a")
    set_position(position_snapshot, **dict(zip(AXES, (1, 0, 0), strict=True)))
    retained = client._observed(config, values, "synthetic-a")
    changed = client._observed(config, values, "synthetic-b")
    assert first.values["levelling_roll"] == 0
    assert retained.values["levelling_roll"] != changed.values["levelling_roll"]
    client._levelling_device = None  # The authenticated-session reset boundary.
    assert client._observed(config, values, "synthetic-a").values == changed.values
    await client.close()


@pytest.mark.parametrize(
    "fault",
    [
        "bool",
        "null",
        "nan",
        "infinity",
        "sentinel",
        "tiny_sentinel",
        "zero",
        "duplicate_row",
        "missing_row",
        "duplicate_definition",
        "mismatch",
        "writable",
        "missing_writable",
        "string_type",
        "partial_offsets",
    ],
)
def test_invalid_levelling_is_grouped_and_isolated(position_snapshot, fault):
    from copy import deepcopy

    from custom_components.adria_mach.client.position import ANGLE_KEYS

    config, values = position_snapshot["configuration"], position_snapshot["values"]
    definition = next(r for r in config["values"] if r["id"] == "ACCELERATION_X")
    row = next(r for r in values["values"] if r["device"] == "ACCELERATION_X")
    invalid = {
        "bool": True,
        "null": None,
        "nan": math.nan,
        "infinity": math.inf,
        "sentinel": -9007199254740991,
        "tiny_sentinel": 5e-324,
    }
    if fault in invalid:
        row["status"] = invalid[fault]
    elif fault == "zero":
        set_position(position_snapshot, ACCELERATION_Z=0)
    elif fault == "duplicate_row":
        values["values"].append(deepcopy(row))
    elif fault == "missing_row":
        values["values"].remove(row)
    elif fault == "duplicate_definition":
        config["values"].append(deepcopy(definition))
    elif fault == "mismatch":
        definition["config"]["id"] = "OTHER"
    elif fault == "writable":
        definition["config"]["writable"] = True
    elif fault == "missing_writable":
        definition["config"].pop("writable")
    elif fault == "string_type":
        definition["config"]["type"] = "string"
    else:
        key = "ACCELERATION_X_ZERO_POSITION_OFFSET"
        config["values"].append(
            {"id": key, "config": {"id": key, "type": "float", "writable": True}}
        )
        values["values"].append({"device": key, "status": 0})
    actual = readings_from(config, values)
    assert all(actual[key] is None for key in ANGLE_KEYS)
    assert actual[VALUE_ID] == 0


@pytest.mark.parametrize(
    "latitude,longitude,valid",
    [
        (10.125, -20.25, True),
        (-90, 180, True),
        (90, -180, True),
        (0, 20, False),
        (10, 0, False),
        (90.1, 20, False),
        (10, -180.1, False),
        (True, 20, False),
        (10, None, False),
        (math.nan, 20, False),
        (10, math.inf, False),
    ],
)
async def test_location_is_private_paired_and_not_retained(
    position_snapshot, latitude, longitude, valid
):
    from dataclasses import FrozenInstanceError

    from custom_components.adria_mach.client.position import GPS_IDS, location_from

    config, values = position_snapshot["configuration"], position_snapshot["values"]
    initial = location_from(config, values)
    with pytest.raises(FrozenInstanceError):
        initial.latitude = 42
    assert "10.125" not in repr(initial)
    set_position(position_snapshot, GPS_LATITUDE=latitude, GPS_LONGITUDE=longitude)
    measurement = portal.MachClient.measurement(config, values, "synthetic-a")
    assert (measurement.location is not None) is valid
    if valid:
        assert (measurement.location.latitude, measurement.location.longitude) == (
            latitude,
            longitude,
        )
    assert not set(GPS_IDS) & measurement.values.keys()
    assert "10.125" not in repr(measurement)
    set_position(position_snapshot, GPS_LATITUDE=11.125, GPS_LONGITUDE=-21.25)
    recovered = location_from(config, values)
    assert (recovered.latitude, recovered.longitude) == (11.125, -21.25)
