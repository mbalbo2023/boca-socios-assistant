"""A45-R28 Accessibility UX: one live read PREPARE and short-id APPLY only.

Text-only first-deploy workflow proof; NEVER dispatch protected jobs or SSH.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "boca-first-deploy.yml"
)


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _step(name: str) -> str:
    text = _text()
    start = f"      - name: {name}\n"
    assert text.count(start) == 1
    return text.split(start, 1)[1].split("      - name:", 1)[0]


def test_dispatch_uses_one_existing_field_no_manual_pins_and_no_third_operation() -> None:
    workflow = _text()
    dispatch = workflow.split("  workflow_dispatch:\n", 1)[1].split("\npermissions:", 1)[0]
    assert dispatch.count("      protected_action_context:\n") == 1
    assert "Leave blank for Boca READ_ONLY PREPARE" in dispatch
    assert "APPLY uses only prior PREPARE run ID" in dispatch
    options = dispatch.split("options: [", 1)[1].split("]", 1)[0].split(",")
    assert " protected-go-prepare" in options or "protected-go-prepare" in options
    assert " lifecycle-apply" in options
    assert "lifecycle-inspect" not in options
    assert "lifecycle-observe" not in options
    assert len(re.findall(r"^      ([a-z_0-9]+):$", dispatch, flags=re.MULTILINE)) == 25
    assert 'test -z "$BOCA_PROTECTED_ACTION_CONTEXT"' in workflow
    assert '[[ "$BOCA_PROTECTED_ACTION_CONTEXT" =~ ^[1-9][0-9]{0,19}$ ]]' in workflow


def test_one_host_read_precedes_prepare_receipt_and_is_not_host_lifecycle_apply() -> None:
    w = _text()
    ssh_setup = _step("Configure pinned READ_ONLY SSH for lifecycle PREPARE")
    observe = _step("Observe one existing Boca owner intent and installed pins READ_ONLY")
    prepare = _step("Prepare one reviewed lifecycle GO from Boca READ_ONLY observation")
    assert "if: inputs.operation == 'protected-go-prepare'" in ssh_setup
    assert "if: inputs.operation == 'protected-go-prepare'" in observe
    assert observe.count(" 95s ssh") == 1
    assert "lifecycle-observe" in observe
    assert "lifecycle-apply" not in observe
    assert "check_main_ref.py" in observe
    assert "build_protected_boca_bundle.py" in observe
    assert "boca-protected-lifecycle-review.pyz" in observe
    assert "boca-lifecycle-observed-public.json" in observe
    assert "check_protected_go_prepare.py --assert-observed" in observe
    for forbidden in (
        "docker start",
        "docker stop",
        "docker rm",
        "docker run",
        "prune",
        "boca-lifecycle-host.receipt",
    ):
        assert forbidden not in observe
    assert "check_protected_go_prepare.py --prepare" in prepare
    assert "host_reads=1 host_mutations=0" in prepare
    assert "ssh " not in prepare
    ids = [
        "Configure pinned READ_ONLY SSH for lifecycle PREPARE",
        "Observe one existing Boca owner intent and installed pins READ_ONLY",
        "Prepare one reviewed lifecycle GO from Boca READ_ONLY observation",
        "Publish exact Boca READ_ONLY lifecycle PREPARE receipt for independent review",
    ]
    assert [w.index(f"      - name: {name}") for name in ids] == sorted(
        w.index(f"      - name: {name}") for name in ids
    )


def test_apply_short_id_downloads_reviewed_context_then_go_before_effect() -> None:
    w = _text()
    gate = _step("Require distinct independent lifecycle GO and immutable PREPARE before SSH")
    assert "check_protected_go_prepare.py --prepare-ref" in gate
    assert '[[ "$prepare_id" =~ ^[1-9][0-9]{0,19}$ ]]' in gate
    assert "gh api" in gate
    assert "gh run download" in gate
    assert "boca-protected-go-prepare" in gate
    assert "check_protected_go_prepare.py --apply" in gate
    assert "BOCA_LIFECYCLE_GO_BINDING_SHA256" in gate
    assert "ssh " not in gate
    effect = _step("Apply one exact-ID Boca owner lifecycle request through fresh host lease")
    assert "if: inputs.operation == 'lifecycle-apply'" in effect
    assert 'timeout --signal=TERM --kill-after=5s 900s ssh' in effect
    assert "check_main_ref.py" in effect
    assert "boca-lifecycle-host.receipt" in effect
    assert "lifecycle-apply" in effect
    assert w.index("      - name: Require distinct independent lifecycle GO") < w.index(
        "      - name: Configure pinned SSH host key and dedicated identity"
    ) < w.index("      - name: Apply one exact-ID")


def test_mobile_prepare_artifact_is_not_itself_approval_or_telegram_access() -> None:
    w = _text()
    artifact = _step(
        "Publish exact Boca READ_ONLY lifecycle PREPARE receipt for independent review"
    )
    assert "boca-lifecycle-observed-public.json" in artifact
    assert "boca-lifecycle-prepare.receipt.json" in artifact
    assert "boca-lifecycle-apply-context.txt" in artifact
    assert "retention-days: 2" in artifact
    assert "BOCA_LIFECYCLE_GO_BINDING_SHA256" in w
    assert "telegram-activate)" in w
    assert "state=NO_GO reason=host_same_lease_backend_unverified" in w
    assert "BOCA_CUTOVER_A_GO_BINDING_SHA256" in w
    assert "BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256" in w
    assert "docker system prune" not in w
