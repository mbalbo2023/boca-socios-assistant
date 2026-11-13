"""R282: reject trivial Ruff/mypy failure before costly Boca image builds."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github/workflows/ci.yml"


def _jobs() -> dict[str, object]:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]


def test_image_and_integration_jobs_wait_for_one_fast_quality_gate() -> None:
    jobs = _jobs()
    assert set(jobs) == {"fast_quality", "quality", "image"}
    assert jobs["image"]["needs"] == "fast_quality"
    assert "needs.fast_quality.result == 'success'" in jobs["image"]["if"]
    assert jobs["quality"]["needs"] == "fast_quality"
    assert jobs["quality"]["if"] == "always()"
    fast = jobs["fast_quality"]
    assert fast["name"] == "fast-quality"
    full = jobs["quality"]
    assert full["name"] == "quality-and-tests"
    assert jobs["image"]["name"] == "image-build"
    assert fast["timeout-minutes"] <= 8


def test_format_lint_types_execute_once_only_in_fast_gate() -> None:
    jobs = _jobs()
    fast = jobs["fast_quality"]["steps"]
    full = jobs["quality"]["steps"]
    ci = CI.read_text(encoding="utf-8")
    assert ci.count("uv run ruff check .") == 1
    assert ci.count("uv run ruff format --check .") == 1
    assert ci.count("uv run mypy src") == 1
    runs = [s.get("run", "") for s in fast]
    assert any("uv run ruff check ." in code for code in runs)
    assert any("uv run ruff format --check ." in code for code in runs)
    assert any("uv run mypy src" in code for code in runs)
    assert any("uv run pytest -q -n 2" in s.get("run", "") for s in full)
    assert any("scripts/check_rca_lessons.py" in s.get("run", "") for s in full)
    assert not any("uv run ruff" in s.get("run", "") for s in full)
    assert not any("uv run mypy" in s.get("run", "") for s in full)
    assert all(
        "steps.docs_pr_scope.outputs.docs_only != 'true'" in s.get("if", "")
        for s in fast
        if s["name"] in ("Lint", "Format", "Types")
    )


def test_failed_fast_gate_causes_required_quality_job_to_fail_not_skip() -> None:
    quality = _jobs()["quality"]
    step = quality["steps"][0]
    assert "needs.fast_quality.result" in step["env"]["FAST_QUALITY_RESULT"]
    source = step["run"]
    for state in ("failure", "cancelled", "skipped", ""):
        proc = subprocess.run(  # noqa: S603 - run only checked-in CI gate shell offline
            ["/usr/bin/bash", "-e", "-c", source],
            env=os.environ | {"FAST_QUALITY_RESULT": state},
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode != 0, state
    passed = subprocess.run(  # noqa: S603 - run only checked-in CI gate shell offline
        ["/usr/bin/bash", "-e", "-c", source],
        env=os.environ | {"FAST_QUALITY_RESULT": "success"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert passed.returncode == 0
