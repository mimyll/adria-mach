"""Shared ownership of bounded manual control cases; no physical-effect claim."""

import asyncio
from functools import partial
from pathlib import Path

from homeassistant.exceptions import HomeAssistantError

from .client.control_model import Case, ControlError, validate_manual
from .client.journal import Journal, manual_light
from .client.light_queue import LightQueue
from .client.operational import AcControl, EquipmentControl
from .const import DOMAIN


class CommandManager:
    def __init__(self, hass, coordinator, entry):
        self.hass, self.coordinator = hass, coordinator
        self.directory = Path(hass.config.path("adria_mach_commands_" + entry.entry_id))
        self.journal = None
        self.io_jobs = set()
        self.task = None
        self.probe_task = None
        self.session_test = False
        self.cleanup_task = None
        self.closed = False
        self.blocked = False
        self.restart_unresolved = False
        self.forward_observed = set()
        self.forward_context = {}
        self.status = "idle"
        self.last_requested = None
        self.last_case = None
        self.ack = None
        self.last_duration_ms = None
        self.feedback = {}
        self.request_sequence = 0
        # Keep the historical attribute for probe/unload callers; this is now the one manual queue.
        self.lights = LightQueue(self._queued_light, self.notify, coalesce=manual_light)

    def start_io(self, function, *args, **kwargs):
        future = self.hass.async_add_executor_job(partial(function, *args, **kwargs))
        self.io_jobs.add(future)

        def done(job):
            self.io_jobs.discard(job)
            if not job.cancelled():
                job.exception()  # Retrieve late IO failure even if the caller was cancelled.

        future.add_done_callback(done)
        return future

    async def io(self, function, *args, **kwargs):
        return await asyncio.shield(self.start_io(function, *args, **kwargs))

    async def setup(self):
        self.journal = Journal(self.directory, allow_light_resume=True, allow_manual_resume=True)
        try:
            await self.io(self.journal.__enter__)
            if self.journal.state["pending"]:
                self.blocked, self.status = True, "unknown"
        except Exception:
            self.blocked, self.status = True, "unknown"

    @property
    def restoration_required(self):
        pending = self.journal.state.get("pending") if self.journal and self.journal.state else None
        return bool(
            not self.blocked
            and pending
            and pending.get("phase") == "forward"
            and pending.get("attempt") == self.journal.attempt
            and pending.get("case") in self.forward_observed
        )

    @property
    def attributes(self):
        completed = self.journal.state.get("completed", []) if self.journal.state else []
        return {
            "command_outcome": self.status,
            "last_requested_value": self.last_requested,
            "last_requested_control": self.last_case,
            "application_positive_candidate": self.ack.get("positive_candidate")
            if self.ack
            else None,
            "http_status": self.ack.get("http_status") if self.ack else None,
            "application_status": self.ack.get("application_status") if self.ack else None,
            "controls_blocked": self.restart_unresolved
            or (self.blocked and not self.can_resynchronize)
            or self.restoration_required,
            "control_lock_reason": "restart_unresolved"
            if self.restart_unresolved
            else "fresh_manual_resync_required"
            if self.blocked and self.can_resynchronize
            else "uncertain_or_storage"
            if self.blocked
            else "legacy_restoration_required"
            if self.restoration_required
            else "command_in_progress"
            if self.task
            else "none",
            "completed_test_cases": list(completed),
            "physical_confirmation": "not_recorded",
            "acknowledgement_policy": "proposed_not_service_verified",
            "last_command_duration_ms": self.last_duration_ms,
            "pending_light_requests": sum(manual_light(s.control) for s in self.lights.pending),
            "pending_control_requests": len(self.lights.pending),
            "unknown_light_history_count": len(
                (self.journal.state or {}).get("unknown_light_archives", [])
            ),
            "unknown_manual_history_count": len(
                (self.journal.state or {}).get("unknown_manual_archives", [])
            ),
            "previous_command_unknown": self.historical_unknown or self.journal.resumable_manual,
        }

    @property
    def thermal_hold(self):
        return False  # Retained uncertainty is history, not a permanent actuator dependency.

    @property
    def historical_unknown(self):
        return bool(
            self.journal
            and self.journal.state
            and (
                self.journal.state.get("unknown_light_archives")
                or self.journal.state.get("unknown_manual_archives")
            )
        )

    @property
    def can_resynchronize(self):
        return bool(
            not self.restart_unresolved
            and self.journal
            and (
                self.journal.resumable_manual
                or (
                    self.historical_unknown
                    and not self.journal.blocked
                    and self.journal.fd is not None
                    and self.journal.state["pending"] is None
                )
            )
        )

    @property
    def light_attributes(self):
        recoverable = self.can_resynchronize
        return {
            **self.attributes,
            "controls_blocked": self.restart_unresolved
            or self.closed
            or self.restoration_required
            or (self.blocked and not recoverable),
            "control_lock_reason": "restart_unresolved"
            if self.restart_unresolved
            else "fresh_light_resync_required"
            if recoverable
            else ("uncertain_or_storage" if self.blocked else "none"),
            "previous_command_unknown": recoverable or self.historical_unknown,
        }

    def notify(self):
        self.coordinator.async_update_listeners()

    def pending_for(self, *controls):
        """Latest admitted intent; rejected/cancelled feedback is not queue ownership."""
        keys = {c if isinstance(c, str) else c.key for c in controls if c is not None}
        slots = [*self.lights.pending]
        if self.lights.active is not None:
            slots.append(self.lights.active)
        return max(
            (slot for slot in slots if slot.control.key in keys),
            key=lambda slot: slot.target[2],
            default=None,
        )

    def attributes_for(self, *controls):
        keys = {c if isinstance(c, str) else c.key for c in controls if c is not None}
        record = max(
            (self.feedback[k] for k in keys if k in self.feedback),
            key=lambda row: row["token"],
            default={},
        )
        active = self.lights.active
        queued = [slot for slot in self.lights.pending if slot.control.key in keys]
        pending = self.pending_for(*controls)
        facts = {
            **self.attributes,
            "command_outcome": record.get("outcome", "idle"),
            "last_requested_value": record.get("target"),
            "last_requested_control": record.get("control"),
            "last_command_duration_ms": record.get("duration_ms"),
            "http_status": record.get("http_status"),
            "application_status": record.get("application_status"),
            "application_positive_candidate": record.get("positive_candidate"),
            "command_in_progress": bool(active and active.control.key in keys),
            "queued_requests": len(queued),
            "request_pending": pending is not None,
            "pending_target": ("on" if pending.target[0] is None else pending.target[0])
            if pending is not None
            else None,
            "controls_blocked": self.restart_unresolved
            or self.closed
            or self.restoration_required
            or (self.blocked and not self.can_resynchronize),
            "control_lock_reason": "restart_unresolved"
            if self.restart_unresolved
            else "uncertain_or_storage"
            if self.blocked and not self.can_resynchronize
            else "legacy_restoration_required"
            if self.restoration_required
            else "fresh_manual_resync_required"
            if self.blocked
            else "none",
        }
        live = getattr(self.coordinator.client, "live", None)
        if live is not None:
            facts.update(live.facts())
        return facts

    def _feedback(self, control, token, **values):
        row = self.feedback.get(control.key)
        if row is not None and row["token"] == token:
            row.update(values)

    def error(self, key):
        return HomeAssistantError(translation_domain=DOMAIN, translation_key=key)

    async def set(self, case, target):
        await self._request(case, target, manual=False)

    async def set_manual(self, control, target, *, climate=False, coalesce=False):
        if self.restart_unresolved:
            raise self.error("controls_blocked")
        if self.session_test:
            raise self.error("probe_busy")
        if (
            isinstance(control, (EquipmentControl, AcControl))
            and control.equipment
            and control.equipment not in self.coordinator.equipment
        ):
            raise self.error("equipment_not_enabled")
        try:
            validate_manual(control, target, allow_default_on=True)
            self.request_sequence += 1
            token = self.request_sequence
            self.feedback[control.key] = {
                "token": token,
                "control": control.value,
                "target": "on" if target is None else target,
                "outcome": "queued",
            }
            await self.lights.submit(control, (target, climate, token), replace_unsent=coalesce)
        except ControlError:
            if "token" in locals():
                self._feedback(control, token, outcome="not_dispatched")
            raise self.error("light_queue_failed") from None
        except (HomeAssistantError, asyncio.CancelledError):
            row = self.feedback.get(control.key, {})
            if row.get("outcome") in ("queued", "preflight"):
                self._feedback(control, token, outcome="not_dispatched")
            raise
        finally:
            self.notify()

    async def _queued_light(self, control, request, deadline):
        target, climate, token = request
        await self._request(
            control,
            target,
            manual=True,
            climate=climate,
            unsent_deadline=deadline,
            feedback_token=token,
        )

    async def _request(
        self, case, target, *, manual, climate=False, unsent_deadline=None, feedback_token=None
    ):
        if self.restart_unresolved:
            raise self.error("controls_blocked")
        if self.session_test:
            raise self.error("probe_busy")
        if manual and self.probe_task is not None:
            async with asyncio.timeout_at(unsent_deadline):
                await asyncio.shield(self.probe_task)
        recoverable = manual and self.can_resynchronize
        if (
            self.closed
            or (self.blocked and not recoverable)
            or (not manual and self.historical_unknown)
        ):
            raise self.error("controls_blocked")
        if (
            self.task is not None
            or self.probe_task is not None
            or (self.lights.worker is not None and asyncio.current_task() is not self.lights.worker)
        ):
            raise self.error("control_busy")
        if manual:
            try:
                validate_manual(case, target, allow_default_on=True)
            except ControlError:
                raise self.error("invalid_control_value") from None
        elif (
            not isinstance(case, Case)
            or type(target) is not type(case.target)
            or target not in (case.baseline, case.target)
        ):
            raise self.error("invalid_control_value")
        state = self.journal.state
        if not manual and case.value in state["completed"]:
            raise self.error("test_case_complete")
        pending = state["pending"]
        if (
            pending
            and not recoverable
            and (manual or pending["case"] != case.value or case.value not in self.forward_observed)
        ):
            raise self.error(
                "legacy_restore_required" if self.restoration_required else "controls_blocked"
            )
        restore = pending is not None and not recoverable
        self.task = asyncio.current_task()
        self.last_case = case.value
        self.last_requested = "on" if manual and target is None else target
        self.ack = None
        self.status = "preflight"
        self._feedback(case, feedback_token, outcome="preflight")
        started_at = asyncio.get_running_loop().time()
        self.notify()
        intent_started = False
        request_id = None
        completion_job = None

        async def resume():
            if recoverable:
                if self.journal.resumable_manual:
                    await self.io(self.journal.resume_manual)
                self.blocked = False

        async def persist(selected_case, restoration):
            nonlocal intent_started, request_id
            intent_started = True
            if manual:
                self.last_requested = restoration  # Resolved from the fresh baseline for bare ON.
                self._feedback(case, feedback_token, target=restoration)
                request_id = await self.io(self.journal.intent_manual, selected_case, restoration)
            else:
                await self.io(self.journal.intent, selected_case, restore=restoration)

        def progress(status, ack):
            self.status = status
            self.ack = ack
            self._feedback(
                case,
                feedback_token,
                outcome=status,
                **{
                    key: (ack or {}).get(key)
                    for key in ("http_status", "application_status", "positive_candidate")
                },
            )
            self.notify()

        try:
            options = {"climate": True} if climate else {}
            if manual:
                options.update(resume=resume, unsent_deadline=unsent_deadline)
            observed, dispatched = await self.coordinator.client.command(
                self.coordinator.device_id,
                case,
                target,
                restore,
                persist,
                progress,
                self.coordinator.async_set_updated_data,
                self.forward_context.get(case.value) if restore else None,
                **options,
            )
            if dispatched:
                if manual:
                    completion_job = self.start_io(
                        self.journal.complete_manual, case, self.last_requested, request_id
                    )
                    await asyncio.shield(completion_job)
                    self.status = (
                        "acknowledged_unconfirmed"
                        if isinstance(case, EquipmentControl) and case.action
                        else "service_observed"
                    )
                elif restore:
                    await self.io(self.journal.complete, case)
                    self.forward_observed.discard(case.value)
                    self.status = "service_roundtrip_complete"
                else:
                    self.forward_observed.add(case.value)
                    self.forward_context[case.value] = dict(
                        observed.control_snapshots[case.value].context
                    )
        except BaseException as error:
            committed = False
            if completion_job is not None:
                while True:
                    try:
                        await asyncio.shield(completion_job)
                        committed = True
                        break
                    except asyncio.CancelledError:
                        if completion_job.cancelled():
                            break
                        # Caller cancellation followed by unload must still join owned IO.
                    except BaseException:
                        break
            if committed:
                # An interrupted caller cannot turn known durable success into uncertainty.
                self.status = (
                    "acknowledged_unconfirmed"
                    if isinstance(case, EquipmentControl) and case.action
                    else "service_observed"
                )
            elif self.journal.blocked or intent_started or restore:
                self.blocked, self.status = True, "unknown"
            else:
                self.status = "not_dispatched"
            if isinstance(error, asyncio.CancelledError):
                raise
            raise self.error(
                "controls_blocked" if self.blocked else "control_preflight_failed"
            ) from None
        finally:
            # A cancelled shield cannot release the writer while its executor can
            # still publish an intent/archive. Keep ownership through repeated cancellation.
            while self.io_jobs:
                waiting = asyncio.gather(*tuple(self.io_jobs), return_exceptions=True)
                while not waiting.done():
                    try:
                        await asyncio.shield(waiting)
                    except asyncio.CancelledError:
                        continue
            self.task = None
            self.last_duration_ms = min(
                1_000_000, round((asyncio.get_running_loop().time() - started_at) * 1000)
            )
            self._feedback(
                case, feedback_token, outcome=self.status, duration_ms=self.last_duration_ms
            )
            self.notify()

    async def close(self):
        self.closed = True
        if self.cleanup_task is None:
            self.cleanup_task = asyncio.create_task(self._close_owned())
        try:
            await asyncio.shield(self.cleanup_task)
        except asyncio.CancelledError:
            await asyncio.shield(self.cleanup_task)
            raise

    async def _close_owned(self):
        await self.lights.close()
        if self.probe_task and self.probe_task is not asyncio.current_task():
            self.probe_task.cancel()
            await asyncio.gather(self.probe_task, return_exceptions=True)
        if self.task and self.task is not asyncio.current_task():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.io_jobs:
            await asyncio.gather(*tuple(self.io_jobs), return_exceptions=True)
        if self.journal:
            await self.io(self.journal.__exit__)
