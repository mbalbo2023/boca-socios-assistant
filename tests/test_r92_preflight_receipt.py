"""R92: execute actual isolated Bash verifier for bounded STOP claim extensions."""

from __future__ import annotations

from pathlib import Path

import pytest

from test_ci_parallel_pytest_contract import assert_required_ci_covers
from test_r83_preflight_workflow import WORKFLOW, _failed_receipt, _verify_receipt


def test_r92_targeted_protected_pr_gate_runs_stop_and_receipt_cases() -> None:
    assert_required_ci_covers(
        "tests/test_r92_stop_ack_evidence.py",
        "tests/test_r92_preflight_receipt.py",
    )
    workflow = WORKFLOW.read_text(encoding="utf-8")
    pr = workflow.split("  pr-validation:\n", 1)[1].split("  deploy:\n", 1)[0]
    assert "uv run python scripts/build_protected_boca_bundle.py" in pr


@pytest.mark.parametrize(
    "cause", ["ACK_EMPTY", "ACK_SHORT_ID", "ACK_NAME", "ACK_MULTILINE", "ACK_OTHER_ID"]
)
def test_r92_runner_preserves_only_new_sanitized_subtype_as_untrusted_claim(
    tmp_path: Path, cause: str
) -> None:
    rc, summary = _verify_receipt(
        tmp_path,
        _failed_receipt(
            phase="CLEANUP", cleanup="INDETERMINATE", primary="NONE", stage="STOP", cause=cause
        ),
    )
    assert rc != 0
    assert "BOCA_CUTOVER_WORKER_PREFLIGHT state=NO_GO host=UNVERIFIED" in summary
    assert f"stop_failure_cause_claim={cause} next=read_only_boca_inventory no_retry=1" in summary
    assert "state=PASS" not in summary


@pytest.mark.parametrize(
    ("stage", "cause"),
    [
        ("RM", "ACK_EMPTY"),
        ("PS", "ACK_NAME"),
        ("STOP", "ACK_secret"),
        ("STOP", "ack_empty"),
        ("STOP", "ACK_OTHER_ID extra"),
    ],
)
def test_r92_runner_rejects_cross_stage_or_unrecognized_claims(
    tmp_path: Path, stage: str, cause: str
) -> None:
    rc, summary = _verify_receipt(tmp_path, _failed_receipt(stage=stage, cause=cause))
    assert rc != 0
    assert "phase_claim=UNVERIFIED cleanup_claim=UNVERIFIED" in summary
    assert "stop_failure_cause_claim=UNVERIFIED" in summary
    assert "state=PASS" not in summary
