"""Dedicated rootless metadata observer never shares an effectful ZIP entrypoint."""

from __future__ import annotations

import hashlib
import io
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import boca_protected_memfd_bootstrap as bootstrap  # noqa: E402
import build_protected_boca_bundle as builder  # noqa: E402


def test_r258_rootless_observer_has_own_checked_readonly_memfd_entrypoint(
    tmp_path: Path,
) -> None:
    target = tmp_path / "rootless-readonly.pyz"
    digest = builder.build(ROOT, target, rootless_mapped_observe=True)
    raw = target.read_bytes()
    bootstrap.verify(raw, digest, rootless_mapped_observe=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = set(archive.namelist())
        assert names == bootstrap.ROOTLESS_MAPPED_ENTRIES
        assert "boca_socios/host_boca_rootless_mapped_custody.py" in names
        assert "boca_socios/host_boca_rootless_mapping_cli.py" in names
        assert all(not item.startswith("release/") for item in names)
        assert "compose.beta.yaml" not in names
        assert "compose.beta.browser.yaml" not in names
        assert "docker/seccomp_profile.json" not in names
        assert not any("browser/" in item for item in names)
        assert b"boca-rootless-mapping-observe" in archive.read("__main__.py")
        assert b"boca-pair-upgrade-apply" not in archive.read("__main__.py")
        assert len(raw) <= 480_000
        assert sum(item.file_size for item in archive.infolist()) <= 1_400_000

    isolated = subprocess.run(  # noqa: S603 - fixed local interpreter/import, no host effects
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import sys; sys.path.insert(0,sys.argv[1]); "
            "from boca_socios.host_boca_rootless_mapping_cli import main; "
            "assert callable(main)",
            str(target),
        ],
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert (isolated.returncode, isolated.stdout, isolated.stderr) == (0, b"", b"")
    second = tmp_path / "rootless-readonly-again.pyz"
    assert builder.build(ROOT, second, rootless_mapped_observe=True) == digest
    assert second.read_bytes() == raw
    with pytest.raises(ValueError, match="allowlist"):
        bootstrap.verify(raw, digest, pair_upgrade=True)


def test_r258_rootless_observer_rejects_missing_cli_even_with_recomputed_digest(
    tmp_path: Path,
) -> None:
    target = tmp_path / "rootless-readonly.pyz"
    builder.build(ROOT, target, rootless_mapped_observe=True)
    changed = io.BytesIO()
    with (
        zipfile.ZipFile(target) as trusted,
        zipfile.ZipFile(changed, "w", compression=zipfile.ZIP_DEFLATED) as tampered,
    ):
        for entry in trusted.infolist():
            if entry.filename != "boca_socios/host_boca_rootless_mapping_cli.py":
                tampered.writestr(entry, trusted.read(entry.filename))
    raw = changed.getvalue()
    with pytest.raises(ValueError, match="allowlist"):
        bootstrap.verify(raw, hashlib.sha256(raw).hexdigest(), rootless_mapped_observe=True)


def test_r258_rootless_observer_rejects_high_ratio_archive_with_matching_digest(
    tmp_path: Path,
) -> None:
    target = tmp_path / "rootless-readonly.pyz"
    builder.build(ROOT, target, rootless_mapped_observe=True)
    changed = io.BytesIO()
    with (
        zipfile.ZipFile(target) as trusted,
        zipfile.ZipFile(changed, "w", compression=zipfile.ZIP_DEFLATED) as tampered,
    ):
        for entry in trusted.infolist():
            data = trusted.read(entry.filename)
            if entry.filename.endswith(".py"):
                data = b"X" * len(data)
            tampered.writestr(entry, data)
    raw = changed.getvalue()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        expanded = sum(item.file_size for item in archive.infolist())
    assert expanded <= 1_400_000
    assert expanded > len(raw) * 8
    with pytest.raises(ValueError, match="compression ratio"):
        bootstrap.verify(raw, hashlib.sha256(raw).hexdigest(), rootless_mapped_observe=True)
