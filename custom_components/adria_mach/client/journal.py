"""Private durable CT-P1 interlock: no reset, alternate path or force CLI."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from .control_model import (
    HEATING_SCOPE_HASH,
    LIGHTING_SCOPE_HASH,
    MANUAL_SCOPE_HASH,
    PLAN_HASH,
    WATER_SCOPE_HASH,
    Case,
    ControlError,
    HeatingControl,
    ManualControl,
    WaterControl,
    manual_scope,
    validate_manual,
)
from .master import MASTER_SCOPE_HASH, MasterControl
from .operational import AC_SCOPE_HASH, EQUIPMENT_SCOPE_HASH, AcControl, EquipmentControl
from .outside import OUTSIDE_SCOPE_HASH, OutsideControl

MAX_CHECKPOINT_BYTES = 32768
MAX_UNKNOWN_LIGHTS = 128


def manual_light(control):
    return isinstance(control, OutsideControl) or (
        isinstance(control, ManualControl) and control is not ManualControl.HEATER
    )


class Journal:
    def __init__(self, directory: Path, *, allow_light_resume=False, allow_manual_resume=False):
        self.directory = directory
        self.fd = None
        self.attempt = uuid4().hex
        self.state = None
        self.blocked = False
        self.allow_light_resume = allow_light_resume
        self.allow_manual_resume = allow_manual_resume

    def __enter__(self):
        self.directory.mkdir(mode=0o700, exist_ok=True)
        self._check(self.directory, directory=True)
        self._sync_directory(self.directory.parent)  # Anchor a newly created interlock directory.
        self.fd = os.open(self.directory / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            self._check(self.directory / "lock")
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.state = self._load()
            return self
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    @staticmethod
    def _check(path, *, directory=False):
        info = path.lstat()
        mode = 0o700 if directory else 0o600
        proper_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        if not proper_type or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != mode:
            raise ControlError("journal_insecure")

    def _load(self):
        path = self.directory / "state.json"
        if not path.exists() and not path.is_symlink():
            return {
                "version": 6,
                "plan_sha256": PLAN_HASH,
                "lighting_scope_sha256": LIGHTING_SCOPE_HASH,
                "manual_scope_sha256": MANUAL_SCOPE_HASH,
                "water_scope_sha256": WATER_SCOPE_HASH,
                "heating_scope_sha256": HEATING_SCOPE_HASH,
                "completed": [],
                "pending": None,
                "last_manual": None,
                "last_water": None,
                "last_heating": None,
                "outside_scope_sha256": OUTSIDE_SCOPE_HASH,
                "last_outside": None,
            }
        self._check(path)
        with path.open() as stream:
            data = json.loads(stream.read(MAX_CHECKPOINT_BYTES + 1))
        if not isinstance(data, dict) or type(data.get("version")) is not int:
            raise ControlError("journal_unresolved_or_invalid")
        version = data["version"]
        legacy = version == 1
        keys = {"version", "plan_sha256", "completed", "pending"}
        if not legacy:
            keys.add("lighting_scope_sha256")
        if version >= 3:
            keys.update(("manual_scope_sha256", "last_manual"))
        if version >= 4:
            keys.update(("water_scope_sha256", "last_water"))
        if version >= 5:
            keys.update(("heating_scope_sha256", "last_heating"))
        if version >= 6:
            keys.update(("outside_scope_sha256", "last_outside"))
        if version >= 7:
            keys.add("unknown_light_archives")
        if version >= 8:
            keys.update(("equipment_scope_sha256", "last_equipment", "unknown_manual_archives"))
        if version >= 9:
            keys.update(("master_scope_sha256", "last_master"))
        if version == 10:
            keys.update(("ac_scope_sha256", "last_ac"))
        permitted = (Case.LIGHT, Case.HEATER) if legacy else tuple(Case)
        if (
            set(data) != keys
            or version not in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
            or (version == 7 and not (self.allow_light_resume or self.allow_manual_resume))
            or (
                version >= 8
                and (
                    not self.allow_manual_resume
                    or data["equipment_scope_sha256"] != EQUIPMENT_SCOPE_HASH
                )
            )
            or (version >= 9 and data["master_scope_sha256"] != MASTER_SCOPE_HASH)
            or (version == 10 and data["ac_scope_sha256"] != AC_SCOPE_HASH)
            or data["plan_sha256"] != PLAN_HASH
            or (not legacy and data["lighting_scope_sha256"] != LIGHTING_SCOPE_HASH)
            or (version >= 3 and data["manual_scope_sha256"] != MANUAL_SCOPE_HASH)
            or (version >= 4 and data["water_scope_sha256"] != WATER_SCOPE_HASH)
            or (version >= 5 and data["heating_scope_sha256"] != HEATING_SCOPE_HASH)
            or (version >= 6 and data["outside_scope_sha256"] != OUTSIDE_SCOPE_HASH)
            or not isinstance(data["completed"], list)
            or any(
                type(v) is not str or v not in [c.value for c in permitted]
                for v in data["completed"]
            )
            or len(set(data["completed"])) != len(data["completed"])
            or (
                data["pending"] is not None
                and not (
                    version >= 6
                    and isinstance(data["pending"], dict)
                    and (
                        version >= 8
                        or data["pending"].get("case") not in {c.value for c in EquipmentControl}
                    )
                    and (
                        version >= 9
                        or data["pending"].get("case") not in {c.value for c in MasterControl}
                    )
                    and (
                        version == 10
                        or data["pending"].get("case") not in {c.value for c in AcControl}
                    )
                    and (
                        (self.allow_manual_resume and self._manual_record(data["pending"]))
                        or (self.allow_light_resume and self._light_pending(data["pending"]))
                    )
                )
            )
        ):
            # Even a valid pending record closes all cases until separate reconciliation.
            raise ControlError("journal_unresolved_or_invalid")
        if version >= 3:
            self._validate_summary(data["last_manual"], ManualControl, MANUAL_SCOPE_HASH)
        if version >= 4:
            self._validate_summary(data["last_water"], WaterControl, WATER_SCOPE_HASH)
        if version >= 5:
            self._validate_summary(data["last_heating"], HeatingControl, HEATING_SCOPE_HASH)
        if version >= 6:
            self._validate_summary(data["last_outside"], OutsideControl, OUTSIDE_SCOPE_HASH)
        else:
            # Only clean validated history migrates; spent cases remain verbatim.
            data = {
                **data,
                "version": 6,
                "lighting_scope_sha256": LIGHTING_SCOPE_HASH,
                "manual_scope_sha256": MANUAL_SCOPE_HASH,
                "last_manual": data.get("last_manual"),
                "water_scope_sha256": WATER_SCOPE_HASH,
                "last_water": data.get("last_water"),
                "heating_scope_sha256": HEATING_SCOPE_HASH,
                "last_heating": data.get("last_heating"),
                "outside_scope_sha256": OUTSIDE_SCOPE_HASH,
                "last_outside": None,
            }
            self.state = data
            self._save()  # Failure prevents dispatch; old pending is never rewritten.
        if version >= 7:
            archives = data["unknown_light_archives"]
            if (
                not isinstance(archives, list)
                or not (1 if version == 7 else 0) <= len(archives) <= MAX_UNKNOWN_LIGHTS
                or any(not self._hex_id(item, 64) for item in archives)
                or len(set(archives)) != len(archives)
            ):
                raise ControlError("journal_unresolved_or_invalid")
            for digest in archives:
                self._archive_bytes(digest)
        if version >= 8:
            self._validate_summary(data["last_equipment"], EquipmentControl, EQUIPMENT_SCOPE_HASH)
            archives = data["unknown_manual_archives"]
            if (
                not isinstance(archives, list)
                or len(archives) + len(data["unknown_light_archives"]) > MAX_UNKNOWN_LIGHTS
                or any(not self._hex_id(item, 64) for item in archives)
                or len(set(archives)) != len(archives)
            ):
                raise ControlError("journal_unresolved_or_invalid")
            for digest in archives:
                self._archive_bytes(digest, manual=True)
        if version >= 9:
            self._validate_summary(data["last_master"], MasterControl, MASTER_SCOPE_HASH)
        if version == 10:
            self._validate_summary(data["last_ac"], AcControl, AC_SCOPE_HASH)
        return data

    @staticmethod
    def _hex_id(value, length=32):
        return (
            type(value) is str
            and len(value) == length
            and all(c in "0123456789abcdef" for c in value)
        )

    @classmethod
    def _light_pending(cls, value):
        return cls._manual_record(value, light_only=True)

    @classmethod
    def _manual_record(cls, value, *, light_only=False):
        if not isinstance(value, dict) or set(value) != {
            "attempt",
            "case",
            "phase",
            "scope",
            "request_id",
            "target",
        }:
            return False
        if value["phase"] != "manual" or not all(
            cls._hex_id(value[key]) for key in ("attempt", "request_id")
        ):
            return False
        try:
            control = next(
                c
                for c in (
                    *ManualControl,
                    *OutsideControl,
                    *WaterControl,
                    *HeatingControl,
                    *EquipmentControl,
                    *MasterControl,
                    *AcControl,
                )
                if c.value == value["case"] and (not light_only or manual_light(c))
            )
            validate_manual(control, value["target"])
            return value["scope"] == manual_scope(control)
        except (StopIteration, ControlError):
            return False

    @property
    def resumable_light(self):
        return bool(
            self.allow_light_resume
            and not self.blocked
            and self.fd is not None
            and self.state
            and self._light_pending(self.state["pending"])
        )

    @property
    def resumable_manual(self):
        return bool(
            self.allow_manual_resume
            and not self.blocked
            and self.fd is not None
            and self.state
            and self._manual_record(self.state["pending"])
        )

    def _archive_bytes(self, digest, *, manual=False):
        path = self.directory / (
            ("unknown-manual-" if manual else "unknown-light-") + digest + ".json"
        )
        self._check(path)
        with path.open("rb") as stream:
            data = stream.read(MAX_CHECKPOINT_BYTES + 1)
        if len(data) > MAX_CHECKPOINT_BYTES or hashlib.sha256(data).hexdigest() != digest:
            raise ControlError("journal_unresolved_or_invalid")
        return data

    def resume_light(self):
        return self._resume(manual=False)

    def resume_manual(self):
        return self._resume(manual=not self._light_pending(self.state["pending"]))

    def _upgrade(self, *, master=False, ac=False):
        self.state = {
            **self.state,
            "version": max(8, self.state["version"]),
            "equipment_scope_sha256": EQUIPMENT_SCOPE_HASH,
            "last_equipment": self.state.get("last_equipment"),
            "unknown_light_archives": self.state.get("unknown_light_archives", []),
            "unknown_manual_archives": self.state.get("unknown_manual_archives", []),
        }
        if master or ac or self.state["version"] >= 9:
            self.state.update(
                version=max(9, self.state["version"]),
                master_scope_sha256=MASTER_SCOPE_HASH,
                last_master=self.state.get("last_master"),
            )
        if ac or self.state["version"] == 10:
            self.state.update(
                version=10, ac_scope_sha256=AC_SCOPE_HASH, last_ac=self.state.get("last_ac")
            )

    def _resume(self, *, manual):
        """After fresh readiness/state only: archive unknown, never settle or replay it."""
        if not (self.resumable_manual if self.allow_manual_resume else self.resumable_light):
            raise ControlError("writes_blocked")
        field = "unknown_manual_archives" if manual else "unknown_light_archives"
        archives = self.state.get(field, [])
        if (
            len(self.state.get("unknown_light_archives", []))
            + len(self.state.get("unknown_manual_archives", []))
            >= MAX_UNKNOWN_LIGHTS
        ):
            raise ControlError("writes_blocked")
        path = self.directory / "state.json"
        self._check(path)
        data = path.read_bytes()
        if len(data) > MAX_CHECKPOINT_BYTES or json.loads(data) != self.state:
            raise ControlError("journal_unresolved_or_invalid")
        digest = hashlib.sha256(data).hexdigest()
        archive = self.directory / (
            ("unknown-manual-" if manual else "unknown-light-") + digest + ".json"
        )
        try:
            try:
                descriptor = os.open(
                    archive, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
                )
            except FileExistsError:
                if self._archive_bytes(digest, manual=manual) != data:
                    raise ControlError("journal_unresolved_or_invalid") from None
            else:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            self._sync_directory(self.directory)
            if self.allow_manual_resume:
                self._upgrade()
            self.state = {
                **self.state,
                "version": self.state["version"] if self.allow_manual_resume else 7,
                "pending": None,
                field: [*archives, digest],
            }
            self._save()
        except BaseException:
            self.blocked = True
            raise

    @staticmethod
    def _validate_summary(value, control_type, scope):
        if value is None:
            return
        if (
            not isinstance(value, dict)
            or set(value) != {"scope", "request_id", "control", "target", "outcome"}
            or value["scope"] != scope
            or value["outcome"]
            not in (
                ("service_observed", "acknowledged_unconfirmed")
                if control_type is EquipmentControl
                else ("service_observed",)
            )
            or not isinstance(value["request_id"], str)
            or len(value["request_id"]) != 32
            or any(c not in "0123456789abcdef" for c in value["request_id"])
        ):
            raise ControlError("journal_unresolved_or_invalid")
        try:
            control = control_type(value["control"])
            validate_manual(control, value["target"])
            if isinstance(control, EquipmentControl) and (
                (value["outcome"] == "acknowledged_unconfirmed") != control.action
            ):
                raise ControlError("journal_unresolved_or_invalid")
        except (ValueError, TypeError, ControlError):
            raise ControlError("journal_unresolved_or_invalid") from None

    def ready(self, case):
        if (
            not isinstance(case, Case)
            or self.blocked
            or self.fd is None
            or self.state["pending"] is not None
            or case.value in self.state["completed"]
        ):
            raise ControlError("writes_blocked")

    def _save(self):
        name = ".state-" + uuid4().hex
        temporary = self.directory / name
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump(self.state, stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            final_publication = self.state["pending"] is None
            if final_publication:
                # Keep the old durable pending record through every fallible preparation.
                self._sync_directory(self.directory)
            # On completion this MUST be the final fallible operation. Losing this
            # publication in a crash reveals the old pending record and blocks.
            os.replace(temporary, self.directory / "state.json")
            if not final_publication:
                self._sync_directory(self.directory)  # Intent is durable BEFORE dispatch.
        except BaseException:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
            raise

    @staticmethod
    def _sync_directory(path):
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def intent(self, case: Case, *, restore: bool):
        if self.blocked:
            raise ControlError("writes_blocked")
        if restore:
            pending = self.state["pending"]
            if pending != {"attempt": self.attempt, "case": case.value, "phase": "forward"}:
                raise ControlError("writes_blocked")
        else:
            self.ready(case)
        self.state["pending"] = {
            "attempt": self.attempt,
            "case": case.value,
            "phase": "restore" if restore else "forward",
        }
        try:
            self._save()  # Must finish BEFORE transport dispatch.
        except BaseException:
            self.blocked = True
            raise

    def complete(self, case: Case):
        if self.state["pending"] != {
            "attempt": self.attempt,
            "case": case.value,
            "phase": "restore",
        }:
            raise ControlError("writes_blocked")
        self.state["completed"].append(case.value)
        self.state["pending"] = None
        try:
            self._save()
        except BaseException:
            self.blocked = True
            raise

    def intent_manual(self, control, target):
        validate_manual(control, target)
        if self.blocked or self.fd is None or self.state["pending"] is not None:
            raise ControlError("writes_blocked")
        request_id = uuid4().hex
        if self.allow_manual_resume:
            self._upgrade(
                master=isinstance(control, MasterControl), ac=isinstance(control, AcControl)
            )
        elif isinstance(control, (EquipmentControl, MasterControl, AcControl)):
            raise ControlError("writes_blocked")
        self.state["pending"] = self._manual_pending(control, target, request_id)
        try:
            self._save()
        except BaseException:
            self.blocked = True
            raise
        return request_id

    def _manual_pending(self, control, target, request_id):
        return {
            "attempt": self.attempt,
            "case": control.value,
            "phase": "manual",
            "scope": manual_scope(control),
            "request_id": request_id,
            "target": target,
        }

    def complete_manual(self, control, target, request_id):
        validate_manual(control, target)
        if self.blocked or self.state["pending"] != self._manual_pending(
            control, target, request_id
        ):
            raise ControlError("writes_blocked")
        summary_key = (
            "last_ac"
            if isinstance(control, AcControl)
            else "last_master"
            if isinstance(control, MasterControl)
            else "last_equipment"
            if isinstance(control, EquipmentControl)
            else "last_outside"
            if isinstance(control, OutsideControl)
            else "last_heating"
            if isinstance(control, HeatingControl)
            else "last_water"
            if isinstance(control, WaterControl)
            else "last_manual"
        )
        self.state[summary_key] = {
            "scope": manual_scope(control),
            "request_id": request_id,
            "control": control.value,
            "target": target,
            "outcome": "acknowledged_unconfirmed"
            if isinstance(control, EquipmentControl) and control.action
            else "service_observed",
        }
        self.state["pending"] = None
        try:
            self._save()
        except BaseException:
            self.blocked = True
            raise
