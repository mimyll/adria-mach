# Changelog

## 0.14.0

Automatic recovery from expired MACH cloud sessions, without re-entering valid credentials.

### Added

- Automatic session renewal using the credentials already stored in Home Assistant, for both periodic monitoring and event-driven refreshes.

### Fixed

- Monitoring stopping at session expiry and immediately asking for manual sign-in even when the saved username and password are still valid.

### Reliability and safety

- Concurrent monitoring reads share one renewal attempt and a fresh connection.
- Automatic login attempts are at least 60 seconds apart and respect server rate limits.
- The configured vehicle is revalidated after login. Rejected authentication, a missing vehicle assignment or another authentication rejection on the renewed session still requires manual reauthentication.
- Recovery retries only a complete monitoring read. Device commands are never replayed, and uncertain command outcomes and history are preserved.

### Upgrade

- Requires Home Assistant 2026.11.0 or newer. Install through Marketplace and restart Home Assistant.
- Keep the existing integration entry. Entity and device identities, settings, enabled location tracking and command history are preserved. No new entities or controls are added.

### Validation and known limitations

- Automated protocol/HTTP tests and native integration tests passed on Home Assistant 2026.11.0 and 2026.11.2.
- Expiry and renewal were tested with a local HTTP/SSE service. The installed integration was verified through fresh monitoring reads after restart.
- Recovery after natural session expiry on the MACH service still awaits real-world confirmation. No physical device commands were used for validation.

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
