"""One candidate reboot request; acknowledgement never confirms physical effect."""

import asyncio

from .model import MachError


async def restart(client, device_id, persist, publish):
    async with client._lock, asyncio.timeout(90):
        if device_id not in {d.id for d in client._devices}:
            raise MachError("device_not_assigned")
        async with client.control_connection(device_id) as stream:
            measurement = await client._read_locked(device_id)
            publish(measurement)
            stream.ensure_connected()
            observed_at = asyncio.get_running_loop().time()
            await persist()
            if asyncio.get_running_loop().time() - observed_at >= 30:
                raise MachError("restart_baseline_expired")
            stream.ensure_connected()
            # No authentication renewal or automatic replay is permitted after intent.
            reply = await client._post(
                "/api/control/req",
                {
                    "type": "ui-req",
                    "payload": {"type": "systemRequest", "content": {"method": "reboot"}},
                },
            )
            # This says nothing about reboot completion or even native-portal compatibility.
            return (
                "accepted_unconfirmed"
                if (
                    type(reply) is dict
                    and type(reply.get("status")) is int
                    and reply["status"] == 200
                )
                else "unknown"
            )
