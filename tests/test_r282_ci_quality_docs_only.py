"""R282: an exact internal Markdown-only PR skips *both* costly CI jobs.

All other PRs and every push/dispatch retain the complete mandatory gates.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from test_ci_docs_only_fast_path import _merged_pr

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/ci.yml"
CLASSIFIER = ROOT / "scripts/classify_exact_internal_pr_docs.py"


def _classify_synthetic(repo: Path, event: dict[str, str]) -> bool:
    (repo / "scripts").mkdir(exist_ok=True)
    shutil.copyfile(CLASSIFIER, repo / "scripts" / CLASSIFIER.name)
    done = subprocess.run(
        ["/usr/bin/python3", "scripts/classify_exact_internal_pr_docs.py"],
        cwd=repo,
        env=os.environ | event,
        check=True,
        capture_output=True,
        text=True,
    )
    assert done.stderr == ""
    assert done.stdout in ("true\n", "false\n")
    return done.stdout == "true\n"


def test_exact_merge_proves_docs_only_and_code_change_never_does(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "code").mkdir()
    docs_repo, docs_event = _merged_pr(tmp_path / "docs", {"docs/ADR/next.md": "docs\n"})
    assert _classify_synthetic(docs_repo, docs_event)
    code_repo, code_event = _merged_pr(tmp_path / "code", {"src/fixture.py": "VERSION = 2\n"})
    assert not _classify_synthetic(code_repo, code_event)
    assert not _classify_synthetic(docs_repo, docs_event | {"GITHUB_EVENT_NAME": "push"})


def test_quality_job_only_skips_full_gates_after_authenticated_docs_only_pr() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    quality = workflow.split("  quality:\n", 1)[1].split("  image:\n", 1)[0]
    image = workflow.split("  image:\n", 1)[1]
    fast = workflow.split("  fast_quality:\n", 1)[1].split("  quality:\n", 1)[0]
    classifier_command = (
        'git show "$PR_BASE_SHA:scripts/classify_exact_internal_pr_docs.py" | python3 -I -'
    )
    assert quality.count(classifier_command) == 1
    assert image.count(classifier_command) == 1
    assert "id: docs_pr_scope" in quality
    assert "id: docs_pr_scope" in image
    assert "git diff --check" in fast
    for step in quality.split("      - name: ")[1:]:
        name = step.split("\n", 1)[0]
        if name in (
            "Require successful fast-quality gate",
            "Checkout exactly the requested commit",
            "Classify exact internal PR Markdown-only changes",
        ):
            continue
        assert "if: steps.docs_pr_scope.outputs.docs_only != 'true'" in step, name
    assert "uv run pytest -q -n 2" in quality
    assert "scripts/check_rca_lessons.py" in quality
    assert "scripts/trivy_scan_image.sh" in image
