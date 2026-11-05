"""R26 current-state guard: proposed postcutover routes remain CODE_ONLY / NO_GO.

This test explicitly protects the one existing Boca workflow from becoming
accidentally effectful before the two-human-phase GO architecture is approved.
No Docker/SSH/Telegram/public Boca/BLACKBOX access.
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


def test_github_dispatch_has_24_inputs_and_exactly_one_spare_slot() -> None:
    names = re.findall(r"^      ([a-z_0-9]+):$", _dispatch(), flags=re.MULTILINE)
    assert len(names) == 24
    assert len(names) == len(set(names))
    assert "protected_action_context" not in names


@pytest.mark.parametrize("operation", ("lifecycle-apply", "telegram-activate"))
def test_unapproved_new_operation_not_exposed_to_host_dispatch(operation: str) -> None:
    workflow = _workflow()
    assert operation not in _options()
    assert not re.search(r"\b" + re.escape(operation) + r"\b", workflow)
    assert "host_lifecycle_actions" not in workflow
    assert "host_telegram_postcutover" not in workflow
    assert "boca-lifecycle-host.receipt" not in workflow
    assert "boca-telegram-activation-host.receipt" not in workflow


@pytest.mark.parametrize(
    ("operation", "gate"),
    (
        ("cutover-a-apply", "BOCA_CUTOVER_A_GO_BINDING_SHA256"),
        ("official-notice-import", "BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256"),
    ),
)
def test_existing_effect_routes_keep_existing_exact_independent_go(
    operation: str, gate: str
) -> None:
    workflow = _workflow()
    assert operation in _options()
    assert gate + ": ${{ vars." + gate + " }}" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "github.actor == 'mbalbo2023'" in workflow
    assert 'test "$GITHUB_RUN_ATTEMPT" = 1' in workflow


def test_draft_documents_two_phase_prepare_and_all_four_go_route_blockers() -> None:
    text = ADR.read_text(encoding="utf-8")
    for marker in (
        "Cutover A",
        "official-notice-import",
        "lifecycle-apply",
        "telegram-activate",
        "prepare/apply",
        "PREPARE",
        "GITHUB_RUN_ID",
        "host_calls=0",
        "Environment",
        "GO arquitectónico",
        "dos despachos humanos",
    ):
        assert marker in text
    assert "NO autorizada" in text or "NO autorizad" in text
    assert "único\narchivo de workflow" in text


def test_legacy_telegram_is_unchanged_not_silently_reused_for_new_route() -> None:
    workflow = _workflow()
    for old_op in (
        "telegram-migrate",
        "telegram-prepare",
        "telegram-install",
        "telegram-verify",
        "telegram-test",
    ):
        assert old_op in _options()
    assert "startsWith(inputs.operation, 'telegram-')" in workflow
    assert "docker system prune" not in workflow


def test_existing_cutover_import_receipt_guards_and_legacy_install_no_go_remain() -> None:
    workflow = _workflow()
    for marker in (
        "cutover-a-apply",
        "official-notice-import",
        "Reject legacy install routes without same-lease Boca-only postflight",
        "Require independent GO and exact official source artifact before SSH",
        "Fail closed on absent or ambiguous Cutover A host terminal receipt",
    ):
        assert marker in workflow
