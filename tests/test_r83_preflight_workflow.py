"""R83 preflight receipt contract exercised against the real Actions Bash step.

Tests execute only the local verifier with disposable receipt fixtures. They do
not start Docker, contact GitHub, SSH to a host, or dispatch an Action.
"""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "boca-first-deploy.yml"
VERIFY_STEP = "Require exact Boca rootless worker preflight receipt and bounded cleanup"
SOURCE_SHA = "a" * 40
NO_GO_PREFIX = b"BOCA_CUTOVER_WORKER_PREFLIGHT state=NO_GO "


def _failed_receipt(
    *,
    phase: str = "CLEANUP",
    cleanup: str = "INDETERMINATE",
    primary: str = "WORKER_START",
    stage: str = "RM",
) -> bytes:
    """Independently specified wire order; no production serializer is reused."""
    return (
        NO_GO_PREFIX
        + f"failed_phase={phase} cleanup={cleanup} ".encode("ascii")
        + f"primary_failed_phase={primary} cleanup_failed_stage={stage}\n".encode("ascii")
    )


def _verifier_bash() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step_marker = f"      - name: {VERIFY_STEP}\n"
    assert workflow.count(step_marker) == 1, "preflight verifier must have one owner"
    step = workflow.split(step_marker, 1)[1].split("\n      - name:", 1)[0]
    assert "        run: |\n" in step
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


def _verify_receipt(
    tmp_path: Path,
    receipt: bytes | None,
    *,
    host_outcome: str = "failure",
) -> tuple[int, str]:
    if receipt is not None:
        (tmp_path / "boca-worker-preflight.receipt").write_bytes(receipt)
    env = dict(os.environ)
    env.update(
        RUNNER_TEMP=str(tmp_path),
        GITHUB_STEP_SUMMARY=str(tmp_path / "step-summary.md"),
        BOCA_PREFLIGHT_HOST_OUTCOME=host_outcome,
        BOCA_SOURCE_SHA=SOURCE_SHA,
    )
    result = subprocess.run(  # noqa: S603 - extracted, local verifier; no host I/O
        ("bash", "-c", _verifier_bash()),  # noqa: S607
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    summary_file = tmp_path / "step-summary.md"
    summary = summary_file.read_text(encoding="utf-8") if summary_file.exists() else ""
    return result.returncode, summary


def test_r83_failure_receipt_preserves_primary_phase_and_cleanup_stage(tmp_path: Path) -> None:
    returncode, summary = _verify_receipt(tmp_path, _failed_receipt())
    assert returncode != 0, "failed host can never yield a PASS"
    assert "BOCA_CUTOVER_WORKER_PREFLIGHT state=NO_GO host=UNVERIFIED" in summary
    assert "phase_claim=CLEANUP cleanup_claim=INDETERMINATE" in summary
    assert "primary_failed_phase_claim=WORKER_START" in summary
    assert "cleanup_failed_stage_claim=RM" in summary
    assert "next=read_only_boca_inventory no_retry=1" in summary


@pytest.mark.parametrize(
    "primary",
    [
        "NONE",
        "ATTEST",
        "GHCR_PULL",
        "SECCOMP_ENTER",
        "WORKER_CREATE",
        "WORKER_START",
        "WORKER_BOUNDARY",
        "UNVERIFIED",
    ],
)
def test_r83_each_allowed_primary_failure_phase_retains_its_claim(
    tmp_path: Path, primary: str
) -> None:
    returncode, summary = _verify_receipt(tmp_path, _failed_receipt(primary=primary))
    assert returncode == 1
    assert f"primary_failed_phase_claim={primary}" in summary
    assert "cleanup_failed_stage_claim=RM" in summary
    assert "state=PASS" not in summary


@pytest.mark.parametrize(
    "stage",
    [
        "TEMP_SECCOMP",
        "PS",
        "INSPECT",
        "OWNERSHIP",
        "STOP",
        "RM",
        "POST_ID",
        "LEGACY",
        "UNVERIFIED",
    ],
)
def test_r83_each_allowed_cleanup_failure_stage_retains_its_claim(
    tmp_path: Path, stage: str
) -> None:
    returncode, summary = _verify_receipt(tmp_path, _failed_receipt(stage=stage))
    assert returncode == 1
    assert "primary_failed_phase_claim=WORKER_START" in summary
    assert f"cleanup_failed_stage_claim={stage}" in summary
    assert "cleanup_claim=INDETERMINATE" in summary


def test_r83_verified_cleanup_may_have_no_cleanup_failure_stage(tmp_path: Path) -> None:
    returncode, summary = _verify_receipt(
        tmp_path,
        _failed_receipt(
            phase="WORKER_CREATE",
            cleanup="VERIFIED",
            primary="WORKER_CREATE",
            stage="NONE",
        ),
    )
    assert returncode == 1
    assert "phase_claim=WORKER_CREATE cleanup_claim=VERIFIED" in summary
    assert "primary_failed_phase_claim=WORKER_CREATE cleanup_failed_stage_claim=NONE" in summary
    assert "state=PASS" not in summary


@pytest.mark.parametrize(
    "corrupt",
    [
        None,
        b"",
        NO_GO_PREFIX + b"failed_phase=CLEANUP cleanup=INDETERMINATE\n",
        NO_GO_PREFIX + b"primary_failed_phase=WORKER_START cleanup_failed_stage=RM\n",
        _failed_receipt().replace(b"primary_failed_phase=WORKER_START ", b""),
        _failed_receipt().replace(b"cleanup_failed_stage=RM", b""),
        _failed_receipt().replace(b"failed_phase=CLEANUP ", b""),
        _failed_receipt().replace(b"cleanup=INDETERMINATE ", b""),
        _failed_receipt().replace(
            b"primary_failed_phase=WORKER_START", b"primary_failed_phase=STOP"
        ),
        _failed_receipt().replace(b"cleanup_failed_stage=RM", b"cleanup_failed_stage=PRUNE"),
        _failed_receipt().replace(b"failed_phase=CLEANUP", b"failed_phase=PREPARE"),
        _failed_receipt().replace(b"cleanup=INDETERMINATE", b"cleanup=UNKNOWN"),
        _failed_receipt().replace(
            b"primary_failed_phase=WORKER_START", b"primary_failed_phase=worker_start"
        ),
        _failed_receipt().replace(b"cleanup_failed_stage=RM", b"cleanup_failed_stage=rm"),
        _failed_receipt().replace(
            b"cleanup_failed_stage=RM", b"cleanup_failed_stage=RM cleanup_failed_stage=RM"
        ),
        _failed_receipt().replace(
            b"primary_failed_phase=WORKER_START",
            b"primary_failed_phase=WORKER_START primary_failed_phase=WORKER_START",
        ),
        _failed_receipt() + _failed_receipt(),
        _failed_receipt()[:-1],
        _failed_receipt()[:-1] + b"\r\n",
        _failed_receipt()[:-1] + b" extra=1\n",
        _failed_receipt().replace(
            b"cleanup=INDETERMINATE primary", b"cleanup=INDETERMINATE  primary"
        ),
        _failed_receipt().replace(
            b"cleanup=INDETERMINATE primary",
            b"primary_failed_phase=WORKER_START cleanup=INDETERMINATE primary",
        ),
        _failed_receipt().replace(b"cleanup_failed_stage=RM", b"cleanup_failed_stage=R\xffM"),
        _failed_receipt()[:-1] + b"x" * 160 + b"\n",
    ],
    ids=[
        "absent",
        "empty",
        "old-format-only",
        "new-fields-only",
        "missing-primary",
        "missing-cleanup-stage",
        "missing-historical-phase",
        "missing-historical-cleanup",
        "unknown-primary",
        "unknown-stage",
        "unknown-historical-phase",
        "unknown-historical-cleanup",
        "lowercase-primary",
        "lowercase-stage",
        "duplicate-stage",
        "duplicate-primary",
        "duplicated-line",
        "no-newline",
        "crlf",
        "extra-field",
        "double-space",
        "reordered-fields",
        "non-ascii",
        "oversized",
    ],
)
def test_r83_missing_duplicate_malformed_or_unknown_receipt_is_all_unverified(
    tmp_path: Path, corrupt: bytes | None
) -> None:
    returncode, summary = _verify_receipt(tmp_path, corrupt)
    assert returncode == 1
    assert summary.splitlines() == [
        "BOCA_CUTOVER_WORKER_PREFLIGHT state=NO_GO host=UNVERIFIED "
        "phase_claim=UNVERIFIED cleanup_claim=UNVERIFIED "
        "primary_failed_phase_claim=UNVERIFIED cleanup_failed_stage_claim=UNVERIFIED "
        "next=read_only_boca_inventory no_retry=1"
    ]


@pytest.mark.parametrize(
    "corrupt",
    [
        _failed_receipt(cleanup="VERIFIED", stage="RM"),
        _failed_receipt(cleanup="INDETERMINATE", stage="NONE"),
        _failed_receipt(phase="WORKER_START", cleanup="INDETERMINATE", stage="RM"),
        _failed_receipt(phase="CLEANUP", cleanup="VERIFIED", stage="NONE"),
        _failed_receipt(phase="CLEANUP", cleanup="UNVERIFIED", stage="UNVERIFIED"),
    ],
    ids=[
        "claimed-verified-but-removal-failed",
        "claimed-indeterminate-without-failed-stage",
        "cleanup-failed-but-phase-not-cleanup",
        "cleanup-phase-with-verified-cleanup",
        "cleanup-phase-with-unverified-cleanup",
    ],
)
def test_r83_inconsistent_cleanup_evidence_must_not_be_credited(
    tmp_path: Path, corrupt: bytes
) -> None:
    returncode, summary = _verify_receipt(tmp_path, corrupt)
    assert returncode == 1
    assert "phase_claim=UNVERIFIED cleanup_claim=UNVERIFIED" in summary
    assert "primary_failed_phase_claim=UNVERIFIED cleanup_failed_stage_claim=UNVERIFIED" in summary
    assert "no_retry=1" in summary


PASS_RECEIPT = (
    f"BOCA_CUTOVER_WORKER_PREFLIGHT state=PASS source_sha={SOURCE_SHA} "
    "images=VERIFIED worker_boundary=VERIFIED cleanup=VERIFIED "
    "original=RUNNING port=127.0.0.1:8443 ipc_worker=NOT_TESTED "
    "prepared_go=UNCONSUMED foreign=UNTOUCHED\n"
).encode("ascii")


def test_r83_preserves_exact_success_receipt_without_new_claims(tmp_path: Path) -> None:
    returncode, summary = _verify_receipt(tmp_path, PASS_RECEIPT, host_outcome="success")
    assert returncode == 0
    assert summary.encode("ascii") == PASS_RECEIPT
    assert "primary_failed_phase" not in summary
    assert "cleanup_failed_stage" not in summary


def test_r83_success_parser_reads_only_one_byte_past_expected_receipt() -> None:
    """Even a successful SSH process must not make parsing allocate unbounded bytes."""
    bash = _verifier_bash()
    pass_body = bash.split('python3 - "$RUNNER_TEMP/boca-worker-preflight.receipt"', 1)[1]
    assert ".read_bytes()" not in pass_body
    assert re.search(r"\.open\(\s*['\"]rb['\"]\s*\)", pass_body)
    assert "len(expected.encode('ascii')) + 1" in pass_body


def test_r83_success_outcome_rejects_megabyte_receipt_without_raw_echo(tmp_path: Path) -> None:
    returncode, summary = _verify_receipt(
        tmp_path, PASS_RECEIPT + b"SECRET_NO_ECHO" * 100_000, host_outcome="success"
    )
    assert returncode != 0
    assert "SECRET_NO_ECHO" not in summary
    assert "state=PASS" not in summary


@pytest.mark.parametrize(
    "forged_receipt",
    [
        PASS_RECEIPT.replace(SOURCE_SHA.encode("ascii"), b"b" * 40),
        PASS_RECEIPT.replace(b"cleanup=VERIFIED", b"cleanup=INDETERMINATE"),
        PASS_RECEIPT + b"\n",
        PASS_RECEIPT[:-1],
        _failed_receipt(),
    ],
    ids=["wrong-sha", "cleanup-unverified", "extra-newline", "missing-newline", "no-go"],
)
def test_r83_success_outcome_cannot_waive_exact_terminal_pass_receipt(
    tmp_path: Path, forged_receipt: bytes
) -> None:
    returncode, summary = _verify_receipt(tmp_path, forged_receipt, host_outcome="success")
    assert returncode != 0
    assert "state=PASS" not in summary


def test_r83_failure_outcome_does_not_promote_forged_pass_receipt(tmp_path: Path) -> None:
    returncode, summary = _verify_receipt(tmp_path, PASS_RECEIPT, host_outcome="failure")
    assert returncode == 1
    assert "state=NO_GO" in summary
    assert "phase_claim=UNVERIFIED cleanup_claim=UNVERIFIED" in summary
    assert "state=PASS" not in summary


def test_r83_failure_parser_reads_at_most_257_bytes_before_validation() -> None:
    """A huge SSH stdout must not be materialized by Path.read_bytes()."""
    bash = _verifier_bash()
    failure_body = bash.split('claim="$(python3 - ', 1)[1].split("\nPY\n", 1)[0]
    assert ".read_bytes()" not in failure_body
    assert re.search(r"\.open\(\s*['\"]rb['\"]\s*\)", failure_body)
    assert re.search(r"\.read\(\s*257\s*\)", failure_body)


def test_r83_megabyte_failure_receipt_is_unverified_without_retry(tmp_path: Path) -> None:
    oversized_receipt = _failed_receipt() + b"X" * (1024 * 1024)
    returncode, summary = _verify_receipt(tmp_path, oversized_receipt)
    assert returncode == 1
    assert "state=NO_GO host=UNVERIFIED" in summary
    assert "phase_claim=UNVERIFIED cleanup_claim=UNVERIFIED" in summary
    assert "primary_failed_phase_claim=UNVERIFIED cleanup_failed_stage_claim=UNVERIFIED" in summary
    assert "no_retry=1" in summary


def test_r83_verifier_is_hostless_and_remains_one_protected_operation() -> None:
    bash = _verifier_bash()
    assert not re.search(r"(?m)^\s*(ssh|docker|gh|curl)\s", bash)
    assert "timeout " not in bash
    assert "BOCA_PREFLIGHT_HOST_OUTCOME" in bash
    assert "no_retry=1" in bash
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split(f"      - name: {VERIFY_STEP}\n", 1)[1].split("\n      - name:", 1)[0]
    assert "always() && inputs.operation == 'cutover-a-worker-preflight'" in step
    assert "  deploy:\n    if: github.event_name == 'workflow_dispatch'" in workflow
    assert "  pr-validation:\n    if: github.event_name == 'pull_request'" in workflow


def test_r83_preflight_receipt_regressions_run_in_existing_pr_validation_gate() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    marker = "      - name: Validate protected Cutover A, Option B ZIP and cleanup offline only\n"
    assert workflow.count(marker) == 1
    step = workflow.split(marker, 1)[1].split("\n      - name:", 1)[0]
    assert step.count("tests/test_r83_preflight_workflow.py") == 1
    assert "tests/test_r82_recovery_workflow.py" in step
    assert "tests/test_r80_recovery_gate.py" in step
