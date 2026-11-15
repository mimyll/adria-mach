"""Resolve explicit minimum/current stable HA test environments from official PyPI."""

import json
import re
import urllib.request

MINIMUM = "2026.11.0"
STABLE = re.compile(r"20[0-9]{2}\.[0-9]+\.[0-9]+")
MAX_METADATA = 32_000_000


def get_pypi(package: str, version: str | None = None) -> dict:
    suffix = "/" + version if version else ""
    url = f"https://pypi.org/pypi/{package}{suffix}/json"
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read(MAX_METADATA + 1)
    if len(data) > MAX_METADATA:
        raise ValueError("PyPI metadata exceeds the expected size.")
    return json.loads(data)


def resolve_matrix(ha: dict, fixture: dict) -> dict:
    version = ha["info"]["version"]
    if STABLE.fullmatch(version) is None or fixture["info"]["version"] != version:
        raise ValueError("Stable HA and its exact test fixture must match.")
    requirements = fixture["info"].get("requires_dist", [])
    if not any(
        re.fullmatch(r"homeassistant\s*==\s*" + re.escape(version), r) for r in requirements
    ):
        raise ValueError("Test fixtures must pin the selected HA version.")
    python_match = re.search(r">=\s*(3\.[0-9]+)", ha["info"]["requires_python"])
    if python_match is None:
        raise ValueError("Cannot resolve HA's supported Python lower bound.")
    return {
        "include": [
            {"name": "minimum", "ha": MINIMUM, "python": "3.14.10"},
            {"name": "latest-stable", "ha": version, "python": python_match.group(1)},
        ]
    }


def main() -> None:
    ha = get_pypi("homeassistant")
    version = ha["info"]["version"]
    if STABLE.fullmatch(version) is None:
        raise ValueError("PyPI latest is not a supported stable HA version.")
    fixture = get_pypi("pytest-homeassistant", version)
    print(json.dumps(resolve_matrix(ha, fixture), separators=(",", ":")))


if __name__ == "__main__":
    main()
