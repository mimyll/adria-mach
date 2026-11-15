"""Production parser and actual HTTP transport, with synthetic account data."""

import asyncio
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
    scenario, monkeypatch
):
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
                    "payload": full_snapshot["configuration"],
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
):
    state = live_wire
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
        count = state.calls.count("getValuesAll")
        for _ in range(5):
            state.streams[0].put_nowait(value_event(7))
        await asyncio.sleep(0.03)
        assert state.calls.count("getValuesAll") == count
    finally:
        await client.close()
    assert not connector.closed
    await connector.close()
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
