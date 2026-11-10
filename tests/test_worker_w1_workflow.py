"""W1 dispatch cannot bypass reviewed checkout, owner gate or rootless-only host entry."""

from __future__ import annotations

from pathlib import Path

WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
).read_text(encoding="utf-8")


def _step(title: str) -> str:
    heading = f"      - name: {title}\n"
    assert WORKFLOW.count(heading) == 1
    remainder = WORKFLOW.split(heading, 1)[1]
    return remainder.split("      - name:", 1)[0]


def test_w1_is_only_a_manual_protected_main_owner_operation() -> None:
    assert "worker-diagnose-once" in WORKFLOW
    assert "github.event_name == 'workflow_dispatch'" in WORKFLOW
    assert "github.ref == 'refs/heads/main'" in WORKFLOW
    assert "github.actor == 'mbalbo2023'" in WORKFLOW
    assert "environment: boca-first-deploy" in WORKFLOW
    assert "BOCA_SOURCE_SHA: ${{ (inputs.operation == 'worker-diagnose-once'" in WORKFLOW


def test_w1_checks_out_source_before_calling_github_or_host() -> None:
    checkout = _step("Checkout exact reviewed main for authenticated artifact discovery")
    assert "inputs.operation == 'worker-diagnose-once'" in checkout
    history = _step(
        "Prove single W1 owner dispatch and exact successful installed Cutover before SSH"
    )
    assert "if: inputs.operation == 'worker-diagnose-once'" in history
    assert "scripts/check_worker_w1_dispatch.py" in history
    assert WORKFLOW.index("Prove single W1 owner dispatch") < WORKFLOW.index(
        "W1 one exact installed worker start"
    )


def test_w1_can_only_run_bounded_host_only_payload_and_sanitize_receipt() -> None:
    step = _step("W1 one exact installed worker start, prearmed private capture and verified stop")
    assert "steps.w1_single_dispatch.outcome == 'success'" in step
    assert "--worker-w1" in step
    assert "boca-target" in step
    assert '"worker-diagnose-once"' in step
    assert "python3 -m boca_socios.host_worker_w1 verify" in step
    assert "sudo" not in step
    assert "docker start" not in step
    assert "docker compose" not in step
    assert "cutover-a-apply" not in step


def test_w1_new_tests_are_part_of_pr_validation() -> None:
    validation = _step("Validate W1 one-start evidence and isolated bounded ZIP offline only")
    for name in (
        "test_host_worker_w1.py",
        "test_worker_w1_dispatch.py",
        "test_worker_w1_bundle.py",
        "test_worker_w1_workflow.py",
    ):
        assert name in validation
