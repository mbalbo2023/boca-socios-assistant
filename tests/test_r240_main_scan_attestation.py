"""R240: a main push may reuse only authenticated exact-sha image scan evidence."""

from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/verify_main_ci_image_scan.py"
SECURITY = ROOT / ".github/workflows/image-security.yml"
SHA = "a" * 40
REPO = "mbalbo2023/boca-socios-assistant"


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("verify_main_ci_image_scan", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _evidence() -> tuple[dict[str, Any], dict[str, Any]]:
    runs = {
        "total_count": 1,
        "workflow_runs": [
            {
                "id": 1234,
                "head_sha": SHA,
                "head_branch": "main",
                "event": "push",
                "path": ".github/workflows/ci.yml",
                "run_attempt": 1,
                "check_suite_id": 4567,
                "status": "completed",
                "conclusion": "success",
                "repository": {"full_name": REPO},
                "head_repository": {"full_name": REPO},
            }
        ],
    }
    jobs = {
        "total_count": 2,
        "jobs": [
            {
                "id": 999,
                "run_id": 1234,
                "name": "image-build",
                "head_sha": SHA,
                "status": "completed",
                "conclusion": "success",
                "steps": [
                    {
                        "name": "Require scan aliases to identify the exact built pair",
                        "status": "completed",
                        "conclusion": "success",
                    },
                    {
                        "name": "Scan before any image publication",
                        "status": "completed",
                        "conclusion": "success",
                    },
                    {
                        "name": "Scan browser image before any publication",
                        "status": "completed",
                        "conclusion": "success",
                    },
                ],
            },
            {
                "id": 998,
                "run_id": 1234,
                "name": "quality-and-tests",
                "head_sha": SHA,
                "run_attempt": 1,
                "status": "completed",
                "conclusion": "success",
                "steps": [],
            },
        ],
    }
    return runs, jobs


@pytest.mark.parametrize("role", ["controller", "browser"])
def test_exact_main_ci_image_scan_attestation(role: str) -> None:
    runs, jobs = _evidence()
    assert _module().verify_attestation(runs, jobs, SHA, role) == (1234, 999)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("total_count",), 2),
        (("workflow_runs", 0, "head_sha"), "b" * 40),
        (("workflow_runs", 0, "head_branch"), "feature"),
        (("workflow_runs", 0, "event"), "pull_request"),
        (("workflow_runs", 0, "path"), ".github/workflows/evil.yml"),
        (("workflow_runs", 0, "run_attempt"), 2),
        (("workflow_runs", 0, "status"), "in_progress"),
        (("workflow_runs", 0, "conclusion"), "failure"),
        (("workflow_runs", 0, "repository", "full_name"), "other/repo"),
        (("workflow_runs", 0, "head_repository", "full_name"), "other/repo"),
        (("jobs", 0, "name"), "quality-and-tests"),
        (("jobs", 0, "head_sha"), "b" * 40),
        (("jobs", 0, "status"), "in_progress"),
        (("jobs", 0, "conclusion"), "failure"),
        (("jobs", 0, "steps", 1, "conclusion"), "skipped"),
        (("jobs", 0, "steps", 2, "name"), "Similar but not scan"),
    ],
)
def test_main_scan_provenance_fail_closed(path: tuple[str | int, ...], value: Any) -> None:
    runs, jobs = _evidence()
    target: Any = runs if path[0] in runs else jobs
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        _module().verify_attestation(runs, jobs, SHA, "controller")


def test_missing_duplicate_or_cross_suite_scan_fail_closed() -> None:
    runs, jobs = _evidence()
    for name, mutated in (
        ("duplicate workflow", (deepcopy(runs), deepcopy(jobs))),
        ("duplicate image job", (deepcopy(runs), deepcopy(jobs))),
        ("cross run", (deepcopy(runs), deepcopy(jobs))),
        ("missing scan", (deepcopy(runs), deepcopy(jobs))),
    ):
        r, j = mutated
        if name == "duplicate workflow":
            r["workflow_runs"].append(deepcopy(r["workflow_runs"][0]))
        elif name == "duplicate image job":
            j["jobs"].append(deepcopy(j["jobs"][0]))
        elif name == "cross run":
            j["jobs"][0]["run_id"] = 1235
        else:
            j["jobs"][0]["steps"].pop(1)
        with pytest.raises(ValueError):
            _module().verify_attestation(r, j, SHA, "controller")


def test_image_security_main_does_not_build_again_but_manual_stays_independent() -> None:
    text = SECURITY.read_text(encoding="utf-8")
    assert "python scripts/verify_main_ci_image_scan.py controller" in text
    assert "python scripts/verify_main_ci_image_scan.py browser" in text
    assert text.count("if: github.event_name == 'workflow_dispatch'") >= 4
    assert text.count("if: github.event_name == 'push'") == 2
    assert "name: image-security-scan" in text
    assert "bash scripts/trivy_scan_image.sh" in text
