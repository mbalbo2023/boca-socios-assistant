"""G18 #1251: fixed precommit incident reader, private channel, no APPLY retry."""

from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import boca_protected_memfd_bootstrap as bootstrap  # noqa: E402
from scripts import build_protected_boca_bundle as builder  # noqa: E402

WORKFLOW = ROOT / ".github/workflows/boca-first-deploy.yml"
SELECTOR = "boca-pair-upgrade-incident-observe-1251"
EXPECTED = {
    "__main__.py",
    "boca_socios/__init__.py",
    "boca_socios/host_cutover_stage.py",
    "boca_socios/host_boca_pair_upgrade_incident_readonly.py",
}


def test_1251_tiny_zip_is_exact_readonly_and_distinct_from_1241(tmp_path: Path) -> None:
    target = tmp_path / "host.pyz"
    digest = builder.build(ROOT, target, pair_upgrade_incident_observe_1251=True)
    raw = target.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    with zipfile.ZipFile(target) as archive:
        assert set(archive.namelist()) == EXPECTED
        assert b"boca-pair-upgrade-incident-observe-1251" in archive.read("__main__.py")
        assert b"boca-pair-upgrade-incident-observe-1241" not in archive.read("__main__.py")
        assert "boca_socios/host_boca_pair_upgrade_cli.py" not in archive.namelist()
        assert "boca_socios/host_boca_pair_upgrade.py" not in archive.namelist()
    bootstrap.verify(raw, digest, pair_upgrade_incident_observe_1251=True)
    with pytest.raises(ValueError):
        bootstrap.verify(raw, "0" * 64, pair_upgrade_incident_observe_1251=True)
    with pytest.raises(ValueError):
        bootstrap.verify(raw, digest, pair_upgrade_incident_observe_1241=True)
    with pytest.raises(ValueError):
        bootstrap.verify(raw, digest, pair_upgrade=True)
    with pytest.raises(ValueError):
        builder.build(
            ROOT,
            tmp_path / "both.pyz",
            pair_upgrade_incident_observe_1241=True,
            pair_upgrade_incident_observe_1251=True,
        )


def test_1251_selector_is_exact_owner_main_only_and_private() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    options = next(
        line
        for line in workflow.splitlines()
        if line.strip().startswith("options: [inspect-prerequisites")
    )
    assert options.count(SELECTOR) == 1
    assert f"if: inputs.operation == '{SELECTOR}'" in workflow
    assert f"{SELECTOR})" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "github.actor == 'mbalbo2023'" in workflow
    assert "check_main_ref.py" in workflow
    step = workflow.split(
        '      - name: "Observe exact G18 #1251 precommit evidence READ_ONLY"\n', 1
    )[1].split("      - name: ", 1)[0]
    assert "--pair-upgrade-incident-observe-1251" in step
    assert "timeout --signal=TERM --kill-after=5s 120s ssh" in step
    assert "timeout-minutes: 3" in step
    assert "umask 077" in step
    assert "O_CREAT | os.O_EXCL" in step
    assert "trap " in step
    assert '> "$receipt_dir/private" 2>/dev/null' in step
    assert '"$receipt_dir/private"' in step
    assert "$GITHUB_STEP_SUMMARY" in step
    assert "BOCA_G18_INCIDENT_1251_READONLY_V1" in step
    assert "boca-target" in step
    assert "GITHUB_RUN_ATTEMPT" in workflow
    assert not any(
        forbidden in step
        for forbidden in (
            "docker ",
            "systemctl ",
            "sqlite3",
            "gh run download",
            "gh run upload",
            "tee ",
            'cat "$receipt_dir/private"',
            'echo "$verified"',
            "--pair-upgrade ",
            "boca-pair-upgrade-apply",
        )
    )
