"""Reusable local HTTP transport boundary; no public service access."""

import json
from pathlib import Path

import pytest
from aiohttp import web


@pytest.fixture
def full_snapshot():
    return json.loads((Path(__file__).parent / "fixtures" / "monitoring.json").read_text())


@pytest.fixture
async def loopback():
    runners = []

    async def start(handler):
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        runners.append(runner)
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        return "http://127.0.0.1:" + str(runner.addresses[0][1])

    yield start
    for runner in reversed(runners):
        await runner.cleanup()
