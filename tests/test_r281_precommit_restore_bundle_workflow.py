"""R281 recovery must be a single owner-dispatch, fixed-source and exact ZIP."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import boca_protected_memfd_bootstrap as bootstrap  # noqa: E402
import build_protected_boca_bundle as builder  # noqa: E402


def test_fixed_recovery_zip_is_bounded_and_excludes_browser_blackbox(tmp_path: Path) -> None:
    package = tmp_path / "recovery.pyz"
    digest = builder.build(ROOT, package, precommit_restore=True)
    raw = package.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    bootstrap.verify(raw, digest, precommit_restore=True)
    with zipfile.ZipFile(package) as archive:
        names = set(archive.namelist())
    assert names == bootstrap.PRECOMMIT_RESTORE_ENTRIES
    assert "boca_socios/host_boca_pair_precommit_restore.py" in names
    assert "boca_socios/host_on_demand_replace.py" in names
    assert "boca_socios/host_boca_park_incident_readonly.py" in names
    assert "boca_socios/host_boca_pair_upgrade_backend.py" not in names
    assert not any("synthetic.py" in name or "ipc_worker.py" in name for name in names)
    assert "compose.beta.yaml" not in names
    with pytest.raises(ValueError):
        bootstrap.verify(raw, digest, postcommit_finalize=True)
    with pytest.raises(ValueError):
        builder.build(ROOT, tmp_path / "mixed.pyz", precommit_restore=True, pair_upgrade=True)


def test_isolated_bundle_import_receipt_roundtrip(tmp_path: Path) -> None:
    package = tmp_path / "recovery.pyz"
    builder.build(ROOT, package, precommit_restore=True)
    # Only import and parse known bounded public receipt, never execute host mode.
    command = (
        "import sys; sys.path.insert(0,sys.argv[1]); "
        "from boca_socios.host_boca_pair_precommit_restore import encode,verify; "
        "receipt=encode('999','NO_GO'); assert verify(receipt,'999')==receipt"
    )
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-B", "-c", command, str(package)],
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8")[:300]


def test_manual_recovery_is_distinct_single_fixed_incident_operation() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    body = yaml.safe_load(workflow)
    options = body[True]["workflow_dispatch"]["inputs"]["operation"]["options"]
    assert options.count("boca-precommit-restore-one-shot") == 1
    assert "if: inputs.operation == 'boca-precommit-restore-one-shot'" in workflow
    assert "--precommit-restore" in workflow
    assert "boca-precommit-restore-one-shot" in workflow
    assert 'test "$GITHUB_ACTOR" = mbalbo2023' in workflow
    assert 'test "$GITHUB_TRIGGERING_ACTOR" = mbalbo2023' in workflow
    assert 'test "$GITHUB_RUN_ATTEMPT" = 1' in workflow
    assert "43489690300" in workflow
    assert "43479367282" in workflow
    assert '"$BOCA_SOURCE_SHA_SUBMITTED" "$BOCA_PROTECTED_ACTION_CONTEXT"' in workflow
    assert 'if [[ "$BOCA_OPERATION" = boca-precommit-restore-one-shot' not in workflow
