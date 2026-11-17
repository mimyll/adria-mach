"""Bounded HTTPS portal reader and exact experimental command adapter."""

from __future__ import annotations

import asyncio
import json
import math
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import aiohttp

from .model import (
    AuthenticationError,
    Device,
    MachError,
    Measurement,
    assigned_devices,
    readings_from,
)

BASE_URL = "https://adria-mach.com"
MAX_BODY_BYTES = 1_048_576
MAX_EVENT_BYTES = 65_536
MAX_INITIAL_STREAM_BYTES = 262_144
READINESS_SECONDS = 15
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20, connect=10, sock_read=15)
STREAM_TIMEOUT = aiohttp.ClientTimeout(total=60, connect=10, sock_read=15)


def _check_status(status: int) -> None:
    if status in (401, 403):
        raise AuthenticationError("authentication_rejected")
    if 300 <= status < 400:
        raise MachError("redirect_rejected")
    if status == 429:
        raise MachError("rate_limited")
    if not 200 <= status < 300:
        raise MachError("http_failure")


class MachClient:
    """One isolated cookie session; a supplied HA connector remains HA-owned."""

    def __init__(self, connector: aiohttp.BaseConnector | None = None, *, persistent=False):
        self._session = aiohttp.ClientSession(
            connector=connector,
            connector_owner=connector is None,
            cookie_jar=aiohttp.CookieJar(),
            trust_env=False,
            timeout=REQUEST_TIMEOUT,
            headers={"X-Requested-With": "XMLHttpRequest", "Origin": BASE_URL},
        )
        self._devices: tuple[Device, ...] = ()
        self._lock = asyncio.Lock()
        self._rate_until = 0
        self._auth_required = False
        self._renewal_credentials = None
        self._renewal_device = None
        self._renewal_after = 0
        self._renewal_rejected = False
        self._closed = False
        self._auth_rejections = 0
        self._auth_rejection_status = None
        self._login_attempts = 0
        self._discoveries = 0
        self._renewals = 0
        self.live = None
        if persistent:
            from .live import LiveConnection

            self.live = LiveConnection(self)

    async def close(self) -> None:
        self._closed = True
        self._renewal_credentials = None
        if self.live:
            await self.live.close()
        async with self._lock:
            await self._session.close()

    def configure_session_renewal(self, device_id, credentials):
        """Obtain current HA-stored credentials on demand, never persist copies."""
        self._renewal_device = device_id
        self._renewal_credentials = credentials

    @property
    def rate_wait(self):
        return max(0, self._rate_until - asyncio.get_running_loop().time())

    def _network_gate(self):
        if self._closed:
            raise MachError("connection_closed")
        if self._auth_required:
            raise AuthenticationError("authentication_rejected")
        if self.rate_wait:
            raise MachError("rate_limited")

    def _response_gate(self, response):
        self._status_gate(response.status, response.headers.get("Retry-After", ""))

    def _status_gate(self, status, retry_after=""):
        if status in (401, 403):
            self._auth_required = True
            self._auth_rejections += 1
            self._auth_rejection_status = status
        if status == 429:
            raw = retry_after
            try:
                delay = (
                    float(raw)
                    if raw.isdigit()
                    else (parsedate_to_datetime(raw) - datetime.now(UTC)).total_seconds()
                )
            except (ValueError, TypeError, OverflowError):
                delay = 30
            if not math.isfinite(delay):
                delay = 30
            self._rate_until = max(
                self._rate_until, asyncio.get_running_loop().time() + max(0, delay)
            )

    @asynccontextmanager
    async def control_connection(self, device_id):
        if self.live is not None:
            await self.live.ensure(device_id)
            yield self.live
        else:
            from .commands import CommandStream
            from .control_model import ControlError

            handshake = await self._post("/api/control/initHandshake", {"machId": device_id})
            if not isinstance(handshake, dict) or handshake.get("granted") is not True:
                raise ControlError("handshake_rejected")
            stream = CommandStream(self)
            async with stream.connected():
                yield stream

    async def reset_connection(self):
        if self.live is not None:
            await self.live.disconnect()

    def _observed(self, configuration, values, device_id):
        from .position import Levelling

        if getattr(self, "_levelling_device", None) != device_id:
            self._levelling = Levelling()
            self._levelling_device = device_id
        measurement = self.measurement(
            configuration,
            values,
            device_id,
            getattr(self, "identified_equipment", ()),
            self._levelling,
        )
        if self.live is not None:
            self.live.record_values(values)
        return measurement

    async def authenticate(self, username: str, password: str) -> tuple[Device, ...]:
        """Log in freshly and retain only assigned, verified device identities."""
        if (
            not isinstance(username, str)
            or not username
            or not isinstance(password, str)
            or not password
        ):
            raise AuthenticationError("authentication_rejected")
        async with self._lock:
            devices = await self._authenticate_locked(username, password)
            self._renewal_rejected = False
            return devices

    async def _authenticate_locked(self, username, password):
        await self.reset_connection()
        self._auth_required = False
        self._devices = ()
        self._levelling_device = None
        self._session.cookie_jar.clear()
        self._login_attempts += 1
        await self._post(
            "/api/login/login",
            {"auth": {"username": username, "password": password}},
            empty=True,
        )
        self._devices = assigned_devices(await self._post("/api/user/listMyDevices", {}))
        self._discoveries += 1
        return self._devices

    async def _renew_session_locked(self, device_id):
        if (
            self._renewal_credentials is None
            or self._renewal_rejected
            or device_id != self._renewal_device
        ):
            raise AuthenticationError("authentication_rejected")
        now = asyncio.get_running_loop().time()
        if now < self._renewal_after or self.rate_wait:
            raise MachError("session_renewal_deferred")
        self._renewal_after = now + 60
        try:
            username, password = self._renewal_credentials()
            devices = await self._authenticate_locked(username, password)
            if device_id not in {device.id for device in devices}:
                raise AuthenticationError("device_not_assigned")
            self._renewals += 1
        except AuthenticationError:
            self._renewal_rejected = True
            self._auth_required = True
            raise
        except BaseException:
            # A partial login/discovery is not a usable session, including cancellation.
            self._auth_required = True
            raise

    async def read(self, device_id: str) -> Measurement:
        """Renew expired sessions once, retrying only this complete read."""
        async with self._lock:
            return await self._read_with_renewal_locked(device_id)

    async def _read_with_renewal_locked(self, device_id):
        if self._renewal_rejected:
            raise AuthenticationError("authentication_rejected")
        try:
            return await self._read_locked(device_id)
        except AuthenticationError:
            await self._renew_session_locked(device_id)
            try:
                return await self._read_locked(device_id)
            except AuthenticationError:
                self._renewal_rejected = True
                raise

    async def test_session_renewal(self, device_id, report):
        """Discard only owned cookies, then exercise the ordinary recovery path."""
        async with self._lock:
            self._network_gate()
            if (
                self.live is None
                or self._renewal_credentials is None
                or self._renewal_rejected
                or device_id != self._renewal_device
                or asyncio.get_running_loop().time() < self._renewal_after
            ):
                raise MachError("session_test_not_ready")
            # No automatic login in the baseline: start only from a healthy session.
            await self._read_locked(device_id)
            report["baseline_read_completed"] = True
            before = (
                self._auth_rejections,
                self._login_attempts,
                self._discoveries,
                self._renewals,
            )
            await self.reset_connection()
            self._session.cookie_jar.clear()
            report["owned_cookies_cleared"] = True
            try:
                measurement = await self._read_with_renewal_locked(device_id)
            finally:
                rejections, logins, discoveries, renewals = before
                rejected = self._auth_rejections > rejections
                report.update(
                    authentication_rejection_observed=rejected,
                    authentication_rejection_status=self._auth_rejection_status
                    if rejected
                    else None,
                    automatic_login_attempts=self._login_attempts - logins,
                    device_discoveries=self._discoveries - discoveries,
                    automatic_renewals=self._renewals - renewals,
                )
            report.update(
                configured_vehicle_verified=True,
                fresh_read_completed=True,
                received_at=measurement.received_at.isoformat(),
            )
            return measurement

    async def _read_locked(self, device_id):
        self._network_gate()
        if device_id not in {device.id for device in self._devices}:
            raise MachError("device_not_assigned")
        if self.live is not None:
            async with self.control_connection(device_id) as stream:
                configuration = await self._device_read("getMachConfiguration")
                if not isinstance(configuration, dict) or configuration.get("machId") != device_id:
                    raise MachError("vehicle_identity_mismatch")
                values = await self._device_read("getValuesAll")
                stream.ensure_connected()
                return self._observed(configuration, values, device_id)
        handshake = await self._post("/api/control/initHandshake", {"machId": device_id})
        if not isinstance(handshake, dict) or handshake.get("granted") is not True:
            raise MachError("handshake_rejected")
        async with self._connected_events():
            configuration = await self._device_read("getMachConfiguration")
            if not isinstance(configuration, dict) or configuration.get("machId") != device_id:
                raise MachError("vehicle_identity_mismatch")
            values = await self._device_read("getValuesAll")
        return self._observed(configuration, values, device_id)

    @staticmethod
    def measurement(configuration, values, device_id, identified_equipment=(), levelling=None):
        from .control_model import (
            OFF_LEVEL,
            Case,
            ControlError,
            HeatingControl,
            ManualControl,
            WaterControl,
            snapshot,
        )
        from .master import MasterControl
        from .operational import CURRENT_CONTROLS, equipment_snapshot
        from .outside import OutsideControl
        from .position import location_from
        from .vehicle import vehicle_from

        controls = {}
        readings = readings_from(configuration, values, levelling)
        location = location_from(configuration, values)
        for case in Case:
            try:
                controls[case.value] = snapshot(
                    configuration, values, device_id, case, asyncio.get_running_loop().time()
                )
                if case.individual_light:
                    readings[case.key] = controls[case.value].observed[case.key] != OFF_LEVEL
            except ControlError:
                pass  # An unsupported control must not remove supported monitoring.
        for control in ManualControl:
            if control.legacy_case.value in controls:
                controls[control.value] = controls[control.legacy_case.value]
        for control in (*OutsideControl, *MasterControl):
            try:
                controls[control.value] = snapshot(
                    configuration, values, device_id, control, asyncio.get_running_loop().time()
                )
            except ControlError:
                pass
        try:
            controls[WaterControl.MODE.value] = snapshot(
                configuration,
                values,
                device_id,
                WaterControl.MODE,
                asyncio.get_running_loop().time(),
            )
        except ControlError:
            pass
        try:
            controls[HeatingControl.MODE.value] = snapshot(
                configuration,
                values,
                device_id,
                HeatingControl.MODE,
                asyncio.get_running_loop().time(),
            )
        except ControlError:
            pass
        from .capabilities import inventory

        for control in CURRENT_CONTROLS:
            try:
                controls[control.value] = equipment_snapshot(
                    configuration, values, device_id, control, asyncio.get_running_loop().time()
                )
            except ControlError:
                pass

        return Measurement(
            readings,
            datetime.now(UTC),
            controls,
            inventory(
                configuration,
                values,
                readings,
                controls,
                identified_equipment,
                location_available=location is not None,
            ),
            location,
            vehicle_from(configuration),
        )

    async def command(
        self,
        device_id,
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
        from .commands import execute

        return await execute(
            self,
            device_id,
            case,
            target,
            restore,
            persist,
            progress,
            publish,
            expected_context,
            climate=climate,
            resume=resume,
            unsent_deadline=unsent_deadline,
        )

    async def _device_read(self, method: str) -> Any:
        # Internal fixed allowlist prevents a future caller from turning this into a write.
        if method not in ("getMachConfiguration", "getValuesAll"):
            raise MachError("operation_rejected")
        result = await self._post(
            "/api/control/req",
            {"type": "ui-req", "payload": {"type": "device", "content": {"method": method}}},
        )
        if not isinstance(result, dict) or type(result.get("status")) is not int:
            raise MachError("invalid_response")
        self._status_gate(result["status"])
        _check_status(result["status"])
        return result.get("payload")

    async def _post(self, path: str, body: dict[str, Any], *, empty: bool = False) -> Any:
        self._network_gate()
        try:
            async with self._session.post(
                BASE_URL + path, json=body, allow_redirects=False
            ) as response:
                self._response_gate(response)
                _check_status(response.status)
                data = bytearray()
                async for chunk in response.content.iter_chunked(16384):
                    if len(data) + len(chunk) > MAX_BODY_BYTES:
                        raise MachError("body_too_large")
                    data.extend(chunk)
                if empty and not data.strip():
                    return None
                try:
                    return json.loads(data)
                except (ValueError, UnicodeError, RecursionError):
                    raise MachError("invalid_json") from None
        except (aiohttp.ClientError, TimeoutError):
            raise MachError("transport_failure") from None

    @asynccontextmanager
    async def _connected_events(self):
        try:
            async with self._session.get(
                BASE_URL + "/api/control/events",
                headers={"Accept": "text/event-stream"},
                timeout=STREAM_TIMEOUT,
                allow_redirects=False,
            ) as response:
                _check_status(response.status)
                if response.content_type != "text/event-stream":
                    raise MachError("invalid_event_stream")
                async with asyncio.timeout(READINESS_SECONDS):
                    await wait_connected(response.content)
                yield
        except (aiohttp.ClientError, TimeoutError):
            raise MachError("transport_failure") from None


def _is_connected(data: bytes) -> bool:
    try:
        event = json.loads(data)
    except (ValueError, UnicodeError, RecursionError):
        raise MachError("invalid_event") from None
    if not isinstance(event, dict) or event.get("type") != "bcknd-msg":
        return False
    payload = event.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "mach-conn":
        return False
    detail = payload.get("payload")
    return isinstance(detail, dict) and detail.get("connected") is True


async def wait_connected(content) -> None:
    """Initial SSE framing only; no background subscription or push claim."""
    pending = bytearray()
    fields = []
    event_bytes = total = 0
    async for chunk in content.iter_chunked(4096):
        total += len(chunk)
        if total > MAX_INITIAL_STREAM_BYTES:
            raise MachError("initial_stream_too_large")
        pending.extend(chunk)
        while b"\n" in pending:
            line, _, pending = pending.partition(b"\n")
            event_bytes += len(line) + 1
            if event_bytes > MAX_EVENT_BYTES:
                raise MachError("event_too_large")
            line = line.removesuffix(b"\r")
            if not line:
                if fields and _is_connected(b"\n".join(fields)):
                    return
                fields = []
                event_bytes = 0
            elif line.startswith(b"data:"):
                fields.append(bytes(line[5:].removeprefix(b" ")))
        if event_bytes + len(pending) > MAX_EVENT_BYTES:
            raise MachError("event_too_large")
    raise MachError("device_not_connected")
