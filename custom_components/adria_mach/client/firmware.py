"""Isolated read-only firmware availability; no installation transport."""

import asyncio
import json
import re
from dataclasses import dataclass

import aiohttp

from .model import MachError

UPDATES_URL = "https://adria-mach-updates.solvesall.com/api/updates/updatesAvailable"
MAX_BODY = 262144
VERSION = re.compile(r"([0-9]{1,9})\.([0-9]{1,9})\.([0-9]{1,9})(?: [A-Za-z0-9_. -]{1,64})?")


def version_key(value):
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise MachError("firmware_version_invalid")
    return tuple(int(x) for x in value.split(" ", 1)[0].split("."))


@dataclass(frozen=True)
class FirmwareInfo:
    installed: str
    latest: str
    notes: str | None = None


def parse_updates(data, installed, language="en"):
    current = version_key(installed)
    if type(data) is not list or len(data) > 256:
        raise MachError("firmware_response_invalid")
    best, latest, notes = current, installed, None
    for row in data:
        if type(row) is not dict:
            raise MachError("firmware_response_invalid")
        key = version_key(row.get("version"))
        release = row.get("releaseNotes")
        if release is not None and (
            type(release) is not dict
            or any(type(k) is not str or type(v) is not str for k, v in release.items())
        ):
            raise MachError("firmware_response_invalid")
        if key > best:
            best, latest = key, row["version"]
            note = (release or {}).get(language) or (release or {}).get("en")
            notes = note[:8192] if note else None
    return FirmwareInfo(installed, latest, notes)


def unique_object(pairs):
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError
        data[key] = value
    return data


class FirmwareClient:
    def __init__(self, *, connector=None):
        self.session = aiohttp.ClientSession(
            connector=connector,
            connector_owner=connector is None,
            cookie_jar=aiohttp.DummyCookieJar(),
            trust_env=False,
            timeout=aiohttp.ClientTimeout(total=20, connect=10, sock_read=15),
        )
        self.lock = asyncio.Lock()
        self.next_request = 0.0
        self.closed = False

    async def check(self, device_id, installed, channel, language="en"):
        version_key(installed)
        if not isinstance(channel, str) or not re.fullmatch(r"[A-Za-z0-9_. -]{1,48}", channel):
            raise MachError("firmware_metadata_missing")
        async with self.lock:
            now = asyncio.get_running_loop().time()
            if self.closed or now < self.next_request:
                raise MachError("firmware_check_deferred")
            self.next_request = now + 30
            try:
                async with self.session.post(
                    UPDATES_URL,
                    json={"machId": device_id, "version": installed, "releaseType": channel},
                    allow_redirects=False,
                ) as response:
                    if response.status != 200:
                        raise MachError("firmware_check_failed")
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(16384):
                        if len(body) + len(chunk) > MAX_BODY:
                            raise MachError("firmware_response_invalid")
                        body.extend(chunk)
                    try:
                        data = json.loads(body, object_pairs_hook=unique_object)
                    except (ValueError, UnicodeError, RecursionError):
                        raise MachError("firmware_response_invalid") from None
                    return parse_updates(data, installed, language)
            except (aiohttp.ClientError, TimeoutError):
                raise MachError("firmware_check_failed") from None

    async def close(self):
        self.closed = True
        await self.session.close()
