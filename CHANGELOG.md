# Changelog

## 0.18.0

- Add an opt-in compact caravan panel with temperature and heating first, a single control for each light, and expandable supplies, location and equipment details.
- Support a combined lighting control for the selected master and exterior lights. Its off direction uses the configured shutdown script. A mixed reported state selects off.
- Allow explicit bindings for external battery, gas, spot-price and levelling readings on the caravan panel. Missing measurements are shown independently.

## 0.17.0

- Add four optional dashboard cards for overview, heating, lights, and water and energy. Choose the Adria MACH device from the card editor. The overview can display the selected vehicle's GPS position when enabled.
- Light cards provide ON/OFF, preset brightness for dimmable lights, and editable display names and icons. Shutdown actions use the vehicle's internal master and, when requested, explicit exterior light targets.

## 0.16.0

### Added

- Connection diagnostics on the existing device: transport status, reported vehicle/cache connection state, last event-stream traffic, last HA read age and optional reported device contact time/age. Missing source metadata remains unknown; HA receipt time is never presented as device sample time.
- A network-free 30-second age clock that stays visible when telemetry reads fail.
- An owned watchdog renews and resynchronizes a stream after 10 minutes without incoming bytes, including comment/unchanged-event activity. This conservative inactivity budget is preventative transport renewal, not proof that the vehicle is offline.

### Reliability

- Automatic recovery respects command/probe/session-test and durable-I/O admission, RPC ownership, authentication cooldown and rate limits. It never replays device commands or modifies command history.
- Old connection metadata is cleared across disconnected generations. Recovery success requires a complete read, and unload joins owned work.

### Upgrade and validation

- Requires Home Assistant 2026.11.0 or newer. Update through Marketplace and restart Home Assistant, retaining the existing entry. All existing entity identities, settings and histories are preserved.
- Synthetic protocol, real local HTTP/SSE and native HA tests cover silent streams, heartbeat bytes, authentication, cancellation, admission, independent ages and identity/lifecycle behavior. No intentional live fault or physical command was used.

## 0.15.0

### Added

- Native MACH restart button with fresh assigned-device checks, durable separate request history and no automatic replay. An acknowledgement does not confirm a physical reboot; portal compatibility still awaits an owner-approved device test.
- Read-only MACH firmware availability and a check button, using observed software version and release channel. Numeric version ordering, isolated HTTP state and independent failure handling keep monitoring available. Firmware installation is not supported.
- Admin-only local restart acknowledgement requiring the exact current request ID and explicit confirmation. It retains uncertainty history and sends nothing to the vehicle.

### Upgrade and validation

- Requires Home Assistant 2026.11.0 or newer. Update through Marketplace, restart Home Assistant and retain the existing entry. Existing identities, options and legacy command history are preserved.
- Synthetic protocol, real local HTTP and native HA checks cover isolation, parsing, serialization, persistence and cancellation. No physical reboot was executed during development.
- Never downgrade to an older integration while restart history is unresolved or its storage is invalid: older versions do not enforce the new restart interlock. Inspect and reconcile the request first.

## 0.14.1

### Added

- Admin-only, explicitly confirmed session-renewal diagnostic. It discards only the integration's local cookies and performs one bounded monitoring cycle against MACH.
- A privacy-filtered result showing actual authentication rejection, automatic login/discovery and fresh read completion. A read without rejection is reported as not reproduced.

### Reliability and safety

- Reject new device commands while the diagnostic is active; preserve existing identities, settings and command history.
- Retain the normal renewal path, rate limits and cooldown. No account-wide logout, credential export or actuator replay is added.

### Upgrade and validation

- Requires Home Assistant 2026.11.0 or newer. Update through Marketplace and restart, keeping the existing integration entry.
- Automated HTTP-loopback and native HA checks cover recovery, admin access, command exclusion and cancellation. Intentional local cookie loss is distinct from natural server-side expiry; live results are recorded separately.

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
