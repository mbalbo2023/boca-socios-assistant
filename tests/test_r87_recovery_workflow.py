"""R87 genuine protected Bash contract, using offline REST and SSH stand-ins.

No test dispatches Actions, invokes Docker or accesses any real Boca host.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from scripts import host_cutover_worker_inspect as observer  # noqa: E402
from scripts import host_cutover_worker_recovery as recovery  # noqa: E402

from test_r82_recovery_workflow import (  # noqa: E402
    HOST_STEP,
    INPUT_STEP,
    REPO,
    VERIFY_STEP,
    _input_environment,
    _step_bash,
    _step_block,
    _workflow,
)
from test_r87_recovery_dispatch import evidence  # noqa: E402

OPERATION = "cutover-a-worker-recover-819"
TITLE = "BOCA-R87-WORKER-819-RECOVER-ONCE"
GATE_STEP = "Require exact 819/821 evidence and zero open PRs before recovery SSH"
SOURCE = "b" * 40
RUN_ID = "99999999999"


def _env() -> dict[str, str]:
    env = _input_environment()
    env["BOCA_OPERATION"] = OPERATION
    return env


def _run_inputs(
    overrides: dict[str, str] | None = None, *, operation: str = OPERATION
) -> subprocess.CompletedProcess[str]:
    env = _env()
    env["BOCA_OPERATION"] = operation
    env.update(overrides or {})
    return subprocess.run(  # noqa: S603 - extracted local admission Bash only
        ("bash", "-c", "set -euo pipefail\n" + _step_bash(INPUT_STEP)),  # noqa: S607
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def test_r87_unique_exact_operation_and_protected_steps() -> None:
    text = _workflow()
    assert text.count(f"'{TITLE}'") == 1
    assert f"inputs.operation == '{OPERATION}' && '{TITLE}'" in text
    options = next(line for line in text.splitlines() if "options: [inspect-prerequisites," in line)
    assert options.count(OPERATION) == 1
    gate = _step_block(GATE_STEP)
    host = _step_block(HOST_STEP)
    verify = _step_block(VERIFY_STEP)
    assert text.index(f"      - name: {GATE_STEP}") < text.index(f"      - name: {HOST_STEP}")
    assert f"if: inputs.operation == '{OPERATION}'" in gate
    assert f"inputs.operation == '{OPERATION}'" in host
    assert f"inputs.operation == '{OPERATION}'" in verify
    assert "--r87" in gate and "gh api" in gate
    assert "cutover-worker-819-recover" in host
    assert "verify-819" in verify
    assert host.count("--worker-recovery") == 1
    assert len(re.findall(r"\bssh\s*\\", host)) == 1
    assert not re.search(r"(?m)^\s*docker\s", host)
    assert "ulimit -f 8 || exit 99" in host
    assert "mktemp -d" in host and "umask 077" in host
    assert "BOCA_WORKER_RECOVERY_RECEIPT" in host and "BOCA_WORKER_RECOVERY_RECEIPT" in verify
    assert "boca-worker-recovery-42353468231" in text


def test_r87_default_blank_dispatch_passes_actual_input_admission() -> None:
    result = _run_inputs()
    assert result.returncode == 0, (result.stdout, result.stderr)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("GITHUB_RUN_ATTEMPT", "2"),
        ("BOCA_SOURCE_SHA", "a" * 40),
        ("BOCA_SOURCE_SHA_SUBMITTED", SOURCE),
        ("BOCA_SERVICE", "browser-worker"),
        ("BOCA_BUDGET", "0.5cpu-256m-64pids"),
        ("BOCA_HOST_READONLY_ENV_READY", "not-ready"),
        ("BOCA_DEPLOY_ENV_READY", "not-ready"),
        ("BOCA_BETA_ENV_READY", "not-ready"),
        ("BOCA_BROWSER_ENV_READY", "not-ready"),
        ("BOCA_PROTECTED_ACTION_CONTEXT", "42353468231"),
        ("BOCA_INCIDENT_PREPARE_RUN_ID", "42352641660"),
        ("BOCA_RELEASE_RUN_ID", "42352641660"),
        ("BOCA_IMAGE_REF", "ghcr.io/example/controller"),
        ("BOCA_BROWSER_IMAGE_REF", "ghcr.io/example/browser"),
        ("BOCA_LEGACY_SOURCE_SHA", "a" * 40),
        ("BOCA_LEGACY_IMAGE_REF", "ghcr.io/example/original"),
        ("BOCA_LEGACY_CONTROLLER_ID", "a" * 64),
        ("BOCA_SITE_ENVELOPE", "forged"),
        ("BOCA_TELEGRAM_ENVELOPE", "forged"),
        ("BOCA_OWNER_CAPABILITY_SHA256", "a" * 64),
        ("BOCA_OFFICIAL_CONTROLLER_ID", "a" * 64),
    ],
)
def test_r87_mutable_or_invalid_inputs_rejected(field: str, value: str) -> None:
    assert _run_inputs({field: value}).returncode != 0, field


def _responses(data: dict[str, Any]) -> dict[str, Any]:
    prefix = f"repos/{REPO}"
    return {
        f"{prefix}/pulls?state=open&per_page=1": data["prs"],
        (
            f"{prefix}/actions/workflows/boca-first-deploy.yml/runs?"
            "event=workflow_dispatch&created=%3E%3D2026-11-07&per_page=100"
        ): data["history"],
        f"{prefix}/actions/runs/42353468231": data["failed"],
        f"{prefix}/actions/runs/42355552701": data["witness"],
        f"{prefix}/actions/runs/42352641660": data["release"],
        f"{prefix}/actions/runs/42353468231/attempts/1/jobs?per_page=100": data["failed_jobs"],
        f"{prefix}/actions/runs/42355552701/attempts/1/jobs?per_page=100": data["witness_jobs"],
        f"{prefix}/git/ref/heads/main": {
            "ref": "refs/heads/main",
            "object": {"type": "commit", "sha": SOURCE},
        },
    }


def _gate(
    tmp_path: Path,
    data: dict[str, Any],
    *,
    bad_main: bool = False,
    missing: str | None = None,
    gate_step: str = GATE_STEP,
    responses: dict[str, Any] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bash = _step_bash(gate_step)
    assert not re.search(r"(?m)^\s*(ssh|docker|curl|gh\s+run)\s", bash)
    replies = _responses(data) if responses is None else responses
    if bad_main:
        replies[f"repos/{REPO}/git/ref/heads/main"]["object"]["sha"] = "a" * 40
    if missing is not None:
        del replies[missing]
    (tmp_path / "fake-gh.json").write_text(json.dumps(replies), encoding="utf-8")
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "with open(os.environ['BOCA_TEST_GH_CALLS'],'a',encoding='utf-8') as out:\n"
        "    out.write(sys.argv[2]+'\\n')\n"
        "with open(os.environ['BOCA_TEST_GH_DATA'],encoding='utf-8') as stream:\n"
        "    data=json.load(stream)\n"
        "print(json.dumps(data[sys.argv[2]]))\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o700)
    env = _env()
    env.update(
        GITHUB_REPOSITORY=REPO,
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        RUNNER_TEMP=str(tmp_path),
        GH_TOKEN="offline-fixture",
        BOCA_TEST_GH_DATA=str(tmp_path / "fake-gh.json"),
        BOCA_TEST_GH_CALLS=str(tmp_path / "calls.txt"),
        PYTHONPATH="src",
        PATH=f"{tmp_path}:{os.environ['PATH']}",
    )
    result = subprocess.run(  # noqa: S603 - fake-gh only; no host code
        ("bash", "-c", "set -euo pipefail\n" + bash),  # noqa: S607
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=12,
        check=False,
    )
    calls_file = tmp_path / "calls.txt"
    return result, calls_file.read_text(
        encoding="utf-8"
    ).splitlines() if calls_file.exists() else []


def test_r87_pre_host_gate_accepts_seven_authentic_receipts(tmp_path: Path) -> None:
    result, calls = _gate(tmp_path, evidence())
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "BOCA_WORKER_RECOVERY_GATE state=PASS incident=42353468231" in result.stdout
    assert "UNIQUE_R87" in (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert len(calls) == 8 and len(set(calls)) == 8
    assert f"repos/{REPO}/git/ref/heads/main" in calls


@pytest.mark.parametrize(
    "attack", ["open_pr", "second_dispatch", "wrong_step", "main_moved", "missing_api"]
)
def test_r87_pre_host_gate_rejects_adversarial_rest_provenance(tmp_path: Path, attack: str) -> None:
    data = evidence()
    bad_main = False
    missing = None
    if attack == "open_pr":
        data["prs"] = [{"number": 999, "draft": True}]
    elif attack == "second_dispatch":
        data["history"]["workflow_runs"].append({**data["history"]["workflow_runs"][0], "id": 1234})
        data["history"]["total_count"] += 1
    elif attack == "wrong_step":
        data["failed_jobs"]["jobs"][0]["steps"][58]["conclusion"] = "success"
    elif attack == "main_moved":
        bad_main = True
    else:
        missing = f"repos/{REPO}/actions/runs/42355552701/attempts/1/jobs?per_page=100"
    result, _ = _gate(tmp_path, data, bad_main=bad_main, missing=missing)
    assert result.returncode != 0, f"R87 gate accepted {attack}: {result.stdout}"
    summary = tmp_path / "summary.md"
    assert not summary.exists() or "state=PASS" not in summary.read_text(encoding="utf-8")


@pytest.mark.parametrize("host_outcome", ["failure", "success"])
def test_r87_terminal_step_rejects_missing_or_forged_receipt(
    tmp_path: Path, host_outcome: str
) -> None:
    private = tmp_path / "boca-worker-recovery.abcdefgh"
    private.mkdir(mode=0o700)
    receipt = private / "receipt"
    if host_outcome == "success":
        receipt.write_text(
            '{"version":"boca-worker-recovery-v1","cleanup":"VERIFIED"}', encoding="ascii"
        )
    env = _env()
    env.update(
        RUNNER_TEMP=str(tmp_path),
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        BOCA_WORKER_RECOVERY_RECEIPT=str(receipt),
        BOCA_WORKER_RECOVERY_HOST_OUTCOME=host_outcome,
        PYTHONPATH="src:.",
    )
    result = subprocess.run(  # noqa: S603 - local verifier only
        ("bash", "-c", "set -euo pipefail\n" + _step_bash(VERIFY_STEP)),  # noqa: S607
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    assert result.returncode != 0, (result.stdout, result.stderr)
    assert "state=NO_GO" in (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert not receipt.exists() and not private.exists()


@pytest.mark.parametrize(
    ("preplant", "receipt_symlink"), [(False, False), (True, False), (False, True)]
)
def test_r87_terminal_step_accepts_exact_receipt_without_overwriting_runner_paths(
    tmp_path: Path, preplant: bool, receipt_symlink: bool
) -> None:
    private = tmp_path / "boca-worker-recovery.abcdefgh"
    private.mkdir(mode=0o700)
    receipt = private / "receipt"
    signed = {
        "version": "boca-worker-recovery-v1",
        "attempt": recovery.TARGET_819.attempt,
        "probe_id": recovery.TARGET_819.cid,
        "legacy_id": recovery.LEGACY_ID,
        "cleanup": "VERIFIED",
        "phase": "COMPLETE",
        "docker_writes": 1,
        "foreign_resources_touched": False,
        "cutover_authorized": False,
        "retry_authorized": False,
        "original": "RUNNING_HEALTHY",
    }
    valid_receipt = observer.canonical(signed) + b"\n"
    if receipt_symlink:
        private_payload = tmp_path / "origin"
        private_payload.write_bytes(valid_receipt)
        receipt.symlink_to(private_payload)
    else:
        receipt.write_bytes(valid_receipt)
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("PRESERVE", encoding="ascii")
    output = tmp_path / "boca-worker-recovery.verified.json"
    if preplant:
        output.symlink_to(sentinel)
    env = _env()
    env.update(
        RUNNER_TEMP=str(tmp_path),
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        BOCA_WORKER_RECOVERY_RECEIPT=str(receipt),
        BOCA_WORKER_RECOVERY_HOST_OUTCOME="success",
        PYTHONPATH="src:.",
    )
    result = subprocess.run(  # noqa: S603 - isolated verified-record Bash, no SSH
        ("bash", "-c", "set -euo pipefail\n" + _step_bash(VERIFY_STEP)),  # noqa: S607
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    assert sentinel.read_text(encoding="ascii") == "PRESERVE"
    assert not private.exists() and not receipt.exists()
    if preplant or receipt_symlink:
        assert result.returncode != 0
        if preplant:
            assert output.is_symlink()
            assert "artifact=UNSAFE" in (tmp_path / "summary.md").read_text(encoding="utf-8")
        else:
            assert not output.exists()
            assert "state=NO_GO" in (tmp_path / "summary.md").read_text(encoding="utf-8")
    else:
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert output.read_bytes() == valid_receipt
        assert "state=CLEANED" in (tmp_path / "summary.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("transport", ["short", "oversized", "ssh_failure", "ulimit_failure"])
@pytest.mark.parametrize(
    ("operation", "expected_mode"),
    [
        ("cutover-a-worker-recover-819", "cutover-worker-819-recover"),
        ("cutover-a-worker-recover-827", "cutover-worker-827-recover"),
    ],
)
def test_r87_actual_host_bash_uses_private_file_limit_and_one_fake_ssh(
    tmp_path: Path, transport: str, operation: str, expected_mode: str
) -> None:
    """Real packaging/Bash, intercepted SSH: zero Docker/network operations."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text(
        "#!/usr/bin/env python3\n"
        "import os,resource,shlex,sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['FAKE_SSH_MARKER']).write_text('called')\n"
        "Path(os.environ['FAKE_SSH_LIMIT']).write_text(str(resource.getrlimit(resource.RLIMIT_FSIZE)[0]))\n"
        "Path(os.environ['FAKE_SSH_MODE']).write_text(str(os.fstat(1).st_mode & 0o777))\n"
        "Path(os.environ['FAKE_SSH_SELECTED_MODE']).write_text(shlex.split(sys.argv[-1])[-1])\n"
        "sys.stdout.buffer.write(b'PRIVATE_HOST_PAYLOAD' * int(os.environ['FAKE_SSH_MULTIPLIER']))\n"
        "sys.stderr.write('PRIVATE_SSH_ERROR_NEVER_PRINT')\n"
        "raise SystemExit(int(os.environ['FAKE_SSH_RC']))\n",
        encoding="utf-8",
    )
    fake_ssh.chmod(0o700)
    env = _env()
    env.update(
        BOCA_OPERATION=operation,
        PATH=f"{fake_bin}:{os.environ['PATH']}",
        RUNNER_TEMP=str(tmp_path),
        GITHUB_ENV=str(tmp_path / "env"),
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        FAKE_SSH_MARKER=str(tmp_path / "ssh.called"),
        FAKE_SSH_LIMIT=str(tmp_path / "ssh.limit"),
        FAKE_SSH_MODE=str(tmp_path / "ssh.mode"),
        FAKE_SSH_SELECTED_MODE=str(tmp_path / "ssh.selected_mode"),
        FAKE_SSH_MULTIPLIER="512" if transport == "oversized" else "1",
        FAKE_SSH_RC="255" if transport == "ssh_failure" else "0",
    )
    if transport == "ulimit_failure":
        startup = tmp_path / "bash-startup"
        startup.write_text("ulimit() { return 1; }\n", encoding="utf-8")
        env["BASH_ENV"] = str(startup)
    result = subprocess.run(  # noqa: S603 - intercepted SSH, no host action
        ("bash", "-c", "set -euo pipefail\n" + textwrap.dedent(_step_bash(HOST_STEP))),  # noqa: S607
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert "PRIVATE_HOST_PAYLOAD" not in result.stdout + result.stderr
    assert "PRIVATE_SSH_ERROR_NEVER_PRINT" not in result.stdout + result.stderr
    private_dirs = list(tmp_path.glob("boca-worker-recovery.????????"))
    assert len(private_dirs) == 1, (result.returncode, result.stdout, result.stderr)
    private = private_dirs[0]
    assert private.stat().st_mode & 0o777 == 0o700
    receipt = private / "receipt"
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert f"BOCA_WORKER_RECOVERY_RECEIPT={receipt}" in (tmp_path / "env").read_text()
    if transport == "ulimit_failure":
        assert not (tmp_path / "ssh.called").exists()
        assert result.returncode != 0
    else:
        assert (tmp_path / "ssh.called").read_text() == "called"
        assert (tmp_path / "ssh.limit").read_text() == "8192"  # 8 ulimit 1KiB blocks
        assert (tmp_path / "ssh.mode").read_text() == "384"  # 0600
        assert (tmp_path / "ssh.selected_mode").read_text() == expected_mode
        assert receipt.stat().st_size <= 8192
        assert (result.returncode == 0) is (transport == "short")


def test_r87_pr_validation_exercises_all_code_only_paths() -> None:
    block = _step_block("Validate protected Cutover A, Option B ZIP and cleanup offline only")
    for target in (
        "tests/test_r87_exact_worker_819_recovery.py",
        "tests/test_r87_recovery_bundle.py",
        "tests/test_r87_recovery_dispatch.py",
        "tests/test_r87_recovery_workflow.py",
    ):
        assert block.count(target) == 1
