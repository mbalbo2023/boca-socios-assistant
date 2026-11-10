"""Offline W1 ZIP/bootloader acceptance: no Docker, no BLACKBOX and no host mutations."""

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


def _build(tmp_path: Path) -> tuple[bytes, str]:
    path = tmp_path / "boca-worker-w1.pyz"
    digest = builder.build(ROOT, path, worker_w1=True)
    return path.read_bytes(), digest


def _bootstrap(
    raw: bytes, digest: str, operation: str, run_id: str
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - fixed interpreter and protected checked local bootstrap
        [
            sys.executable,
            "-S",
            str(ROOT / "scripts" / "boca_protected_memfd_bootstrap.py"),
            digest,
            operation,
            run_id,
        ],
        input=raw,
        capture_output=True,
        timeout=15,
        check=False,
    )


def test_w1_zip_allowlist_isolated_from_full_cutover_and_blackbox(tmp_path: Path) -> None:
    raw, digest = _build(tmp_path)
    assert 0 < len(raw) < builder.W1_MAX_ARCHIVE_BYTES
    assert hashlib.sha256(raw).hexdigest() == digest
    bootstrap.verify(raw, digest, worker_w1=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = set(archive.namelist())
        assert names == bootstrap.W1_ENTRIES
        assert "boca_socios/host_worker_w1.py" in names
        assert "boca_socios/host_boca_transaction.py" not in names
        assert "boca_socios/host_boca_cutover.py" not in names
        assert not any("synthetic.py" in name or "ipc_worker.py" in name for name in names)
        assert archive.read("__main__.py") == builder.W1_MAIN
    with pytest.raises(ValueError, match="allowlist mismatch"):
        bootstrap.verify(raw, digest)
    with pytest.raises(ValueError, match="mismatch"):
        bootstrap.verify(raw, digest, recovery=True)


def test_w1_verified_stdlib_only_memfd_import_rejects_bad_run_before_host(tmp_path: Path) -> None:
    raw, digest = _build(tmp_path)
    result = _bootstrap(raw, digest, "worker-diagnose-once", "0")
    assert result.returncode == 3, (result.stdout, result.stderr)
    assert result.stdout == b"BOCA_WORKER_W1 result=NO_GO\n"
    assert result.stderr == b""


def test_w1_rejects_wrong_digest_or_wrong_dispatch_without_host(tmp_path: Path) -> None:
    raw, digest = _build(tmp_path)
    wrong_hash = _bootstrap(raw, "0" * 64, "worker-diagnose-once", "0")
    assert wrong_hash.returncode == 1
    assert b"state=PASS" not in wrong_hash.stdout

    wrong_operation = _bootstrap(raw, digest, "cutover-a-apply", "0")
    assert wrong_operation.returncode != 0
    assert b"state=PASS" not in wrong_operation.stdout


def test_w1_mode_exclusive_at_builder_and_bootstrap(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="exclusive"):
        builder.build(ROOT, tmp_path / "invalid.pyz", worker_w1=True, worker_recovery=True)
    with pytest.raises(ValueError, match="exclusive"):
        bootstrap.verify(b"", "0" * 64, worker_w1=True, worker_preflight=True)
