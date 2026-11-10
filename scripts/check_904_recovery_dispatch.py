"""Runner-only evidence for one recovery of Boca incident #904. No host access."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from scripts import check_boca_deploy_dispatch as deploy
from scripts import host_cutover_postapply_reconcile as observer
from scripts.check_r96_stage_dispatch import load_paginated_history
from scripts.check_release_dispatch import RUN_ID, SOURCE_SHA, DispatchError
from scripts.check_v3_stage_github import validate

R904, R904_SHA = observer.R904, observer.R904_SHA
R908 = 42745950217
R908_SHA = "518bd31d0585deb8900d43cb4957d94b873e4bed"
JOB908 = 129597962453
INVENTORY = "BOCA-R137-904-RECOVERY-INVENTORY"
JOB = "approved-boca-manual-operation"
AUTH_STEP = "Authenticate exact failed V3 incidents from GitHub READ_ONLY"
READ_STEP = "Reconcile exact failed Cutover A attempt on Boca host READ_ONLY"
PROFILE_STEP = "Confirm pinned inventory for Boca recovery 904"
TITLE = "BOCA-V3-STAGE-RECOVER-" + R904


def _require(value: bool) -> None:
    if not value:
        raise DispatchError("Boca 904 recovery evidence unverified")


def _matches(record: Any, fields: dict[str, Any]) -> None:
    _require(type(record) is dict)
    for field, value in fields.items():
        _require(field in record and type(record[field]) is type(value) and record[field] == value)


def _run(
    record: Any, run_id: int, number: int, sha: str, title: str, conclusion: str | None
) -> None:
    _matches(
        record,
        {
            "id": run_id,
            "run_number": number,
            "run_attempt": 1,
            "event": "workflow_dispatch",
            "path": deploy.WORKFLOW,
            "head_branch": "main",
            "head_sha": sha,
            "display_title": title,
            "status": "completed" if conclusion else "in_progress",
            "conclusion": conclusion,
        },
    )
    for key in ("actor", "triggering_actor"):
        _matches(record.get(key), {"login": "mbalbo2023"})
    for key in ("repository", "head_repository"):
        _matches(record.get(key), {"full_name": deploy.REPO})


def _job(record: Any, run_id: int, sha: str, required_steps: tuple[str, ...]) -> None:
    _matches(
        record,
        {
            "run_id": run_id,
            "run_attempt": 1,
            "head_sha": sha,
            "name": JOB,
            "status": "completed",
            "conclusion": "success",
        },
    )
    steps = record.get("steps")
    _require(type(steps) is list and all(type(step) is dict for step in steps))
    for name in required_steps:
        found = [step for step in steps if step.get("name") == name]
        _require(len(found) == 1)
        _matches(found[0], {"status": "completed", "conclusion": "success"})


def select_inventory(history: Any, sha: str, current_number: str) -> str:
    """Select the latest read-only run on this main, including any unsuccessful result."""
    _require(SOURCE_SHA.fullmatch(sha) is not None and RUN_ID.fullmatch(current_number) is not None)
    _require(type(history) is dict and history.get("total_count") == history.get("fetched_count"))
    runs = history.get("workflow_runs")
    _require(type(runs) is list and all(type(run) is dict for run in runs))
    candidates = [
        r for r in runs if r.get("display_title") == INVENTORY and r.get("head_sha") == sha
    ]
    _require(bool(candidates))
    numbers = [item.get("run_number") for item in candidates]
    _require(all(type(n) is int and 908 < n < int(current_number) for n in numbers))
    _require(len(numbers) == len(set(numbers)))
    latest = max(candidates, key=lambda row: row["run_number"])
    run_id = latest.get("id")
    _require(type(run_id) is int and run_id > 0)
    _matches(latest, {"run_attempt": 1, "status": "completed", "conclusion": "success"})
    return str(run_id)


def verify_recovery(
    env: Mapping[str, str], proof: dict[str, Any], incident: Any, history: Any
) -> None:
    """Only one authenticated recovery, preceded by a successful per-CID read on its SHA."""
    for key, expected in {
        "GITHUB_REPOSITORY": deploy.REPO,
        "GITHUB_ACTOR": "mbalbo2023",
        "GITHUB_TRIGGERING_ACTOR": "mbalbo2023",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": f"{deploy.REPO}/{deploy.WORKFLOW}@refs/heads/main",
        "BOCA_OPERATION": "cutover-a-stage-recover",
        "BOCA_PROTECTED_ACTION_CONTEXT": R904,
    }.items():
        _require(env.get(key) == expected)
    sha, run_id, number = env["GITHUB_SHA"], env["GITHUB_RUN_ID"], env["GITHUB_RUN_NUMBER"]
    latest = int(select_inventory(history, sha, number))
    _require(sha not in (R904_SHA, R908_SHA) and len({str(latest), run_id, R904, str(R908)}) == 4)
    _require(validate(incident, history, proof["pulls"], sha, run_id, R904) == R904_SHA)
    _require(proof["main"].get("object", {}).get("sha") == sha)
    inputs = proof["event"].get("inputs")
    _matches(
        inputs,
        {
            "operation": "cutover-a-stage-recover",
            "protected_action_context": R904,
            "service": "controller",
        },
    )
    _require(inputs.get("resource_budget") in ("0.5cpu-256m-64pids", "1.5cpu-1024m-192pids"))
    _require(
        all(
            value == ""
            for key, value in inputs.items()
            if key not in {"operation", "protected_action_context", "service", "resource_budget"}
        )
    )

    _run(incident, int(R904), 904, R904_SHA, deploy.TITLE, "failure")
    _run(proof["historical"], R908, 908, R908_SHA, "Boca first deploy", "success")
    _matches(proof["historical_job"], {"id": JOB908})
    _job(proof["historical_job"], R908, R908_SHA, (AUTH_STEP, READ_STEP))
    _run(proof["run"], int(run_id), int(number), sha, TITLE, None)

    inventory = proof["inventory"]
    chosen = [r for r in history["workflow_runs"] if r.get("id") == latest]
    _require(len(chosen) == 1)
    _run(inventory, latest, chosen[0]["run_number"], sha, INVENTORY, "success")
    jobs = proof["jobs"]
    _require(type(jobs) is dict and type(jobs.get("jobs")) is list)
    rows = jobs["jobs"]
    _matches(jobs, {"total_count": len(rows)})
    _require(all(type(job) is dict for job in rows))
    matches = [job for job in rows if job.get("name") == JOB]
    _require(len(matches) == 1 and type(matches[0].get("id")) is int and matches[0]["id"] > 0)
    _job(matches[0], latest, sha, (AUTH_STEP, READ_STEP, PROFILE_STEP))
    deploy.verify_completed_ci(sha, proof["ci"], proof["checks"])


def verify_profile(raw: bytes) -> int:
    try:
        readback = observer.verify_runner(raw, R904, None, source_sha=R904_SHA)
        profile = observer.recovery_profile904(readback)
        _require(profile in observer.RECOVERY_904_PROFILES)
    except (ValueError, TypeError, KeyError, OSError):
        print("BOCA_904_INVENTORY recovery_profile=UNVERIFIED observer_writes=0")
        return 1
    print(f"BOCA_904_INVENTORY recovery_profile={profile} observer_writes=0")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if args == ["profile"]:
            return verify_profile(sys.stdin.buffer.read(observer.R904_LIMIT + 1))
        if len(args) == 4 and args[0] == "inventory-run":
            print(select_inventory(load_paginated_history(Path(args[1])), args[2], args[3]))
            return 0
        if len(args) != 4 or args[0] != "authorize":
            return 2
        folder, incident, history = map(Path, args[1:])
        proof = {
            name: deploy.load_evidence(folder / f"{name}.json", paginated=name in ("checks", "ci"))
            for name in (
                "run",
                "historical",
                "historical_job",
                "inventory",
                "jobs",
                "ci",
                "checks",
                "pulls",
                "main",
            )
        }
        proof["event"] = deploy.load_evidence(Path(os.environ["GITHUB_EVENT_PATH"]))
        verify_recovery(
            os.environ, proof, deploy.load_evidence(incident), load_paginated_history(history)
        )
    except (ValueError, TypeError, KeyError, OSError, AttributeError):
        print("BOCA_904_RECOVERY_GATE state=NO_GO host_writes=0", file=sys.stderr)
        return 1
    print("BOCA_904_RECOVERY_GATE state=PASS host_preflight=REQUIRED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
