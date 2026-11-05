"""Workflow-level P0 GO_B PREPARE/APPLY regression matrix (no SSH executes)."""

from __future__ import annotations

from pathlib import Path

_YAML = (Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml").read_text(
    encoding="utf-8"
)


def _step(label: str, *, next_name: str = "      - name: ") -> str:
    anchor = f"      - name: {label}\n"
    assert _YAML.count(anchor) == 1
    return _YAML.split(anchor, 1)[1].split(next_name, 1)[0]


def test_protected_dispatch_25_input_max_and_no_new_ports() -> None:
    head = _YAML.split("permissions:\n", 1)[0]
    inputs = head.split("    inputs:\n", 1)[1]
    assert (
        sum(
            line.startswith("      ") and line.strip().endswith(":") for line in inputs.splitlines()
        )
        == 25
    )
    assert "port: 9000" not in _YAML
    assert "https://localhost:8443" not in _YAML
    assert "127.0.0.1:8443" in _YAML


def test_both_legacy_operations_prepare_with_blank_and_apply_with_run_id_only() -> None:
    early = _step("Require verified protected environment and matching main commit")
    assert (
        '[[ -z "$BOCA_PROTECTED_ACTION_CONTEXT" || "$BOCA_PROTECTED_ACTION_CONTEXT" =~ ^[1-9][0-9]{0,19}$ ]]'
        in early
    )
    assert '"$BOCA_PROTECTED_ACTION_CONTEXT" != "$GITHUB_RUN_ID"' in early
    assert 'test -z "$BOCA_OFFICIAL_CONTROLLER_ID"' in early
    assert 'test -z "$BOCA_LEGACY_CONTROLLER_ID"' in early
    assert "BOCA_SOURCE_SHA_SUBMITTED" in early


def test_android_voice_prepare_pins_are_derived_not_typed() -> None:
    first = _step("Derive current main image and browser release from genuine Actions receipts")
    assert "gh api" in first
    assert "select-current-release" in first
    assert "verify-current-release" in first
    observer = _step("Observe ONLY Boca rootless original/installed controller before GO_B review")
    assert "cutover-inventory-observe" in observer
    assert "official-inventory-observe" in observer
    assert "boca-legacy-readonly-ssh/config" in observer
    assert "boca-legacy-inventory-host.receipt" in observer
    assert "accept-observer" in observer
    assert "BOCA_LEGACY_GO" not in observer
    source = _step("Discover the one selected reviewed public notice artifact automatically")
    assert "select-official-artifact" in source
    assert "resolve-official-source" in source
    assert "BOCA_OFFICIAL_NEWS_RUN_ID" in source
    assert "runner-host-command" not in source


def test_prepare_only_publishes_reviewed_artifact_without_effect() -> None:
    stage = _step("Prepare no-effect immutable Cutover or official GO_B review object")
    assert "inputs.protected_action_context == ''" in stage
    assert "check_legacy_go_dispatch.py prepare" in stage
    assert "GO_BINDING_SHA256" not in stage
    assert "ssh " not in stage
    artifact = _step("Publish inert reviewed GO_B PREPARE coordinates and receipt")
    assert "boca-protected-legacy-go-prepare" in artifact
    assert "retention-days: 2" in artifact
    assert "upload-artifact@" in artifact


def test_apply_requires_actual_completed_prepare_and_protected_go_env() -> None:
    restore = _step("Restore independently reviewed legacy PREPARE source for APPLY")
    assert "gh api" in restore
    assert "gh run download" in restore
    assert "restore-early" in restore
    cutover = _step(
        "Require independently approved Cutover A GO_B bound to PREPARE and reviewed bytes"
    )
    assert "inputs.protected_action_context != ''" in cutover
    assert (
        "BOCA_CUTOVER_A_GO_BINDING_SHA256: ${{ vars.BOCA_CUTOVER_A_GO_BINDING_SHA256 }}" in cutover
    )
    assert "check_legacy_go_dispatch.py apply" in cutover
    assert "check_cutover_a_go.py --prepared-from-actions" in cutover
    assert "check_cutover_a_go.py --from-actions" not in cutover
    official = _step("Require independent official import GO_B and exact source ZIP")
    assert (
        "BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256: ${{ vars.BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256 }}"
        in official
    )
    assert "check_legacy_go_dispatch.py apply" in official
    assert "runner-preflight-prepared" in official
    assert "runner-preflight \\" not in official


def test_effect_and_ack_routes_are_apply_only_and_same_reviewed_host() -> None:
    ssh = _step("Configure pinned SSH host key and dedicated identity")
    assert "inputs.protected_action_context == ''" in ssh
    cutover = _step("Apply exactly one reviewed Cutover A host transaction through memfd")
    assert "inputs.protected_action_context != ''" in cutover
    assert "BOCA_CUTOVER_A_APPROVED_GO_BINDING_SHA256" in cutover
    assert "boca-cutover-a-host.receipt" in cutover
    official = _step("Import one reviewed official notice into the existing Boca volume")
    assert "inputs.protected_action_context != ''" in official
    assert "runner-host-command-prepared" in official
    assert "boca-official-import-host.receipt" in official
    cleanup = _step("Fail closed on absent or ambiguous Cutover A host terminal receipt")
    assert "inputs.protected_action_context != ''" in cleanup
    assert "scripts/check_cutover_a_go.py --assert-host-receipt" in cleanup
    assert "docker system prune" not in cleanup


def test_telegram_and_six_legacy_installs_remain_explicit_no_go() -> None:
    preflight = _step("Reject legacy install routes without same-lease Boca-only postflight")
    assert "NO_GO" in preflight
    check = _step("Require verified protected environment and matching main commit")
    assert "BOCA_TELEGRAM_POSTCUTOVER state=NO_GO" in check
    assert "cutover-a-apply" in check
    assert "official-notice-import" in check
    assert "telegram-activate" in check
