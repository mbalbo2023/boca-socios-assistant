"""One-shot #834 recovery wiring and bounded runner; no live SSH."""

from __future__ import annotations

import copy
import hashlib
import io
import os
import re
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path
from typing import Any

import pytest

from test_ci_parallel_pytest_contract import assert_required_ci_covers

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from scripts import boca_protected_memfd_bootstrap as bootstrap  # noqa: E402
from scripts import build_protected_boca_bundle as builder  # noqa: E402

from test_r82_recovery_bundle import EXPECTED_RECOVERY_ENTRIES, _boot, _fixture_root  # noqa: E402
from test_r82_recovery_workflow import (  # noqa: E402
    HOST_STEP,
    REPO,
    VERIFY_STEP,
    _step_bash,
    _step_block,
    _workflow,
)
from test_r87_recovery_workflow import _gate, _run_inputs  # noqa: E402
from test_r94_worker_834_dispatch import (  # noqa: E402
    CURRENT_SHA,
    FAILED_ID,
    RELEASE_ID,
    TITLE,
    WITNESS_ID,
    evidence,
)

OPERATION = "cutover-a-worker-recover-834"
GATE_STEP = "Require exact 834/836 evidence and zero open PRs before recovery SSH"
MODE = "cutover-worker-834-recover"


def test_r94_distinct_protected_operation_and_unique_one_shot_marker() -> None:
    content = _workflow()
    assert content.count(f"'{TITLE}'") == 1
    options = next(
        line for line in content.splitlines() if "options: [inspect-prerequisites," in line
    )
    assert options.count(OPERATION) == 1
    assert f"inputs.operation == '{OPERATION}' && '{TITLE}'" in content
    gate = _step_block(GATE_STEP)
    host = _step_block(HOST_STEP)
    verify = _step_block(VERIFY_STEP)
    assert content.index(f"      - name: {GATE_STEP}") < content.index(f"      - name: {HOST_STEP}")
    assert f"if: inputs.operation == '{OPERATION}'" in gate
    assert "--r94" in gate and "gh api" in gate
    assert f"inputs.operation == '{OPERATION}'" in host
    assert f"inputs.operation == '{OPERATION}'" in verify
    assert MODE in host and "verify-834" in verify
    assert host.count("--worker-recovery") == 1
    assert len(re.findall(r"\bssh\s*\\", host)) == 1
    assert not re.search(r"(?m)^\s*(docker|curl|gh\s+run)\s", host)
    assert "ulimit -f 8 || exit 99" in host
    assert "mktemp -d" in host and "umask 077" in host
    assert "boca-worker-recovery-42375050546" in content


def test_r94_blank_protected_dispatch_inputs_pass_real_admission_bash() -> None:
    result = _run_inputs(operation=OPERATION)
    assert result.returncode == 0, (result.stdout, result.stderr)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("GITHUB_RUN_ATTEMPT", "2"),
        ("BOCA_SOURCE_SHA", "a" * 40),
        ("BOCA_SOURCE_SHA_SUBMITTED", CURRENT_SHA),
        ("BOCA_SERVICE", "browser-worker"),
        ("BOCA_BUDGET", "0.5cpu-256m-64pids"),
        ("BOCA_PROTECTED_ACTION_CONTEXT", str(FAILED_ID)),
        ("BOCA_LEGACY_CONTROLLER_ID", "f" * 64),
        ("BOCA_LEGACY_SOURCE_SHA", "f" * 40),
        ("BOCA_LEGACY_IMAGE_REF", "ghcr.io/foreign:latest"),
        ("BOCA_IMAGE_REF", "ghcr.io/foreign:latest"),
        ("BOCA_BROWSER_IMAGE_REF", "ghcr.io/foreign:latest"),
        ("BOCA_RELEASE_RUN_ID", str(RELEASE_ID)),
        ("BOCA_LEGACY_RELEASE_RUN_ID", "41893887078"),
        ("BOCA_HOST_READONLY_ENV_READY", "wrong"),
        ("BOCA_BROWSER_ENV_READY", "wrong"),
        ("BOCA_SITE_ENVELOPE", "private"),
    ],
)
def test_r94_forbid_extra_or_wrong_protected_inputs(field: str, value: str) -> None:
    result = _run_inputs({field: value}, operation=OPERATION)
    assert result.returncode != 0, field


def _responses(data: dict[str, Any], *, main: str = CURRENT_SHA) -> dict[str, Any]:
    prefix = f"repos/{REPO}"
    return {
        f"{prefix}/pulls?state=open&per_page=1": data["prs"],
        (
            f"{prefix}/actions/workflows/boca-first-deploy.yml/runs?"
            "event=workflow_dispatch&created=%3E%3D2026-11-07&per_page=100"
        ): data["history"],
        f"{prefix}/actions/runs/{FAILED_ID}": data["failed"],
        f"{prefix}/actions/runs/{WITNESS_ID}": data["witness"],
        f"{prefix}/actions/runs/{RELEASE_ID}": data["release"],
        f"{prefix}/actions/runs/{FAILED_ID}/attempts/1/jobs?per_page=100": data["failed_jobs"],
        f"{prefix}/actions/runs/{WITNESS_ID}/attempts/1/jobs?per_page=100": data["witness_jobs"],
        f"{prefix}/git/ref/heads/main": {
            "ref": "refs/heads/main",
            "object": {"type": "commit", "sha": main},
        },
    }


def _gate_r94(tmp_path: Path, data: dict[str, Any], *, main: str = CURRENT_SHA):
    return _gate(
        tmp_path,
        data,
        gate_step=GATE_STEP,
        responses=_responses(data, main=main),
    )


def test_r94_real_bash_fake_gh_accepts_eight_exact_rest_reads_pre_ssh(tmp_path: Path) -> None:
    result, calls = _gate_r94(tmp_path, evidence())
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "state=PASS incident=42375050546" in result.stdout
    assert "UNIQUE_R94" in (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert len(calls) == 8 and len(set(calls)) == 8


@pytest.mark.parametrize(
    "attack",
    ["open_pr", "duplicate", "wrong_step", "wrong_release", "moved_main", "missing_api"],
)
def test_r94_real_bash_fake_gh_denies_bad_provenance_before_ssh(
    tmp_path: Path, attack: str
) -> None:
    data = evidence()
    main = CURRENT_SHA
    if attack == "open_pr":
        data["prs"] = [{"number": 440, "draft": True}]
    elif attack == "duplicate":
        data["history"]["workflow_runs"].append(copy.deepcopy(data["history"]["workflow_runs"][0]))
        data["history"]["total_count"] += 1
    elif attack == "wrong_step":
        next(s for s in data["failed_jobs"]["jobs"][0]["steps"] if s["number"] == 61)[
            "conclusion"
        ] = "success"
    elif attack == "wrong_release":
        data["release"]["id"] += 1
    elif attack == "moved_main":
        main = "a" * 40
    else:
        data["witness_jobs"]["total_count"] = 2
    result, _ = _gate_r94(tmp_path, data, main=main)
    assert result.returncode != 0, (attack, result.stdout)
    summary = tmp_path / "summary.md"
    assert not summary.exists() or "state=PASS" not in summary.read_text(encoding="utf-8")


@pytest.mark.parametrize("transport", ["ssh_255", "oversized_stdout", "ulimit_failed"])
def test_r94_runner_uses_bounded_private_capture_and_one_fake_ssh(
    tmp_path: Path, transport: str
) -> None:
    """Execute real host Bash with a fake SSH executable: never host/Docker."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text(
        "#!/usr/bin/env python3\n"
        "import os,shlex,sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['FAKE_SSH_CALL']).write_text(shlex.split(sys.argv[-1])[-1])\n"
        "sys.stdout.buffer.write(b'HOST_PRIVATE_PAYLOAD' * int(os.environ['FAKE_MULTIPLIER']))\n"
        "sys.stderr.write('HOST_PRIVATE_ERROR_NEVER_LEAK')\n"
        "raise SystemExit(int(os.environ['FAKE_SSH_RC']))\n",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o700)
    env = os.environ.copy()
    env.update(
        BOCA_OPERATION=OPERATION,
        PATH=f"{fake_bin}:{os.environ['PATH']}",
        RUNNER_TEMP=str(tmp_path),
        GITHUB_ENV=str(tmp_path / "env"),
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        FAKE_SSH_CALL=str(tmp_path / "ssh.call"),
        FAKE_MULTIPLIER="500" if transport == "oversized_stdout" else "1",
        FAKE_SSH_RC="255" if transport == "ssh_255" else "0",
    )
    if transport == "ulimit_failed":
        startup = tmp_path / "bash-startup"
        startup.write_text("ulimit() { return 1; }\n", encoding="utf-8")
        env["BASH_ENV"] = str(startup)
    result = subprocess.run(  # noqa: S603 - all SSH intercepted; local code only
        ("bash", "-c", "set -euo pipefail\n" + textwrap.dedent(_step_bash(HOST_STEP))),  # noqa: S607
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode != 0
    assert "HOST_PRIVATE_PAYLOAD" not in result.stdout + result.stderr
    assert "HOST_PRIVATE_ERROR_NEVER_LEAK" not in result.stdout + result.stderr
    if transport == "ulimit_failed":
        assert not (tmp_path / "ssh.call").exists()
    else:
        assert (tmp_path / "ssh.call").read_text(encoding="ascii") == MODE
    private_dirs = list(tmp_path.glob("boca-worker-recovery.????????"))
    assert len(private_dirs) == 1
    private = private_dirs[0]
    assert private.stat().st_mode & 0o777 == 0o700
    receipt = private / "receipt"
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert receipt.stat().st_size <= 8192


def test_r94_recovery_zip_exact_allowlist_sha_and_bootstrap_mode(tmp_path: Path) -> None:
    fixture = _fixture_root(tmp_path)
    fake = (
        "def main(argv):\n"
        "    if argv == ['host-834']:\n"
        "        print('BOCA_SYNTHETIC_834 host=UNTOUCHED')\n"
        "        return 0\n"
        "    return 3\n"
    ).encode("ascii")
    (fixture / "scripts/host_cutover_worker_recovery.py").write_bytes(fake)
    bundle = tmp_path / "recover-834.pyz"
    digest = builder.build(fixture, bundle, worker_recovery=True)
    raw = bundle.read_bytes()
    assert digest == hashlib.sha256(raw).hexdigest()
    assert len(raw) <= 128000
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert set(archive.namelist()) == EXPECTED_RECOVERY_ENTRIES
        assert len(archive.namelist()) == 7
    bootstrap.verify(raw, digest, recovery=True)
    with pytest.raises(ValueError):
        bootstrap.verify(raw, digest, recovery=False)
    result = _boot(raw, digest, MODE)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert result.stdout == b"BOCA_SYNTHETIC_834 host=UNTOUCHED\n"
    for wrong in ("cutover-a-apply", "cutover-worker-835-recover"):
        denied = _boot(raw, digest, wrong)
        assert denied.returncode != 0
        assert b"BOCA_SYNTHETIC_834" not in denied.stdout


def test_r94_historical_recovery_zip_modes_and_prod_pin_remain(tmp_path: Path) -> None:
    output = tmp_path / "real.pyz"
    digest = builder.build(ROOT, output, worker_recovery=True)
    raw = output.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    bootstrap.verify(raw, digest, recovery=True)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert set(archive.namelist()) == EXPECTED_RECOVERY_ENTRIES
        script = archive.read("scripts/host_cutover_worker_recovery.py")
        entry = archive.read("__main__.py")
        for attempt in (b"42329475083", b"42341290485", b"42353468231", b"42368541950"):
            assert attempt in script
        assert b"42375050546" in script
        assert b"cutover-worker-834-recover" in entry


def test_r94_protected_pr_validation_includes_all_three_new_suites() -> None:
    assert_required_ci_covers(
        "tests/test_r94_worker_834_recovery.py",
        "tests/test_r94_worker_834_dispatch.py",
        "tests/test_r94_worker_834_workflow.py",
    )
