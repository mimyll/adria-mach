"""Build the exact versioned ZIP consumed by Home Assistant Marketplace."""

import argparse
import hashlib
import io
import json
import re
import tempfile
import tomllib
import zipfile
from pathlib import Path

try:
    from .package_integration import FILES
except ImportError:
    from package_integration import FILES

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "mimyll/adria-mach"
PREFIX = "custom_components/adria_mach/"
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


class ReleaseError(Exception):
    """A bounded release validation failure."""


def read_selected(root: Path, name: str) -> bytes:
    path = root
    for part in Path(name).parts:
        if part in ("..", "."):
            raise ReleaseError("Unsafe selected path.")
        path /= part
        if path.is_symlink():
            raise ReleaseError("Selected release inputs must not be symbolic links.")
    if not path.is_file():
        raise ReleaseError("A selected release input is missing.")
    return path.read_bytes()


def release_files(root: Path, version: str) -> dict[str, bytes]:
    """Validate identity/versions and return deterministic public release artifacts."""
    if VERSION_RE.fullmatch(version) is None:
        raise ReleaseError("Use a stable three-part version.")
    runtime = {name: read_selected(root, PREFIX + name) for name in sorted(FILES)}
    manifest = json.loads(runtime["manifest.json"])
    project = tomllib.loads(read_selected(root, "pyproject.toml").decode())
    hacs = json.loads(read_selected(root, "hacs.json"))
    if (
        manifest.get("domain") != "adria_mach"
        or manifest.get("version") != version
        or project.get("project", {}).get("version") != version
        or manifest.get("documentation") != "https://github.com/" + REPOSITORY
        or hacs.get("filename") != "adria_mach.zip"
        or hacs.get("zip_release") is not True
        or hacs.get("homeassistant") != "2026.11.0"
    ):
        raise ReleaseError("Manifest, package, repository or Marketplace metadata disagree.")
    changelog = read_selected(root, "CHANGELOG.md").decode()
    match = re.search(
        r"^## " + re.escape(version) + r"\s*\n(.*?)(?=^## |\Z)", changelog, re.M | re.S
    )
    if match is None or not match.group(1).strip():
        raise ReleaseError("The version needs release notes in CHANGELOG.md.")
    archive_files = runtime | {"LICENSE": read_selected(root, "LICENSE")}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in sorted(archive_files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data, compresslevel=9)
    archive = output.getvalue()
    digest = hashlib.sha256(archive).hexdigest()
    metadata = {
        "repository": REPOSITORY,
        "version": version,
        "tag": "v" + version,
        "minimum_home_assistant": hacs["homeassistant"],
        "archive": "adria_mach.zip",
        "archive_sha256": digest,
        "files": {
            name: hashlib.sha256(data).hexdigest() for name, data in sorted(archive_files.items())
        },
    }
    return {
        "adria_mach.zip": archive,
        "adria_mach.zip.sha256": (digest + "  adria_mach.zip\n").encode(),
        "release.json": (json.dumps(metadata, indent=2, sort_keys=True) + "\n").encode(),
        "release-notes.md": (match.group(1).strip() + "\n").encode(),
    }


def build_release(root: Path, output: Path, version: str) -> Path:
    files = release_files(root, version)
    for path in (output.absolute(), *output.absolute().parents):
        if path.is_symlink():
            raise ReleaseError("Output must not contain symbolic links.")
    destination = output / ("v" + version)
    if destination.exists() or destination.is_symlink():
        if (
            destination.is_dir()
            and not destination.is_symlink()
            and {p.name for p in destination.iterdir()} == files.keys()
            and all(not (destination / n).is_symlink() for n in files)
            and all(
                (destination / n).is_file() and (destination / n).read_bytes() == b
                for n, b in files.items()
            )
        ):
            return destination
        raise ReleaseError("Existing versioned output differs; refusing overwrite.")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".release-", dir=output) as temporary:
        stage = Path(temporary) / "release"
        stage.mkdir()
        for name, data in files.items():
            (stage / name).write_bytes(data)
        stage.rename(destination)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    try:
        destination = build_release(ROOT, args.output_dir, args.version)
    except (ReleaseError, OSError, ValueError):
        parser.exit(1, "Release build failed: invalid or conflicting release inputs/output.\n")
    print(f"Built {destination.name}/adria_mach.zip; no publication performed.")


if __name__ == "__main__":
    main()
