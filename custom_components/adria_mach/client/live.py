"""Owned HA event connection; value notifications invalidate verified snapshots."""

import asyncio
from contextlib import suppress

import aiohttp

from . import BASE_URL, READINESS_SECONDS, _check_status
from .catalog import FIELDS
from .control_model import CONTEXT_KEYS, Case, HeatingControl, ManualControl, WaterControl
from .master import MasterControl
from .model import AuthenticationError, MachError
from .operational import CURRENT_CONTROLS
from .outside import OutsideControl

REFRESH_DELAY = 0.25
RECONNECT_DELAYS = (2, 4, 8, 16, 30)
KNOWN_IDS = (
    frozenset(FIELDS)
    | frozenset(CONTEXT_KEYS)
    | {
        c.key
        for c in (
            *Case,
            *ManualControl,
            *HeatingControl,
            *WaterControl,
            *OutsideControl,
            *MasterControl,
            *CURRENT_CONTROLS,
        )
    }
)


class LiveConnection:
    def __init__(self, client):
        self.client = client
        self.device_id = None
        self.pump = None
        self.maintenance = None
        self.ready = asyncio.Event()
        self.dirty = asyncio.Event()
        self.closed = False
        self.generation = 0
        self.invalidations = 0
        self.refreshes = 0
        self.handshakes = 0
        self.status = "disconnected"
        self.error = None
        self.values = {}
        self.listener = None
        self.error_listener = None

    def facts(self):
        return {
            "connection_state": self.status,
            "connection_generation": self.generation,
            "connection_ready": self.ready.is_set()
            and self.pump is not None
            and not self.pump.done(),
            "connection_handshakes": self.handshakes,
            "value_notifications": self.invalidations,
            "event_refreshes": self.refreshes,
        }

    async def ensure(self, device_id):
        """Called only while the client's RPC lock is held."""
        if self.closed:
            raise MachError("connection_closed")
        self.client._network_gate()
        if self.device_id not in (None, device_id):
            raise MachError("vehicle_identity_mismatch")
        self.device_id = device_id
        if self.ready.is_set() and self.pump and not self.pump.done():
            return
        await self.disconnect()
        self.status = "connecting"
        result = await self.client._post("/api/control/initHandshake", {"machId": device_id})
        if not isinstance(result, dict) or result.get("granted") is not True:
            raise MachError("handshake_rejected")
        self.handshakes = min(1_000_000, self.handshakes + 1)
        self.generation += 1
        self.error = None
        self.pump = asyncio.create_task(self._listen(self.generation))
        waiter = asyncio.create_task(self.ready.wait())
        try:
            async with asyncio.timeout(READINESS_SECONDS):
                await asyncio.wait((self.pump, waiter), return_when=asyncio.FIRST_COMPLETED)
                self.ensure_connected()
        except BaseException:
            await self.disconnect()
            raise
        finally:
            waiter.cancel()
            with suppress(asyncio.CancelledError):
                await waiter

    def ensure_connected(self):
        if not self.ready.is_set() or self.pump is None or self.pump.done():
            if isinstance(self.error, AuthenticationError):
                raise AuthenticationError("authentication_rejected")
            raise MachError("stream_not_connected")

    async def _listen(self, generation):
        from .commands import CommandStream

        try:
            self.client._network_gate()
            async with self.client._session.get(
                BASE_URL + "/api/control/events",
                allow_redirects=False,
                headers={"Accept": "text/event-stream"},
                timeout=aiohttp.ClientTimeout(total=None, connect=10, sock_read=None),
            ) as response:
                self.client._response_gate(response)
                _check_status(response.status)
                if response.content_type != "text/event-stream":
                    raise MachError("invalid_event_stream")
                parser = CommandStream(self.client)
                async for event in parser._events(response.content):
                    if generation != self.generation or self.closed:
                        return
                    connected = parser._connection(event)
                    if connected is True:
                        self.status = "ready"
                        self.ready.set()
                    elif connected is False and self.ready.is_set():
                        raise MachError("stream_disconnected")
                    elif self.ready.is_set():
                        self._invalidate(event)
                raise MachError("stream_disconnected")
        except asyncio.CancelledError:
            raise
        except AuthenticationError as error:
            self.error = error
            self.status = "authentication_required"
        except Exception:
            self.error = MachError("stream_disconnected")
            self.status = "disconnected"
        finally:
            if generation == self.generation:
                self.ready.clear()
                if not self.closed:
                    self.dirty.set()
                    self._schedule()

    def _invalidate(self, event):
        if not isinstance(event, dict) or event.get("type") != "mach-msg":
            return
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "values":
            return
        rows = payload.get("values")
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = row.get("device")
            value = row.get("status")
            if not isinstance(key, str):
                key, value = row.get("valueId"), row.get("value")
            if (
                isinstance(key, str)
                and key in KNOWN_IDS
                and (
                    key not in self.values
                    or type(value) is not type(self.values[key])
                    or value != self.values[key]
                )
            ):
                self.invalidations = min(1_000_000, self.invalidations + 1)
                self.dirty.set()
                self._schedule()
                return

    def record_values(self, values):
        self.values = {
            r["device"]: r.get("status")
            for r in values.get("values", [])
            if isinstance(r, dict) and isinstance(r.get("device"), str) and r["device"] in KNOWN_IDS
        }

    def _schedule(self):
        if self.listener is not None and not self.closed and self.maintenance is None:
            self.maintenance = asyncio.create_task(self._refresh())

    async def _refresh(self):
        failures = 0
        try:
            while self.dirty.is_set() and not self.closed:
                self.dirty.clear()
                if failures >= len(RECONNECT_DELAYS):
                    break
                if not self.ready.is_set() or failures:
                    delay = max(RECONNECT_DELAYS[failures], self.client.rate_wait)
                    self.status = "reconnecting"
                    await asyncio.sleep(delay)
                else:
                    await asyncio.sleep(REFRESH_DELAY)
                version = self.invalidations
                try:
                    async with asyncio.timeout(30):
                        measurement = await self.client.read(self.device_id)
                    self.status = "ready"
                    self.refreshes = min(1_000_000, self.refreshes + 1)
                    failures = 0
                    if self.listener is not None and not self.closed:
                        self.listener(measurement)
                    if version != self.invalidations:
                        self.dirty.set()
                except AuthenticationError:
                    self.status = "authentication_required"
                    if self.error_listener:
                        self.error_listener(AuthenticationError("authentication_rejected"))
                    break
                except (MachError, aiohttp.ClientError, TimeoutError):
                    failures += 1
                    self.dirty.set()
        finally:
            self.maintenance = None

    async def disconnect(self):
        self.generation += 1  # Fence old consumers before closing their response.
        self.ready.clear()
        pump, self.pump = self.pump, None
        if pump is not None:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)

    async def close(self):
        self.closed = True
        self.status = "closed"
        if self.maintenance is not None:
            self.maintenance.cancel()
            await asyncio.gather(self.maintenance, return_exceptions=True)
        await self.disconnect()
