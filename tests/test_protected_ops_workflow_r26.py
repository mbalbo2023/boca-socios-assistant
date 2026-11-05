"""R26 contract: one protected Boca workflow; physical control is never a PR side effect.

Tests use source text only: no Docker, SSH, Telegram, public Boca navigation or
BLACKBOX imports. A code-only CI pass never means physical ACK.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "boca-first-deploy.yml"
)
LIFECYCLE = "lifecycle-apply"
TELEGRAM = "telegram-activate"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _step(name: str) -> str:
    marker = f"      - name: {name}\n"
    parts = _workflow().split(marker, 1)
    assert len(parts) == 2, f"missing protected step: {name}"
    return parts[1].split("      - name:", 1)[0]


def _dispatch() -> str:
    return _workflow().split("  workflow_dispatch:\n", 1)[1].split("\npermissions:", 1)[0]


def test_only_one_extra_dispatch_input_for_both_new_routes() -> None:
    dispatch = _dispatch()
    names = re.findall(r"^      ([a-z_0-9]+):$", dispatch, flags=re.MULTILINE)
    # The reviewed R24 branch already consumed 24 of GitHub's maximum 25.
    assert len(names) <= 25
    assert len(names) == len(set(names))
    assert names.count("protected_action_context") == 1
    assert "      protected_action_context:\n" in dispatch
    assert "type: string" in dispatch.split("      protected_action_context:\n", 1)[1]


@pytest.mark.parametrize("operation", (LIFECYCLE, TELEGRAM))
def test_operation_is_registered_only_in_existing_manual_workflow(operation: str) -> None:
    text = _workflow()
    options = text.split("options: [", 1)[1].split("]", 1)[0].split(", ")
    assert options.count(operation) == 1
    assert "github.event_name == 'workflow_dispatch'" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "github.actor == 'mbalbo2023'" in text
    assert "test \"$GITHUB_RUN_ATTEMPT\" = 1" in text


@pytest.mark.parametrize(
    ("operation", "go_name", "preflight"),
    (
        (
            LIFECYCLE,
            "BOCA_LIFECYCLE_GO_BINDING_SHA256",
            "Require independent GO and exact Boca lifecycle intent before SSH",
        ),
        (
            TELEGRAM,
            "BOCA_TELEGRAM_ACTIVATE_GO_BINDING_SHA256",
            "Require independent post-Cutover Telegram activation GO before SSH",
        ),
    ),
)
def test_separate_go_binding_is_protected_and_precedes_ssh(
    operation: str, go_name: str, preflight: str
) -> None:
    workflow = _workflow()
    section = _step(preflight)
    assert f"if: inputs.operation == '{operation}'" in section
    assert f"{go_name}:" in section
    assert "vars." + go_name in section
    assert "protected_action_context" in workflow
    assert "check_main_ref.py" in section
    assert "NO_GO" in section or "exit 1" in section
    assert workflow.index(f"      - name: {preflight}") < workflow.index(
        "      - name: Configure pinned SSH host key"
    )


@pytest.mark.parametrize(
    ("operation", "effect", "receipt"),
    (
        (
            LIFECYCLE,
            "Apply one exact-ID owner lifecycle request through Boca-only lease",
            "Reject absent or ambiguous Boca lifecycle physical ACK",
        ),
        (
            TELEGRAM,
            "Activate staged Telegram custody after owner Chrome step",
            "Reject absent or ambiguous post-Cutover Telegram activation receipt",
        ),
    ),
)
def test_one_host_transaction_and_terminal_receipt_gate(
    operation: str, effect: str, receipt: str
) -> None:
    workflow = _workflow()
    execute = _step(effect)
    verify = _step(receipt)
    assert f"if: inputs.operation == '{operation}'" in execute
    assert f"inputs.operation == '{operation}'" in verify
    assert "always()" in verify
    assert "NO_GO" in verify
    assert "boca-target" in execute
    assert "timeout" in execute
    assert "check_main_ref.py" in execute
    assert workflow.index(f"      - name: {effect}") < workflow.index(
        f"      - name: {receipt}"
    )


@pytest.mark.parametrize(
    "name",
    (
        "Recheck current main before Telegram post-install custody",
        "Mark Telegram host attempt before starting existing Boca daemon",
        "Start only stopped existing dedicated Boca daemon",
        "Execute protected Telegram schema, custody or one-shot test",
        "Stop positively identified Boca services after Telegram custody",
    ),
)
def test_telegram_postcutover_cannot_enter_legacy_start_stop_route(name: str) -> None:
    step = _step(name)
    assert "inputs.operation != 'telegram-activate'" in step


def test_existing_cutover_import_and_legacy_install_finalizer_are_preserved() -> None:
    workflow = _workflow()
    for marker in (
        "cutover-a-apply",
        "official-notice-import",
        "Reject legacy install routes without same-lease Boca-only postflight",
        "Require independent GO and exact official source artifact before SSH",
        "Fail closed on absent or ambiguous Cutover A host terminal receipt",
    ):
        assert marker in workflow
    assert "docker system prune" not in workflow


def test_pr_smoke_never_produces_lifecycle_or_telegram_host_receipts() -> None:
    section = _step("Assert PR cannot produce host cutover or cleanup receipt")
    assert "boca-lifecycle-host.receipt" in section
    assert "boca-telegram-activation-host.receipt" in section
    assert "NO_GO" in section
