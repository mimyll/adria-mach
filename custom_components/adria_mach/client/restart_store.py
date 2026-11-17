"""Separate durable restart history, protected by the existing journal lifetime lock."""

import json
import os
import re
from datetime import UTC, datetime
from uuid import uuid4

from .control_model import ControlError
from .journal import Journal

MAX_BYTES = 1048576
EVENTS = {"requested", "accepted_unconfirmed", "unknown", "owner_acknowledged"}


class RestartStore:
    def __init__(self, journal):
        self.journal = journal
        self.path = journal.directory / "restart.json"
        self.events = []
        self.blocked = True

    def _guard(self):
        if self.journal.fd is None or self.journal.blocked:
            raise ControlError("restart_storage_unavailable")
        Journal._check(self.journal.directory, directory=True)

    def load(self):
        self._guard()
        if self.path.exists() or self.path.is_symlink():
            Journal._check(self.path)
            with self.path.open("rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ControlError("restart_storage_unavailable")
            data = json.loads(raw)
            if (
                type(data) is not dict
                or set(data) != {"version", "events"}
                or (
                    type(data["version"]) is not int
                    or data["version"] != 1
                    or type(data["events"]) is not list
                )
            ):
                raise ControlError("restart_storage_unavailable")
            self._validate(data["events"])
            self.events = data["events"]
        self.blocked = False

    @staticmethod
    def _validate(events):
        active, outcome = None, None
        seen = set()
        for row in events:
            if type(row) is not dict or set(row) != {"id", "event", "at"}:
                raise ControlError("restart_storage_unavailable")
            if (
                type(row["id"]) is not str
                or not re.fullmatch(r"[a-f0-9]{32}", row["id"])
                or row["event"] not in EVENTS
                or type(row["at"]) is not str
            ):
                raise ControlError("restart_storage_unavailable")
            datetime.fromisoformat(row["at"])
            if row["event"] == "requested":
                if active is not None or row["id"] in seen:
                    raise ControlError("restart_storage_unavailable")
                active = row["id"]
                seen.add(active)
            elif row["id"] != active or (
                row["event"] != "owner_acknowledged" and outcome != "requested"
            ):
                raise ControlError("restart_storage_unavailable")
            if row["event"] == "owner_acknowledged":
                active = None
            outcome = row["event"]

    @property
    def unresolved(self):
        return self.blocked or bool(
            self.events and self.events[-1]["event"] != "owner_acknowledged"
        )

    @property
    def attributes(self):
        row = self.events[-1] if self.events else {}
        event = row.get("event", "idle")
        return {
            "restart_outcome": "unknown" if event == "requested" else event,
            "restart_request_id": row.get("id"),
            "restart_updated_at": row.get("at"),
            "restart_unresolved": self.unresolved,
            "restart_storage_available": not self.blocked,
            "physical_confirmation": "not_recorded",
            "restart_protocol_compatibility": "candidate_not_service_verified",
        }

    def append(self, event, request_id):
        try:
            self._guard()
            if self.blocked:
                raise ControlError("restart_storage_unavailable")
            rows = [
                *self.events,
                {"id": request_id, "event": event, "at": datetime.now(UTC).isoformat()},
            ]
            self._validate(rows)
            raw = (json.dumps({"version": 1, "events": rows}) + "\n").encode()
            if len(raw) > MAX_BYTES:
                raise ControlError("restart_storage_unavailable")
            if self.path.exists() or self.path.is_symlink():
                Journal._check(self.path)
            temporary = self.path.with_name("restart-" + uuid4().hex + ".tmp")
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                Journal._sync_directory(self.path.parent)
                self.events = rows
            finally:
                temporary.unlink(missing_ok=True)
        except BaseException:
            self.blocked = True
            raise
