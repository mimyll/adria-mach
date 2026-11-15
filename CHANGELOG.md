# Changelog

## 0.11.0

- Add read-only mobile network, signal quality, SIM status and device power diagnostics where reported.
- Show installed MACH software, OS release, firmware versions and release channel.
- Add the last successful read timestamp; reuse the existing shared connection.
- Preserve existing entities, controls, settings and command history. Device firmware updates and network configuration remain in the manufacturer application.

## 0.10.2

- Add GitHub release packaging and native Home Assistant Marketplace updates.
- Test minimum and current stable Home Assistant on changes and weekly.
- Publish under MIT with an original neutral caravan icon.
- Preserve existing control behavior, entities, settings and command history. Restart Home Assistant after adoption or update.

## 0.10.1

- Keep admitted light/AUX requests visible until readback completes, with reported state exposed separately.
- Retain ordered commands, timeouts, connection recovery and no replay of ambiguous commands.
