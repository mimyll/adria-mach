# Changelog

## 0.13.1

- Accept chassis numbers enclosed in the manufacturer's asterisk markers, preserving the displayed text and existing privacy protections.

## 0.13.0

- Add read-only vehicle model, chassis number and four reported dimensions in millimetres.
- Keep vehicle metadata out of integration diagnostics; the chassis-number entity is disabled by default.
- Preserve existing entities, settings, location tracking and command history.

## 0.12.0

- Add longitudinal and lateral levelling angles using reported mounting and calibration data.
- Add an optional native GPS location entity, disabled by default. Enable it in the entity settings to show the vehicle on the map; Home Assistant may record location history.
- Reuse shared reads and keep coordinates out of diagnostic exports. Existing entities, settings and command history remain unchanged.

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
