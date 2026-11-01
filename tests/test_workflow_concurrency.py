"""PR validation must not consume the manual host-operation pending slot."""

import re
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ".github/workflows/boca-first-deploy.yml"
GROUP = (
    "${{ github.event_name == 'pull_request' && "
    "format('boca-first-deploy-pr-{0}', github.event.pull_request.number) "
    "|| 'boca-first-deploy' }}"
)
check_policy = runpy.run_path(str(ROOT / "scripts/check_repo_policy.py"))["check_policy"]


def _group(event: str, number: int | None = None) -> str:
    """Evaluate only the workflow's bounded event/PR routing grammar."""
    workflow = (ROOT / WORKFLOW).read_text()
    block = workflow.split("\nconcurrency:\n", 1)[1].split("\njobs:\n", 1)[0]
    expression = block.split("  group: ", 1)[1].splitlines()[0]
    if not expression.startswith("${{"):
        return expression
    match = re.fullmatch(
        r"\$\{\{ github.event_name == '([^']+)' && "
        r"format\('([^']+)', github.event.pull_request.number\) \|\| '([^']+)' \}\}",
        expression,
    )
    assert match is not None, "unexpected concurrency expression; review routing semantics"
    selected_event, template, fallback = match.groups()
    return template.format(number) if event == selected_event else fallback


def test_unrelated_prs_cannot_replace_each_others_pending_validation() -> None:
    groups = {_group("pull_request", number) for number in (128, 130, 132, 135)}
    assert len(groups) == 4
    assert "boca-first-deploy" not in groups
    assert _group("pull_request", 128) == "boca-first-deploy-pr-128"


def test_all_manual_operations_keep_one_constant_host_mutex() -> None:
    # No operation, SHA, ref or run ID participates in the accepted expression.
    assert _group("workflow_dispatch") == "boca-first-deploy"
    assert _group("workflow_dispatch", 128) == "boca-first-deploy"
    assert _group("push") == "boca-first-deploy"


def test_running_operations_are_never_cancelled_and_push_cannot_deploy() -> None:
    workflow = (ROOT / WORKFLOW).read_text()
    block = workflow.split("\nconcurrency:\n", 1)[1].split("\njobs:\n", 1)[0]
    assert block.strip().splitlines() == [f"group: {GROUP}", "  cancel-in-progress: false"]
    triggers = workflow.split("\non:\n", 1)[1].split("\npermissions:\n", 1)[0]
    assert re.findall(r"^  ([a-z_]+):", triggers, re.MULTILINE) == [
        "pull_request",
        "workflow_dispatch",
    ]
    assert (
        "  deploy:\n"
        "    if: github.event_name == 'workflow_dispatch' && "
        "github.ref == 'refs/heads/main' && "
        "github.repository == 'mbalbo2023/boca-socios-assistant' && "
        "github.actor == 'mbalbo2023'\n"
    ) in workflow


def test_policy_rejects_shared_pr_group_or_split_manual_mutex(tmp_path: Path) -> None:
    for relative in ("compose.yaml", "AGENTS.md", ".github/CODEOWNERS", ".github/pull_request_template.md"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((ROOT / relative).read_text())
    target = tmp_path / WORKFLOW
    target.parent.mkdir(parents=True, exist_ok=True)
    workflow = (ROOT / WORKFLOW).read_text()
    target.write_text(workflow)
    assert check_policy(tmp_path) == []
    for replacement in (
        "boca-first-deploy",
        "boca-first-deploy-${{ github.sha }}",
        GROUP.replace("pull_request'", "workflow_dispatch'"),
        GROUP.replace("|| 'boca-first-deploy'", "|| github.run_id"),
        GROUP.replace("pull_request.number", "run_id"),
    ):
        target.write_text(workflow.replace(f"  group: {GROUP}", f"  group: {replacement}"))
        assert any("concurrency" in finding for finding in check_policy(tmp_path)), replacement
    target.write_text(workflow.replace("cancel-in-progress: false", "cancel-in-progress: true"))
    assert any("concurrency" in finding for finding in check_policy(tmp_path))
