"""Contract tests for the optional, no-egress Chromium synthetic journey in CI."""

from __future__ import annotations

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


def test_ci_synthetic_chromium_is_offline_capped_and_selectively_cleaned() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    start = workflow.index("      - name: Run synthetic Chromium DOM journey offline")
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
        "scripts.run_synthetic_ticket_flow",
    ):
        assert required in smoke
    assert "if: always()" in cleanup
    assert "docker container rm" in cleanup
    assert "docker image rm" in cleanup
    assert "docker system prune" not in workflow
    assert "boca-target" not in smoke + cleanup


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
