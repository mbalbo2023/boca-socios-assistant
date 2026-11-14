"""R282: reject trivial Ruff/mypy failure before costly Boca image builds."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github/workflows/ci.yml"


def _jobs() -> tuple[str, str, str]:
    source = CI.read_text(encoding="utf-8")
    fast = source.split("  fast_quality:\n", 1)[1].split("  quality:\n", 1)[0]
    quality = source.split("  quality:\n", 1)[1].split("  image:\n", 1)[0]
    image = source.split("  image:\n", 1)[1]
    assert source.count("  fast_quality:\n") == 1
    assert source.count("  quality:\n") == 1
    assert source.count("  image:\n") == 1
    return fast, quality, image


def test_image_and_integration_jobs_wait_for_one_fast_quality_gate() -> None:
    fast, full, image = _jobs()
    assert "    needs: fast_quality\n" in image
    assert "    if: needs.fast_quality.result == 'success'\n" in image
    assert "    needs: fast_quality\n" in full
    assert "    if: always()\n" in full
    assert "    name: fast-quality\n" in fast
    assert "    name: quality-and-tests\n" in full
    assert "    name: image-build\n" in image
    assert "    timeout-minutes: 8\n" in fast


def test_format_lint_types_execute_once_only_in_fast_gate() -> None:
    fast, full, _image = _jobs()
    ci = CI.read_text(encoding="utf-8")
    assert ci.count("uv run ruff check .") == 1
    assert ci.count("uv run ruff format --check .") == 1
    assert ci.count("uv run mypy src") == 1
    assert "uv run ruff check ." in fast
    assert "uv run ruff format --check ." in fast
    assert "uv run mypy src" in fast
    assert "uv run pytest -q -n 2" in full
    assert "scripts/check_rca_lessons.py" in full
    assert "uv run ruff" not in full
    assert "uv run mypy" not in full
    for name in ("Lint", "Format", "Types"):
        step = fast.split(f"      - name: {name}\n", 1)[1].split("      - name:", 1)[0]
        assert "if: steps.docs_pr_scope.outputs.docs_only != 'true'" in step


def test_pytest_collection_is_covered_before_image_build_without_executing_cases() -> None:
    fast, full, _image = _jobs()
    marker = "      - name: Collect exact pytest inventory before Docker builds\n"
    assert marker in fast
    collection = fast.split(marker, 1)[1].split("      - name:", 1)[0]
    assert "if: steps.docs_pr_scope.outputs.docs_only != 'true'" in collection
    assert "uv run pytest --collect-only -q" in collection
    assert "run pytest -q -n 2" not in collection
    assert "uv run pytest -q -n 2" in full


def test_docs_path_still_checks_adr_uniqueness_before_expensive_jobs() -> None:
    fast, full, _image = _jobs()
    marker = "      - name: Repository isolation gate\n"
    assert marker in fast
    step = fast.split(marker, 1)[1].split("      - name:", 1)[0]
    assert "        if:" not in step
    assert "run: python3 scripts/check_repo_policy.py" in step
    assert "scripts/check_repo_policy.py" not in full


def test_failed_fast_gate_causes_required_quality_job_to_fail_not_skip() -> None:
    _fast, quality, _image = _jobs()
    step = quality.split("      - name: Require successful fast-quality gate\n", 1)[1].split(
        "      - name:", 1
    )[0]
    assert "FAST_QUALITY_RESULT: ${{ needs.fast_quality.result }}" in step
    source = step.split("        run: ", 1)[1].split("\n", 1)[0]
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
