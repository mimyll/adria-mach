"""Serialized exact commands with initial readiness and bounded service readback."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager, suppress

import aiohttp

from . import BASE_URL, MAX_BODY_BYTES, MAX_EVENT_BYTES, MAX_INITIAL_STREAM_BYTES
from .ack import empty_facts, inspect_ack
from .control_model import (
    OFF_LEVEL,
    Case,
    ControlError,
    HeatingControl,
    ManualControl,
    WaterControl,
    command,
    manual_command,
    validate_manual,
)
from .journal import manual_light
from .master import MasterControl
from .model import MachError
from .operational import AcControl, EquipmentControl
from .outside import OutsideControl


class CommandStream:
    def __init__(self, client):
        self.client = client
        self._monitor = None

    @asynccontextmanager
    async def connected(self):
        async with self.client._session.get(
            BASE_URL + "/api/control/events",
            allow_redirects=False,
            headers={"Accept": "text/event-stream"},
            timeout=aiohttp.ClientTimeout(total=180, connect=10, sock_read=70),
        ) as response:
            if response.status != 200 or response.content_type != "text/event-stream":
                raise ControlError("stream_rejected")
            events = self._events(response.content)
            async with asyncio.timeout(15):
                async for event in events:
                    if self._connection(event) is True:
                        break
                else:
                    raise ControlError("stream_not_connected")
            self._monitor = asyncio.create_task(self._watch(events))
            try:
                yield
            finally:
                self._monitor.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await self._monitor
                await events.aclose()
                self._monitor = None

    @staticmethod
    def _connection(event):
        if isinstance(event, dict) and event.get("type") == "bcknd-msg":
            payload = event.get("payload")
            if isinstance(payload, dict) and payload.get("type") == "mach-conn":
                detail = payload.get("payload")
                if isinstance(detail, dict) and type(detail.get("connected")) is bool:
                    return detail["connected"]
        return None

    async def _watch(self, events):
        async for event in events:
            if self._connection(event) is False:
                raise ControlError("stream_disconnected")
        raise ControlError("stream_disconnected")

    async def _events(self, content):
        pending = bytearray()
        fields = []
        size = 0
        initial_bytes = 0
        ready = False
        async for chunk in content.iter_chunked(4096):
            initial_bytes += len(chunk)
            if not ready and initial_bytes > MAX_INITIAL_STREAM_BYTES:
                raise ControlError("stream_failure")
            pending.extend(chunk)
            while b"\n" in pending:
                line, _, pending = pending.partition(b"\n")
                size += len(line) + 1
                if size > MAX_EVENT_BYTES:
                    raise ControlError("stream_failure")
                line = line.removesuffix(b"\r")
                if not line:
                    if fields:
                        try:
                            event = json.loads(b"\n".join(fields))
                            ready = ready or self._connection(event) is True
                            yield event
                        except (ValueError, RecursionError):
                            raise ControlError("stream_failure") from None
                    fields, size = [], 0
                elif line.startswith(b"data:"):
                    fields.append(bytes(line[5:].removeprefix(b" ")))
            if size + len(pending) > MAX_EVENT_BYTES:
                raise ControlError("stream_failure")

    def ensure_connected(self):
        if self._monitor is None or self._monitor.done():
            raise ControlError("stream_not_connected")


READ_SPACING = 15
WRITE_SECONDS = 20


async def _read(client, device_id, case):
    configuration = await client._device_read("getMachConfiguration")
    if not isinstance(configuration, dict) or configuration.get("machId") != device_id:
        raise ControlError("vehicle_identity_mismatch")
    values = await client._device_read("getValuesAll")
    measurement = client._observed(configuration, values, device_id)
    current = measurement.control_snapshots.get(case.value)
    if current is None:
        raise ControlError("unsupported_command_definition")
    return measurement, current


async def _write(client, envelope, report=None):
    """One POST, no redirects/retry; export only bounded technical fields."""
    now = asyncio.get_running_loop().time
    started = now()
    ack = {
        "http_status": None,
        "application_status": None,
        "positive_candidate": False,
        "diagnostics": empty_facts(),
    }
    try:
        client._network_gate()
        async with (
            asyncio.timeout(WRITE_SECONDS),
            client._session.post(
                BASE_URL + "/api/control/req", json=envelope, allow_redirects=False
            ) as response,
        ):
            client._response_gate(response)
            ack["http_status"] = response.status
            if not 200 <= response.status < 300:
                ack["diagnostics"] = empty_facts("http_error")
                return ack
            data = bytearray()
            async for chunk in response.content.iter_chunked(16384):
                if len(data) + len(chunk) > MAX_BODY_BYTES:
                    ack["diagnostics"] = empty_facts("body_too_large")
                    raise ControlError("body_too_large")
                data.extend(chunk)
            legacy, app, facts = inspect_ack(data)
            client._status_gate(app)
            ack.update(positive_candidate=legacy, application_status=app, diagnostics=facts)
        return ack
    except asyncio.CancelledError:
        ack["diagnostics"] = empty_facts("cancelled")
        raise
    except TimeoutError:
        ack["diagnostics"] = empty_facts("response_timeout")
        raise
    except aiohttp.ClientError:
        ack["diagnostics"] = empty_facts("transport_failure")
        raise
    finally:
        ack["diagnostics"]["elapsed_ms"] = min(1_000_000, round((now() - started) * 1000))
        if report:
            report(ack)


async def execute(
    client,
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
    """One owner request, including a fresh baseline; never send an inverse automatically."""
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
    action = isinstance(case, EquipmentControl) and case.action
    if (resume is not None or unsent_deadline is not None) and not manual:
        raise ControlError("command_rejected")
    if type(climate) is not bool or (climate and case is not ManualControl.HEATER):
        raise ControlError("command_rejected")
    if type(restore) is not bool or not isinstance(
        case,
        (
            Case,
            ManualControl,
            WaterControl,
            HeatingControl,
            OutsideControl,
            EquipmentControl,
            AcControl,
            MasterControl,
        ),
    ):
        raise ControlError("command_rejected")
    if manual:
        if restore:
            raise ControlError("command_rejected")
        validate_manual(case, target, allow_default_on=True)
    elif type(target) is not type(case.target) or target not in (case.baseline, case.target):
        raise ControlError("command_rejected")
    async with (
        asyncio.timeout_at(unsent_deadline) as admission_timeout,
        asyncio.timeout_at(unsent_deadline)
        if manual and unsent_deadline is not None
        else asyncio.timeout(120 if manual else None),
        client._lock,
        asyncio.timeout(None if manual else 150),
    ):
        if device_id not in {d.id for d in client._devices}:
            raise ControlError("device_not_assigned")
        async with client.control_connection(device_id) as stream:
            measurement, baseline = await _read(client, device_id, case)
            climate_context = None
            if climate:
                # Native thermostat adds its context gate; the old Number contract stays intact.
                if HeatingControl.MODE.value not in measurement.control_snapshots:
                    raise ControlError("unsupported_heater_mode")
                climate_context = {
                    k: v
                    for k, v in measurement.control_snapshots[
                        HeatingControl.MODE.value
                    ].context.items()
                    if k != case.key
                }
            stream.ensure_connected()
            publish(measurement)
            if resume is not None:
                await resume()
            if expected_context is not None and baseline.context != expected_context:
                raise ControlError("context_changed")
            if manual and target is None:
                current = baseline.observed[case.key]
                target = 50 if current == OFF_LEVEL else current
            if (
                isinstance(case, (EquipmentControl, AcControl))
                and case.choices
                and target not in baseline.choices
            ):
                raise ControlError("invalid_control_value")
            if (
                not action
                and not isinstance(case, MasterControl)
                and baseline.observed[case.key] == target
            ):
                progress("unchanged", None)
                return measurement, False
            if manual:
                validate_manual(case, target)
                envelope = manual_command(case, target)
            else:
                expected = case.target if restore else case.baseline
                intended = case.baseline if restore else case.target
                if baseline.observed[case.key] != expected or target != intended:
                    raise ControlError("baseline_mismatch")
                envelope = command(case, restore=restore)
            now = asyncio.get_running_loop().time
            if now() - baseline.monotonic_at >= 30:
                raise ControlError("baseline_expired")
            await persist(case, target if manual else restore)
            if now() - baseline.monotonic_at >= 30:
                raise ControlError("baseline_expired")
            stream.ensure_connected()
            if unsent_deadline is not None and now() >= unsent_deadline:
                raise ControlError("baseline_expired")
            admission_timeout.reschedule(None)
            started = now()
            deadline = started + case.seconds
            progress("requested", None)
            ack = await _write(client, envelope, lambda facts: progress("requested", facts))
            stream.ensure_connected()
            progress("candidate_positive" if ack["positive_candidate"] else "unknown", ack)
            if not ack["positive_candidate"]:
                if (
                    manual_light(case)
                    and ack["http_status"] not in (401, 403, 429)
                    and ack["application_status"] not in (401, 403, 429)
                ):
                    # A negative ACK can still have changed the reported setting.
                    # Observe once within the original budget; never settle/retry the write.
                    with suppress(MachError, aiohttp.ClientError, TimeoutError):
                        async with asyncio.timeout(max(0, deadline - now())):
                            measurement, _ = await _read(client, device_id, case)
                            publish(measurement)
                raise ControlError("acknowledgement_unknown")
            if action:
                # The service acknowledges a keyword, not memory persistence/light effects.
                progress("acknowledged_unconfirmed", ack)
                return measurement, True
            previous = None
            for _ in range(2):
                if previous is not None:
                    await asyncio.sleep(max(0, previous + READ_SPACING - now()))
                if now() >= deadline:
                    raise ControlError("confirmation_expired")
                previous = now()
                async with asyncio.timeout(deadline - now()):
                    measurement, observed = await _read(client, device_id, case)
                stream.ensure_connected()
                publish(measurement)
                if climate_context is not None:
                    heating = measurement.control_snapshots.get(HeatingControl.MODE.value)
                    if (
                        heating is None
                        or {k: v for k, v in heating.context.items() if k != case.key}
                        != climate_context
                    ):
                        raise ControlError("context_changed")
                if not started < observed.monotonic_at <= now() or now() >= deadline:
                    raise ControlError("stale_readback")
                if observed.context != baseline.context:
                    raise ControlError("context_changed")
                if observed.observed[case.key] == target:
                    progress("service_observed", ack)
                    return measurement, True
            raise ControlError("confirmation_missing")
