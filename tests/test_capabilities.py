"""Pure privacy/completeness owner; configuration never becomes generic controls."""

import json
from copy import deepcopy

from custom_components.adria_mach.client.capabilities import inventory


def test_inventory_classifies_every_row_without_private_strings(full_snapshot):
    data = deepcopy(full_snapshot)
    secret = "synthetic-password-token-vehicle-location"
    data["configuration"]["machId"] = secret
    data["configuration"]["drivers"] = [{"name": secret, "parameters": secret}]
    definitions = data["configuration"]["values"]
    definitions[0]["config"]["label"] = secret
    definitions += [
        {"id": secret, "config": {"id": secret, "type": "string", "range": [1, 2]}},
        {
            "id": "GPS_LATITUDE",
            "config": {"id": "GPS_LATITUDE", "type": "float", "range": [61.123456, 25.654321]},
        },
        {
            "id": "ENERGY_SOURCE",
            "config": {
                "id": "ENERGY_SOURCE",
                "type": "categorical",
                "categories": [{"id": "gas", "label": secret}, secret],
            },
        },
        {"id": "AUX_VALUE", "config": {"id": "AUX_VALUE", "type": "categorical"}},
        {"id": "AIR_CONDITION_VALUE", "config": {"id": secret, "type": "integer"}},
        None,
    ]
    data["values"]["values"].append({"device": secret, "status": secret})
    report = inventory(data["configuration"], data["values"], data["normalized"], {})
    exported = report.export()
    encoded = json.dumps(exported)
    assert len(report.definitions) == len(definitions)
    assert secret not in encoded and "61.123456" not in encoded and "25.654321" not in encoded
    assert report.definitions[-6].identifier is None
    assert report.definitions[-5].disposition == "excluded"
    assert report.definitions[-4].categories == ("gas",)
    assert report.definitions[-3].reason == "duplicate_definition"
    assert report.definitions[-2].reason == "invalid_definition"
    assert report.definitions[-1].identifier is None
    assert exported["source_sample_at"] is None
    assert "FRIDGE_VALUE" in exported["absent_reviewed_candidates"]
    assert sum(v for k, v in report.summary.items() if k != "configured_definitions") == len(
        definitions
    )


def test_inventory_uses_reviewed_schema_and_separates_write_eligibility(full_snapshot):
    data = full_snapshot
    report = inventory(data["configuration"], data["values"], data["normalized"], {})
    rows = {r.identifier: r for r in report.definitions}
    assert rows["LIVING_MEASURED_TEMPERATURE"].unit == "°C"
    assert rows["LIVING_MEASURED_TEMPERATURE"].read_available  # Valid zero.
    assert rows["AIR_HEATER_VALUE"].native_domains == ("binary_sensor",)
    assert not rows["AIR_HEATER_VALUE"].control_available
    assert rows["WATER_PUMP_VALUE"].command_policies == ()
    assert rows["AIR_HEATER_TEMPERATURE"].verified_range is None
    assert not hasattr(report, "write")


def test_inventory_unsupported_schema_does_not_hide_supported_sibling(full_snapshot):
    data = full_snapshot
    data["configuration"]["values"][0]["config"]["type"] = "arbitrary-secret-type"
    report = inventory(data["configuration"], data["values"], {}, {})
    assert report.definitions[0].reason == "invalid_definition"
    assert report.definitions[0].definition_type == "unknown"
    assert "arbitrary-secret-type" not in json.dumps(report.export())
