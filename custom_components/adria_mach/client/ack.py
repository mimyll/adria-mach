"""Bounded technical ACK facts; never a new delivery/acceptance contract."""

import json

from .control_model import positive_candidate

COUNT_LIMIT = 65535


def empty_facts(kind="no_reply"):
    return {
        "profile": "scalar_facts_v1",
        "classification": kind,
        "response_kind": "not_parsed",
        "expected_successes": 1,
        "successes_count": None,
        "true_count": 0,
        "false_count": 0,
        "invalid_count": 0,
        "outer_extra_count": 0,
        "payload_extra_count": 0,
        "duplicate_key_count": 0,
    }


def inspect_ack(data):
    """Return legacy predicate and allowlisted facts, never parsed remote data.

    Duplicate detection is diagnostic only: last-key parsing deliberately keeps
    the installed acceptance predicate unchanged in this first implementation.
    """
    facts = empty_facts("invalid_json")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                facts["duplicate_key_count"] = min(COUNT_LIMIT, facts["duplicate_key_count"] + 1)
            result[key] = value
        return result

    try:
        result = json.loads(data, object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError):
        return False, None, facts
    legacy = positive_candidate(result)
    facts["response_kind"] = "object" if isinstance(result, dict) else "non_object"
    facts["classification"] = "invalid_shape"
    pending = [(result, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > 64:
            facts["classification"] = "depth_exceeded"
            return legacy, None, facts
        if isinstance(value, dict):
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)
    if not isinstance(result, dict):
        return legacy, None, facts
    app = result.get("status")
    app_status = app if type(app) is int and 100 <= app <= 599 else None
    facts["outer_extra_count"] = min(COUNT_LIMIT, len(result.keys() - {"status", "payload"}))
    payload = result.get("payload")
    if isinstance(payload, dict):
        facts["payload_extra_count"] = min(COUNT_LIMIT, len(payload.keys() - {"successes"}))
        successes = payload.get("successes")
        if isinstance(successes, list):
            facts["successes_count"] = min(COUNT_LIMIT, len(successes))
            facts["true_count"] = min(COUNT_LIMIT, sum(item is True for item in successes))
            facts["false_count"] = min(COUNT_LIMIT, sum(item is False for item in successes))
            facts["invalid_count"] = min(
                COUNT_LIMIT, sum(type(item) is not bool for item in successes)
            )
            facts["classification"] = (
                "unexpected_cardinality"
                if len(successes) != 1
                else "invalid_shape"
                if type(successes[0]) is not bool
                else "unprofiled_status"
                if type(app) is not int or app != 200
                else "positive_candidate"
                if successes[0]
                else "negative_candidate"
            )
    if facts["duplicate_key_count"]:
        facts["classification"] = "duplicate_keys"
    return legacy, app_status, facts
