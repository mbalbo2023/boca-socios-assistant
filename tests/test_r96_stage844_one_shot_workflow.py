"""R96 exact failed #844 staging recovery, without duplicating the host implementation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from test_ci_parallel_pytest_contract import assert_required_ci_covers

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_release_dispatch import DispatchError  # noqa: E402
from scripts.check_worker_preflight_dispatch import validate_dispatch_history  # noqa: E402

WORKFLOW = ROOT / ".github/workflows/boca-first-deploy.yml"
OPERATION = "cutover-a-stage-recover-844"
INCIDENT = "42388694186"
PREPARE = "42381545964"
WITNESS = "42388994569"
TITLE = "BOCA-R96-STAGE-844-RECOVER-ONCE"
SHA = "a" * 40


def _history_entry(identifier: int, *, title: str = TITLE, sha: str = SHA, **overrides) -> dict:
    return {
        "id": identifier,
        "display_title": title,
        "event": "workflow_dispatch",
        "head_sha": sha,
        "head_branch": "main",
        "run_attempt": 1,
        "actor": {"login": "mbalbo2023"},
        "repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
        "path": ".github/workflows/boca-first-deploy.yml",
        **overrides,
    }


def test_r96_all_sha_history_allows_only_its_first_unique_run() -> None:
    """A past unrelated run on a different SHA does not block R96."""
    runs = [
        _history_entry(42389000001, title="Boca first deploy", sha="b" * 40),
        _history_entry(42389000002),
    ]
    validate_dispatch_history(
        {"total_count": 2, "workflow_runs": runs},
        [],
        SHA,
        "42389000002",
        marker=TITLE,
        across_all_shas=True,
    )


@pytest.mark.parametrize(
    "run_set,open_prs",
    [
        ([_history_entry(42389000002), _history_entry(42390000001, sha="c" * 40)], []),
        ([_history_entry(42389000002)], [{"number": 456}]),
        ([_history_entry(42389000003)], []),
        ([_history_entry(42389000002, run_attempt=2)], []),
    ],
)
def test_r96_rejects_cross_sha_replay_open_pr_or_wrong_run(run_set, open_prs) -> None:
    """A second R96 dispatch on another SHA must not get a second SSH."""
    with pytest.raises(DispatchError):
        validate_dispatch_history(
            {"total_count": len(run_set), "workflow_runs": run_set},
            open_prs,
            SHA,
            "42389000002",
            marker=TITLE,
            across_all_shas=True,
        )


def test_r96_protected_stage_route_is_distinct_from_historical_recovery() -> None:
    """An old recovery pin must never be reclassified as authorization for #844."""
    flow = WORKFLOW.read_text(encoding="utf-8")
    assert OPERATION in flow.split("options: [", 1)[1].split("]", 1)[0].split(", ")
    # The generic operation is V3-only; the historical #844 route retains its own pins.
    assert "stage_incident=42317092809" not in flow
    assert "BOCA-V3-STAGE-RECOVER-{0}" in flow
    assert "stage_844_incident=42388694186" in flow
    assert "stage_844_prepare=42381545964" in flow
    assert "stage_844_readonly=42388994569" in flow


def test_r96_admission_gates_exact_identity_and_three_runs() -> None:
    """Wrong incident/prepared/witness IDs or a nonfresh dispatch must fail before SSH."""
    flow = WORKFLOW.read_text(encoding="utf-8")
    assert 'test "$GITHUB_RUN_ATTEMPT" = 1' in flow
    assert 'test "$BOCA_PROTECTED_ACTION_CONTEXT" = "$incident"' in flow
    assert 'test "$BOCA_INCIDENT_PREPARE_RUN_ID" = "$prepare"' in flow
    assert 'gh api "repos/$GITHUB_REPOSITORY/actions/runs/$readonly"' in flow
    assert "python3 -m scripts.check_r96_stage_evidence" in flow
    recheck = flow.split("- name: Recheck exact historical Cutover incident", 1)[1].split(
        "- name: Build deterministic reviewed Boca stage recovery memfd package", 1
    )[0]
    assert "assert " not in recheck  # Python -O cannot disable any provenance check.
    assert "python scripts/check_main_ref.py" in flow
    assert 'test "$BOCA_BUDGET" = 1.5cpu-1024m-192pids' in flow


def test_r96_protected_pr_job_executes_the_new_incident_contract() -> None:
    assert_required_ci_covers(
        "tests/test_r96_stage844_one_shot_workflow.py",
        "tests/test_r96_stage844_evidence_gate.py",
        "tests/test_r96_stage844_dispatch_gate.py",
    )


def test_r96_unique_marker_and_gate_precede_any_recovery_ssh() -> None:
    flow = WORKFLOW.read_text(encoding="utf-8")
    assert (
        "inputs.operation == 'cutover-a-stage-recover-844' && 'BOCA-R96-STAGE-844-RECOVER-ONCE'"
        in flow
    )
    gate = flow.split(
        "- name: Require one unique R96 stage recovery dispatch and zero open PRs", 1
    )[1].split("- name: Recheck exact historical Cutover incident", 1)[0]
    assert "if: inputs.operation == 'cutover-a-stage-recover-844'" in gate
    assert "actions/workflows/boca-first-deploy.yml/runs?event=workflow_dispatch" in gate
    assert "--paginate" in gate
    assert "--slurp" not in gate  # Not supported by the pinned gh CLI.
    assert "run_ids:(.workflow_runs|map(.id))" in gate
    assert "pulls?state=open&per_page=1" in gate
    assert "python3 -m scripts.check_r96_stage_dispatch" in gate
    assert 'gh api "repos/$GITHUB_REPOSITORY/git/ref/heads/main"' in gate
    assert "scripts/check_main_ref.py" in gate
    assert (
        flow.index("- name: Require one unique R96 stage recovery dispatch")
        < flow.index("- name: Recheck exact historical Cutover incident")
        < flow.index("- name: Remove only authenticated uncommitted Cutover stage")
    )


def test_r96_reuses_only_reviewed_zip_and_exact_host_verifier() -> None:
    """A physical action cannot skip the existing receipt verifier or rerun stage cleanup."""
    flow = WORKFLOW.read_text(encoding="utf-8")
    block = flow.split("- name: Build deterministic reviewed Boca stage recovery memfd package", 1)[
        1
    ].split("- name: Attest one historical Boca image release", 1)[0]
    assert block.count("scripts/build_protected_boca_bundle.py") == 1
    assert block.count("scripts/boca_protected_memfd_bootstrap.py") == 1
    assert "cutover-stage-recover" in block
    assert "python3 -m scripts.host_cutover_stage_recovery verify" in block
    assert "physical_ACK_missing_or_invalid retry=NO_GO" in block
    assert block.count(OPERATION) >= 3  # build, host, and finalizer must all admit exact alias
    assert "docker rm" not in block
    assert "docker image rm" not in block
    assert "prune" not in block


def test_r96_rejects_all_unrelated_dispatch_inputs() -> None:
    flow = WORKFLOW.read_text(encoding="utf-8")
    case = flow.split('elif [[ "$BOCA_OPERATION" = cutover-a-stage-recover-844 ]]; then', 1)[
        1
    ].split("else", 1)[0]
    assert 'test -z "$BOCA_SOURCE_SHA_SUBMITTED"' in case
    for name in (
        "BOCA_OFFICIAL_CONTROLLER_ID",
        "BOCA_OFFICIAL_NEWS_RUN_ID",
        "BOCA_OFFICIAL_NEWS_SOURCE_SHA",
        "BOCA_OFFICIAL_NEWS_ARTIFACT_ID",
        "BOCA_OFFICIAL_NEWS_ZIP_SHA256",
        "BOCA_OFFICIAL_NEWS_JSONL_SHA256",
        "BOCA_OFFICIAL_NEWS_HTML_SHA256",
        "BOCA_OFFICIAL_NEWS_OBSERVED_AT_UTC",
    ):
        assert f'"${name}"' in case


def test_r96_existing_host_verifier_rejects_missing_receipt() -> None:
    """A missing ACK for the new incident is rejected by the real existing verifier."""
    result = subprocess.run(  # noqa: S603 - fixed local Python interpreter, no shell
        [sys.executable, "-m", "scripts.host_cutover_stage_recovery", "verify", INCIDENT, PREPARE],
        cwd=ROOT,
        env={"PYTHONPATH": "src:."},
        input=b"",
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 3
    assert b"BOCA_STAGE_RECOVERY state=NO_GO" in result.stderr
    assert b"ModuleNotFoundError" not in result.stderr
