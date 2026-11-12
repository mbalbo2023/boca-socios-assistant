"""R245: an exact internal PR docs change may bypass disposable image probes only."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/ci.yml"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - isolated real Git fixture; fixed repository path
        ["/usr/bin/git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _merged_pr(
    tmp_path: Path,
    changed: dict[str, str | None],
    *,
    symlink: bool = False,
    executable: bool = False,
    empty: bool = False,
) -> tuple[Path, dict[str, str]]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "CI Test")
    _git(repo, "config", "user.email", "ci@example.invalid")
    for name, value in {
        "src/fixture.py": "VERSION = 1\n",
        "docs/ADR/baseline.md": "base\n",
        "docs/handoffs/old.md": "historical\n",
    }.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    _git(repo, "add", "--all")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "-q", "-c", "pr")
    for name, value in changed.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if value is None:
            path.unlink()
        elif symlink:
            path.symlink_to("baseline.md")
        else:
            path.write_text(value, encoding="utf-8")
            if executable:
                path.chmod(0o755)
    _git(repo, "add", "--all")
    if empty:
        _git(repo, "commit", "-qm", "empty", "--allow-empty")
    else:
        _git(repo, "commit", "-qm", "candidate")
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "-q", "main")
    _git(repo, "merge", "--no-ff", "-qm", "synthetic PR merge", "pr")
    merge = _git(repo, "rev-parse", "HEAD")
    return repo, {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_REPOSITORY": "mbalbo2023/boca-socios-assistant",
        "GITHUB_REF": "refs/pull/493/merge",
        "GITHUB_SHA": merge,
        "PR_HEAD_REPO": "mbalbo2023/boca-socios-assistant",
        "PR_BASE_REF": "main",
        "PR_BASE_SHA": base,
        "PR_HEAD_SHA": head,
    }


def _classifier_body() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    marker = "      - name: Classify exact internal PR Markdown-only changes\n"
    assert marker in workflow, "Missing fail-closed image-build path classifier"
    step = workflow.split(marker, 1)[1].split("      - name:", 1)[0]
    assert "        run: |\n" in step
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


def _classify(repo: Path, context: dict[str, str]) -> tuple[bool, str]:
    output = repo / "output.txt"
    env = os.environ | context | {"GITHUB_OUTPUT": str(output)}
    result = subprocess.run(  # noqa: S603 - checked-in CI shell, synthetic Git repo
        ["/usr/bin/bash", "-e", "-c", _classifier_body()],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=8,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text(encoding="utf-8") in (
        "docs_only=true\n",
        "docs_only=false\n",
    )
    return output.read_text(encoding="utf-8") == "docs_only=true\n", result.stdout


@pytest.mark.parametrize(
    "changed",
    [
        {"docs/ADR/0248-r245.md": "ADR only\n"},
        {"docs/handoffs/r245.md": "handoff only\n"},
        {"docs/ADR/next/nested.md": "nested ADR\n", "docs/handoffs/next.md": "new\n"},
        {"docs/handoffs/old.md": None},
    ],
)
def test_exact_merge_parent_docs_only_internal_pr_is_fast(
    tmp_path: Path, changed: dict[str, str | None]
) -> None:
    repo, event = _merged_pr(tmp_path, changed)
    fast, receipt = _classify(repo, event)
    assert fast
    assert "BOCA_CI_SCOPE mode=DOCS_ONLY" in receipt


@pytest.mark.parametrize(
    "changed",
    [
        {"README.md": "copied into the controller image\n"},
        {"Dockerfile.browser": "FROM scratch\n"},
        {"src/fixture.py": "VERSION = 2\n"},
        {".github/workflows/ci.yml": "name: CI\n"},
        {"docs/quality/rca.md": "unreviewed doc category\n"},
        {"docs/ADR/not-markdown.txt": "wrong extension\n"},
        {"docs/ADR/escape\nname.md": "control character\n"},
        {"docs/ADR/valid.md": "ADR\n", "src/fixture.py": "VERSION = 2\n"},
    ],
)
def test_any_image_input_or_unsafe_doc_path_forces_full_ci(
    tmp_path: Path, changed: dict[str, str]
) -> None:
    repo, event = _merged_pr(tmp_path, changed)
    fast, receipt = _classify(repo, event)
    assert not fast
    assert "BOCA_CI_SCOPE mode=FULL" in receipt


@pytest.mark.parametrize(
    "key,value",
    [
        ("GITHUB_EVENT_NAME", "push"),
        ("GITHUB_EVENT_NAME", "workflow_dispatch"),
        ("GITHUB_REPOSITORY", "foreign/boca-socios-assistant"),
        ("GITHUB_REF", "refs/heads/main"),
        ("GITHUB_SHA", "a" * 40),
        ("PR_BASE_SHA", "b" * 40),
        ("PR_HEAD_SHA", "c" * 40),
        ("PR_BASE_REF", "develop"),
        ("PR_HEAD_REPO", "fork/boca-socios-assistant"),
    ],
)
def test_unauthenticated_or_wrong_commit_context_forces_full_ci(
    tmp_path: Path, key: str, value: str
) -> None:
    repo, event = _merged_pr(tmp_path, {"docs/ADR/next.md": "doc\n"})
    fast, _ = _classify(repo, event | {key: value})
    assert not fast


@pytest.mark.parametrize("symlink,executable", [(True, False), (False, True)])
def test_non_regular_markdown_file_forces_full_ci(
    tmp_path: Path, symlink: bool, executable: bool
) -> None:
    repo, event = _merged_pr(
        tmp_path, {"docs/ADR/next.md": "doc\n"}, symlink=symlink, executable=executable
    )
    fast, _ = _classify(repo, event)
    assert not fast


def test_empty_pr_diff_forces_full_ci(tmp_path: Path) -> None:
    repo, event = _merged_pr(tmp_path, {}, empty=True)
    fast, _ = _classify(repo, event)
    assert not fast


def test_missing_git_history_or_nonmerge_head_forces_full_ci(tmp_path: Path) -> None:
    repo, event = _merged_pr(tmp_path, {"docs/ADR/next.md": "doc\n"})
    _git(repo, "checkout", "-q", event["PR_HEAD_SHA"])
    fast, _ = _classify(repo, event | {"GITHUB_SHA": event["PR_HEAD_SHA"]})
    assert not fast


def test_required_image_context_and_all_real_probes_are_preserved_on_full_path() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "  pull_request:" in workflow and "  push:\n    branches: [main]" in workflow
    assert "    name: image-build" in workflow
    assert workflow.count("docker build") == 2
    assert workflow.count("run: bash scripts/trivy_scan_image.sh") == 2
    image = workflow.split("  image:\n", 1)[1]
    steps = image.split("      - name: ")[1:]
    assert len(steps) >= 35
    for step in steps:
        name = step.split("\n", 1)[0]
        if name in (
            "Checkout exact source",
            "Classify exact internal PR Markdown-only changes",
        ):
            continue
        assert "        if: " in step, f"Full-image step missing docs guard: {name}"
        assert "steps.docs_pr_scope.outputs.docs_only != 'true'" in step, name
        if name.startswith("Remove only ") or name.startswith("Clean disposable "):
            assert "if: always() && " in step, name
