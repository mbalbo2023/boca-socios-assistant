"""Synthetic provenance for unique R94 protected recovery; no remote calls."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import check_worker_recovery_dispatch as gate  # noqa: E402

from test_r87_recovery_dispatch import COMMON, FAILED_MORE, _paths  # noqa: E402
from test_r91_worker_827_dispatch import evidence as old_evidence  # noqa: E402

FAILED_ID = 42375050546
FAILED_SHA = "79da7ebe9918d98216ac7eb46ff008d7f6e62429"
FAILED_JOB = 128410810023
WITNESS_ID = 42376876875
WITNESS_SHA = "6e75c020001c7de00faad2fcecfa171ac22e361f"
WITNESS_JOB = 128416172147
RELEASE_ID = 42374319918
CURRENT_ID = 99999999999
CURRENT_SHA = "b" * 40
TITLE = "BOCA-R94-WORKER-834-RECOVER-ONCE"
FAILED_TITLE = "BOCA-R84-WORKER-PREFLIGHT-ONCE"
WITNESS_TITLE = "BOCA-R93-WORKER-834-READONLY"
NUMBERS = [*range(1, 157), 312, 313]

# Exact projected GitHub REST job step numbers/accepted non-skipped names.
_COMMON = {number: name for number, name in COMMON.items() if number not in (308, 309)}
_COMMON.update(
    {
        312: "Post Checkout exact main commit without persisted credentials",
        313: "Complete job",
    }
)
_FAILED = {
    **_COMMON,
    **{number: name for number, name in FAILED_MORE.items() if number != 58},
    60: "Require one unique R84 worker preflight dispatch before SSH",
    61: "Preflight exact dual GHCR image and rootless worker boundary without PREPARE",
    62: "Require exact Boca rootless worker preflight receipt and bounded cleanup",
}
_WITNESS = {
    **_COMMON,
    44: "Inspect one failed Boca worker probe READ_ONLY by exact identity",
}


def evidence() -> dict[str, Any]:
    """R91's full REST shape re-pinned to authentic #834/#836 job projections."""
    data = old_evidence()
    prior_827 = copy.deepcopy(data["history"]["workflow_runs"][2])
    data["failed"].update(id=FAILED_ID, head_sha=FAILED_SHA, display_title=FAILED_TITLE)
    data["witness"].update(id=WITNESS_ID, head_sha=WITNESS_SHA, display_title=WITNESS_TITLE)
    data["release"].update(id=RELEASE_ID, head_sha=FAILED_SHA)
    data["history"]["workflow_runs"][0].update(
        id=CURRENT_ID, head_sha=CURRENT_SHA, display_title=TITLE
    )
    data["history"]["workflow_runs"][1] = copy.deepcopy(data["witness"])
    data["history"]["workflow_runs"][2] = copy.deepcopy(data["failed"])
    data["history"]["workflow_runs"].append(prior_827)
    data["history"]["total_count"] = len(data["history"]["workflow_runs"])
    for which, job_id, run_id, names in (
        ("failed_jobs", FAILED_JOB, FAILED_ID, _FAILED),
        ("witness_jobs", WITNESS_JOB, WITNESS_ID, _WITNESS),
    ):
        jobs = data[which]["jobs"]
        for offset, job in enumerate(jobs):
            job["id"] = job_id + offset
            job["run_id"] = run_id
        steps = []
        for number in NUMBERS:
            conclusion = (
                "failure"
                if which == "failed_jobs" and number in (61, 62)
                else "success"
                if number in names
                else "skipped"
            )
            steps.append(
                {
                    "number": number,
                    "name": names.get(number, f"Skipped phase {number}"),
                    "status": "completed",
                    "conclusion": conclusion,
                }
            )
        jobs[0]["steps"] = steps
    return data


def test_r94_requires_dedicated_834_836_provenance_gate() -> None:
    assert callable(getattr(gate, "verify_r94", None))


def test_r94_exact_failed_witness_and_release_are_accepted_once(tmp_path: Path) -> None:
    gate.verify_r94(_paths(tmp_path, evidence()), run_id=CURRENT_ID, source=CURRENT_SHA)


@pytest.mark.parametrize(
    ("part", "field", "value"),
    [
        ("failed", "id", FAILED_ID + 1),
        ("failed", "head_sha", "f" * 40),
        ("failed", "conclusion", "success"),
        ("failed", "run_attempt", 2),
        ("failed", "display_title", "forged"),
        ("witness", "id", WITNESS_ID + 1),
        ("witness", "head_sha", "f" * 40),
        ("witness", "conclusion", "failure"),
        ("witness", "display_title", "forged"),
        ("witness", "event", "push"),
        ("release", "id", RELEASE_ID + 1),
        ("release", "head_sha", "f" * 40),
        ("release", "path", ".github/workflows/foreign.yml"),
    ],
)
def test_r94_wrong_historical_provenance_never_admits_host(
    tmp_path: Path, part: str, field: str, value: Any
) -> None:
    data = evidence()
    data[part][field] = value
    with pytest.raises(ValueError):
        gate.verify_r94(_paths(tmp_path, data), run_id=CURRENT_ID, source=CURRENT_SHA)


@pytest.mark.parametrize(
    ("which", "step", "conclusion"),
    [
        ("failed_jobs", 60, "skipped"),
        ("failed_jobs", 61, "success"),
        ("failed_jobs", 62, "success"),
        ("failed_jobs", 44, "success"),
        ("witness_jobs", 44, "skipped"),
        ("witness_jobs", 61, "failure"),
        ("witness_jobs", 312, "skipped"),
        ("witness_jobs", 313, "failure"),
    ],
)
def test_r94_wrong_executed_or_skipped_historical_step_fails(
    tmp_path: Path, which: str, step: int, conclusion: str
) -> None:
    data = evidence()
    current = next(s for s in data[which]["jobs"][0]["steps"] if s["number"] == step)
    current["conclusion"] = conclusion
    with pytest.raises(ValueError):
        gate.verify_r94(_paths(tmp_path, data), run_id=CURRENT_ID, source=CURRENT_SHA)


@pytest.mark.parametrize(
    "attack",
    [
        "open_pr",
        "duplicate_r94",
        "truncated_history",
        "wrong_main",
        "missing_witness_history",
        "wrong_failed_history",
        "failed_missing_job",
        "witness_extra_job",
        "missing_step",
        "duplicate_step",
        "unverified_witness_job",
        "mutated_witness_step_name",
    ],
)
def test_r94_anti_replay_and_job_completeness_fail_closed(tmp_path: Path, attack: str) -> None:
    data = evidence()
    source = CURRENT_SHA
    if attack == "open_pr":
        data["prs"] = [{"number": 440, "draft": True}]
    elif attack == "duplicate_r94":
        repeat = copy.deepcopy(data["history"]["workflow_runs"][0])
        repeat.update(id=1234, head_sha="f" * 40)
        data["history"]["workflow_runs"].append(repeat)
        data["history"]["total_count"] += 1
    elif attack == "truncated_history":
        data["history"]["total_count"] = 101
    elif attack == "wrong_main":
        source = "a" * 40
    elif attack == "missing_witness_history":
        data["history"]["workflow_runs"][1]["id"] = 0
    elif attack == "wrong_failed_history":
        data["history"]["workflow_runs"][2]["run_attempt"] = 2
    elif attack == "failed_missing_job":
        data["failed_jobs"]["total_count"] = 2
    elif attack == "witness_extra_job":
        data["witness_jobs"]["jobs"][1]["conclusion"] = "success"
    elif attack == "missing_step":
        data["failed_jobs"]["jobs"][0]["steps"].pop(0)
    elif attack == "duplicate_step":
        data["witness_jobs"]["jobs"][0]["steps"][2]["number"] = 2
    elif attack == "unverified_witness_job":
        data["witness_jobs"]["jobs"][0]["conclusion"] = "skipped"
    else:
        next(s for s in data["witness_jobs"]["jobs"][0]["steps"] if s["number"] == 44)["name"] = (
            "Read unpinned host"
        )
    with pytest.raises(ValueError):
        gate.verify_r94(_paths(tmp_path, data), run_id=CURRENT_ID, source=source)


def test_r94_duplicate_json_keys_in_rest_input_are_rejected(tmp_path: Path) -> None:
    paths = _paths(tmp_path, evidence())
    Path(paths[1]).write_text('{"id":42375050546,"id":42375050546}', encoding="ascii")
    with pytest.raises(ValueError):
        gate.verify_r94(paths, run_id=CURRENT_ID, source=CURRENT_SHA)
