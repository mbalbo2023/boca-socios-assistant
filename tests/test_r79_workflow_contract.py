"""R79 host recovery invariants carried into the R80 protected dispatch."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/boca-first-deploy.yml"
REPO = "mbalbo2023/boca-socios-assistant"
R78_MAIN = "7dc0b477479aec118ed4e46edd1ffb4541558dbc"
FAILED_SOURCE = "92624ed6b7e75c6010f59670c866df00a29766dd"
CID = "65d844edb438710f44ce83c397906932710ad7f04f3e7a52634f9eaaf1fcc504"
ONCE_TITLE = "BOCA-R80-WORKER-RECOVER-ONCE"
HISTORY_URI = (
    f"repos/{REPO}/actions/workflows/boca-first-deploy.yml/runs?"
    "event=workflow_dispatch&created=%3E%3D2026-11-07&per_page=100"
)


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _step(name: str) -> str:
    start = f"      - name: {name}\n"
    assert _workflow().count(start) == 1, f"missing or duplicate workflow step: {name}"
    return _workflow().split(start, 1)[1].split("\n      - name:", 1)[0]


def _run_script(name: str) -> str:
    fragment = _step(name)
    assert "        run: |\n" in fragment
    return textwrap.dedent(fragment.split("        run: |\n", 1)[1])


def _gate_env(**changes: str) -> dict[str, str]:
    script = _run_script("Require verified protected environment and matching main commit")
    env = dict(os.environ)
    for variable in set(re.findall(r"\$([A-Z_][A-Z0-9_]*)", script)):
        env[variable] = ""
    env.update(
        GITHUB_RUN_ATTEMPT="1",
        GITHUB_RUN_ID="99999999999",
        GITHUB_SHA=R78_MAIN,
        BOCA_SOURCE_SHA=R78_MAIN,
        BOCA_SOURCE_SHA_SUBMITTED="",
        BOCA_OPERATION="cutover-a-worker-recover",
        BOCA_SERVICE="controller",
        BOCA_BUDGET="1.5cpu-1024m-192pids",
        BOCA_HOST_READONLY_ENV_READY="ready",
        BOCA_DEPLOY_ENV_READY="ready",
        BOCA_BETA_ENV_READY="ready",
        BOCA_BROWSER_ENV_READY="ready",
    )
    env.update(changes)
    return env


def _shell(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - local Bash only; never Actions/host
        ("bash", "-c", f"set -euo pipefail\n{script}"),  # noqa: S607
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_dispatch_remains_one_owner_only_manual_workflow() -> None:
    workflow = _workflow()
    dispatch = workflow.split("  workflow_dispatch:\n", 1)[1].split("\npermissions:", 1)[0]
    assert len(re.findall(r"\bcutover-a-worker-recover(?!-807|-819)\b", dispatch)) == 1
    assert len(re.findall(r"\bcutover-a-worker-recover-807\b", dispatch)) == 1
    deploy = workflow.split("  deploy:\n", 1)[1]
    assert (
        "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main' "
        "&& github.repository == 'mbalbo2023/boca-socios-assistant' "
        "&& github.actor == 'mbalbo2023'"
    ) in deploy
    assert "environment: boca-first-deploy" in deploy
    assert "name: approved-boca-manual-operation" in deploy
    assert "group: ${{ github.event_name == 'pull_request'" in workflow
    assert "BOCA_SOURCE_SHA: ${{ (" in deploy
    assert (
        "inputs.operation == 'cutover-a-worker-recover' || "
        "inputs.operation == 'cutover-a-worker-recover-807' || "
        "inputs.operation == 'cutover-a-worker-recover-819') && github.sha"
    ) in deploy


def test_recovery_input_gate_accepts_only_empty_unrelated_fields() -> None:
    script = _run_script("Require verified protected environment and matching main commit")
    assert _shell(script, _gate_env()).returncode == 0


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("GITHUB_RUN_ATTEMPT", "2"),
        ("BOCA_SOURCE_SHA_SUBMITTED", R78_MAIN),
        ("BOCA_PROTECTED_ACTION_CONTEXT", "42329475083"),
        ("BOCA_BUDGET", "0.5cpu-256m-64pids"),
        ("BOCA_HOST_READONLY_ENV_READY", ""),
        ("BOCA_DEPLOY_ENV_READY", ""),
        ("BOCA_BETA_ENV_READY", ""),
        ("BOCA_BROWSER_ENV_READY", ""),
        ("BOCA_IMAGE_REF", "foreign-image"),
        ("BOCA_BROWSER_IMAGE_REF", "foreign-browser"),
        ("BOCA_RELEASE_RUN_ID", "123"),
        ("BOCA_LEGACY_SOURCE_SHA", FAILED_SOURCE),
        ("BOCA_LEGACY_IMAGE_REF", "foreign-legacy"),
        ("BOCA_LEGACY_RELEASE_RUN_ID", "123"),
        ("BOCA_LEGACY_CONTROLLER_ID", CID),
        ("BOCA_SITE_ENVELOPE", "unexpected"),
        ("BOCA_TELEGRAM_ENVELOPE", "unexpected"),
        ("BOCA_OWNER_ENVELOPE", "unexpected"),
        ("BOCA_OWNER_CAPABILITY_SHA256", "f" * 64),
        ("BOCA_OFFICIAL_CONTROLLER_ID", CID),
        ("BOCA_OFFICIAL_NEWS_RUN_ID", "1"),
        ("BOCA_OFFICIAL_NEWS_SOURCE_SHA", R78_MAIN),
        ("BOCA_OFFICIAL_NEWS_ARTIFACT_ID", "1"),
        ("BOCA_OFFICIAL_NEWS_ZIP_SHA256", "f" * 64),
        ("BOCA_OFFICIAL_NEWS_JSONL_SHA256", "f" * 64),
        ("BOCA_OFFICIAL_NEWS_HTML_SHA256", "f" * 64),
        ("BOCA_OFFICIAL_NEWS_OBSERVED_AT_UTC", "2026-11-07"),
        ("BOCA_FAILED_TELEGRAM_RUN_ID", "1"),
    ],
)
def test_recovery_input_gate_rejects_extra_authority(field: str, invalid: str) -> None:
    script = _run_script("Require verified protected environment and matching main commit")
    result = _shell(script, _gate_env(**{field: invalid}))
    assert result.returncode != 0, f"unexpectedly accepted {field}"


def _github_fixtures() -> dict[str, object]:
    # Reuse the R80 live-REST-shaped fixture; the old R79 happy path no longer
    # describes the protected one-shot state after physical pre-SSH abort #804.
    from test_r80_recovery_gate import _evidence

    data = _evidence()
    data["history"]["workflow_runs"][2]["head_sha"] = R78_MAIN
    prefix = f"repos/{REPO}"
    return {
        f"{prefix}/pulls?state=open&per_page=1": data["prs"],
        HISTORY_URI: data["history"],
        f"{prefix}/actions/runs/42329475083": data["failed"],
        f"{prefix}/actions/runs/42337103473": data["witness"],
        f"{prefix}/actions/runs/42329201039": data["release"],
        f"{prefix}/actions/runs/42339451485": data["prior"],
        f"{prefix}/actions/runs/42339451485/attempts/1/jobs?per_page=100": data["jobs"],
        f"{prefix}/git/ref/heads/main": {
            "ref": "refs/heads/main",
            "object": {"type": "commit", "sha": R78_MAIN},
        },
    }


def _attest(tmp_path: Path, fixtures: dict[str, object]) -> subprocess.CompletedProcess[str]:
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "with open(os.environ['BOCA_TEST_GH_RESPONSES'], encoding='utf-8') as source:\n"
        "    data=json.load(source)\n"
        "print(json.dumps(data[sys.argv[2]]))\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o700)
    responses = tmp_path / "responses.json"
    responses.write_text(json.dumps(fixtures), encoding="utf-8")
    env = _gate_env(
        PATH=f"{tmp_path}:{os.environ['PATH']}",
        GH_TOKEN="local-fixture-not-a-secret",
        GITHUB_REPOSITORY=REPO,
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"),
        RUNNER_TEMP=str(tmp_path),
        BOCA_TEST_GH_RESPONSES=str(responses),
        PYTHONPATH="src",
    )
    return _shell(
        _run_script("Require exact 795/802 evidence and zero open PRs before recovery SSH"),
        env,
    )


def test_exact_historical_runs_and_empty_open_pr_inventory_allow_pre_ssh(
    tmp_path: Path,
) -> None:
    assert _attest(tmp_path, _github_fixtures()).returncode == 0


@pytest.mark.parametrize(
    "mismatch",
    [
        "open-pr",
        "failed-run-id",
        "failed-run-sha",
        "failed-run-conclusion",
        "witness-id",
        "witness-sha",
        "witness-conclusion",
        "witness-attempt",
        "release-sha",
        "historical-workflow-ref",
        "release-workflow-ref",
        "previous-recovery-dispatch",
        "history-overflow",
        "history-title-missing",
        "main-moved",
    ],
)
def test_provenance_or_open_pr_mismatch_blocks_before_ssh(tmp_path: Path, mismatch: str) -> None:
    fixtures = _github_fixtures()
    prefix = f"repos/{REPO}"
    failed = fixtures[f"{prefix}/actions/runs/42329475083"]
    witness = fixtures[f"{prefix}/actions/runs/42337103473"]
    release = fixtures[f"{prefix}/actions/runs/42329201039"]
    main = fixtures[f"{prefix}/git/ref/heads/main"]
    history = fixtures[HISTORY_URI]
    assert isinstance(failed, dict)
    assert isinstance(witness, dict)
    assert isinstance(release, dict)
    assert isinstance(main, dict)
    assert isinstance(history, dict)
    if mismatch == "open-pr":
        fixtures[f"{prefix}/pulls?state=open&per_page=1"] = [{"number": 421, "draft": True}]
    elif mismatch == "failed-run-id":
        failed["id"] = 1
    elif mismatch == "failed-run-sha":
        failed["head_sha"] = R78_MAIN
    elif mismatch == "failed-run-conclusion":
        failed["conclusion"] = "success"
    elif mismatch == "witness-id":
        witness["id"] = 1
    elif mismatch == "witness-sha":
        witness["head_sha"] = FAILED_SOURCE
    elif mismatch == "witness-conclusion":
        witness["conclusion"] = "failure"
    elif mismatch == "witness-attempt":
        witness["run_attempt"] = 2
    elif mismatch == "release-sha":
        release["head_sha"] = R78_MAIN
    elif mismatch == "historical-workflow-ref":
        witness["path"] = ".github/workflows/boca-first-deploy.yml@untrusted-branch"
    elif mismatch == "release-workflow-ref":
        release["path"] = ".github/workflows/release-image.yml@untrusted-branch"
    elif mismatch == "previous-recovery-dispatch":
        history["workflow_runs"].append({"id": 99999999998, "display_title": ONCE_TITLE})
        history["total_count"] = 3
    elif mismatch == "history-overflow":
        history["total_count"] = 101
    elif mismatch == "history-title-missing":
        history["workflow_runs"][1]["display_title"] = "Boca first deploy"
    elif mismatch == "main-moved":
        main["object"] = {"type": "commit", "sha": FAILED_SOURCE}
    result = _attest(tmp_path, fixtures)
    assert result.returncode != 0, f"accepted mismatch: {mismatch}"


def test_protected_remote_transport_and_terminal_ack_are_separate_gates() -> None:
    flow = _workflow()
    assert "run-name: ${{" in flow and ONCE_TITLE in flow
    attest = "Require exact 795/802 evidence and zero open PRs before recovery SSH"
    remote = "Recover only the stopped exact 795 807 or 819 worker probe under Boca lease"
    verify = "Require exact terminal worker recovery receipt on every outcome"
    assert flow.index(f"      - name: {attest}") < flow.index(f"      - name: {remote}")
    assert flow.index(f"      - name: {remote}") < flow.index(f"      - name: {verify}")
    remote_step = _step(remote)
    assert "if: inputs.operation == 'cutover-a-worker-recover'" in remote_step
    assert "|| inputs.operation == 'cutover-a-worker-recover-807'" in remote_step
    assert "scripts/build_protected_boca_bundle.py --worker-recovery" in remote_step
    assert "cutover-a-worker-recover) worker_mode=cutover-worker-recover ;;" in remote_step
    assert "cutover-a-worker-recover-807) worker_mode=cutover-worker-807-recover ;;" in remote_step
    assert "boca_protected_memfd_bootstrap.py" in remote_step
    assert "timeout --signal=TERM --kill-after=5s" in remote_step
    assert "boca-target" in remote_step
    assert "docker rm" not in remote_step
    terminal_step = _step(verify)
    assert "always() && (inputs.operation == 'cutover-a-worker-recover' || " in terminal_step
    assert "inputs.operation == 'cutover-a-worker-recover-807' || " in terminal_step
    assert "inputs.operation == 'cutover-a-worker-recover-819')" in terminal_step
    assert "steps.cutover_worker_recover_host.outcome" in terminal_step
    assert (
        "cutover-a-worker-recover) verifier_mode=verify; recovery_attempt=42329475083 ;;"
        in terminal_step
    )
    assert (
        "cutover-a-worker-recover-807) verifier_mode=verify-807; recovery_attempt=42341290485 ;;"
        in terminal_step
    )
    assert 'scripts.host_cutover_worker_recovery "$verifier_mode" "$receipt"' in terminal_step
    assert "BOCA_WORKER_RECOVERY_VERIFIED" in terminal_step
    assert "NO_GO" in terminal_step
    for name in (attest, remote, verify):
        result = subprocess.run(
            ("bash", "-n"),  # noqa: S603,S607 - syntax-only local code check
            input=_run_script(name),
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, (name, result.stderr)


def test_terminal_receipt_verifier_imports_in_clean_github_runner(
    tmp_path: Path,
) -> None:
    """R79 regression: after a physical rm the terminal ACK must be importable."""
    terminal = _step("Require exact terminal worker recovery receipt on every outcome")
    assert "          PYTHONPATH: src:.\n" in terminal
    record = {
        "version": "boca-worker-recovery-v1",
        "attempt": "42329475083",
        "probe_id": CID,
        "legacy_id": "27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793",
        "cleanup": "VERIFIED",
        "phase": "COMPLETE",
        "docker_writes": 1,
        "foreign_resources_touched": False,
        "cutover_authorized": False,
        "retry_authorized": False,
        "original": "RUNNING_HEALTHY",
    }
    receipt = tmp_path / "terminal.json"
    receipt.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONPATH"] = "src:."
    process = subprocess.run(  # noqa: S603 - real import, no host or Docker
        (sys.executable, "-m", "scripts.host_cutover_worker_recovery", "verify", str(receipt)),
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    assert process.stdout.strip() == "BOCA_WORKER_RECOVERY_VERIFIED"
