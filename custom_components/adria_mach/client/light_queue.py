"""Bounded volatile manual admission; only unsent absolute lights coalesce."""

import asyncio
from dataclasses import dataclass

from .control_model import ControlError

WAIT_SECONDS = 120
DEBOUNCE_SECONDS = 0.25
CAPACITY = 12


@dataclass
class Slot:
    control: object
    target: object
    expires: float
    ready: float
    future: asyncio.Future
    replaceable: bool = False
    expiry_handle: object = None


class LightQueue:
    def __init__(self, execute, notify, *, coalesce=lambda control: True):
        self.execute, self.notify = execute, notify
        self.pending = []
        self.worker = None
        self.active = None
        self.closed = False
        self.coalesce = coalesce

    async def submit(self, control, target, *, replace_unsent=None):
        if self.closed:
            raise ControlError("queue_closed")
        loop = asyncio.get_running_loop()
        now = loop.time()
        light = self.coalesce(control) if replace_unsent is None else replace_unsent
        previous = None
        if light:
            latest = next((s for s in reversed(self.pending) if s.control == control), None)
            if latest is not None and latest.replaceable:
                previous = latest
        future = loop.create_future()
        if previous is not None:
            # Replace the unsent slot only. Its order and original expiry do not change.
            if not previous.future.done():
                previous.future.set_result("superseded")
            previous.target, previous.future = target, future
            previous.ready = min(previous.expires, now + DEBOUNCE_SECONDS)
            slot = previous
        else:
            if len(self.pending) >= CAPACITY:
                raise ControlError("queue_full")
            slot = Slot(
                control,
                target,
                now + WAIT_SECONDS,
                now + DEBOUNCE_SECONDS if light else now,
                future,
                light,
            )
            self.pending.append(slot)
            slot.expiry_handle = loop.call_at(slot.expires, self._expire, slot)
        if self.worker is None:
            self.worker = asyncio.create_task(self._run())
        self.notify()
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            if self.active is slot and slot.future is future:
                self.worker.cancel()
            elif slot in self.pending and slot.future is future:
                self.pending.remove(slot)
                slot.expiry_handle.cancel()
            future.cancel()
            raise

    def _expire(self, slot):
        if slot in self.pending:
            self.pending.remove(slot)
            if not slot.future.done():
                slot.future.set_exception(ControlError("queue_expired"))
            self.notify()

    def _flush(self):
        for slot in self.pending:
            slot.expiry_handle.cancel()
            if not slot.future.done():
                slot.future.set_exception(ControlError("queue_interrupted"))
        self.pending.clear()

    async def _run(self):
        now = asyncio.get_running_loop().time
        try:
            while self.pending and not self.closed:
                slot = self.pending[0]
                await asyncio.sleep(max(0, slot.ready - now()))
                # Replacement can move debounce while sleeping; keep the slot mutable here.
                if slot not in self.pending or now() < slot.ready:
                    continue
                self.pending.remove(slot)
                slot.expiry_handle.cancel()
                if slot.future.cancelled():
                    continue
                if now() >= slot.expires:
                    slot.future.set_exception(ControlError("queue_expired"))
                    continue
                self.active = slot  # Freeze target at dequeue, before any network preflight.
                try:
                    await self.execute(slot.control, slot.target, slot.expires)
                except asyncio.CancelledError:
                    if not slot.future.done():
                        slot.future.cancel()
                    raise
                except Exception as error:
                    if not slot.future.done():
                        slot.future.set_exception(error)
                    # Other explicit intents remain queued. Their executor must obtain
                    # fresh readiness/state and retain the previous unknown before dispatch.
                else:
                    if not slot.future.done():
                        slot.future.set_result("completed")
                finally:
                    self.active = None
                    self.notify()
        finally:
            self._flush()
            self.worker = None
            self.notify()

    async def close(self):
        self.closed = True
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        self._flush()
