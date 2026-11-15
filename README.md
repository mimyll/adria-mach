# Adria MACH for Home Assistant

![Adria MACH integration](custom_components/adria_mach/brand/icon.png)

Unofficial cloud integration for an Adria vehicle assigned to your MACH account. Requires Home Assistant **2026.11.0 or newer**. Equipment and available controls depend on the capabilities reported by your vehicle. Compatibility beyond the original owner's vehicle is not established.

## Install and update

1. Open **Settings → Marketplace → Add from link**.
2. Add `https://github.com/mimyll/adria-mach` as an integration and install the latest release.
3. Restart Home Assistant, then add **Adria MACH** under **Settings → Devices & services** and sign in.

Already using the manually installed integration? Install through Marketplace to adopt its source files, then restart. Keep your existing Adria MACH integration entry, settings, entity registry and command-history data. Do not remove or recreate the integration.

Later versions appear under **Settings → Updates**. Read the release notes, install and restart when requested. Link-added repositories require Marketplace's GitHub connection; its periodic checks can take up to 48 hours. You can refresh the repository manually. [Marketplace documentation](https://www.home-assistant.io/integrations/marketplace/).

## Features

Temperatures, tank and battery measurements; native lights, heating thermostat, water heater, refrigerator, air conditioning and verified equipment controls. Optional equipment must be identified in integration options. Commands are serialized, expire within a bounded time and are never automatically replayed after uncertainty.

Lights temporarily display the latest queued request; `reported_state` and `reported_brightness` retain the observed values. Cloud/vehicle delays still apply. The master lights-off operation can briefly flash the physical lights; the owner also observed this in the official MACH app.

English source/default labels and separate Finnish translations. Updating preserves existing entity IDs and settings. The neutral caravan icon is original artwork; this project is independent of Adria.

## Development and releases

Work in a clone of this repository. For the minimum supported environment:

```sh
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p pytest_asyncio.plugin tests/test_client.py tests/test_ack_diagnostics.py tests/test_capabilities.py tests/test_release.py -q
EXPECTED_HA_VERSION=2026.11.0 python -m pytest -c pytest-ha.ini -q
```

Push a branch and open a pull request. CI runs the synthetic/HTTP and native HA suites against both the minimum and the current stable Home Assistant. Weekly checks repeat current-stable compatibility. Failures require a reviewed code fix; passing today cannot guarantee future compatibility. Dependabot proposes GitHub Actions updates.

For a release, update `manifest.json`, `pyproject.toml` and `CHANGELOG.md` to the same version, merge the tested change, then run **Actions → Release → Run workflow** on `main` with that version. The workflow retests both HA targets, builds the exact Marketplace ZIP and publishes its GitHub tag/release after all checks pass. Existing releases/assets are not overwritten. Marketplace installs the released ZIP, not unreviewed branch changes.

Tests use synthetic data and local HTTP, never vehicle commands. Report issues without credentials, tokens, vehicle identifiers, locations or raw captures. MIT licensed; see [NOTICE.md](NOTICE.md).
