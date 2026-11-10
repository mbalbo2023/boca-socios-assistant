"""Offline single-boot host package; never import the protected browser modules."""

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


def test_physical_zip_contains_only_typed_host_program_and_seccomp(tmp_path: Path) -> None:
    path = tmp_path / "boca-physical-worker.pyz"
    digest = builder.build(ROOT, path, worker_physical=True)
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    assert len(raw) < builder.PHYSICAL_MAX_ARCHIVE_BYTES
    bootstrap.verify(raw, digest, worker_physical=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert set(archive.namelist()) == bootstrap.PHYSICAL_ENTRIES
        assert "boca_socios/host_worker_physical.py" in archive.namelist()
        assert "docker/seccomp_profile.json" in archive.namelist()
        assert "boca_socios/host_boca_transaction.py" not in archive.namelist()
        assert all(
            "synthetic.py" not in name and "ipc_worker.py" not in name
            for name in archive.namelist()
        )


def test_physical_zip_rejects_wrong_mode_and_digest(tmp_path: Path) -> None:
    path = tmp_path / "boca-physical-worker.pyz"
    digest = builder.build(ROOT, path, worker_physical=True)
    with pytest.raises(ValueError):
        bootstrap.verify(path.read_bytes(), "0" * 64, worker_physical=True)
    with pytest.raises(ValueError):
        bootstrap.verify(path.read_bytes(), digest, worker_w1=True)
    with pytest.raises(ValueError):
        builder.build(ROOT, tmp_path / "bad.pyz", worker_physical=True, worker_w1=True)
