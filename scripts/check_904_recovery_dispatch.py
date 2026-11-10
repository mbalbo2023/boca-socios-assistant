"""Runner-only evidence for one recovery of Boca incident #904. No host access."""

from __future__ import annotations

import os
import re
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from scripts import check_boca_deploy_dispatch as deploy
from scripts import host_cutover_postapply_reconcile as observer
from scripts.check_r96_stage_dispatch import load_paginated_history
from scripts.check_release_dispatch import RUN_ID, SOURCE_SHA, DispatchError
from scripts.check_v3_stage_github import validate
from scripts.check_worker_preflight_dispatch import validate_dispatch_history

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
R915, R916, R917 = "42750716605", "42750940352", "42751222045"
SHA916 = "3c7dd8ae08bc5372a01a25701b6c5524ec9b3386"
PLAN_TITLE = "BOCA-R138-916-IMAGE-PLAN"
FINISH_TITLE = "BOCA-V3-STAGE-RECOVER-" + R916
PLAN_VERIFIED = "Verify physical Boca incident receipt"
PLAN_ARTIFACT = "Publish verified Boca 916 image plan"
FINISH_OPERATION = "cutover-a-stage-recover"
OBSERVE_OPERATION = "cutover-a-reconcile"


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


def _job(
    record: Any,
    run_id: int,
    sha: str,
    required_steps: tuple[str, ...],
    *,
    failed_steps: tuple[str, ...] = (),
) -> None:
    _matches(
        record,
        {
            "run_id": run_id,
            "run_attempt": 1,
            "head_sha": sha,
            "name": JOB,
            "status": "completed",
            "conclusion": "failure" if failed_steps else "success",
        },
    )
    steps = record.get("steps")
    _require(type(steps) is list and all(type(step) is dict for step in steps))
    for name in (*required_steps, *failed_steps):
        found = [step for step in steps if step.get("name") == name]
        _require(len(found) == 1)
        _matches(
            found[0],
            {"status": "completed", "conclusion": "failure" if name in failed_steps else "success"},
        )


def select_inventory(
    history: Any, sha: str, current_number: str, *, title: str = INVENTORY, after: int = 908
) -> str:
    """Select the latest read-only run on this main, including any unsuccessful result."""
    _require(SOURCE_SHA.fullmatch(sha) is not None and RUN_ID.fullmatch(current_number) is not None)
    _require(type(history) is dict and history.get("total_count") == history.get("fetched_count"))
    runs = history.get("workflow_runs")
    _require(type(runs) is list and all(type(run) is dict for run in runs))
    candidates = [r for r in runs if r.get("display_title") == title and r.get("head_sha") == sha]
    _require(bool(candidates))
    numbers = [item.get("run_number") for item in candidates]
    _require(all(type(n) is int and after < n < int(current_number) for n in numbers))
    _require(len(numbers) == len(set(numbers)))
    latest = max(candidates, key=lambda row: row["run_number"])
    run_id = latest.get("id")
    _require(type(run_id) is int and run_id > 0)
    _matches(latest, {"run_attempt": 1, "status": "completed", "conclusion": "success"})
    return str(run_id)


def _dispatch_context(
    env: Mapping[str, str], proof: dict[str, Any], operation: str, context: str
) -> tuple[str, str, str]:
    for key, expected in {
        "GITHUB_REPOSITORY": deploy.REPO,
        "GITHUB_ACTOR": "mbalbo2023",
        "GITHUB_TRIGGERING_ACTOR": "mbalbo2023",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": f"{deploy.REPO}/{deploy.WORKFLOW}@refs/heads/main",
        "BOCA_OPERATION": operation,
        "BOCA_PROTECTED_ACTION_CONTEXT": context,
    }.items():
        _require(env.get(key) == expected)
    sha, run_id, number = env["GITHUB_SHA"], env["GITHUB_RUN_ID"], env["GITHUB_RUN_NUMBER"]
    _require(
        SOURCE_SHA.fullmatch(sha) is not None
        and RUN_ID.fullmatch(run_id) is not None
        and RUN_ID.fullmatch(number) is not None
        and proof["pulls"] == []
    )
    _require(proof["main"].get("object", {}).get("sha") == sha)
    inputs = proof["event"].get("inputs")
    _matches(
        inputs,
        {
            "operation": operation,
            "protected_action_context": context,
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

    return sha, run_id, number


def verify_recovery(
    env: Mapping[str, str], proof: dict[str, Any], incident: Any, history: Any
) -> None:
    """Only one authenticated recovery, preceded by a successful per-CID read on its SHA."""
    sha, run_id, number = _dispatch_context(env, proof, FINISH_OPERATION, R904)
    latest = int(select_inventory(history, sha, number))
    _require(sha not in (R904_SHA, R908_SHA) and len({str(latest), run_id, R904, str(R908)}) == 4)
    _require(validate(incident, history, proof["pulls"], sha, run_id, R904) == R904_SHA)
    _run(incident, int(R904), 904, R904_SHA, deploy.TITLE, "failure")
    _run(proof["historical"], R908, 908, R908_SHA, "Boca first deploy", "success")
    _matches(proof["historical_job"], {"id": JOB908})
    _job(proof["historical_job"], R908, R908_SHA, (AUTH_STEP, READ_STEP))
    _run(proof["run"], int(run_id), int(number), sha, TITLE, None)

    _successful_inventory(
        proof, history, latest, sha, INVENTORY, (AUTH_STEP, READ_STEP, PROFILE_STEP)
    )
    deploy.verify_completed_ci(sha, proof["ci"], proof["checks"])


def _successful_inventory(
    proof: dict[str, Any], history: Any, latest: int, sha: str, title: str, steps: tuple[str, ...]
) -> None:
    inventory = proof["inventory"]
    chosen = [r for r in history["workflow_runs"] if r.get("id") == latest]
    _require(len(chosen) == 1)
    _run(inventory, latest, chosen[0]["run_number"], sha, title, "success")
    jobs = proof["jobs"]
    _require(type(jobs) is dict and type(jobs.get("jobs")) is list)
    rows = jobs["jobs"]
    _matches(jobs, {"total_count": len(rows)})
    _require(all(type(job) is dict for job in rows))
    matches = [job for job in rows if job.get("name") == JOB]
    _require(len(matches) == 1 and type(matches[0].get("id")) is int and matches[0]["id"] > 0)
    _job(matches[0], latest, sha, steps)


def verify_916_dispatch(env: Mapping[str, str], proof: dict[str, Any], *, history: Any) -> None:
    """Authenticate the actual recovery/observations and, for finish, the new plan run."""
    operation = env.get("BOCA_OPERATION", "")
    _require(operation in (OBSERVE_OPERATION, FINISH_OPERATION))
    sha, run_id, number = _dispatch_context(env, proof, operation, R916)
    observe = operation == OBSERVE_OPERATION
    _require(int(number) > 917 and sha != SHA916 and run_id not in (R915, R916, R917))
    _run(proof["run"], int(run_id), int(number), sha, PLAN_TITLE if observe else FINISH_TITLE, None)
    for n, historical, job in (
        (915, R915, 129613417052),
        (916, R916, 129614147059),
        (917, R917, 129615059001),
    ):
        _run(
            proof[f"run{n}"],
            int(historical),
            n,
            SHA916,
            TITLE if n == 916 else INVENTORY,
            "failure" if n == 916 else "success",
        )
        attested = proof[f"job{n}"]
        _matches(attested, {"id": job})
        if n == 916:
            _job(
                attested,
                int(historical),
                SHA916,
                ("Authenticate both historical runs and the latest pinned inventory",),
                failed_steps=(
                    "Remove only authenticated uncommitted Cutover stage or recover Boca incident 904 under lease",
                    "Verify physical outcome and failed subphase of Boca recovery 904",
                ),
            )
        else:
            _job(attested, int(historical), SHA916, (AUTH_STEP, READ_STEP, PROFILE_STEP))
    deploy.verify_completed_ci(sha, proof["ci"], proof["checks"])
    if observe:
        return
    latest = int(select_inventory(history, sha, number, title=PLAN_TITLE, after=917))
    _require(latest != int(run_id))
    matches = [row for row in history["workflow_runs"] if row.get("display_title") == FINISH_TITLE]
    validate_dispatch_history(
        {"total_count": len(matches), "workflow_runs": matches},
        proof["pulls"],
        sha,
        run_id,
        marker=FINISH_TITLE,
        across_all_shas=True,
    )
    _successful_inventory(proof, history, latest, sha, PLAN_TITLE, (PLAN_VERIFIED, PLAN_ARTIFACT))


def _read_receipt(path: Path, limit: int) -> bytes:
    metadata = path.lstat()
    _require(stat.S_ISREG(metadata.st_mode) and 0 < metadata.st_size <= limit)
    with path.open("rb") as stream:
        return stream.read(limit + 1)


def _verified_plan(path: Path, run_id: str, source_sha: str) -> dict[str, Any]:
    from scripts import host_cutover_904_recovery as recovery

    _require(
        path.name == "boca-916-plan.json"
        and not path.parent.is_symlink()
        and list(path.parent.iterdir()) == [path]
    )
    plan = recovery.verify_916(
        _read_receipt(path, recovery.LIMIT_916),
        (R916, SHA916, R917, run_id, source_sha),
        observation=True,
    )
    digest = plan.get("plan_sha256")
    _require(
        plan.get("state") == "READY"
        and isinstance(digest, str)
        and re.fullmatch(r"[a-f0-9]{64}", digest) is not None
    )
    return plan


def _match_finish(
    plan_path: Path, finish_path: Path, run_id: str, source_sha: str, plan_run: str, plan_sha: str
) -> None:
    from scripts import host_cutover_904_recovery as recovery

    plan = _verified_plan(plan_path, plan_run, source_sha)
    _require(plan["plan_sha256"] == plan_sha)
    finish = recovery.verify_916(
        _read_receipt(finish_path, recovery.LIMIT_916),
        (R916, SHA916, R917, run_id, source_sha, plan_run, plan_sha),
        observation=False,
    )
    _require(finish["state"] == "COMPLETED")
    recovery.verify_916_finish_against_plan(finish, plan)


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
        if len(args) == 4 and args[0] in ("inventory-run", "plan-run-916"):
            history = load_paginated_history(Path(args[1]))
            print(
                select_inventory(history, args[2], args[3], title=PLAN_TITLE, after=917)
                if args[0] == "plan-run-916"
                else select_inventory(history, args[2], args[3])
            )
            return 0
        if len(args) == 4 and args[0] == "plan-digest-916":
            print(_verified_plan(Path(args[1]), args[2], args[3])["plan_sha256"])
            return 0
        if len(args) == 7 and args[0] == "match-finish-916":
            _match_finish(Path(args[1]), Path(args[2]), args[3], args[4], args[5], args[6])
            return 0
        if not args or args[0] not in ("authorize", "authorize-916"):
            return 2
        is_916 = args[0] == "authorize-916"
        if len(args) != (3 if is_916 else 4):
            return 2
        folder = Path(args[1])
        names = ["run", "ci", "checks", "pulls", "main"]
        if is_916:
            names.extend(f"{kind}{n}" for n in (915, 916, 917) for kind in ("run", "job"))
        else:
            names.extend(("historical", "historical_job"))
        if not is_916 or os.environ["BOCA_OPERATION"] == FINISH_OPERATION:
            names.extend(("inventory", "jobs"))
        proof = {
            name: deploy.load_evidence(folder / f"{name}.json", paginated=name in ("checks", "ci"))
            for name in names
        }
        proof["event"] = deploy.load_evidence(Path(os.environ["GITHUB_EVENT_PATH"]))
        if is_916:
            history = (
                None
                if os.environ["BOCA_OPERATION"] == OBSERVE_OPERATION
                else load_paginated_history(Path(args[2]))
            )
            verify_916_dispatch(os.environ, proof, history=history)
        else:
            verify_recovery(
                os.environ,
                proof,
                deploy.load_evidence(Path(args[2])),
                load_paginated_history(Path(args[3])),
            )
    except (ValueError, TypeError, KeyError, OSError, AttributeError):
        if args and args[0] == "match-finish-916":
            print(
                "BOCA_916_ACK state=NO_GO step=ACK_PLAN_MISMATCH effects=UNKNOWN", file=sys.stderr
            )
        elif args and args[0].endswith("-916"):
            print(
                "BOCA_916_GATE state=NO_GO step="
                + args[0].upper().replace("-", "_")
                + " host_writes=0",
                file=sys.stderr,
            )
        else:
            print("BOCA_904_RECOVERY_GATE state=NO_GO host_writes=0", file=sys.stderr)
        return 1
    print(
        ("BOCA_916_GATE" if is_916 else "BOCA_904_RECOVERY_GATE")
        + " state=PASS host_preflight=REQUIRED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
