# Adria MACH for Home Assistant

![Adria MACH integration](custom_components/adria_mach/brand/icon.png)

Unofficial integration for monitoring and controlling your Adria vehicle through the MACH cloud service. Provides measurements, lights, heating and other controls supported by your vehicle.

Requires **Home Assistant 2026.11.0 or newer** and a MACH account with an assigned vehicle.

## Installation

1. Open **Settings → Marketplace → Add from link**. Connect your GitHub account if prompted.
2. Add `https://github.com/mimyll/adria-mach` and install the latest release.
3. Restart Home Assistant.
4. Open **Settings → Devices & services → Add integration**, select **Adria MACH** and sign in with your MACH account.

Already installed manually? Install through Marketplace and restart. Keep your existing integration entry; do not remove or recreate it, so your entities, settings and command history remain intact.

## Updates

New releases appear under **Settings → Updates**. Read the release notes, install the update and restart Home Assistant. Keep GitHub connected in Marketplace for update checks; new releases can take up to 48 hours to appear. See the [Marketplace guide](https://www.home-assistant.io/integrations/marketplace/) for details.

## Limitations

- Vehicle specifications depend on reported data. The **Chassis number** entity is disabled by default; enable it if wanted. Home Assistant may record it, but integration diagnostics exclude it. Dimensions are reported specifications, not measured travel clearance.

- Vehicle location is disabled by default. Enable the **Location** entity to show it on the Home Assistant map; Home Assistant may record its history. Coordinates are excluded from integration diagnostics. Levelling angles use the latest shared snapshot; they do not reproduce the MACH app’s animated smoothing or calibrate the vehicle.

- Network and installed-version diagnostics depend on the fields reported by the device. LTE enabled is a setting, not proof of internet connectivity. Firmware update availability and installation are not supported.

- Requires internet access and the MACH cloud service. Cloud and vehicle delays affect readings and controls.
- Tested on one vehicle; compatibility with other vehicles is not established. Available controls depend on the installed equipment. Configure optional equipment in the integration options.
- **All lights off** can briefly flash the physical lights. This behavior has also been observed in the official MACH app.
