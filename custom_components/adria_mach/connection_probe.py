"""One-shot read-only readiness reconnect experiment on the existing client."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime

from .client import AuthenticationError, MachError

PROBE_SECONDS = 60
CYCLE_SECONDS = 30


async def run_probe(coordinator):
    """Collect initial readiness only; no writer, retry loop or ledger access."""
    now = asyncio.get_running_loop().time
    started = now()
    report = {
        "outcome": "failed",
        "started_at": datetime.now(UTC).isoformat(),
        "reads": [],
        "initial_readiness_only": True,
        "session_renewal_tested": False,
        "push_or_delivery_proven": False,
    }
    try:
        async with asyncio.timeout(PROBE_SECONDS):
            for cycle in (1, 2):
                cycle_start = now()
                item = {"cycle": cycle, "outcome": "read_failed"}
                report["reads"].append(item)
                try:
                    async with asyncio.timeout(CYCLE_SECONDS):
                        if hasattr(coordinator.client, "reset_connection"):
                            await coordinator.client.reset_connection()
                        snapshot = await coordinator.client.read(coordinator.device_id)
                    coordinator.async_set_updated_data(snapshot)
                    item.update(outcome="completed", received_at=snapshot.received_at.isoformat())
                except AuthenticationError:
                    item["outcome"] = "authentication_required"
                    break
                except TimeoutError:
                    item["outcome"] = "timed_out"
                except MachError as error:
                    # Only transient reader failures may use the second attempt.
                    # Never retry a rate/identity/permission rejection here.
                    code = error.args[0] if error.args and type(error.args[0]) is str else None
                    if code in (
                        "rate_limited",
                        "vehicle_identity_mismatch",
                        "device_not_assigned",
                        "handshake_rejected",
                        "redirect_rejected",
                    ):
                        item["outcome"] = code
                        break
                finally:
                    item["elapsed_ms"] = min(1_000_000, round((now() - cycle_start) * 1000))
    except TimeoutError:
        report["outcome"] = "timed_out"
        if report["reads"]:
            report["reads"][-1]["outcome"] = "timed_out"
    except asyncio.CancelledError:
        report["outcome"] = "cancelled"
        if report["reads"]:
            report["reads"][-1]["outcome"] = "cancelled"
        raise
    else:
        outcomes = [item["outcome"] for item in report["reads"]]
        report["outcome"] = (
            "completed"
            if outcomes == ["completed", "completed"]
            else "recovered"
            if len(outcomes) == 2 and outcomes[-1] == "completed"
            else "authentication_required"
            if outcomes[-1] == "authentication_required"
            else "failed"
        )
    finally:
        report["elapsed_ms"] = min(1_000_000, round((now() - started) * 1000))
        coordinator.last_connection_probe = deepcopy(report)
    return report
