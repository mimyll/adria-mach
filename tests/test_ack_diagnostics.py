"""Pure ACK facts/privacy and preserved legacy predicate, using synthetic data."""

import json

import pytest

from custom_components.adria_mach.client.ack import inspect_ack
from custom_components.adria_mach.client.control_model import positive_candidate

SECRET = "synthetic-cookie-location-vehicle-error"


@pytest.mark.parametrize(
    "payload,classification",
    [
        ({"successes": [True]}, "positive_candidate"),
        ({"successes": [False]}, "negative_candidate"),
        ({"successes": []}, "unexpected_cardinality"),
        ({"successes": [True, False]}, "unexpected_cardinality"),
        ({"successes": [1]}, "invalid_shape"),
        ({"successes": [0]}, "invalid_shape"),
        ({"successes": [SECRET]}, "invalid_shape"),
        ({"successes": [{SECRET: SECRET}]}, "invalid_shape"),
        ({}, "invalid_shape"),
        ([], "invalid_shape"),
    ],
)
def test_fixed_facts_do_not_become_a_new_acceptance_policy(payload, classification):
    response = {"status": 200, "payload": payload}
    legacy, app, facts = inspect_ack(json.dumps(response).encode())
    assert legacy is positive_candidate(response)
    assert app == 200 and facts["classification"] == classification
    assert SECRET not in json.dumps(facts)


@pytest.mark.parametrize(
    "data,classification",
    [
        (b"null", "invalid_shape"),
        (b"[]", "invalid_shape"),
        (b"not json", "invalid_json"),
        (b'"' + b"x" * 10, "invalid_json"),
        (b"[" * 100 + b"0" + b"]" * 100, "depth_exceeded"),
        (b'{"status":201,"payload":{"successes":[true]}}', "unprofiled_status"),
        (b'{"status":true,"payload":{"successes":[true]}}', "unprofiled_status"),
        (
            b'{"status":400,"status":200,"payload":{"successes":[true]}}',
            "duplicate_keys",
        ),
    ],
)
def test_invalid_or_duplicate_facts_preserve_installed_json_guard(data, classification):
    legacy, _, facts = inspect_ack(data)
    try:
        prior = positive_candidate(json.loads(data))
    except (ValueError, RecursionError):
        prior = False
    assert legacy is prior
    assert facts["classification"] == classification


def test_additive_metadata_and_saturating_counts_never_export_remote_fields():
    response = {
        "status": 200,
        "payload": {"successes": [True], SECRET: {SECRET: [SECRET]}},
        SECRET: SECRET,
    }
    legacy, _, facts = inspect_ack(json.dumps(response).encode())
    assert not legacy and facts["classification"] == "positive_candidate"
    assert facts["outer_extra_count"] == facts["payload_extra_count"] == 1
    assert SECRET not in json.dumps(facts)
    _, _, facts = inspect_ack(
        json.dumps({"status": 200, "payload": {"successes": [False] * 70000}}).encode()
    )
    assert facts["successes_count"] == facts["false_count"] == 65535
