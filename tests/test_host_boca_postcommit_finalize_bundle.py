"""R186 finalizer must travel in its own SHA-pinned minimal host ZIP."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import boca_protected_memfd_bootstrap as bootstrap  # noqa: E402
import build_protected_boca_bundle as builder  # noqa: E402


def test_finalizer_zip_is_deterministic_exact_scope_and_no_blackbox(tmp_path: Path) -> None:
    first, second = tmp_path / "finalize-a.pyz", tmp_path / "finalize-b.pyz"
    sha = builder.build(ROOT, first, postcommit_finalize=True)
    assert builder.build(ROOT, second, postcommit_finalize=True) == sha
    raw = first.read_bytes()
    assert raw == second.read_bytes()
    bootstrap.verify(raw, sha, postcommit_finalize=True)
    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
    assert "boca_socios/host_boca_pair_postcommit_finalize.py" in names
    assert "boca_socios/host_on_demand_replace.py" in names
    assert "boca_socios/host_boca_pair_upgrade_backend.py" not in names
    assert "compose.beta.yaml" not in names
    assert not any("synthetic.py" in name or "ipc_worker.py" in name for name in names)
    assert names == bootstrap.POSTCOMMIT_FINALIZE_ENTRIES


def test_finalize_zip_is_not_approved_as_inert_witness(tmp_path: Path) -> None:
    target = tmp_path / "once.pyz"
    sha = builder.build(ROOT, target, postcommit_finalize=True)
    with pytest.raises(ValueError):
        bootstrap.verify(target.read_bytes(), sha, postcommit_observe=True)
    with pytest.raises(ValueError):
        builder.build(ROOT, tmp_path / "twice.pyz", postcommit_finalize=True, pair_upgrade=True)


def test_finalizer_zip_can_verify_original_terminal_under_isolated_python(tmp_path: Path) -> None:
    payload = tmp_path / "finalizer.pyz"
    builder.build(ROOT, payload, postcommit_finalize=True)
    # Execute only the bounded original receipt parser; no host or provider IO.
    code = (
        "import sys; sys.path.insert(0,sys.argv[1]); "
        "from boca_socios.host_boca_pair_postcommit_finalize import _journal; "
        "from boca_socios.host_boca_pair_upgrade_cli import verify_upgrade; "
        "from boca_socios.host_boca_pair_upgrade import PairUpgradeReceipt; "
        "from boca_socios.host_boca_pair_upgrade_cli import encode_upgrade; "
        "r=PairUpgradeReceipt('43217075287','NO_GO','INDETERMINATE',False,True,None,None,'RETIRE_OLD'); "
        "assert verify_upgrade(encode_upgrade(r),'43217075287') == encode_upgrade(r)"
    )
    result = subprocess.run(  # noqa: S603 - fixed test-owned interpreter and payload
        [sys.executable, "-I", "-B", "-c", code, str(payload)],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8")[:300]
