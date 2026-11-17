"""Restart admission and firmware polling with independent failure/lifetime ownership."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client.firmware import FirmwareClient
from .client.model import MachError
from .client.restart import restart
from .client.restart_store import RestartStore

LOGGER = logging.getLogger(__name__)


class Maintenance:
    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.store = None

    @property
    def commands(self):
        return self.coordinator.commands

    async def setup(self):
        self.store = RestartStore(self.commands.journal)
        try:
            await self.commands.io(self.store.load)
        except Exception:
            self.store.blocked = True
        self.commands.restart_unresolved = self.store.unresolved

    def _admit(self, *, acknowledge=False):
        c = self.commands
        if (
            c.closed
            or c.task
            or c.probe_task
            or c.session_test
            or c.lights.worker
            or (c.lights.pending or c.io_jobs)
        ):
            raise c.error("control_busy")
        if (
            self.store is None
            or self.store.blocked
            or (
                not acknowledge
                and (
                    self.store.unresolved
                    or c.blocked
                    or c.restoration_required
                    or c.journal.state is None
                    or c.journal.state["pending"] is not None
                )
            )
        ):
            raise c.error("controls_blocked")
        c.task = asyncio.current_task()

    async def _finish(self):
        # Repeated caller/unload cancellation must not release admission before durable IO ends.
        while self.commands.io_jobs:
            try:
                await asyncio.shield(asyncio.gather(*self.commands.io_jobs, return_exceptions=True))
            except asyncio.CancelledError:
                continue
        self.commands.restart_unresolved = self.store.unresolved
        self.commands.task = None
        self.commands.notify()

    async def async_restart(self):
        self._admit()
        request_id = uuid4().hex
        intent_started = False

        async def persist():
            nonlocal intent_started
            intent_started = True
            self.commands.restart_unresolved = True
            await self.commands.io(self.store.append, "requested", request_id)
            self.commands.notify()

        try:
            outcome = await restart(
                self.coordinator.client,
                self.coordinator.device_id,
                persist,
                self.coordinator.async_set_updated_data,
            )
            await self.commands.io(self.store.append, outcome, request_id)
            if outcome == "unknown":
                raise self.commands.error("restart_unknown")
        except BaseException as error:
            # Requested intent is already durable and maps to unknown. An in-flight
            # completion must finish alone; never start a concurrent append on cancellation.
            if isinstance(error, asyncio.CancelledError):
                raise
            raise self.commands.error(
                "restart_unknown" if intent_started else "control_preflight_failed"
            ) from None
        finally:
            await self._finish()

    async def async_acknowledge(self, request_id):
        # This local operation does not send a command or claim a physical observation.
        self._admit(acknowledge=True)
        try:
            if (
                not self.store.unresolved
                or not self.store.events
                or (self.store.events[-1]["id"] != request_id)
            ):
                raise self.commands.error("restart_acknowledgement_mismatch")
            await self.commands.io(self.store.append, "owner_acknowledged", request_id)
            return {"outcome": "owner_acknowledged", "physical_confirmation": "not_recorded"}
        except asyncio.CancelledError:
            raise
        except Exception:
            raise self.commands.error("restart_acknowledgement_mismatch") from None
        finally:
            await self._finish()


class FirmwareCoordinator(DataUpdateCoordinator):
    def __init__(self, coordinator, entry):
        super().__init__(
            coordinator.hass,
            LOGGER,
            name="MACH firmware",
            config_entry=entry,
            update_interval=timedelta(hours=12),
        )
        self.main = coordinator
        self.client = FirmwareClient(connector=async_get_clientsession(self.hass).connector)
        self.checked_at = None
        self.next_check = 0.0
        self.closed = False
        self.check_task = None

    async def _async_update_data(self):
        if self.closed:
            raise UpdateFailed("firmware_unavailable")
        now = asyncio.get_running_loop().time()
        if now < self.next_check:
            if self.last_update_success and self.data is not None:
                return self.data
            raise UpdateFailed("firmware_check_deferred")
        self.next_check = now + 30
        self.check_task = asyncio.current_task()
        try:
            sample = self.main.data
            if (datetime.now(UTC) - sample.received_at).total_seconds() > 90:
                # The ordinary telemetry poll is slower than the firmware freshness gate.
                # Acquire one read-only snapshot rather than reject a healthy manual check.
                await self.main.async_request_refresh()
                sample = self.main.data
            if (
                not self.main.last_update_success
                or (datetime.now(UTC) - sample.received_at).total_seconds() < 0
                or (datetime.now(UTC) - sample.received_at).total_seconds() > 90
            ):
                raise MachError("firmware_metadata_missing")
            info = await self.client.check(
                self.main.device_id,
                sample.values.get("mach_software_version"),
                sample.values.get("mach_release_channel"),
                self.hass.config.language,
            )
            self.checked_at = datetime.now(UTC).isoformat()
            return info
        except MachError:
            raise UpdateFailed("firmware_check_failed") from None
        finally:
            self.check_task = None

    async def async_close(self):
        self.closed = True
        if self.check_task and self.check_task is not asyncio.current_task():
            self.check_task.cancel()
            await asyncio.gather(self.check_task, return_exceptions=True)
        await self.async_shutdown()
        await self.client.close()
