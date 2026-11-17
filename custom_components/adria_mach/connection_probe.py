"""One-shot read-only readiness reconnect experiment on the existing client."""

import asyncio
from copy import deepcopy
from datetime import UTC, datetime

from .client import AuthenticationError, MachError

PROBE_SECONDS = 60
CYCLE_SECONDS = 30
SESSION_TEST_SECONDS = 90


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


async def run_session_renewal_test(coordinator):
    """One confirmed local cookie-loss experiment; no actuator or journal access."""
    started = asyncio.get_running_loop().time()
    report = {
        "outcome": "failed",
        "started_at": datetime.now(UTC).isoformat(),
        "baseline_read_completed": False,
        "owned_cookies_cleared": False,
        "authentication_rejection_observed": False,
        "authentication_rejection_status": None,
        "automatic_login_attempts": 0,
        "device_discoveries": 0,
        "automatic_renewals": 0,
        "configured_vehicle_verified": False,
        "fresh_read_completed": False,
        "natural_expiry_tested": False,
        "actuator_calls": 0,
        "failure_classification": None,
    }
    try:
        async with asyncio.timeout(SESSION_TEST_SECONDS):
            snapshot = await coordinator.client.test_session_renewal(coordinator.device_id, report)
            coordinator.async_set_updated_data(snapshot)
            report["outcome"] = (
                "completed"
                if report["authentication_rejection_observed"]
                and report["automatic_login_attempts"] == 1
                and report["device_discoveries"] == 1
                and report["automatic_renewals"] == 1
                else "not_reproduced"
            )
    except AuthenticationError:
        report["failure_classification"] = "authentication_rejected"
        if report["owned_cookies_cleared"]:
            report["outcome"] = "authentication_required"
            coordinator._live_error(AuthenticationError("authentication_rejected"))
        else:
            report["outcome"] = "baseline_unavailable"
    except TimeoutError:
        report["outcome"] = "timed_out"
        report["failure_classification"] = "deadline_exceeded"
    except MachError as error:
        code = error.args[0] if error.args and type(error.args[0]) is str else None
        report["failure_classification"] = (
            code
            if code
            in (
                "session_test_not_ready",
                "session_renewal_deferred",
                "rate_limited",
                "vehicle_identity_mismatch",
                "device_not_assigned",
                "handshake_rejected",
                "redirect_rejected",
                "http_failure",
                "invalid_json",
                "transport_failure",
                "stream_not_connected",
                "connection_closed",
            )
            else "read_failed"
        )
        report["outcome"] = "failed"
    except asyncio.CancelledError:
        report["outcome"] = "cancelled"
        raise
    finally:
        report["elapsed_ms"] = min(
            1_000_000, round((asyncio.get_running_loop().time() - started) * 1000)
        )
        coordinator.last_session_renewal_test = deepcopy(report)
    return report
