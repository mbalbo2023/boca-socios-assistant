"""Offline CI contracts for the owner's externally validated browser blackbox."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from runpy import run_path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_browser_image_contains_only_required_synthetic_contracts() -> None:
    dockerfile = (ROOT / "Dockerfile.browser").read_text(encoding="utf-8")
    assert "COPY scripts/run_synthetic_ticket_flow.py" in dockerfile
    assert "COPY src/boca_socios/browser/" in dockerfile
    assert "src/boca_socios/domain/policy.py" in dockerfile
    assert "PYTHONPATH=/app/src" in dockerfile
    assert "COPY src/ ./src/" not in dockerfile
    assert "COPY src/boca_socios/runtime.py" not in dockerfile
    assert "BOCA_OBSERVER_STOP=1" in dockerfile


def test_ci_excludes_owner_synthetic_journey_but_preserves_other_offline_fixtures() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "      - name: Run synthetic Chromium DOM journey offline" not in workflow
    assert "python -m scripts.run_synthetic_ticket_flow" not in workflow
    start = workflow.index("      - name: Run public-login structural fixtures in offline Chromium")
    end = workflow.index("      - name: Clean disposable browser runner resources", start)
    smoke = workflow[start:end]
    cleanup = workflow[end:]
    for required in (
        "--network none",
        "--cgroupns=private",
        "--read-only",
        "--memory=768m",
        "--pids-limit=128",
        "--cpus=1",
        "--security-opt no-new-privileges",
        "--user 10002:10002",
        "seccomp=docker/seccomp_profile.json",
        "scripts.run_public_observer_offline_chromium",
        "scripts.run_telegram_setup_ui_offline_chromium",
    ):
        assert required in smoke
    assert "if: always()" in cleanup
    assert "docker container rm" in cleanup
    assert "docker image rm" in cleanup
    assert "docker system prune" not in workflow
    assert "boca-target" not in smoke + cleanup


def test_linters_types_and_local_tests_exclude_only_owner_blackbox_modules() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    reserved = (
        "src/boca_socios/browser/synthetic.py",
        "src/boca_socios/browser/ipc_worker.py",
    )
    assert set(reserved) <= set(config["tool"]["ruff"]["extend-exclude"])
    mypy = config["tool"]["mypy"]
    for path in reserved:
        assert any(re.fullmatch(pattern, path) for pattern in mypy["exclude"])
    assert any(
        override["follow_imports"] == "skip"
        and set(override["module"])
        == {"boca_socios.browser.synthetic", "boca_socios.browser.ipc_worker"}
        for override in config["tool"]["mypy"]["overrides"]
    )
    assert {
        "--ignore=tests/test_synthetic_browser_worker.py",
        "--ignore=tests/test_browser_playwright_factory.py",
        "--ignore=tests/test_browser_on_demand.py",
        "--ignore=tests/test_browser_ipc.py",
    } <= set(config["tool"]["pytest"]["ini_options"]["addopts"])


def test_synthetic_browser_receipt_requires_exact_allowlisted_fields() -> None:
    parser = run_path(str(ROOT / "scripts/check_synthetic_browser_receipt.py"))
    assert parser["validate_receipt"](
        '{"mode":"synthetic_only","result":"reserved_in_simulator","notices":1}\n'
    )
    for invalid in (
        "",
        "{}",
        '{"mode":"live","result":"reserved_in_simulator","notices":1}\n',
        '{"mode":"synthetic_only","result":"confirmed","notices":1}\n',
        '{"mode":"synthetic_only","result":"reserved_in_simulator","notices":2}\n',
        '{"mode":"synthetic_only","result":"reserved_in_simulator","notices":1,"extra":1}\n',
        '{"mode":"synthetic_only","result":"reserved_in_simulator","notices":1}\n{}\n',
    ):
        with pytest.raises(ValueError):
            parser["validate_receipt"](invalid)
