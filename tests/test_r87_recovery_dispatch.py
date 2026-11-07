"""Synthetic GitHub REST provenance for one #819 stopped-only recovery.

Pure fixture tests; no GitHub API, SSH or Docker calls. The historical job
numbers and executed step names are taken from genuine #819 and #821 REST.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import check_worker_recovery_dispatch as gate  # noqa: E402

FAILED_ID = 42353468231
FAILED_SHA = "0538b3fb29cc0245a8387b7023c394883d0ea9a8"
FAILED_JOB = 128346380462
WITNESS_ID = 42355552701
WITNESS_SHA = "2859b9d31621e3cbec70b1aec649cc281ba130f5"
WITNESS_JOB = 128352753886
RELEASE_ID = 42352641660
CURRENT_ID = 99999999999
CURRENT_SHA = "b" * 40
TITLE = "BOCA-R87-WORKER-819-RECOVER-ONCE"
FAILED_TITLE = "BOCA-R84-WORKER-PREFLIGHT-ONCE"
WITNESS_TITLE = "BOCA-R86-WORKER-819-READONLY"
STEPNUMBERS = [*range(1, 155), 308, 309]
COMMON = {
    1: "Set up job",
    5: "Require verified protected environment and matching main commit",
    6: "Reject legacy install routes without same-lease Boca-only postflight",
    7: "Checkout exact main commit without persisted credentials",
    8: "Confirm current main HEAD before host access",
    19: "Hash reviewed Boca Compose file",
    36: "Configure pinned SSH host key and dedicated identity",
    308: "Post Checkout exact main commit without persisted credentials",
    309: "Complete job",
}
FAILED_MORE = {
    10: "Validate immutable inputs and successful matching release",
    11: "Require same-run immutable browser companion release manifest",
    18: "Authenticate separate historical controller release and original Compose file",
    20: "Hash reviewed served BETA Compose file",
    21: "Hash reviewed optional browser IPC overlay and seccomp",
    24: "Validate exact optional dual-service IPC Compose model before SSH",
    58: "Require one unique R84 worker preflight dispatch before SSH",
}
FAILED_ERRORS = {
    59: "Preflight exact dual GHCR image and rootless worker boundary without PREPARE",
    60: "Require exact Boca rootless worker preflight receipt and bounded cleanup",
}
WITNESS_ONLY = {42: "Inspect one failed Boca worker probe READ_ONLY by exact identity"}


def _run(
    number: int, sha: str, conclusion: str, *, title: str = "Boca first deploy"
) -> dict[str, Any]:
    return {
        "id": number,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": conclusion,
        "run_attempt": 1,
        "head_branch": "main",
        "head_sha": sha,
        "path": ".github/workflows/boca-first-deploy.yml",
        "display_title": title,
        "actor": {"login": "mbalbo2023"},
        "repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
    }


def _jobs(*, witness: bool) -> dict[str, Any]:
    run_id = WITNESS_ID if witness else FAILED_ID
    job_id = WITNESS_JOB if witness else FAILED_JOB
    executed = dict(COMMON)
    executed.update(WITNESS_ONLY if witness else FAILED_MORE)
    steps = []
    for number in STEPNUMBERS:
        if not witness and number in FAILED_ERRORS:
            name, conclusion = FAILED_ERRORS[number], "failure"
        else:
            name = executed.get(number, f"Skipped phase {number}")
            conclusion = "success" if number in executed else "skipped"
        steps.append(
            {"number": number, "name": name, "status": "completed", "conclusion": conclusion}
        )
    return {
        "total_count": 3,
        "jobs": [
            {
                "id": job_id,
                "name": "approved-boca-manual-operation",
                "run_id": run_id,
                "status": "completed",
                "conclusion": "success" if witness else "failure",
                "steps": steps,
            },
            {
                "id": job_id + 1,
                "name": "first-deploy-pr-validation",
                "run_id": run_id,
                "status": "completed",
                "conclusion": "skipped",
            },
            {
                "id": job_id + 2,
                "name": "first-deploy-runtime-smoke",
                "run_id": run_id,
                "status": "completed",
                "conclusion": "skipped",
            },
        ],
    }


def evidence() -> dict[str, Any]:
    current = {
        **_run(CURRENT_ID, CURRENT_SHA, "success", title=TITLE),
        "status": "in_progress",
        "conclusion": None,
    }
    return {
        "prs": [],
        "failed": _run(FAILED_ID, FAILED_SHA, "failure", title=FAILED_TITLE),
        "witness": _run(WITNESS_ID, WITNESS_SHA, "success", title=WITNESS_TITLE),
        "release": {
            **_run(RELEASE_ID, FAILED_SHA, "success"),
            "path": ".github/workflows/release-image.yml",
        },
        "history": {
            "total_count": 3,
            "workflow_runs": [
                current,
                {**_run(WITNESS_ID, WITNESS_SHA, "success", title=WITNESS_TITLE)},
                {**_run(FAILED_ID, FAILED_SHA, "failure", title=FAILED_TITLE)},
            ],
        },
        "failed_jobs": _jobs(witness=False),
        "witness_jobs": _jobs(witness=True),
    }


def _paths(tmp_path: Path, data: dict[str, Any]) -> list[str]:
    paths = []
    for key in ("prs", "failed", "witness", "release", "history", "failed_jobs", "witness_jobs"):
        path = tmp_path / f"{key}.json"
        path.write_text(json.dumps(data[key]), encoding="utf-8")
        paths.append(str(path))
    return paths


def test_r87_genuine_exact_failed_witness_and_single_dispatch_accepted(tmp_path: Path) -> None:
    gate.verify_r87(_paths(tmp_path, evidence()), run_id=CURRENT_ID, source=CURRENT_SHA)


@pytest.mark.parametrize(
    ("path", "field", "value"),
    [
        ("failed", "id", FAILED_ID + 1),
        ("failed", "head_sha", "a" * 40),
        ("failed", "conclusion", "success"),
        ("failed", "display_title", "other preflight"),
        ("failed", "run_attempt", 2),
        ("witness", "id", WITNESS_ID + 1),
        ("witness", "head_sha", "a" * 40),
        ("witness", "conclusion", "failure"),
        ("witness", "display_title", "fake read only"),
        ("witness", "head_branch", "foreign"),
        ("release", "id", RELEASE_ID + 1),
        ("release", "head_sha", "a" * 40),
        ("release", "path", ".github/workflows/other.yml"),
    ],
)
def test_r87_wrong_run_provenance_denied(tmp_path: Path, path: str, field: str, value: Any) -> None:
    data = evidence()
    data[path][field] = value
    with pytest.raises(ValueError):
        gate.verify_r87(_paths(tmp_path, data), run_id=CURRENT_ID, source=CURRENT_SHA)


@pytest.mark.parametrize(
    ("which", "number", "change"),
    [
        ("failed_jobs", 59, "success"),
        ("failed_jobs", 58, "skipped"),
        ("failed_jobs", 42, "success"),
        ("witness_jobs", 42, "skipped"),
        ("witness_jobs", 43, "success"),
        ("witness_jobs", 309, "failure"),
    ],
)
def test_r87_unreviewed_execution_step_denied(
    tmp_path: Path, which: str, number: int, change: str
) -> None:
    data = evidence()
    steps = data[which]["jobs"][0]["steps"]
    next(step for step in steps if step["number"] == number)["conclusion"] = change
    with pytest.raises(ValueError):
        gate.verify_r87(_paths(tmp_path, data), run_id=CURRENT_ID, source=CURRENT_SHA)


def test_r87_duplicate_recovers_or_truncated_history_fail_closed(tmp_path: Path) -> None:
    data = evidence()
    data["history"]["workflow_runs"].append(copy.deepcopy(data["history"]["workflow_runs"][0]))
    data["history"]["total_count"] += 1
    with pytest.raises(ValueError):
        gate.verify_r87(_paths(tmp_path, data), run_id=CURRENT_ID, source=CURRENT_SHA)

    data = evidence()
    data["history"]["total_count"] = 101
    with pytest.raises(ValueError):
        gate.verify_r87(_paths(tmp_path, data), run_id=CURRENT_ID, source=CURRENT_SHA)


def test_r87_any_open_pr_and_wrong_main_fail_closed(tmp_path: Path) -> None:
    data = evidence()
    data["prs"] = [{"number": 428, "draft": True}]
    with pytest.raises(ValueError):
        gate.verify_r87(_paths(tmp_path, data), run_id=CURRENT_ID, source=CURRENT_SHA)
    data = evidence()
    with pytest.raises(ValueError):
        gate.verify_r87(_paths(tmp_path, data), run_id=CURRENT_ID, source="a" * 40)


def test_r87_manual_job_requires_three_real_conclusions_and_exact_numbers(tmp_path: Path) -> None:
    data = evidence()
    data["failed_jobs"]["jobs"][0]["steps"][2]["number"] = 999
    with pytest.raises(ValueError):
        gate.verify_r87(_paths(tmp_path, data), run_id=CURRENT_ID, source=CURRENT_SHA)
    data = evidence()
    data["witness_jobs"]["jobs"][1]["conclusion"] = "success"
    with pytest.raises(ValueError):
        gate.verify_r87(_paths(tmp_path, data), run_id=CURRENT_ID, source=CURRENT_SHA)
