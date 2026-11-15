"""Verify released bytes and explicit supported HA environments without service access."""

import hashlib
import io
import json
import zipfile

import pytest

from scripts.ci_matrix import resolve_matrix
from scripts.package_integration import FILES
from scripts.package_release import PREFIX, ReleaseError, build_release, release_files


@pytest.fixture
def release_project(tmp_path):
    root = tmp_path / "project"
    for name in FILES:
        path = root / PREFIX / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("synthetic runtime " + name).encode())
    (root / PREFIX / "manifest.json").write_text(
        json.dumps(
            {
                "domain": "adria_mach",
                "version": "0.10.2",
                "documentation": "https://github.com/mimyll/adria-mach",
            }
        )
    )
    (root / "pyproject.toml").write_text('[project]\nversion = "0.10.2"\n')
    (root / "hacs.json").write_text(
        json.dumps(
            {"filename": "adria_mach.zip", "zip_release": True, "homeassistant": "2026.11.0"}
        )
    )
    (root / "CHANGELOG.md").write_text("# Changelog\n\n## 0.10.2\n\nSynthetic release notes.\n")
    (root / "LICENSE").write_text("MIT License\n\nSynthetic copyright and permission notice.\n")
    return root


def test_deterministic_marketplace_asset_and_metadata(release_project, tmp_path):
    (release_project / ".env").write_text("PRIVATE_CANARY")
    (release_project / PREFIX / "private.txt").write_text("PRIVATE_CANARY")
    first = build_release(release_project, tmp_path / "a", "0.10.2")
    second = build_release(release_project, tmp_path / "b", "0.10.2")
    assert {p.name: p.read_bytes() for p in first.iterdir()} == {
        p.name: p.read_bytes() for p in second.iterdir()
    }
    metadata = json.loads((first / "release.json").read_bytes())
    archive = (first / "adria_mach.zip").read_bytes()
    digest = hashlib.sha256(archive).hexdigest()
    assert metadata["version"] == "0.10.2" and metadata["tag"] == "v0.10.2"
    assert metadata["archive_sha256"] == digest
    assert (first / "adria_mach.zip.sha256").read_text() == digest + "  adria_mach.zip\n"
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        assert set(z.namelist()) == set(FILES) | {"LICENSE"}
        assert len(z.namelist()) == len(FILES) + 1
        assert all(not n.startswith("custom_components/") for n in z.namelist())
        assert z.read("LICENSE") == (release_project / "LICENSE").read_bytes()
        assert metadata["files"]["LICENSE"] == hashlib.sha256(z.read("LICENSE")).hexdigest()
        for name in FILES:
            assert z.read(name) == (release_project / PREFIX / name).read_bytes()
            assert metadata["files"][name] == hashlib.sha256(z.read(name)).hexdigest()
        assert b"PRIVATE_CANARY" not in b"".join(z.read(n) for n in z.namelist())
    assert build_release(release_project, tmp_path / "a", "0.10.2") == first
    (first / "adria_mach.zip").write_bytes(b"preserve conflicting artifact")
    with pytest.raises(ReleaseError):
        build_release(release_project, tmp_path / "a", "0.10.2")
    assert (first / "adria_mach.zip").read_bytes() == b"preserve conflicting artifact"


@pytest.mark.parametrize("broken", ["version", "manifest", "package", "asset", "notes", "link"])
def test_invalid_release_cannot_produce_an_artifact(release_project, broken):
    version = "0.10.2"
    if broken == "version":
        version = "0.10.3"
    elif broken == "manifest":
        (release_project / PREFIX / "manifest.json").write_text('{"domain":"other"}')
    elif broken == "package":
        (release_project / "pyproject.toml").write_text('[project]\nversion="9.0.0"\n')
    elif broken == "asset":
        (release_project / "hacs.json").write_text("{}")
    elif broken == "notes":
        (release_project / "CHANGELOG.md").write_text("# No versioned notes\n")
    else:
        path = release_project / PREFIX / "__init__.py"
        path.unlink()
        path.symlink_to(release_project / "CHANGELOG.md")
    with pytest.raises(ReleaseError):
        release_files(release_project, version)


def test_output_symlink_is_rejected(release_project, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    output = tmp_path / "output"
    output.symlink_to(target, target_is_directory=True)
    with pytest.raises(ReleaseError):
        build_release(release_project, output, "0.10.2")
    assert not list(target.iterdir())


def test_minimum_and_current_ha_use_their_actual_supported_python_and_fixture():
    ha = {"info": {"version": "2026.12.0", "requires_python": ">=3.15.2"}}
    fixture = {"info": {"version": "2026.12.0", "requires_dist": ["homeassistant==2026.12.0"]}}
    assert resolve_matrix(ha, fixture) == {
        "include": [
            {"name": "minimum", "ha": "2026.11.0", "python": "3.14.10"},
            {"name": "latest-stable", "ha": "2026.12.0", "python": "3.15"},
        ]
    }


@pytest.mark.parametrize("broken", ["prerelease", "fixture_version", "fixture_pin", "python"])
def test_invalid_compatibility_target_is_not_silently_substituted(broken):
    ha = {"info": {"version": "2026.12.0", "requires_python": ">=3.15.0"}}
    fixture = {"info": {"version": "2026.12.0", "requires_dist": ["homeassistant==2026.12.0"]}}
    if broken == "prerelease":
        ha["info"]["version"] = "2026.12.0b1"
    elif broken == "fixture_version":
        fixture["info"]["version"] = "2026.11.0"
    elif broken == "fixture_pin":
        fixture["info"]["requires_dist"] = ["homeassistant>=2026.11.0"]
    else:
        ha["info"]["requires_python"] = "unsupported"
    with pytest.raises(ValueError):
        resolve_matrix(ha, fixture)
