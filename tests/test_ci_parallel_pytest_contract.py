"""Keep faster required CI collection deterministic and its RCA gate complete."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_required_ci_uses_pinned_two_workers_with_the_original_full_rca_gate() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert 'run: uv run pytest -q -n 2 --junitxml="$RUNNER_TEMP/rca-tests.xml"' in workflow
    assert workflow.index("      - name: Test\n") < workflow.index(
        "      - name: Enforce accepted RCA lessons against executed regressions\n"
    )
    assert 'run: uv run python scripts/check_rca_lessons.py "$RUNNER_TEMP/rca-tests.xml"' in (
        workflow
    )
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "pytest-xdist==3.8.0" in project["dependency-groups"]["dev"]
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    assert next(p["version"] for p in lock["package"] if p["name"] == "pytest-xdist") == ("3.8.0")


def test_telegram_negative_case_ids_do_not_change_with_worker_hash_seed() -> None:
    runs: list[list[str]] = []
    for seed in ("1", "42"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        env.pop("PYTEST_XDIST_WORKER", None)
        env.pop("PYTEST_XDIST_WORKER_COUNT", None)
        completed = subprocess.run(  # noqa: S603 - offline fixed test collection only
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "tests/test_telegram_pairing_ui.py",
            ],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
            timeout=20,
        )
        node_ids = [line for line in completed.stdout.splitlines() if line.startswith("tests/")]
        assert len(node_ids) > 10
        runs.append(node_ids)
    assert runs[0] == runs[1]
