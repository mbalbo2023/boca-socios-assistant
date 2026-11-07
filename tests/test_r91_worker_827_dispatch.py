"""Synthetic exact GitHub REST provenance for one #827 recovery (no network)."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from scripts import check_worker_recovery_dispatch as gate  # noqa: E402

from test_r87_recovery_dispatch import _paths  # noqa: E402
from test_r87_recovery_dispatch import evidence as old_evidence  # noqa: E402

FAILED_ID = 42368541950
FAILED_SHA = "8a69d155354362e0712dab1229f7d7e4b3e24dd6"
FAILED_JOB = 128391674779
WITNESS_ID = 42370005970
WITNESS_SHA = "bd45f2e234a17ba12743ff12cf0c0199497b66f6"
WITNESS_JOB = 128395981058
RELEASE_ID = 42361009081
TITLE = "BOCA-R91-WORKER-827-RECOVER-ONCE"
FAILED_TITLE = "BOCA-R84-WORKER-PREFLIGHT-ONCE"
WITNESS_TITLE = "BOCA-R90-WORKER-827-READONLY"
CURRENT_ID = 99999999999
CURRENT_SHA = "b" * 40
NUMBERS = [*range(1, 156), 310, 311]


def evidence() -> dict[str, Any]:
    data = old_evidence()
    data["failed"].update(id=FAILED_ID, head_sha=FAILED_SHA, display_title=FAILED_TITLE)
    data["witness"].update(id=WITNESS_ID, head_sha=WITNESS_SHA, display_title=WITNESS_TITLE)
    data["release"].update(id=RELEASE_ID, head_sha=FAILED_SHA)
    data["history"]["workflow_runs"] = [
        {
            **data["history"]["workflow_runs"][0],
            "id": CURRENT_ID,
            "head_sha": CURRENT_SHA,
            "display_title": TITLE,
        },
        copy.deepcopy(data["witness"]),
        copy.deepcopy(data["failed"]),
        # R84 was also used in #819. A historic same-title run is legitimate,
        # but only the exact failed #827 ID matches this contract.
        {**copy.deepcopy(data["failed"]), "id": 42353468231, "head_sha": "a" * 40},
    ]
    data["history"]["total_count"] = 4
    for key, run_id, job_id, replaced in (
        (
            "failed_jobs",
            FAILED_ID,
            FAILED_JOB,
            {
                59: "Require one unique R84 worker preflight dispatch before SSH",
                60: "Preflight exact dual GHCR image and rootless worker boundary without PREPARE",
                61: "Require exact Boca rootless worker preflight receipt and bounded cleanup",
            },
        ),
        (
            "witness_jobs",
            WITNESS_ID,
            WITNESS_JOB,
            {43: "Inspect one failed Boca worker probe READ_ONLY by exact identity"},
        ),
    ):
        jobs = data[key]["jobs"]
        jobs[0]["id"] = job_id
        jobs[0]["run_id"] = run_id
        for offset, item in enumerate(jobs[1:], 1):
            item["id"] = job_id + offset
            item["run_id"] = run_id
        saved = {step["number"]: step for step in jobs[0]["steps"]}
        saved[310] = {**saved.pop(308), "number": 310}
        saved[311] = {**saved.pop(309), "number": 311}
        saved[155] = {
            "number": 155,
            "name": "Inspect only Boca health and dormant motor",
            "status": "completed",
            "conclusion": "skipped",
        }
        for step in saved.values():
            if step["number"] in (58, 59, 60, 61, 42, 43):
                step["conclusion"] = "skipped"
                step["name"] = f"Skipped phase {step['number']}"
        for number, name in replaced.items():
            saved[number]["name"] = name
            saved[number]["conclusion"] = (
                "failure" if key == "failed_jobs" and number in (60, 61) else "success"
            )
        jobs[0]["steps"] = [saved[number] for number in NUMBERS]
    return data


def test_r91_exact_827_failed_829_witness_737_release_unique_dispatch(tmp_path: Path) -> None:
    gate.verify_r91(_paths(tmp_path, evidence()), run_id=CURRENT_ID, source=CURRENT_SHA)


@pytest.mark.parametrize(
    ("part", "field", "value"),
    [
        ("failed", "id", FAILED_ID + 1),
        ("failed", "head_sha", "f" * 40),
        ("failed", "conclusion", "success"),
        ("failed", "run_attempt", 2),
        ("witness", "id", WITNESS_ID + 1),
        ("witness", "head_sha", "f" * 40),
        ("witness", "conclusion", "failure"),
        ("witness", "display_title", "wrong witness"),
        ("release", "id", RELEASE_ID + 1),
    ],
)
def test_r91_any_wrong_run_provenance_rejected(
    tmp_path: Path, part: str, field: str, value: Any
) -> None:
    data = evidence()
    data[part][field] = value
    with pytest.raises(ValueError):
        gate.verify_r91(_paths(tmp_path, data), run_id=CURRENT_ID, source=CURRENT_SHA)


@pytest.mark.parametrize(
    ("which", "step", "conclusion"),
    [
        ("failed_jobs", 59, "skipped"),
        ("failed_jobs", 60, "success"),
        ("failed_jobs", 61, "success"),
        ("failed_jobs", 43, "success"),
        ("witness_jobs", 43, "skipped"),
        ("witness_jobs", 60, "success"),
        ("witness_jobs", 310, "skipped"),
    ],
)
def test_r91_any_forged_executed_step_rejected(
    tmp_path: Path, which: str, step: int, conclusion: str
) -> None:
    data = evidence()
    next(s for s in data[which]["jobs"][0]["steps"] if s["number"] == step)["conclusion"] = (
        conclusion
    )
    with pytest.raises(ValueError):
        gate.verify_r91(_paths(tmp_path, data), run_id=CURRENT_ID, source=CURRENT_SHA)


@pytest.mark.parametrize(
    "attack",
    [
        "duplicate_dispatch",
        "truncated",
        "open_pr",
        "wrong_main",
        "wrong_827_history",
        "wrong_829_history",
        "missing_job",
    ],
)
def test_r91_history_and_main_fail_closed(tmp_path: Path, attack: str) -> None:
    data = evidence()
    source = CURRENT_SHA
    if attack == "duplicate_dispatch":
        data["history"]["workflow_runs"].append(copy.deepcopy(data["history"]["workflow_runs"][0]))
        data["history"]["total_count"] += 1
    elif attack == "truncated":
        data["history"]["total_count"] = 101
    elif attack == "open_pr":
        data["prs"] = [{"number": 432, "draft": True}]
    elif attack == "wrong_main":
        source = "a" * 40
    elif attack == "wrong_827_history":
        data["history"]["workflow_runs"][2]["id"] = 1234
    elif attack == "wrong_829_history":
        data["history"]["workflow_runs"][1]["status"] = "in_progress"
    else:
        data["failed_jobs"]["total_count"] = 2
    with pytest.raises(ValueError):
        gate.verify_r91(_paths(tmp_path, data), run_id=CURRENT_ID, source=source)
