"""Offline contracts for the protected, read-only-artifact import route.

These tests inspect only the dedicated Boca workflow. They never download an
artifact, invoke SSH/Docker or touch the controller's /data volume.
"""

from __future__ import annotations

from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
HOST_HELPER = (
    Path(__file__).resolve().parents[1] / "src/boca_socios/host_official_notice_actions.py"
)
OP = "official-notice-import"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _named_step(name: str) -> str:
    marker = f"      - name: {name}\n"
    parts = _text().split(marker, 1)
    assert len(parts) == 2, f"required step absent: {name}"
    return parts[1].split("      - name:", 1)[0]


def test_manual_operation_is_explicit_and_requires_exact_source_artifact_inputs() -> None:
    workflow = _text()
    assert OP in workflow.split("options: [", 1)[1].split("]", 1)[0]
    for name in (
        "official_news_run_id",
        "official_news_artifact_id",
        "official_news_zip_sha256",
        "official_news_jsonl_sha256",
        "official_news_html_sha256",
        "official_news_observed_at_utc",
    ):
        assert f"      {name}:\n" in workflow


def test_artifact_go_is_independent_of_dispatch_and_precedes_ssh() -> None:
    workflow = _text()
    preflight = "Require independent GO and exact official source artifact before SSH"
    assert workflow.index(f"      - name: {preflight}\n") < workflow.index(
        "      - name: Configure pinned SSH host key"
    )
    step = _named_step(preflight)
    assert f"if: inputs.operation == '{OP}'" in step
    assert (
        "BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256: ${{ vars.BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256 }}"
        in step
    )
    assert "BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256" in step
    assert "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in step
    assert "gh api" in step
    assert "artifact" in step.lower()
    assert "SHA256" in step or "sha256" in step


def test_host_effect_route_and_terminal_no_go_are_both_explicit() -> None:
    workflow = _text()
    effect = "Import one reviewed official notice into the existing Boca volume"
    receipt = "Refuse missing or ambiguous official import receipt"
    assert workflow.index(f"      - name: {effect}") < workflow.index(f"      - name: {receipt}")
    assert f"if: inputs.operation == '{OP}'" in _named_step(effect)
    assert f"inputs.operation == '{OP}'" in _named_step(receipt)
    assert "if: ${{ always()" in _named_step(receipt)
    assert "NO_GO" in _named_step(receipt)


@pytest.mark.parametrize(
    "phrase",
    (
        "boca-socios-assistant",
        "actions/runs",
        "artifact",
        "source_sha256",
        "observed_at_utc",
        "boca_official_notices.jsonl",
    ),
)
def test_official_import_does_not_infer_identity_or_destination(phrase: str) -> None:
    section = _text().split("      - name: Require independent GO and exact official", 1)[1]
    # The workflow supplies only reviewed coordinates; the fixed helper
    # constructs the non-overridable /data destination and public source.
    assert phrase in (section + HOST_HELPER.read_text(encoding="utf-8"))


def test_pr_validation_is_offline_and_manual_job_is_never_reached_on_pr() -> None:
    workflow = _text()
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "github.actor == 'mbalbo2023'" in workflow
    pr = workflow.split("  pr-validation:", 1)[1].split("  pr-runtime-smoke:", 1)[0]
    assert "tests/test_official_import_actions_r24.py" in pr
    assert "ssh boca-target" not in pr
