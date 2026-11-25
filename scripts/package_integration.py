"""Build a deterministic private-install ZIP containing only runtime sources."""

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "adria_mach"
FILES = (
    "__init__.py",
    "binary_sensor.py",
    "brand/icon.png",
    "brand/icon@2x.png",
    "client/__init__.py",
    "client/ack.py",
    "client/firmware.py",
    "client/restart.py",
    "client/restart_store.py",
    "maintenance.py",
    "update.py",
    "client/catalog.py",
    "client/capabilities.py",
    "client/model.py",
    "client/telemetry.py",
    "client/position.py",
    "client/vehicle.py",
    "device_tracker.py",
    "client/outside.py",
    "client/control_model.py",
    "client/commands.py",
    "client/journal.py",
    "client/light_queue.py",
    "client/live.py",
    "client/health.py",
    "connection_health.py",
    "client/operational.py",
    "client/master.py",
    "command_manager.py",
    "climate.py",
    "equipment_entity.py",
    "master_entity.py",
    "switch.py",
    "select.py",
    "button.py",
    "scene.py",
    "diagnostics.py",
    "config_flow.py",
    "const.py",
    "coordinator.py",
    "dashboard.py",
    "dashboard.js",
    "connection_probe.py",
    "entity.py",
    "manifest.json",
    "light.py",
    "number.py",
    "water_heater.py",
    "sensor.py",
    "services.py",
    "services.yaml",
    "strings.json",
    "translations/en.json",
    "translations/fi.json",
)


def main() -> None:
    version = json.loads((COMPONENT / "manifest.json").read_text())["version"]
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    archive = output / f"adria-mach-{version}.zip"
    files = {
        f"custom_components/adria_mach/{name}": (COMPONENT / name).read_bytes()
        for name in sorted(FILES)
    }
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    sums = "".join(f"{digest}  {name}\n" for name, digest in hashes.items()).encode()
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as package:
        for name, data in {**files, "SHA256SUMS": sums}.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(info, data, compresslevel=9)
    (output / f"adria-mach-{version}.SHA256SUMS").write_bytes(sums)
    receipt = {
        "version": version,
        "archive": archive.name,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "files": hashes,
    }
    (output / f"adria-mach-{version}.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"{archive.name}: {len(files)} runtime files, SHA256 {receipt['archive_sha256']}")


if __name__ == "__main__":
    main()
