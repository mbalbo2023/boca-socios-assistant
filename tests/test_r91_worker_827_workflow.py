"""R91 protected Bash workflow exercised with offline fake GitHub REST.

The fake `gh` is confined to a temporary PATH; no host, Docker or Actions.
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from test_r82_recovery_workflow import (  # noqa: E402
    HOST_STEP,
    REPO,
    VERIFY_STEP,
    _step_block,
    _workflow,
)
from test_r87_recovery_workflow import _gate, _run_inputs  # noqa: E402
from test_r91_worker_827_dispatch import (  # noqa: E402
    CURRENT_SHA,
    FAILED_ID,
    RELEASE_ID,
    TITLE,
    WITNESS_ID,
    evidence,
)

OPERATION = "cutover-a-worker-recover-827"
GATE_STEP = "Require exact 827/829 evidence and zero open PRs before recovery SSH"


def _responses(data: dict[str, Any]) -> dict[str, Any]:
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
            "object": {"type": "commit", "sha": CURRENT_SHA},
        },
    }


def _gate_r91(tmp_path: Path, data: dict[str, Any], *, main: str = CURRENT_SHA):
    replies = _responses(data)
    replies[f"repos/{REPO}/git/ref/heads/main"]["object"]["sha"] = main
    return _gate(tmp_path, data, gate_step=GATE_STEP, responses=replies)


def test_r91_one_distinct_operation_and_only_one_shared_stopped_only_host_step() -> None:
    text = _workflow()
    options = next(line for line in text.splitlines() if "options: [inspect-prerequisites," in line)
    assert options.count(OPERATION) == 1
    assert text.count(f"'{TITLE}'") == 1
    assert f"inputs.operation == '{OPERATION}' && '{TITLE}'" in text
    gate = _step_block(GATE_STEP)
    host = _step_block(HOST_STEP)
    verify = _step_block(VERIFY_STEP)
    assert text.index(f"      - name: {GATE_STEP}") < text.index(f"      - name: {HOST_STEP}")
    assert f"if: inputs.operation == '{OPERATION}'" in gate
    assert "--r91" in gate and "gh api" in gate
    assert f"inputs.operation == '{OPERATION}'" in host
    assert "cutover-worker-827-recover" in host
    assert "verify-827" in verify
    assert "boca-worker-recovery-42368541950" in text
    assert host.count("--worker-recovery") == 1
    assert len(re.findall(r"\bssh\s*\\", host)) == 1
    assert not re.search(r"(?m)^\s*(docker|curl|gh\s+run)\s", host)
    assert "ulimit -f 8 || exit 99" in host and "mktemp -d" in host
    assert "^[A-Za-z0-9]" not in verify  # no arbitrary user-provided receipt path
    assert "^boca-worker-recovery\\.[A-Za-z0-9]{8}/receipt$" in verify


def test_r91_empty_dispatch_input_passes_actual_bash_gate() -> None:
    result = _run_inputs(operation=OPERATION)
    assert result.returncode == 0, (result.stdout, result.stderr)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("GITHUB_RUN_ATTEMPT", "2"),
        ("BOCA_SOURCE_SHA", "a" * 40),
        ("BOCA_SOURCE_SHA_SUBMITTED", CURRENT_SHA),
        ("BOCA_BUDGET", "0.5cpu-256m-64pids"),
        ("BOCA_PROTECTED_ACTION_CONTEXT", str(FAILED_ID)),
        ("BOCA_LEGACY_CONTROLLER_ID", "a" * 64),
        ("BOCA_RELEASE_RUN_ID", str(RELEASE_ID)),
        ("BOCA_BROWSER_IMAGE_REF", "fake"),
        ("BOCA_HOST_READONLY_ENV_READY", "wrong"),
        ("BOCA_BROWSER_ENV_READY", "wrong"),
        ("BOCA_SITE_ENVELOPE", "ciphertext"),
    ],
)
def test_r91_optional_inputs_or_wrong_protected_environment_denied(field: str, value: str) -> None:
    result = _run_inputs({field: value}, operation=OPERATION)
    assert result.returncode != 0, field


def test_r91_real_bash_rest_gate_passes_exact_eight_api_calls(tmp_path: Path) -> None:
    result, calls = _gate_r91(tmp_path, evidence())
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "state=PASS incident=42368541950" in result.stdout
    assert "UNIQUE_R91" in (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert len(calls) == 8 and len(set(calls)) == 8


@pytest.mark.parametrize(
    "attack", ["open_pr", "duplicate", "wrong_step", "wrong_release", "moved_main", "missing_api"]
)
def test_r91_bash_rest_gate_fails_before_any_host_access(tmp_path: Path, attack: str) -> None:
    data = evidence()
    main = CURRENT_SHA
    if attack == "open_pr":
        data["prs"] = [{"number": 432, "draft": True}]
    elif attack == "duplicate":
        data["history"]["workflow_runs"].append(copy.deepcopy(data["history"]["workflow_runs"][0]))
        data["history"]["total_count"] += 1
    elif attack == "wrong_step":
        next(s for s in data["failed_jobs"]["jobs"][0]["steps"] if s["number"] == 60)[
            "conclusion"
        ] = "success"
    elif attack == "wrong_release":
        data["release"]["id"] = 1234
    elif attack == "moved_main":
        main = "a" * 40
    else:
        data["witness_jobs"]["jobs"][0]["conclusion"] = "skipped"
    result, _ = _gate_r91(tmp_path, data, main=main)
    assert result.returncode != 0, f"R91 unsafe {attack} allowed: {result.stdout}"
    summary = tmp_path / "summary.md"
    assert not summary.exists() or "state=PASS" not in summary.read_text(encoding="utf-8")
