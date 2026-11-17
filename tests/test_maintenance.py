"""Maintenance parser, persistence and real isolated HTTP boundaries; synthetic data only."""

import asyncio
import json
import os

import aiohttp
import pytest
from aiohttp import web

from custom_components.adria_mach.client import MachClient
from custom_components.adria_mach.client import firmware as fw
from custom_components.adria_mach.client import restart as reboot
from custom_components.adria_mach.client.control_model import ControlError
from custom_components.adria_mach.client.journal import Journal
from custom_components.adria_mach.client.model import MachError
from custom_components.adria_mach.client.restart_store import RestartStore

RID = "a" * 32


def test_numeric_versions_direct_array_and_no_downgrade():
    info = fw.parse_updates(
        [
            {"version": "1.9.0", "releaseNotes": {"en": "Older"}},
            {"version": "1.10.0 build-1", "releaseNotes": {"fi": "Uusi", "en": "New"}},
        ],
        "1.8.0",
        "fi",
    )
    assert info.latest == "1.10.0 build-1" and info.notes == "Uusi"
    assert fw.parse_updates([], "2.0.0").latest == "2.0.0"
    assert fw.parse_updates([{"version": "1.9.0"}], "2.0.0").latest == "2.0.0"


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"updates": []},
        [None],
        [{}],
        [{"version": "1.2"}],
        [{"version": "bad"}],
        [{"version": True}],
        [{"version": "1.2.3", "releaseNotes": "bad"}],
    ],
)
def test_invalid_updates_are_unknown(data):
    with pytest.raises(MachError):
        fw.parse_updates(data, "1.0.0")


def test_restart_history_is_separate_retained_and_no_reload_replay(tmp_path):
    with Journal(tmp_path) as journal:
        store = RestartStore(journal)
        store.load()
        assert not store.unresolved
        store.append("requested", RID)
        store.append("unknown", RID)
        prior = list(store.events)
        reopened = RestartStore(journal)
        reopened.load()
        assert reopened.unresolved and reopened.events == prior
        reopened.append("owner_acknowledged", RID)
        assert not reopened.unresolved and reopened.events[:2] == prior
        assert not (tmp_path / "state.json").exists()
        assert os.stat(store.path).st_mode & 0o777 == 0o600


@pytest.mark.parametrize("kind", ["insecure", "symlink", "corrupt", "version", "sequence"])
def test_restart_store_fails_closed(tmp_path, kind):
    with Journal(tmp_path) as journal:
        path = tmp_path / "restart.json"
        path.write_text(json.dumps({"version": 1, "events": []}))
        path.chmod(0o600)
        if kind == "insecure":
            path.chmod(0o644)
        elif kind == "symlink":
            path.unlink()
            path.symlink_to(tmp_path / "absent")
        elif kind == "corrupt":
            path.write_text("bad")
        elif kind == "version":
            path.write_text('{"version":2,"events":[]}')
        else:
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "events": [
                            {
                                "id": RID,
                                "event": "owner_acknowledged",
                                "at": "2030-01-01T00:00:00+00:00",
                            }
                        ],
                    }
                )
            )
        store = RestartStore(journal)
        with pytest.raises((ControlError, ValueError)):
            store.load()
        assert store.unresolved


@pytest.mark.parametrize("operation", ["replace", "fsync"])
def test_restart_durability_failure_keeps_guard_and_old_history(tmp_path, monkeypatch, operation):
    with Journal(tmp_path) as journal:
        store = RestartStore(journal)
        store.load()
        store.append("requested", RID)
        before = store.path.read_bytes()

        def fail(*args):
            raise OSError("synthetic failure")

        monkeypatch.setattr(os, operation, fail)
        with pytest.raises(OSError):
            store.append("unknown", RID)
        assert store.unresolved and store.blocked and store.path.read_bytes() == before
        assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize(
    "mode", ["ok", "empty", "redirect", "malformed", "oversize", "duplicate", "drop", "auth"]
)
async def test_firmware_isolated_real_http(loopback, monkeypatch, mode):
    calls, redirected = [], []

    async def other(request):
        redirected.append(True)
        return web.json_response([])

    destination = await loopback(other)

    async def handler(request):
        calls.append(await request.json())
        assert not request.cookies
        assert all(
            k not in request.headers for k in ("Authorization", "Origin", "X-Requested-With")
        )
        if mode == "redirect":
            raise web.HTTPTemporaryRedirect(destination)
        if mode == "auth":
            return web.Response(status=401, text="synthetic-secret")
        if mode == "drop":
            request.transport.close()
            return web.Response()
        if mode == "oversize":
            return web.Response(body=b" " * (fw.MAX_BODY + 1))
        if mode == "duplicate":
            return web.Response(text='[{"version":"1.0.0","version":"2.0.0"}]')
        if mode == "malformed":
            return web.Response(text="synthetic-secret")
        return web.json_response([] if mode == "empty" else [{"version": "1.10.0"}])

    monkeypatch.setattr(fw, "UPDATES_URL", await loopback(handler))
    async with aiohttp.ClientSession() as shared:
        client = fw.FirmwareClient(connector=shared.connector)
        try:
            if mode in {"ok", "empty"}:
                result = await client.check("synthetic-a", "1.9.0", "PRODUCTION")
                assert result.latest == ("1.10.0" if mode == "ok" else "1.9.0")
            else:
                with pytest.raises(MachError) as caught:
                    await client.check("synthetic-a", "1.9.0", "PRODUCTION")
                assert "synthetic-secret" not in str(caught.value)
            with pytest.raises(MachError, match="firmware_check_deferred"):
                await client.check("synthetic-a", "1.9.0", "PRODUCTION")
        finally:
            await client.close()
        assert not shared.closed and not shared.connector.closed
    assert calls == [{"machId": "synthetic-a", "version": "1.9.0", "releaseType": "PRODUCTION"}]
    assert not redirected


@pytest.mark.parametrize("mode", ["ok", "drop", "redirect", "auth", "malformed", "cancel"])
async def test_restart_exact_single_request_and_durable_intent(
    loopback, monkeypatch, full_snapshot, tmp_path, mode
):
    from custom_components.adria_mach import client as portal
    from custom_components.adria_mach.client.model import Device

    writes, redirects = [], []
    ready, release = asyncio.Event(), asyncio.Event()

    async def other(request):
        redirects.append(True)
        return web.Response()

    destination = await loopback(other)

    async def handler(request):
        if request.path.endswith("events"):
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            await response.write(
                b'data: {"type":"bcknd-msg","payload":{"type":"mach-conn",'
                b'"payload":{"connected":true}}}\n\n'
            )
            await release.wait()
            return response
        body = await request.json()
        if request.path.endswith("initHandshake"):
            return web.json_response({"granted": True})
        method = body["payload"]["content"]["method"]
        if method != "reboot":
            return web.json_response(
                {
                    "status": 200,
                    "payload": full_snapshot[
                        "configuration" if method == "getMachConfiguration" else "values"
                    ],
                }
            )
        assert store.unresolved and store.events[-1]["event"] == "requested"
        writes.append(body)
        ready.set()
        if mode == "cancel":
            await release.wait()
        if mode == "drop":
            request.transport.close()
            return web.Response()
        if mode == "redirect":
            raise web.HTTPTemporaryRedirect(destination)
        if mode == "auth":
            return web.Response(status=401)
        if mode == "malformed":
            return web.Response(text="synthetic-secret")
        return web.json_response({"status": 200, "payload": {}})

    monkeypatch.setattr(portal, "BASE_URL", await loopback(handler))
    with Journal(tmp_path) as journal:
        store = RestartStore(journal)
        store.load()

        async def persist():
            store.append("requested", RID)

        from custom_components.adria_mach.client import commands, live

        monkeypatch.setattr(commands, "BASE_URL", portal.BASE_URL)
        monkeypatch.setattr(live, "BASE_URL", portal.BASE_URL)
        client = MachClient(persistent=True)
        client._devices = (Device("synthetic-a", "Synthetic"),)
        try:
            task = asyncio.create_task(
                reboot.restart(client, "synthetic-a", persist, lambda m: None)
            )
            await asyncio.wait_for(ready.wait(), 5)
            if mode == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            elif mode == "ok":
                assert await task == "accepted_unconfirmed"
            else:
                with pytest.raises(MachError):
                    await task
        finally:
            release.set()
            await client.close()
    assert writes == [
        {"type": "ui-req", "payload": {"type": "systemRequest", "content": {"method": "reboot"}}}
    ]
    assert not redirects
