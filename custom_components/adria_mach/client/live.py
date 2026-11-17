"""Owned HA event connection; value notifications invalidate verified snapshots."""

import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime

import aiohttp

from . import BASE_URL, READINESS_SECONDS, _check_status
from .catalog import FIELDS
from .control_model import CONTEXT_KEYS, Case, HeatingControl, ManualControl, WaterControl
from .health import ConnectionMetadata
from .master import MasterControl
from .model import AuthenticationError, MachError
from .operational import CURRENT_CONTROLS
from .outside import OutsideControl
from .position import POSITION_IDS
from .telemetry import DIAGNOSTIC_FIELDS

REFRESH_DELAY = 0.25
RECONNECT_DELAYS = (2, 4, 8, 16, 30)
WATCHDOG_SECONDS = 30
STREAM_IDLE_SECONDS = 600
KNOWN_IDS = (
    frozenset(FIELDS)
    | frozenset(DIAGNOSTIC_FIELDS)
    | POSITION_IDS
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
        self.state_listener = None
        self.metadata = ConnectionMetadata()
        self.watchdog = None
        self.recovery = None
        self.last_traffic_at = None
        self.last_traffic_monotonic = None
        self.recovery_attempts = 0
        self.recoveries = 0
        self.last_recovery_at = None
        self.last_recovery_reason = None
        self.last_error_code = None

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
            "last_stream_traffic_at": self.last_traffic_at.isoformat()
            if self.last_traffic_at
            else None,
            "stream_idle_seconds": self.idle_seconds,
            "stream_inactivity_budget_seconds": STREAM_IDLE_SECONDS,
            "recovery_attempts": self.recovery_attempts,
            "successful_recoveries": self.recoveries,
            "last_recovery_at": self.last_recovery_at,
            "last_recovery_reason": self.last_recovery_reason,
            "last_connection_error": self.last_error_code,
            **self.metadata.facts(),
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
        self.metadata = ConnectionMetadata()
        self.last_traffic_at = None
        self.last_traffic_monotonic = None
        self._notify()
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
                if self.watchdog is None:
                    self.watchdog = asyncio.create_task(self._watchdog())
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
                async for event in parser._events(
                    response.content, activity=lambda: self._activity(generation)
                ):
                    if generation != self.generation or self.closed:
                        return
                    before = self.metadata.facts()
                    self.metadata.observe(event)
                    if before != self.metadata.facts():
                        self._notify()
                    connected = parser._connection(event)
                    if connected is True:
                        self.status = "ready"
                        self.ready.set()
                        self.last_error_code = None
                        self._notify()
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
            self.last_error_code = "authentication_rejected"
        except Exception:
            self.error = MachError("stream_disconnected")
            self.status = "disconnected"
            self.last_error_code = "stream_disconnected"
        finally:
            if generation == self.generation:
                self.ready.clear()
                self.metadata = ConnectionMetadata()
                self._notify()
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

    @property
    def idle_seconds(self):
        if self.last_traffic_monotonic is None:
            return None
        return max(0, asyncio.get_running_loop().time() - self.last_traffic_monotonic)

    def _notify(self):
        if self.state_listener is not None and not self.closed:
            self.state_listener()

    def _activity(self, generation):
        if generation == self.generation and not self.closed:
            self.last_traffic_monotonic = asyncio.get_running_loop().time()
            self.last_traffic_at = datetime.now(UTC)

    @asynccontextmanager
    async def _unreserved(self):
        yield True

    async def _watchdog(self):
        try:
            while not self.closed:
                await asyncio.sleep(WATCHDOG_SECONDS)
                if (
                    self.ready.is_set()
                    and self.idle_seconds is not None
                    and (self.idle_seconds >= STREAM_IDLE_SECONDS)
                ):
                    self.recovery = asyncio.create_task(self._recover_idle(self.generation))
                    try:
                        await self.recovery
                    finally:
                        self.recovery = None
        finally:
            self.watchdog = None

    async def _recover_idle(self, generation):
        admission = self.client.recovery_admission
        async with admission() if admission is not None else self._unreserved() as admitted:
            if not admitted:
                return
            attempted = False
            try:
                async with asyncio.timeout(30), self.client._lock:
                    if (
                        self.closed
                        or generation != self.generation
                        or not self.ready.is_set()
                        or (self.idle_seconds is None or self.idle_seconds < STREAM_IDLE_SECONDS)
                    ):
                        return
                    self.client._network_gate()
                    attempted = True
                    self.recovery_attempts = min(1_000_000, self.recovery_attempts + 1)
                    self.last_recovery_reason = "stream_inactive"
                    self.last_recovery_at = datetime.now(UTC).isoformat()
                    self.status = "checking"
                    self._notify()
                    await self.disconnect()
                    measurement = await self.client._read_with_renewal_locked(self.device_id)
                    self.recoveries = min(1_000_000, self.recoveries + 1)
                    self.last_error_code = None
                    if self.listener is not None and not self.closed:
                        self.listener(measurement)
            except asyncio.CancelledError:
                raise
            except AuthenticationError:
                self.status = "authentication_required"
                self.last_error_code = "authentication_rejected"
                if self.error_listener is not None:
                    self.error_listener(AuthenticationError("authentication_rejected"))
            except (MachError, aiohttp.ClientError, TimeoutError):
                if not attempted and not self.client.rate_wait:
                    return
                limited = self.client.rate_wait > 0
                self.status = "rate_limited" if limited else "disconnected"
                self.last_error_code = "rate_limited" if limited else "recovery_failed"
            finally:
                self._notify()

    async def disconnect(self):
        self.generation += 1  # Fence old consumers before closing their response.
        self.metadata = ConnectionMetadata()
        self.ready.clear()
        self._notify()
        pump, self.pump = self.pump, None
        if pump is not None:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)

    async def close(self):
        self.closed = True
        self.status = "closed"
        tasks = [
            t
            for t in (self.maintenance, self.watchdog, self.recovery)
            if t is not None and t is not asyncio.current_task()
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.maintenance = self.watchdog = self.recovery = None
        await self.disconnect()
