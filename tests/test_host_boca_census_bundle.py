"""The current rootless census has a separate, minimal, inert memfd ZIP."""

from __future__ import annotations

import hashlib
import io
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import boca_protected_memfd_bootstrap as bootstrap  # noqa: E402
import build_protected_boca_bundle as builder  # noqa: E402


def test_census_archive_is_tiny_deterministic_and_separate_from_effectful_dispatch(tmp_path):
    first = tmp_path / "census-first.pyz"
    second = tmp_path / "census-second.pyz"
    digest = builder.build(ROOT, first, census=True)
    assert builder.build(ROOT, second, census=True) == digest
    raw = first.read_bytes()
    assert second.read_bytes() == raw
    assert hashlib.sha256(raw).hexdigest() == digest
    assert len(raw) <= builder.CENSUS_MAX_ARCHIVE_BYTES
    bootstrap.verify(raw, digest, census=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert set(archive.namelist()) == bootstrap.CENSUS_ENTRIES
        assert "boca_socios/host_first_deploy.py" not in archive.namelist()
        assert "boca_socios/host_boca_transaction.py" not in archive.namelist()
        assert "docker/seccomp_profile.json" not in archive.namelist()
        assert "compose.yaml" not in archive.namelist()
        assert b"cutover-a-census" in archive.read("__main__.py")
        assert b"host_boca_census" in archive.read("__main__.py")
        assert all(not name.startswith("boca_socios/browser/") for name in archive.namelist())


def test_census_bootstrap_rejects_other_modes_extra_entries_and_unpinned_digest(tmp_path):
    path = tmp_path / "census.pyz"
    digest = builder.build(ROOT, path, census=True)
    raw = path.read_bytes()
    with pytest.raises(ValueError):
        bootstrap.verify(raw, "0" * 64, census=True)
    with pytest.raises(ValueError):
        bootstrap.verify(raw, digest)
    with pytest.raises(ValueError):
        bootstrap.verify(raw, digest, recovery=True)
    with pytest.raises(ValueError):
        bootstrap.verify(raw, digest, census=True, worker_physical=True)
    with pytest.raises(ValueError):
        builder.build(ROOT, tmp_path / "bad.pyz", census=True, worker_w1=True)

    changed = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as src, zipfile.ZipFile(changed, "w") as dst:
        for name in src.namelist():
            dst.writestr(name, src.read(name))
        dst.writestr("boca_socios/host_boca_transaction.py", b"raise SystemExit(3)\n")
    modified = changed.getvalue()
    with pytest.raises(ValueError):
        bootstrap.verify(modified, hashlib.sha256(modified).hexdigest(), census=True)
