"""R26 protected two-dispatch lifecycle / Telegram fail-closed workflow contract.

No SSH, Docker, Telegram API or protected BLACKBOX module is imported; this
text-only QA never produces a physical host receipt or opens a remote port.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "boca-first-deploy.yml"
ADR = ROOT / "docs" / "ADR" / "0159-protected-ops-postcutover-workflow.md"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _dispatch() -> str:
    return _workflow().split("  workflow_dispatch:\n", 1)[1].split("\npermissions:", 1)[0]


def _options() -> list[str]:
    dispatch = _dispatch()
    choices = dispatch.split("options: [", 1)[1].split("]", 1)[0]
    return [option.strip() for option in choices.split(",")]


def _step(name: str) -> str:
    text = _workflow()
    start = f"      - name: {name}\n"
    assert text.count(start) == 1
    return text.split(start, 1)[1].split("      - name:", 1)[0]


def test_github_dispatch_has_exactly_25_inputs_with_one_shared_public_context() -> None:
    names = re.findall(r"^      ([a-z_0-9]+):$", _dispatch(), flags=re.MULTILINE)
    assert len(names) == 25
    assert len(names) == len(set(names))
    assert names.count("protected_action_context") == 1
    assert "type: string" in _dispatch().split("      protected_action_context:\n", 1)[1]
    assert "BOCA_PROTECTED_ACTION_CONTEXT: ${{ inputs.protected_action_context }}" in _workflow()


@pytest.mark.parametrize(
    "operation", ("protected-go-prepare", "lifecycle-apply", "telegram-activate")
)
def test_three_new_operations_exist_only_in_reviewed_single_workflow(operation: str) -> None:
    workflow = _workflow()
    assert _options().count(operation) == 1
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "github.actor == 'mbalbo2023'" in workflow
    assert 'test "$GITHUB_RUN_ATTEMPT" = 1' in workflow


def test_prepare_has_no_host_effect_and_publishes_reviewable_artifact() -> None:
    prepare = _step("Prepare one reviewed lifecycle GO without accessing Boca host")
    artifact = _step("Publish exact no-host lifecycle PREPARE receipt for independent review")
    assert "if: inputs.operation == 'protected-go-prepare'" in prepare
    assert "check_protected_go_prepare.py --prepare" in prepare
    assert "build_protected_boca_bundle.py" in prepare
    assert "ssh " not in prepare and "docker " not in prepare
    assert "if: inputs.operation == 'protected-go-prepare'" in artifact
    assert "upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in artifact
    assert "boca-protected-go-prepare" in artifact
    assert "boca-lifecycle-prepare.receipt.json" in artifact
    assert "boca-lifecycle-apply-context.txt" in artifact
    assert "if: inputs.operation != 'protected-go-prepare'" in _step(
        "Configure pinned SSH host key and dedicated identity"
    )


def test_apply_rechecks_prepared_artifact_and_go_before_any_ssh() -> None:
    workflow = _workflow()
    gate_name = "Require distinct independent lifecycle GO and immutable PREPARE before SSH"
    preflight = _step(gate_name)
    assert "if: inputs.operation == 'lifecycle-apply'" in preflight
    assert "BOCA_LIFECYCLE_GO_BINDING_SHA256: ${{ vars.BOCA_LIFECYCLE_GO_BINDING_SHA256 }}" in preflight
    assert "check_protected_go_prepare.py --prepare-ref" in preflight
    assert "check_protected_go_prepare.py --apply" in preflight
    assert "gh api " in preflight and "gh run download" in preflight
    assert "ssh " not in preflight
    assert workflow.index(f"      - name: {gate_name}") < workflow.index(
        "      - name: Configure pinned SSH host key and dedicated identity"
    )


def test_exact_id_host_effect_is_single_ssh_with_terminal_ack_guard() -> None:
    workflow = _workflow()
    name = "Apply one exact-ID Boca owner lifecycle request through fresh host lease"
    effect = _step(name)
    finalizer = _step("Refuse any absent or ambiguous Boca lifecycle physical ACK")
    assert "if: inputs.operation == 'lifecycle-apply'" in effect
    assert "boca_protected_memfd_bootstrap.py" in effect
    assert "lifecycle-apply" in effect and "boca-target" in effect
    assert "timeout --signal=TERM --kill-after=5s 900s ssh" in effect
    assert "check_main_ref.py" in effect
    assert "boca-lifecycle-host.receipt" in effect
    assert "always() && inputs.operation == 'lifecycle-apply'" in finalizer
    assert "check_protected_go_prepare.py --assert-host-receipt" in finalizer
    assert workflow.index(f"      - name: {name}") < workflow.index(
        "      - name: Refuse any absent or ambiguous Boca lifecycle physical ACK"
    )


def test_telegram_activation_explicitly_no_go_and_excluded_from_legacy_steps() -> None:
    workflow = _workflow()
    assert "telegram-activate)" in workflow
    assert "state=NO_GO reason=host_same_lease_backend_unverified" in workflow
    for name in (
        "Recheck current main before Telegram post-install custody",
        "Mark Telegram host attempt before starting existing Boca daemon",
        "Start only stopped existing dedicated Boca daemon",
        "Execute protected Telegram schema, custody or one-shot test",
        "Stop positively identified Boca services after Telegram custody",
    ):
        assert "inputs.operation != 'telegram-activate'" in _step(name)


def test_existing_import_cutover_and_legacy_six_install_no_go_preserved() -> None:
    workflow = _workflow()
    for marker in (
        "cutover-a-apply",
        "official-notice-import",
        "BOCA_CUTOVER_A_GO_BINDING_SHA256: ${{ vars.BOCA_CUTOVER_A_GO_BINDING_SHA256 }}",
        "BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256: ${{ vars.BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256 }}",
        "Reject legacy install routes without same-lease Boca-only postflight",
        "Fail closed on absent or ambiguous Cutover A host terminal receipt",
    ):
        assert marker in workflow
    assert "docker system prune" not in workflow


def test_pr_validation_cannot_emit_lifecycle_host_or_prepare_receipts() -> None:
    section = _step("Assert PR cannot produce host cutover or cleanup receipt")
    assert "boca-lifecycle-host.receipt" in section
    assert "boca-lifecycle-prepare.receipt.json" in section
    assert "NO_GO" in section
    assert "tests/test_protected_go_prepare_r26.py" in _workflow()


def test_adr_explicitly_records_four_go_deadlocks_and_no_real_host_run() -> None:
    content = ADR.read_text(encoding="utf-8")
    for phrase in (
        "cutover-a-apply",
        "official-notice-import",
        "lifecycle-apply",
        "telegram-activate",
        "GO arquitectónico",
        "GITHUB_RUN_ID",
        "dos despachos humanos",
        "host_calls=0",
    ):
        assert phrase in content
