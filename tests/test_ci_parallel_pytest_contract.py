"""Keep faster required CI collection deterministic and its RCA gate complete."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def assert_required_ci_covers(*test_modules: str) -> None:
    """Require the real, unfiltered CI suite to discover these protected regressions."""
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    quality = workflow.split("  quality:\n", 1)[1].split("\n  image:\n", 1)[0]
    assert "    name: quality-and-tests\n" in quality
    step = quality.split("      - name: Test\n", 1)[1].split("      - name:", 1)[0]
    command = re.search(r"^        run: (.+)$", step, flags=re.MULTILINE)
    assert command is not None
    assert shlex.split(command[1]) == [
        "uv",
        "run",
        "pytest",
        "-q",
        "-n",
        "2",
        "--junitxml=$RUNNER_TEMP/rca-tests.xml",
    ]
    assert "        if: steps.docs_pr_scope.outputs.docs_only != 'true'\n" in step
    assert "continue-on-error" not in quality
    assert "PYTEST_ADDOPTS" not in workflow
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    options = project["tool"]["pytest"]["ini_options"]
    assert set(options) == {"testpaths", "addopts"}
    assert options["testpaths"] == ["tests"]
    approved_ignores = {
        "tests/test_synthetic_browser_worker.py",
        "tests/test_browser_playwright_factory.py",
        "tests/test_browser_on_demand.py",
        "tests/test_browser_ipc.py",
    }
    assert set(options["addopts"]) == {
        "-ra",
        "--strict-markers",
        "--strict-config",
        *(f"--ignore={path}" for path in approved_ignores),
    }
    for module in test_modules:
        path = Path(module)
        assert path.parent == Path("tests") and path.match("test_*.py"), module
        assert (ROOT / path).is_file(), module
        assert module not in approved_ignores, module


def test_first_deploy_pr_keeps_exclusive_checks_without_repeating_required_ci() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    pr = workflow.split("  pr-validation:\n", 1)[1].split("\n  deploy:\n", 1)[0]
    assert "    name: first-deploy-pr-validation\n" in pr
    assert "    if: github.event_name == 'pull_request'\n" in pr
    assert not re.search(r"(?m)^\s+(?:run: )?uv run pytest\b", pr)
    assert not re.search(r"(?m)^\s+(?:run: )?uv run mypy src(?:/|\s|$)", pr)
    assert (
        pr.count("uv run mypy --follow-imports=skip scripts/check_worker_physical_dispatch.py") == 1
    )
    assert pr.count("uv run python scripts/build_protected_boca_bundle.py") == 1
    assert "docker compose -p boca-socios -f compose.beta.yaml config --format json" in pr
    assert "-f compose.beta.yaml -f compose.beta.browser.yaml config --format json" in pr
    assert '"$BOCA_IMAGE" --topology=browser-ipc-v2' in pr
    assert "      - name: Assert PR cannot produce host cutover or cleanup receipt\n" in pr
    assert "BOCA_CUTOVER_A_PR_VERIFY state=SOURCE_ONLY host_calls=0" in pr
    assert "ssh boca-target" not in pr
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert re.search(r"(?m)^        run: uv run mypy src$", ci)
    assert_required_ci_covers("tests/test_ci_parallel_pytest_contract.py")


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
