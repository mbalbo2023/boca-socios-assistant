"""R89: one-shot worker preflight form guidance must match protected admission.

These tests read workflow/UI help and the current operator guide only. No
GitHub Actions dispatch, Docker, SSH, browser or host operation is performed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/boca-first-deploy.yml"
OPERATIONS = ROOT / "docs/OPERATIONS.md"
OPERATION = "cutover-a-worker-preflight"
FIELDS = (
    "source_sha",
    "image_ref",
    "browser_image_ref",
    "release_run_id",
    "legacy_source_sha",
    "legacy_image_ref",
    "legacy_release_run_id",
    "legacy_controller_id",
)


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _form_help() -> dict[str, str]:
    """Extract precisely the user-visible workflow_dispatch input help."""
    workflow = _workflow()
    assert workflow.count("  workflow_dispatch:\n    inputs:\n") == 1
    input_block = workflow.split("  workflow_dispatch:\n    inputs:\n", 1)[1].split(
        "\npermissions:\n", 1
    )[0]
    entries = re.findall(
        r"^      ([a-z][a-z0-9_]*):\n        description: ([^\n]+)$",
        input_block,
        re.MULTILINE,
    )
    names = [name for name, _ in entries]
    assert len(names) == len(set(names)), "duplicate form input key"
    return dict(entries)


@pytest.mark.parametrize(
    ("field", "required_terms"),
    [
        ("image_ref", ("required", "controller", "sha256", "release")),
        ("browser_image_ref", ("required", "browser", "sha256", "release")),
        ("release_run_id", ("required", "dual", "manifest", "run")),
        ("legacy_release_run_id", ("required", "historical", "release", "run")),
        ("legacy_controller_id", ("required", "original", "64-hex", "cid")),
    ],
)
def test_one_shot_preflight_ui_help_requires_each_pinned_value(
    field: str, required_terms: tuple[str, ...]
) -> None:
    """A misleading optional/blank instruction could consume the only dispatch."""
    description = _form_help()[field].lower()
    assert OPERATION in description, f"{field}: missing exact one-shot operation in form help"
    for term in required_terms:
        assert term in description, f"{field}: missing {term!r} in form help"
    assert not re.search(r"\bblank\s+for\s+[^;,.]*preflight\b", description)


def test_worker_preflight_legacy_release_is_not_cutover_prepare_run() -> None:
    description = _form_help()["legacy_release_run_id"].lower()
    assert "historical" in description and "release" in description
    assert re.search(r"\bnot\b.{0,28}\bprepare\b", description), (
        "historical release run ID must be distinguished from a Cutover PREPARE run"
    )
    assert "reconcile only" not in description


def test_worker_preflight_budget_help_identifies_exact_required_choice() -> None:
    """The form must identify the safe budget before a one-shot dispatch."""
    description = _form_help()["resource_budget"].lower()
    assert OPERATION in description
    assert "1.5cpu-1024m-192pids" in description
    assert "required" in description
    workflow = _workflow()
    assert "options: [0.5cpu-256m-64pids, 1.5cpu-1024m-192pids, 1.75cpu-1152m-224pids]" in workflow


def test_worker_preflight_context_help_distinguishes_effects_from_readonly_prepare() -> None:
    """An empty context is required, but the Docker preflight is effectful."""
    description = _form_help()["protected_action_context"]
    assert "Leave blank for Boca READ_ONLY PREPARE" in description
    assert OPERATION in description
    lowered = description.lower()
    assert "blank" in lowered
    assert "effectful" in lowered
    assert "not read_only" in lowered or "not read-only" in lowered


def test_form_help_corresponds_to_actual_fail_closed_pre_ssh_gate() -> None:
    """Keep form help coupled to existing gates, without changing the gates."""
    workflow = _workflow()
    case = "            cutover-a-observe|cutover-a-worker-preflight|cutover-a-apply)\n"
    assert workflow.count(case) == 1
    branch = workflow.split(case, 1)[1].split("            official-notice-import)", 1)[0]
    assert (
        '"$BOCA_OPERATION" = cutover-a-observe || "$BOCA_OPERATION" = cutover-a-worker-preflight'
    ) in branch
    assert (
        '"$BOCA_OPERATION" = cutover-a-apply || "$BOCA_OPERATION" = cutover-a-worker-preflight'
    ) in branch

    for required in (
        '[[ "$BOCA_LEGACY_SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]]',
        '[[ "$BOCA_LEGACY_IMAGE_REF" =~ ^ghcr[.]io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}$ ]]',
        '[[ "$BOCA_LEGACY_RELEASE_RUN_ID" =~ ^[1-9][0-9]{0,19}$ ]]',
        '[[ "$BOCA_LEGACY_CONTROLLER_ID" =~ ^[0-9a-f]{64}$ ]]',
        '[[ "$BOCA_BROWSER_IMAGE_REF" =~ ^ghcr[.]io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}$ ]]',
        'test -n "$BOCA_IMAGE_REF"',
        'test -n "$BOCA_RELEASE_RUN_ID"',
        'test -z "$BOCA_PROTECTED_ACTION_CONTEXT"',
    ):
        assert required in branch, f"protected pre-SSH preflight admission weakened: {required}"


def test_one_shot_anti_replay_remains_before_ssh() -> None:
    workflow = _workflow()
    assert workflow.count("'BOCA-R84-WORKER-PREFLIGHT-ONCE'") == 1
    gate = workflow.index("- name: Require one unique R84 worker preflight dispatch before SSH")
    ssh = workflow.index(
        "- name: Preflight exact dual GHCR image and rootless worker boundary without PREPARE"
    )
    assert gate < ssh
    assert "python -m scripts.check_worker_preflight_dispatch" in workflow[gate:ssh]


def test_r89_guidance_regression_is_selected_by_protected_pr_validation() -> None:
    workflow = _workflow()
    marker = "      - name: Validate protected Cutover A, Option B ZIP and cleanup offline only\n"
    assert workflow.count(marker) == 1
    step = workflow.split(marker, 1)[1].split("\n      - name:", 1)[0]
    assert step.count("tests/test_r89_preflight_input_descriptions.py") == 1


def _current_worker_guide() -> str:
    text = OPERATIONS.read_text(encoding="utf-8")
    current_headings = list(re.finditer(r"(?m)^## Procedimiento vigente Cutover V3[^\n]*$", text))
    assert len(current_headings) == 1, "Rule84 requires exactly one current Cutover V3 procedure"
    # Scope to the actual current procedure, not an unrelated historical
    # checkpoint that may precede it in the living operations document.
    remainder = text[current_headings[0].end() :]
    next_section = re.search(r"(?m)^## ", remainder)
    current = remainder[: next_section.start()] if next_section else remainder
    headings = list(re.finditer(r"(?im)^###\s+[^\n]*worker preflight[^\n]*$", current))
    assert len(headings) == 1, (
        "Rule84 requires one current worker preflight checklist before historical instructions"
    )
    return current[headings[0].end() :].split("\n### ", 1)[0]


def test_rule84_current_worker_preflight_checklist_names_all_manual_coordinates() -> None:
    guide = _current_worker_guide().lower()
    assert OPERATION in guide
    for field in FIELDS:
        assert f"`{field}`" in guide, f"Rule84 worker preflight checklist omits {field}"
    assert "`protected_action_context`" in guide
    assert "vacío" in guide or "empty" in guide
    assert "manifest" in guide and "dual" in guide


def test_rule84_explains_invalid_dispatch_consumes_same_sha_one_shot() -> None:
    guide = _current_worker_guide().lower()
    assert "cutover-a-apply" in guide and "prepare" in guide
    assert "one-shot" in guide and "no_retry" in guide
    assert "sha" in guide and "ssh" in guide
    assert "antes" in guide or "before" in guide
    assert "no_go" in guide
    assert "pr" in guide and "go" in guide
