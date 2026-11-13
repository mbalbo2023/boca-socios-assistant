"""Config-only Boca controller -> cold worker boundary, without navigation."""

from __future__ import annotations

import importlib
import json
import os
import stat
from pathlib import Path

import pytest


def _runtime():
    return importlib.import_module("boca_socios.browser.site_url_runtime")


def _prepared(tmp_path: Path) -> tuple[Path, dict[str, int]]:
    directory = tmp_path / "boca-site-config"
    directory.mkdir(mode=0o711)
    directory.chmod(0o711)
    return directory / "boca-site-url.runtime.json", {
        "owner_uid": os.geteuid(),
        "owner_gid": os.getegid(),
    }


def test_config_only_volume_applies_latest_url_on_each_cold_read(tmp_path: Path) -> None:
    runtime = _runtime()
    path, owner = _prepared(tmp_path)
    first = "http://boca.sandbox.internal:8443/test"
    second = "https://soysocio.bocajuniors.com.ar/"

    fingerprint = runtime.publish_site_url(path, first, **owner)
    assert fingerprint == runtime.site_url_fingerprint(first)
    assert runtime.read_site_url(path, **owner) == first
    assert stat.S_IMODE(path.stat().st_mode) == 0o644
    assert set(json.loads(path.read_text())) == {"version", "SITE_URL", "sha256"}

    first_inode = path.stat().st_ino
    assert runtime.publish_site_url(path, second, **owner) != fingerprint
    assert path.stat().st_ino != first_inode
    assert runtime.read_site_url(path, **owner) == second


def test_missing_or_insecure_runtime_configuration_is_no_go(tmp_path: Path) -> None:
    runtime = _runtime()
    path, owner = _prepared(tmp_path)
    with pytest.raises(runtime.RuntimeSiteUrlUnavailable):
        runtime.read_site_url(path, **owner)

    runtime.publish_site_url(path, "https://sandbox.internal/", **owner)
    path.chmod(0o666)
    with pytest.raises(runtime.RuntimeSiteUrlUnavailable):
        runtime.read_site_url(path, **owner)
    with pytest.raises(runtime.RuntimeSiteUrlUnavailable):
        runtime.publish_site_url(path, "https://next.test/", **owner)


def test_optional_site_reader_distinguishes_never_configured_from_corrupted(
    tmp_path: Path,
) -> None:
    runtime = _runtime()
    path, owner = _prepared(tmp_path)
    # This read-only observer is permitted to report absence; worker START is not.
    assert runtime.read_optional_site_url(path, **owner) is None
    with pytest.raises(runtime.RuntimeSiteUrlUnavailable):
        runtime.read_site_url(path, **owner)
    runtime.publish_site_url(path, "https://my.sandbox.example/", **owner)
    assert runtime.read_optional_site_url(path, **owner) == "https://my.sandbox.example/"
    path.write_text("malformed")
    with pytest.raises(runtime.RuntimeSiteUrlUnavailable):
        runtime.read_optional_site_url(path, **owner)
    path.unlink()
    path.symlink_to(tmp_path / "nonexistent-target")
    with pytest.raises(runtime.RuntimeSiteUrlUnavailable):
        runtime.read_optional_site_url(path, **owner)


def test_runtime_file_symlink_and_hardlink_are_rejected(tmp_path: Path) -> None:
    runtime = _runtime()
    path, owner = _prepared(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("untouched")
    path.symlink_to(outside)
    with pytest.raises(runtime.RuntimeSiteUrlUnavailable):
        runtime.read_site_url(path, **owner)
    with pytest.raises(runtime.RuntimeSiteUrlUnavailable):
        runtime.publish_site_url(path, "https://sandbox.internal/", **owner)
    assert outside.read_text() == "untouched"

    path.unlink()
    runtime.publish_site_url(path, "https://sandbox.internal/", **owner)
    outside_link = tmp_path / "second-link"
    os.link(path, outside_link)
    with pytest.raises(runtime.RuntimeSiteUrlUnavailable):
        runtime.read_site_url(path, **owner)
    with pytest.raises(runtime.RuntimeSiteUrlUnavailable):
        runtime.publish_site_url(path, "https://next.test/", **owner)


def test_runtime_rejects_tampered_hash_schema_and_unsafe_owner(tmp_path: Path) -> None:
    runtime = _runtime()
    path, owner = _prepared(tmp_path)
    runtime.publish_site_url(path, "https://sandbox.internal/", **owner)
    data = json.loads(path.read_text())
    data["SITE_URL"] = "https://other.internal/"
    path.write_text(json.dumps(data))
    with pytest.raises(runtime.RuntimeSiteUrlUnavailable):
        runtime.read_site_url(path, **owner)

    path.write_text('{"version":1,"SITE_URL":"https://sandbox.internal/","sha256":1}')
    with pytest.raises(runtime.RuntimeSiteUrlUnavailable):
        runtime.read_site_url(path, **owner)

    with pytest.raises(runtime.RuntimeSiteUrlUnavailable):
        runtime.read_site_url(path, owner_uid=10001, owner_gid=owner["owner_gid"])
    with pytest.raises(runtime.RuntimeSiteUrlUnavailable):
        runtime.publish_site_url(
            path, "https://sandbox.internal/", owner_uid=10001, owner_gid=owner["owner_gid"]
        )


def test_runtime_requires_preprovisioned_exact_directory_and_no_secrets(tmp_path: Path) -> None:
    runtime = _runtime()
    path, owner = _prepared(tmp_path)
    with pytest.raises(runtime.RuntimeSiteUrlUnavailable):
        runtime.publish_site_url(path.with_name("wrong-name.json"), "https://site.test/", **owner)

    nonexistent = tmp_path / "missing" / path.name
    with pytest.raises(runtime.RuntimeSiteUrlUnavailable):
        runtime.publish_site_url(nonexistent, "https://site.test/", **owner)
    assert not nonexistent.parent.exists()

    path.parent.chmod(0o777)
    with pytest.raises(runtime.RuntimeSiteUrlUnavailable):
        runtime.publish_site_url(path, "https://site.test/", **owner)


@pytest.mark.parametrize(
    "invalid",
    [
        "https://user:secret@site.test/",
        "https://site.test/path?token=abc",
        "https://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
    ],
)
def test_runtime_rejects_credential_or_metadata_destination(tmp_path: Path, invalid: str) -> None:
    runtime = _runtime()
    path, owner = _prepared(tmp_path)
    with pytest.raises(runtime.SiteUrlInvalid):
        runtime.publish_site_url(path, invalid, **owner)
    assert not path.exists()
