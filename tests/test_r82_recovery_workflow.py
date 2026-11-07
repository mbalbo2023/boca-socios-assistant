"""R82 protected Actions operation: exact routing, input denial, offline REST gate.

Run only isolated workflow Bash bodies and a fake GitHub REST CLI. No SSH,
Docker, Actions dispatch, or real GitHub mutation is exercised by these tests.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_r82_recovery_dispatch import _evidence  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "boca-first-deploy.yml"
OPERATION = "cutover-a-worker-recover-807"
TITLE = "BOCA-R82-WORKER-807-RECOVER-ONCE"
SOURCE = "b" * 40
RUN_ID = "99999999999"
GATE_STEP = "Require exact 807/809 evidence and zero open PRs before recovery SSH"
INPUT_STEP = "Require verified protected environment and matching main commit"
HOST_STEP = "Recover only the stopped exact 795 807 819 or 827 worker probe under Boca lease"
VERIFY_STEP = "Require exact terminal worker recovery receipt on every outcome"
REPO = "mbalbo2023/boca-socios-assistant"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _step_block(name: str) -> str:
    text = _workflow()
    marker = f"      - name: {name}\n"
    assert text.count(marker) == 1, f"missing or duplicated protected step: {name}"
    return text.split(marker, 1)[1].split("\n      - name:", 1)[0]


def _step_bash(name: str) -> str:
    block = _step_block(name)
    assert "        run: |\n" in block, f"missing Bash run body: {name}"
    return block.split("        run: |\n", 1)[1]


def _input_environment() -> dict[str, str]:
    env = dict(os.environ)
    blank_inputs = (
        "BOCA_PROTECTED_ACTION_CONTEXT",
        "BOCA_INCIDENT_PREPARE_RUN_ID",
        "BOCA_SOURCE_SHA_SUBMITTED",
        "BOCA_IMAGE_REF",
        "BOCA_BROWSER_IMAGE_REF",
        "BOCA_RELEASE_RUN_ID",
        "BOCA_LEGACY_SOURCE_SHA",
        "BOCA_LEGACY_IMAGE_REF",
        "BOCA_LEGACY_RELEASE_RUN_ID",
        "BOCA_LEGACY_CONTROLLER_ID",
        "BOCA_SITE_ENVELOPE",
        "BOCA_TELEGRAM_ENVELOPE",
        "BOCA_OWNER_ENVELOPE",
        "BOCA_OWNER_CAPABILITY_SHA256",
        "BOCA_FAILED_TELEGRAM_RUN_ID",
        "BOCA_OFFICIAL_CONTROLLER_ID",
        "BOCA_OFFICIAL_NEWS_RUN_ID",
        "BOCA_OFFICIAL_NEWS_SOURCE_SHA",
        "BOCA_OFFICIAL_NEWS_ARTIFACT_ID",
        "BOCA_OFFICIAL_NEWS_ZIP_SHA256",
        "BOCA_OFFICIAL_NEWS_JSONL_SHA256",
        "BOCA_OFFICIAL_NEWS_HTML_SHA256",
        "BOCA_OFFICIAL_NEWS_OBSERVED_AT_UTC",
        "BOCA_TELEGRAM_OWNER_READY",
        "BOCA_TELEGRAM_ENV_READY",
        "BOCA_TELEGRAM_EXPECTED_BOT_ID",
        "BOCA_TELEGRAM_EXPECTED_CHAT_HMAC",
    )
    env.update({key: "" for key in blank_inputs})
    env.update(
        BOCA_OPERATION=OPERATION,
        BOCA_SERVICE="controller",
        BOCA_BUDGET="1.5cpu-1024m-192pids",
        BOCA_SOURCE_SHA=SOURCE,
        GITHUB_SHA=SOURCE,
        GITHUB_RUN_ID=RUN_ID,
        GITHUB_RUN_ATTEMPT="1",
        BOCA_HOST_READONLY_ENV_READY="ready",
        BOCA_DEPLOY_ENV_READY="ready",
        BOCA_BETA_ENV_READY="ready",
        BOCA_BROWSER_ENV_READY="ready",
    )
    return env


def _inputs_result(*, overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    shell = _step_bash(INPUT_STEP)
    assert "ssh " not in shell and "docker " not in shell and "gh api" not in shell
    env = _input_environment()
    env.update(overrides or {})
    return subprocess.run(  # noqa: S603 - only extracted local assertions; no network/host
        ("bash", "-c", "set -euo pipefail\n" + shell),  # noqa: S607
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def test_r82_operation_has_one_exact_run_name_and_one_allowed_input_choice() -> None:
    text = _workflow()
    assert text.count("'BOCA-R80-WORKER-RECOVER-ONCE'") == 1
    assert text.count(f"'{TITLE}'") == 1
    assert f"inputs.operation == '{OPERATION}' && '{TITLE}'" in text
    option_line = next(
        line for line in text.splitlines() if "options: [inspect-prerequisites," in line
    )
    assert option_line.count(OPERATION) == 1
    assert option_line.count("cutover-a-worker-recover,") == 1
    assert "environment: boca-first-deploy" in text
    assert (
        "if: github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main' "
        "&& github.repository == 'mbalbo2023/boca-socios-assistant' && github.actor == 'mbalbo2023'"
    ) in text


def test_exact_r82_blank_inputs_and_fixed_budget_pass_actual_dispatch_bash() -> None:
    result = _inputs_result()
    assert result.returncode == 0, (result.stdout, result.stderr)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("GITHUB_RUN_ATTEMPT", "2"),
        ("BOCA_SOURCE_SHA", "a" * 40),
        ("BOCA_SOURCE_SHA_SUBMITTED", SOURCE),
        ("BOCA_SERVICE", "browser-worker"),
        ("BOCA_BUDGET", "0.5cpu-256m-64pids"),
        ("BOCA_BUDGET", "1.75cpu-1152m-224pids"),
        ("BOCA_HOST_READONLY_ENV_READY", "not-ready"),
        ("BOCA_DEPLOY_ENV_READY", "not-ready"),
        ("BOCA_BETA_ENV_READY", "not-ready"),
        ("BOCA_BROWSER_ENV_READY", "not-ready"),
        ("BOCA_PROTECTED_ACTION_CONTEXT", "42341290485"),
        ("BOCA_INCIDENT_PREPARE_RUN_ID", "42340930071"),
        ("BOCA_IMAGE_REF", "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64),
        (
            "BOCA_BROWSER_IMAGE_REF",
            "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "b" * 64,
        ),
        ("BOCA_RELEASE_RUN_ID", "42340930071"),
        ("BOCA_LEGACY_SOURCE_SHA", "a" * 40),
        ("BOCA_LEGACY_IMAGE_REF", "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64),
        ("BOCA_LEGACY_RELEASE_RUN_ID", "42329201039"),
        ("BOCA_LEGACY_CONTROLLER_ID", "a" * 64),
        ("BOCA_SITE_ENVELOPE", "forged"),
        ("BOCA_TELEGRAM_ENVELOPE", "forged"),
        ("BOCA_OWNER_ENVELOPE", "forged"),
        ("BOCA_OWNER_CAPABILITY_SHA256", "a" * 64),
        ("BOCA_FAILED_TELEGRAM_RUN_ID", "123456789"),
        ("BOCA_OFFICIAL_CONTROLLER_ID", "a" * 64),
        ("BOCA_OFFICIAL_NEWS_RUN_ID", "123456789"),
        ("BOCA_OFFICIAL_NEWS_SOURCE_SHA", "a" * 40),
        ("BOCA_OFFICIAL_NEWS_ARTIFACT_ID", "123456789"),
        ("BOCA_OFFICIAL_NEWS_ZIP_SHA256", "a" * 64),
        ("BOCA_OFFICIAL_NEWS_JSONL_SHA256", "a" * 64),
        ("BOCA_OFFICIAL_NEWS_HTML_SHA256", "a" * 64),
        ("BOCA_OFFICIAL_NEWS_OBSERVED_AT_UTC", "2026-11-07T00:00:00Z"),
    ],
)
def test_worker_807_recovery_rejects_any_mutable_dispatch_input(field: str, value: str) -> None:
    result = _inputs_result(overrides={field: value})
    assert result.returncode != 0, f"accepted mutable R82 input: {field}"


def _rest_responses(evidence: dict[str, Any]) -> dict[str, Any]:
    prefix = f"repos/{REPO}"
    return {
        f"{prefix}/pulls?state=open&per_page=1": evidence["prs"],
        (
            f"{prefix}/actions/workflows/boca-first-deploy.yml/runs?"
            "event=workflow_dispatch&created=%3E%3D2026-11-07&per_page=100"
        ): evidence["history"],
        f"{prefix}/actions/runs/42341290485": evidence["failed"],
        f"{prefix}/actions/runs/42342822240": evidence["witness"],
        f"{prefix}/actions/runs/42340930071": evidence["release"],
        f"{prefix}/actions/runs/42341290485/attempts/1/jobs?per_page=100": evidence["failed_jobs"],
        f"{prefix}/actions/runs/42342822240/attempts/1/jobs?per_page=100": evidence["witness_jobs"],
        f"{prefix}/git/ref/heads/main": {
            "ref": "refs/heads/main",
            "object": {"type": "commit", "sha": SOURCE},
        },
    }


def _shell_gate(
    tmp_path: Path,
    evidence: dict[str, Any],
    *,
    corrupt_main: bool = False,
    omit_endpoint: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run ONLY the genuine pre-SSH body; fake GH never calls a service."""
    bash = _step_bash(GATE_STEP)
    assert not re.search(r"(?m)^\s*(ssh|docker|curl|gh\s+run)\s", bash)
    assert "scripts/check_main_ref.py" in bash
    assert "scripts/check_worker_recovery_dispatch.py" in bash
    assert "--r82" in bash
    replies = _rest_responses(evidence)
    if corrupt_main:
        replies[f"repos/{REPO}/git/ref/heads/main"]["object"]["sha"] = "a" * 40
    if omit_endpoint is not None:
        del replies[omit_endpoint]
    replies_file = tmp_path / "fake-gh-responses.json"
    calls_file = tmp_path / "fake-gh-calls.txt"
    replies_file.write_text(json.dumps(replies), encoding="utf-8")
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "with open(os.environ['BOCA_TEST_GH_CALLS'],'a',encoding='utf-8') as calls:\n"
        "    calls.write(sys.argv[2]+'\\n')\n"
        "with open(os.environ['BOCA_TEST_GH_DATA'],encoding='utf-8') as stream:\n"
        "    data=json.load(stream)\n"
        "print(json.dumps(data[sys.argv[2]]))\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o700)
    env = _input_environment()
    env.update(
        GITHUB_REPOSITORY=REPO,
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        RUNNER_TEMP=str(tmp_path),
        GH_TOKEN="offline-gate-fixture",
        BOCA_TEST_GH_DATA=str(replies_file),
        BOCA_TEST_GH_CALLS=str(calls_file),
        PYTHONPATH="src",
        PATH=f"{tmp_path}:{os.environ['PATH']}",
    )
    result = subprocess.run(  # noqa: S603 - local fake gh; extracted body has no SSH
        ("bash", "-c", "set -euo pipefail\n" + bash),  # noqa: S607
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    calls = calls_file.read_text(encoding="utf-8").splitlines() if calls_file.exists() else []
    return result, calls


def test_exact_protected_rest_gate_accepts_seven_authentic_receipts_before_ssh(
    tmp_path: Path,
) -> None:
    result, calls = _shell_gate(tmp_path, _evidence())
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "BOCA_WORKER_RECOVERY_GATE state=PASS incident=42341290485" in result.stdout
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "dispatch=UNIQUE_R82" in summary and "host_writes=0" in summary
    assert len(calls) == 8 and len(set(calls)) == 8
    assert f"repos/{REPO}/git/ref/heads/main" in calls
    assert f"repos/{REPO}/pulls?state=open&per_page=1" in calls
    assert not (tmp_path / "boca-worker-recovery.receipt.json").exists()


@pytest.mark.parametrize(
    "attack",
    [
        "open_pr",
        "second_r82",
        "failed_step_forged",
        "observer_step_forged",
        "main_moved",
        "missing_api",
    ],
)
def test_pre_ssh_gate_denies_replay_open_pr_forged_jobs_and_main_ref(
    tmp_path: Path, attack: str
) -> None:
    evidence = _evidence()
    corrupt_main = False
    omit_endpoint = None
    if attack == "open_pr":
        evidence["prs"] = [{"number": 421, "draft": True}]
    elif attack == "second_r82":
        evidence["history"]["workflow_runs"].append(
            {
                **evidence["history"]["workflow_runs"][-1],
                "id": 88888888888,
            }
        )
        evidence["history"]["total_count"] += 1
    elif attack == "failed_step_forged":
        evidence["failed_jobs"]["jobs"][0]["steps"][56]["conclusion"] = "success"
    elif attack == "observer_step_forged":
        evidence["witness_jobs"]["jobs"][0]["steps"][40]["conclusion"] = "skipped"
    elif attack == "main_moved":
        corrupt_main = True
    else:
        omit_endpoint = f"repos/{REPO}/actions/runs/42342822240/attempts/1/jobs?per_page=100"
    result, _ = _shell_gate(
        tmp_path, evidence, corrupt_main=corrupt_main, omit_endpoint=omit_endpoint
    )
    assert result.returncode != 0, f"pre-SSH gate accepted {attack}: {result.stdout}"
    summary_file = tmp_path / "summary.md"
    assert not summary_file.exists() or "state=PASS" not in summary_file.read_text(encoding="utf-8")


def test_r82_reuses_one_bounded_recovery_ssh_and_verifier_not_a_second_flow() -> None:
    text = _workflow()
    gate = _step_block(GATE_STEP)
    assert f"if: inputs.operation == '{OPERATION}'" in gate
    assert text.index(f"      - name: {GATE_STEP}\n") < text.index(f"      - name: {HOST_STEP}\n")
    assert "gh api" in gate and "--jq" in gate
    assert "status" in gate and "conclusion" in gate
    host = _step_block(HOST_STEP)
    assert f"inputs.operation == '{OPERATION}'" in host
    assert "cutover-worker-recover" in host and "cutover-worker-807-recover" in host
    assert host.count("--worker-recovery") == 1
    assert "sha256sum" in host and "boca_protected_memfd_bootstrap.py" in host
    assert len(re.findall(r"\bssh\s*\\", host)) == 1
    assert not re.search(r"(?m)^\s*docker\s", host)
    verifier = _step_block(VERIFY_STEP)
    assert "always()" in verifier
    assert f"inputs.operation == '{OPERATION}'" in verifier
    assert "verify-807" in verifier
    assert "INDETERMINATE" in verifier
    assert "retry=NO_GO cutover=NO_GO" in verifier
    assert "boca-worker-recovery-42329475083" in text  # R80 provenance retained.
    assert "boca-worker-recovery-42341290485" in text  # Separate R82 proof.


@pytest.mark.parametrize("host_outcome", ["failure", "success"])
def test_r82_terminal_verifier_denies_missing_or_forged_receipts_without_retry(
    tmp_path: Path, host_outcome: str
) -> None:
    body = _step_bash(VERIFY_STEP)
    assert "docker " not in body and "ssh " not in body
    private = tmp_path / "boca-worker-recovery.abcdefgh"
    private.mkdir(mode=0o700)
    receipt = private / "receipt"
    if host_outcome == "success":
        # A forged/partial receipt can never certify the #807 host mutation.
        receipt.write_text(
            '{"version":"boca-worker-recovery-v1","status":"CLEANED"}',
            encoding="utf-8",
        )
    env = _input_environment()
    env.update(
        RUNNER_TEMP=str(tmp_path),
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        BOCA_WORKER_RECOVERY_RECEIPT=str(receipt),
        BOCA_WORKER_RECOVERY_HOST_OUTCOME=host_outcome,
        PYTHONPATH="src:.",
    )
    result = subprocess.run(  # noqa: S603 - isolated runner receipt verification only
        ("bash", "-c", "set -euo pipefail\n" + body),  # noqa: S607
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    assert result.returncode != 0, result.stdout
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "state=NO_GO" in summary
    assert "cleanup=INDETERMINATE" in summary
    assert "retry=NO_GO cutover=NO_GO" in summary
    assert "state=CLEANED" not in summary
    assert not (tmp_path / "boca-worker-recovery.verified.json").exists()
    assert not receipt.exists() and not private.exists()


def test_pull_request_cannot_enter_protected_deploy_or_issue_host_receipt() -> None:
    text = _workflow()
    assert "  deploy:\n    if: github.event_name == 'workflow_dispatch'" in text
    assert "  pr-validation:\n    if: github.event_name == 'pull_request'" in text
    assert "  pr-runtime-smoke:\n    if: github.event_name == 'pull_request'" in text
    assert "Assert PR cannot produce host cutover or cleanup receipt" in text
    pr_workflow = text.split("  deploy:\n", 1)[0]
    assert f"      - name: {GATE_STEP}\n" not in pr_workflow
    assert "BOCA_CUTOVER_A_PR_VERIFY state=SOURCE_ONLY host_calls=0" in pr_workflow


def test_protected_pr_validation_keeps_r80_and_runs_r82_code_only_regressions() -> None:
    block = _step_block("Validate protected Cutover A, Option B ZIP and cleanup offline only")
    for test_file in (
        "tests/test_r80_recovery_gate.py",
        "tests/test_r82_exact_worker_807_recovery.py",
        "tests/test_r82_recovery_bundle.py",
        "tests/test_r82_recovery_dispatch.py",
        "tests/test_r82_recovery_workflow.py",
    ):
        assert block.count(test_file) == 1, f"missing or duplicated CODE_ONLY PR gate: {test_file}"
