"""G17 #1241 fixed read-only selector, sealed tiny ZIP, private runner framing."""

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
SELECTOR = "boca-pair-upgrade-incident-observe-1241"
EXPECTED = {
    "__main__.py",
    "boca_socios/__init__.py",
    "boca_socios/host_cutover_stage.py",
    "boca_socios/host_boca_pair_upgrade_incident_readonly.py",
}


def test_exact_tiny_host_bundle_is_reproducible_and_contains_no_mutating_actor(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.pyz"
    second = tmp_path / "second.pyz"
    digest = builder.build(ROOT, first, pair_upgrade_incident_observe_1241=True)
    assert builder.build(ROOT, second, pair_upgrade_incident_observe_1241=True) == digest
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert set(archive.namelist()) == EXPECTED
        assert "host_boca_pair_upgrade.py" not in archive.namelist()
        assert "host_boca_pair_upgrade_cli.py" not in archive.namelist()
        assert b"boca-pair-upgrade-incident-observe-1241" in archive.read("__main__.py")
    bootstrap.verify(first.read_bytes(), digest, pair_upgrade_incident_observe_1241=True)
    with pytest.raises(ValueError):
        bootstrap.verify(first.read_bytes(), "0" * 64, pair_upgrade_incident_observe_1241=True)
    with pytest.raises(ValueError):
        bootstrap.verify(first.read_bytes(), digest, pair_upgrade=True)


def test_selector_has_exact_owner_main_gate_and_private_runner_channel() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    options = next(
        line
        for line in workflow.splitlines()
        if line.strip().startswith("options: [inspect-prerequisites")
    )
    assert options.count(SELECTOR) == 1
    assert f"if: inputs.operation == '{SELECTOR}'" in workflow
    # New #1251 reader shares the same exact owner-only read-only case gate.
    assert f"{SELECTOR}|boca-pair-upgrade-incident-observe-1251)" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "github.actor == 'mbalbo2023'" in workflow
    assert "check_main_ref.py" in workflow
    step = workflow.split(
        '      - name: "Observe exact G17 #1241 durable terminal READ_ONLY"\n', 1
    )[1].split("      - name: ", 1)[0]
    assert "--pair-upgrade-incident-observe-1241" in step
    assert "timeout --signal=TERM --kill-after=5s 120s ssh" in step
    assert "timeout-minutes: 3" in step
    assert "umask 077" in step
    assert "O_CREAT | os.O_EXCL" in step or "mktemp" in step
    assert "private" in step and "trap" in step
    assert '> "$receipt_dir/private" 2>/dev/null' in step
    assert '"$receipt_dir/private"' in step
    assert "$GITHUB_STEP_SUMMARY" in step
    assert "BOCA_G17_INCIDENT_READONLY_V1" in step
    assert "boca-target" in step
    assert "no-retry" in step.lower() or "GITHUB_RUN_ATTEMPT" in workflow
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


def test_new_memfd_archive_fails_as_full_cutover_and_extra_members(tmp_path: Path) -> None:
    archive = tmp_path / "host.pyz"
    digest = builder.build(ROOT, archive, pair_upgrade_incident_observe_1241=True)
    raw = archive.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    with pytest.raises(ValueError):
        bootstrap.verify(raw, digest)
