"""R80: attest one proven pre-SSH R79 abort before a unique host recovery.

Consumes only bounded GitHub REST evidence collected by the protected runner.
This module has no network, Docker, SSH, or filesystem effects beyond reads.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

REPO = "mbalbo2023/boca-socios-assistant"
DEPLOY = ".github/workflows/boca-first-deploy.yml"
RELEASE = ".github/workflows/release-image.yml"
R79_TITLE = "BOCA-R79-WORKER-RECOVER-ONCE"
R80_TITLE = "BOCA-R80-WORKER-RECOVER-ONCE"
R81_TITLE = "BOCA-R81-WORKER-807-READONLY"
R82_TITLE = "BOCA-R82-WORKER-807-RECOVER-ONCE"
R82_FAILED_ID = 42341290485
R82_FAILED_SHA = "1199c46fee8053e637b220ad9365ce3af15eb8e5"
R82_FAILED_JOB = 128309316427
R82_WITNESS_ID = 42342822240
R82_WITNESS_SHA = "8146ab94c1fedf02fbe0ba14e225bbce61339044"
R82_WITNESS_JOB = 128314064855
R82_RELEASE_ID = 42340930071
R87_TITLE = "BOCA-R87-WORKER-819-RECOVER-ONCE"
R87_FAILED_TITLE = "BOCA-R84-WORKER-PREFLIGHT-ONCE"
R87_WITNESS_TITLE = "BOCA-R86-WORKER-819-READONLY"
R87_FAILED_ID = 42353468231
R87_FAILED_SHA = "0538b3fb29cc0245a8387b7023c394883d0ea9a8"
R87_FAILED_JOB = 128346380462
R87_WITNESS_ID = 42355552701
R87_WITNESS_SHA = "2859b9d31621e3cbec70b1aec649cc281ba130f5"
R87_WITNESS_JOB = 128352753886
R87_RELEASE_ID = 42352641660
R91_TITLE = "BOCA-R91-WORKER-827-RECOVER-ONCE"
R91_FAILED_TITLE = "BOCA-R84-WORKER-PREFLIGHT-ONCE"
R91_WITNESS_TITLE = "BOCA-R90-WORKER-827-READONLY"
R91_FAILED_ID = 42368541950
R91_FAILED_SHA = "8a69d155354362e0712dab1229f7d7e4b3e24dd6"
R91_FAILED_JOB = 128391674779
R91_WITNESS_ID = 42370005970
R91_WITNESS_SHA = "bd45f2e234a17ba12743ff12cf0c0199497b66f6"
R91_WITNESS_JOB = 128395981058
R91_RELEASE_ID = 42361009081
R80_RECOVERY_ID = 42340750343
PRIOR_ID = 42339451485
PRIOR_SHA = "d9100c6c4666c61ba66fbbefa48e61102a20ce5d"
PRIOR_JOB = 128303677116
FAILED_SHA = "92624ed6b7e75c6010f59670c866df00a29766dd"
WITNESS_SHA = "7dc0b477479aec118ed4e46edd1ffb4541558dbc"

# Exact #804 Actions steps observed independently on the pinned source SHA.
# Skipped steps after 152 are omitted from the GitHub jobs REST response.
PRIOR_STEP_NUMBERS = [*range(1, 153), 304, 305]
PRIOR_EXECUTED = {
    1: ("Set up job", "success"),
    5: ("Require verified protected environment and matching main commit", "success"),
    6: ("Reject legacy install routes without same-lease Boca-only postflight", "success"),
    7: ("Checkout exact main commit without persisted credentials", "success"),
    8: ("Confirm current main HEAD before host access", "success"),
    19: ("Hash reviewed Boca Compose file", "success"),
    36: ("Configure pinned SSH host key and dedicated identity", "success"),
    37: ("Require exact 795/802 evidence and zero open PRs before recovery SSH", "failure"),
    39: ("Require exact terminal worker recovery receipt on every outcome", "failure"),
    304: ("Post Checkout exact main commit without persisted credentials", "success"),
    305: ("Complete job", "success"),
}
PRIOR_SKIPPED_HOST = (
    38,
    "Recover only the stopped exact 795 worker probe under Boca lease",
)


def _read_json(path: str, *, maximum: int = 32768) -> Any:
    raw = Path(path).read_bytes()
    if not 0 < len(raw) <= maximum:
        raise ValueError("bounded REST receipt missing or oversized")

    def unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate REST field")
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=unique_fields)


def _expect(condition: bool) -> None:
    if not condition:
        raise ValueError("GitHub attestation mismatch")


def _run(
    record: Any,
    *,
    number: int,
    source: str,
    conclusion: str,
    workflow: str,
    title: str | None = None,
) -> None:
    _expect(isinstance(record, dict))
    actor = record.get("actor")
    repository = record.get("repository")
    _expect(
        type(record.get("id")) is int
        and record["id"] == number
        and record.get("event") == "workflow_dispatch"
        and record.get("status") == "completed"
        and record.get("conclusion") == conclusion
        and type(record.get("run_attempt")) is int
        and record["run_attempt"] == 1
        and record.get("head_branch") == "main"
        and record.get("head_sha") == source
        # Live GitHub REST returns a bare workflow path; accept only these
        # three exact forms, never other refs or arbitrary workflow names.
        and record.get("path") in {workflow, f"{workflow}@main", f"{workflow}@refs/heads/main"}
        and isinstance(actor, dict)
        and actor.get("login") == "mbalbo2023"
        and isinstance(repository, dict)
        and repository.get("full_name") == REPO
        and (title is None or record.get("display_title") == title)
    )


def _history_matches(history: Any, *, run_id: int, source: str) -> None:
    _expect(isinstance(history, dict))
    runs = history.get("workflow_runs")
    total = history.get("total_count")
    _expect(
        type(total) is int
        and 2 <= total <= 100
        and isinstance(runs, list)
        and len(runs) == total
        and all(isinstance(item, dict) for item in runs)
    )

    def unique(title: str, expected_id: int, expected_sha: str) -> None:
        matched = [record for record in runs if record.get("display_title") == title]
        _expect(len(matched) == 1)
        record = matched[0]
        actor = record.get("actor")
        _expect(
            type(record.get("id")) is int
            and record["id"] == expected_id
            and record.get("event") == "workflow_dispatch"
            and record.get("head_branch") == "main"
            and record.get("head_sha") == expected_sha
            and type(record.get("run_attempt")) is int
            and record["run_attempt"] == 1
            and isinstance(actor, dict)
            and actor.get("login") == "mbalbo2023"
        )

    unique(R79_TITLE, PRIOR_ID, PRIOR_SHA)
    unique(R80_TITLE, run_id, source)
    _expect(PRIOR_ID != run_id)


def _prior_jobs(receipt: Any) -> None:
    _expect(isinstance(receipt, dict))
    jobs = receipt.get("jobs")
    _expect(
        type(receipt.get("total_count")) is int
        and receipt["total_count"] == 3
        and isinstance(jobs, list)
        and len(jobs) == 3
        and all(isinstance(job, dict) for job in jobs)
    )
    manual = [job for job in jobs if job.get("id") == PRIOR_JOB]
    _expect(len(manual) == 1)
    manual_job = manual[0]
    _expect(
        manual_job.get("name") == "approved-boca-manual-operation"
        and manual_job.get("run_id") == PRIOR_ID
        and manual_job.get("status") == "completed"
        and manual_job.get("conclusion") == "failure"
    )
    rest = [job for job in jobs if job.get("id") != PRIOR_JOB]
    _expect(
        {job.get("name") for job in rest}
        == {"first-deploy-runtime-smoke", "first-deploy-pr-validation"}
        and all(
            job.get("run_id") == PRIOR_ID
            and job.get("status") == "completed"
            and job.get("conclusion") == "skipped"
            for job in rest
        )
    )
    steps = manual_job.get("steps")
    _expect(isinstance(steps, list) and len(steps) == len(PRIOR_STEP_NUMBERS))
    _expect(
        all(isinstance(step, dict) for step in steps)
        and [step.get("number") for step in steps] == PRIOR_STEP_NUMBERS
    )
    for step in steps:
        number = step["number"]
        _expect(step.get("status") == "completed" and isinstance(step.get("name"), str))
        if number in PRIOR_EXECUTED:
            _expect((step["name"], step.get("conclusion")) == PRIOR_EXECUTED[number])
        elif number == PRIOR_SKIPPED_HOST[0]:
            _expect(step["name"] == PRIOR_SKIPPED_HOST[1] and step.get("conclusion") == "skipped")
        else:
            # No unknown step, including a different SSH route, may have run.
            _expect(step.get("conclusion") == "skipped")


def verify(paths: list[str], *, run_id: int, source: str) -> None:
    _expect(len(paths) == 7 and run_id > 0 and len(source) == 40)
    prs, failed, witness, release, history, prior, jobs = [
        _read_json(path, maximum=131072 if index == 6 else 32768)
        for index, path in enumerate(paths)
    ]
    _expect(prs == [])
    _run(
        failed,
        number=42329475083,
        source=FAILED_SHA,
        conclusion="failure",
        workflow=DEPLOY,
    )
    _run(
        witness,
        number=42337103473,
        source=WITNESS_SHA,
        conclusion="success",
        workflow=DEPLOY,
    )
    _run(
        release,
        number=42329201039,
        source=FAILED_SHA,
        conclusion="success",
        workflow=RELEASE,
    )
    _run(
        prior,
        number=PRIOR_ID,
        source=PRIOR_SHA,
        conclusion="failure",
        workflow=DEPLOY,
        title=R79_TITLE,
    )
    _history_matches(history, run_id=run_id, source=source)
    _prior_jobs(jobs)


R82_FAILED_EXECUTED = {
    **{
        number: (name, "success")
        for number, name in {
            1: "Set up job",
            5: "Require verified protected environment and matching main commit",
            6: "Reject legacy install routes without same-lease Boca-only postflight",
            7: "Checkout exact main commit without persisted credentials",
            8: "Confirm current main HEAD before host access",
            10: "Validate immutable inputs and successful matching release",
            11: "Require same-run immutable browser companion release manifest",
            18: "Authenticate separate historical controller release and original Compose file",
            19: "Hash reviewed Boca Compose file",
            20: "Hash reviewed served BETA Compose file",
            21: "Hash reviewed optional browser IPC overlay and seccomp",
            24: "Validate exact optional dual-service IPC Compose model before SSH",
            36: "Configure pinned SSH host key and dedicated identity",
            304: "Post Checkout exact main commit without persisted credentials",
            305: "Complete job",
        }.items()
    },
    57: ("Preflight exact dual GHCR image and rootless worker boundary without PREPARE", "failure"),
    58: ("Require exact Boca rootless worker preflight receipt and bounded cleanup", "failure"),
}
R82_WITNESS_EXECUTED = {
    number: R82_FAILED_EXECUTED[number] for number in (1, 5, 6, 7, 8, 19, 36, 304, 305)
}
R82_WITNESS_EXECUTED[41] = (
    "Inspect one failed Boca worker probe READ_ONLY by exact identity",
    "success",
)


def _r82_history(history: Any, *, run_id: int, source: str) -> None:
    _expect(isinstance(history, dict))
    runs = history.get("workflow_runs")
    total = history.get("total_count")
    _expect(
        type(total) is int
        and 5 <= total <= 100
        and isinstance(runs, list)
        and len(runs) == total
        and all(isinstance(item, dict) for item in runs)
    )
    expected = (
        (R79_TITLE, PRIOR_ID, PRIOR_SHA, "completed", "failure"),
        (R80_TITLE, R80_RECOVERY_ID, R82_FAILED_SHA, "completed", "success"),
        (R81_TITLE, R82_WITNESS_ID, R82_WITNESS_SHA, "completed", "success"),
        (R82_TITLE, run_id, source, None, None),
    )
    for title, expected_id, expected_sha, expected_status, expected_conclusion in expected:
        matches = [item for item in runs if item.get("display_title") == title]
        _expect(len(matches) == 1)
        item = matches[0]
        actor = item.get("actor")
        _expect(
            type(item.get("id")) is int
            and item["id"] == expected_id
            and item.get("event") == "workflow_dispatch"
            and item.get("head_branch") == "main"
            and item.get("head_sha") == expected_sha
            and type(item.get("run_attempt")) is int
            and item["run_attempt"] == 1
            and isinstance(actor, dict)
            and actor.get("login") == "mbalbo2023"
        )
        if title == R82_TITLE:
            _expect(item.get("status") in {"in_progress", "queued", "waiting", "pending"})
            _expect(item.get("conclusion") is None)
        else:
            _expect(
                item.get("status") == expected_status
                and item.get("conclusion") == expected_conclusion
            )


def _r82_jobs(
    receipt: Any,
    *,
    run_id: int,
    job_id: int,
    conclusion: str,
    executed: dict[int, tuple[str, str]],
    step_numbers: list[int] | None = None,
) -> None:
    if step_numbers is None:
        step_numbers = PRIOR_STEP_NUMBERS
    _expect(isinstance(receipt, dict))
    jobs = receipt.get("jobs")
    _expect(
        type(receipt.get("total_count")) is int
        and receipt["total_count"] == 3
        and isinstance(jobs, list)
        and len(jobs) == 3
        and all(isinstance(job, dict) for job in jobs)
    )
    manual = [job for job in jobs if job.get("id") == job_id]
    _expect(len(manual) == 1)
    job = manual[0]
    _expect(
        job.get("name") == "approved-boca-manual-operation"
        and job.get("run_id") == run_id
        and job.get("status") == "completed"
        and job.get("conclusion") == conclusion
    )
    skipped = [item for item in jobs if item.get("id") != job_id]
    _expect(
        {item.get("name") for item in skipped}
        == {"first-deploy-runtime-smoke", "first-deploy-pr-validation"}
        and all(
            item.get("run_id") == run_id
            and item.get("status") == "completed"
            and item.get("conclusion") == "skipped"
            for item in skipped
        )
    )
    steps = job.get("steps")
    _expect(
        isinstance(steps, list)
        and len(steps) == len(step_numbers)
        and all(isinstance(step, dict) for step in steps)
        and [step.get("number") for step in steps] == step_numbers
    )
    for step in steps:
        number = step["number"]
        _expect(step.get("status") == "completed" and isinstance(step.get("name"), str))
        if number in executed:
            _expect((step["name"], step.get("conclusion")) == executed[number])
        else:
            _expect(step.get("conclusion") == "skipped")


def verify_r82(paths: list[str], *, run_id: int, source: str) -> None:
    """Attest exact #807/#809 provenance and one unique R82 before SSH."""
    _expect(len(paths) == 7 and type(run_id) is int and run_id > 0)
    _expect(
        type(source) is str and len(source) == 40 and all(c in "0123456789abcdef" for c in source)
    )
    prs, failed, witness, release, history, failed_jobs, witness_jobs = [
        _read_json(path, maximum=131072 if index in (5, 6) else 32768)
        for index, path in enumerate(paths)
    ]
    _expect(prs == [])
    _run(
        failed,
        number=R82_FAILED_ID,
        source=R82_FAILED_SHA,
        conclusion="failure",
        workflow=DEPLOY,
    )
    _run(
        witness,
        number=R82_WITNESS_ID,
        source=R82_WITNESS_SHA,
        conclusion="success",
        workflow=DEPLOY,
        title=R81_TITLE,
    )
    _run(
        release,
        number=R82_RELEASE_ID,
        source=R82_FAILED_SHA,
        conclusion="success",
        workflow=RELEASE,
    )
    _r82_history(history, run_id=run_id, source=source)
    _r82_jobs(
        failed_jobs,
        run_id=R82_FAILED_ID,
        job_id=R82_FAILED_JOB,
        conclusion="failure",
        executed=R82_FAILED_EXECUTED,
    )
    _r82_jobs(
        witness_jobs,
        run_id=R82_WITNESS_ID,
        job_id=R82_WITNESS_JOB,
        conclusion="success",
        executed=R82_WITNESS_EXECUTED,
    )


# The genuine #819 and #821 manual jobs were recorded with 1..154 and
# 308/309. These are historical REST facts: never infer them from a new
# workflow layout or weaken the R82 job contract.
R87_STEP_NUMBERS = [*range(1, 155), 308, 309]
R87_COMMON = {
    number: (name, "success")
    for number, name in {
        1: "Set up job",
        5: "Require verified protected environment and matching main commit",
        6: "Reject legacy install routes without same-lease Boca-only postflight",
        7: "Checkout exact main commit without persisted credentials",
        8: "Confirm current main HEAD before host access",
        19: "Hash reviewed Boca Compose file",
        36: "Configure pinned SSH host key and dedicated identity",
        308: "Post Checkout exact main commit without persisted credentials",
        309: "Complete job",
    }.items()
}
R87_FAILED_EXECUTED = {
    **R87_COMMON,
    **{
        number: (name, "success")
        for number, name in {
            10: "Validate immutable inputs and successful matching release",
            11: "Require same-run immutable browser companion release manifest",
            18: "Authenticate separate historical controller release and original Compose file",
            20: "Hash reviewed served BETA Compose file",
            21: "Hash reviewed optional browser IPC overlay and seccomp",
            24: "Validate exact optional dual-service IPC Compose model before SSH",
            58: "Require one unique R84 worker preflight dispatch before SSH",
        }.items()
    },
    59: ("Preflight exact dual GHCR image and rootless worker boundary without PREPARE", "failure"),
    60: ("Require exact Boca rootless worker preflight receipt and bounded cleanup", "failure"),
}
R87_WITNESS_EXECUTED = {
    **R87_COMMON,
    42: ("Inspect one failed Boca worker probe READ_ONLY by exact identity", "success"),
}


def _r87_history(history: Any, *, run_id: int, source: str) -> None:
    """One global R87 marker, not one attempt per different main SHA."""
    _expect(isinstance(history, dict))
    runs = history.get("workflow_runs")
    total = history.get("total_count")
    _expect(
        type(total) is int
        and 3 <= total <= 100
        and isinstance(runs, list)
        and len(runs) == total
        and all(isinstance(item, dict) for item in runs)
    )
    for title, expected_id, expected_sha in (
        (R87_FAILED_TITLE, R87_FAILED_ID, R87_FAILED_SHA),
        (R87_WITNESS_TITLE, R87_WITNESS_ID, R87_WITNESS_SHA),
        (R87_TITLE, run_id, source),
    ):
        matched = [item for item in runs if item.get("display_title") == title]
        _expect(len(matched) == 1)
        item = matched[0]
        actor = item.get("actor")
        _expect(
            type(item.get("id")) is int
            and item["id"] == expected_id
            and item.get("event") == "workflow_dispatch"
            and item.get("head_branch") == "main"
            and item.get("head_sha") == expected_sha
            and type(item.get("run_attempt")) is int
            and item["run_attempt"] == 1
            and isinstance(actor, dict)
            and actor.get("login") == "mbalbo2023"
        )
        if title == R87_TITLE:
            _expect(
                item.get("status") in {"in_progress", "queued", "waiting", "pending"}
                and item.get("conclusion") is None
            )
        else:
            _expect(
                item.get("status") == "completed"
                and item.get("conclusion")
                == ("failure" if title == R87_FAILED_TITLE else "success")
            )


def verify_r87(paths: list[str], *, run_id: int, source: str) -> None:
    """Attest #819 failed, #821 read-only, #732 release and unique R87 BEFORE SSH."""
    _expect(len(paths) == 7 and type(run_id) is int and run_id > 0)
    _expect(
        type(source) is str and len(source) == 40 and all(c in "0123456789abcdef" for c in source)
    )
    prs, failed, witness, release, history, failed_jobs, witness_jobs = [
        _read_json(path, maximum=131072 if index in (5, 6) else 32768)
        for index, path in enumerate(paths)
    ]
    _expect(prs == [])
    _run(
        failed,
        number=R87_FAILED_ID,
        source=R87_FAILED_SHA,
        conclusion="failure",
        workflow=DEPLOY,
        title=R87_FAILED_TITLE,
    )
    _run(
        witness,
        number=R87_WITNESS_ID,
        source=R87_WITNESS_SHA,
        conclusion="success",
        workflow=DEPLOY,
        title=R87_WITNESS_TITLE,
    )
    _run(
        release,
        number=R87_RELEASE_ID,
        source=R87_FAILED_SHA,
        conclusion="success",
        workflow=RELEASE,
    )
    _r87_history(history, run_id=run_id, source=source)
    _r82_jobs(
        failed_jobs,
        run_id=R87_FAILED_ID,
        job_id=R87_FAILED_JOB,
        conclusion="failure",
        executed=R87_FAILED_EXECUTED,
        step_numbers=R87_STEP_NUMBERS,
    )
    _r82_jobs(
        witness_jobs,
        run_id=R87_WITNESS_ID,
        job_id=R87_WITNESS_JOB,
        conclusion="success",
        executed=R87_WITNESS_EXECUTED,
        step_numbers=R87_STEP_NUMBERS,
    )


# #827 and #829 have exactly 157 historic REST steps. Their layout differs
# from #819/#821; never reinterpret a prior job against the latest workflow.
R91_STEP_NUMBERS = [*range(1, 156), 310, 311]
R91_COMMON = {
    **{number: item for number, item in R87_COMMON.items() if number not in (308, 309)},
    310: ("Post Checkout exact main commit without persisted credentials", "success"),
    311: ("Complete job", "success"),
}
R91_FAILED_EXECUTED = {
    **R91_COMMON,
    **{
        number: item
        for number, item in R87_FAILED_EXECUTED.items()
        if number not in (58, 59, 60, 308, 309)
    },
    59: ("Require one unique R84 worker preflight dispatch before SSH", "success"),
    60: ("Preflight exact dual GHCR image and rootless worker boundary without PREPARE", "failure"),
    61: ("Require exact Boca rootless worker preflight receipt and bounded cleanup", "failure"),
}
R91_WITNESS_EXECUTED = {
    **R91_COMMON,
    43: ("Inspect one failed Boca worker probe READ_ONLY by exact identity", "success"),
}


def _r91_history(history: Any, *, run_id: int, source: str) -> None:
    """Validate exact historic run IDs but a unique *global* R91 operation.

    R84's display title was legitimately reused by #819 and #827. Matching
    only the title would spuriously block #827 and cannot prove identity.
    """
    _expect(isinstance(history, dict))
    runs = history.get("workflow_runs")
    total = history.get("total_count")
    _expect(
        type(total) is int
        and 3 <= total <= 100
        and isinstance(runs, list)
        and len(runs) == total
        and all(isinstance(item, dict) for item in runs)
    )
    for title, expected_id, expected_sha, expected_status, expected_conclusion in (
        (R91_FAILED_TITLE, R91_FAILED_ID, R91_FAILED_SHA, "completed", "failure"),
        (R91_WITNESS_TITLE, R91_WITNESS_ID, R91_WITNESS_SHA, "completed", "success"),
        (R91_TITLE, run_id, source, None, None),
    ):
        by_id = [item for item in runs if item.get("id") == expected_id]
        _expect(len(by_id) == 1)
        item = by_id[0]
        if title == R91_TITLE:
            # Hard anti-replay across SHA changes and all previous dispatches.
            _expect(len([entry for entry in runs if entry.get("display_title") == title]) == 1)
        actor = item.get("actor")
        _expect(
            item.get("display_title") == title
            and item.get("event") == "workflow_dispatch"
            and item.get("head_branch") == "main"
            and item.get("head_sha") == expected_sha
            and type(item.get("run_attempt")) is int
            and item["run_attempt"] == 1
            and isinstance(actor, dict)
            and actor.get("login") == "mbalbo2023"
        )
        if title == R91_TITLE:
            _expect(
                item.get("status") in {"in_progress", "queued", "waiting", "pending"}
                and item.get("conclusion") is None
            )
        else:
            _expect(
                item.get("status") == expected_status
                and item.get("conclusion") == expected_conclusion
            )


def verify_r91(paths: list[str], *, run_id: int, source: str) -> None:
    """R91 READ_ONLY witness, failed #827, dual #737 and global PR0 one-shot."""
    _expect(len(paths) == 7 and type(run_id) is int and run_id > 0)
    _expect(
        type(source) is str and len(source) == 40 and all(c in "0123456789abcdef" for c in source)
    )
    prs, failed, witness, release, history, failed_jobs, witness_jobs = [
        _read_json(path, maximum=131072 if index in (5, 6) else 32768)
        for index, path in enumerate(paths)
    ]
    _expect(prs == [])
    _run(
        failed,
        number=R91_FAILED_ID,
        source=R91_FAILED_SHA,
        conclusion="failure",
        workflow=DEPLOY,
        title=R91_FAILED_TITLE,
    )
    _run(
        witness,
        number=R91_WITNESS_ID,
        source=R91_WITNESS_SHA,
        conclusion="success",
        workflow=DEPLOY,
        title=R91_WITNESS_TITLE,
    )
    _run(
        release,
        number=R91_RELEASE_ID,
        source=R91_FAILED_SHA,
        conclusion="success",
        workflow=RELEASE,
    )
    _r91_history(history, run_id=run_id, source=source)
    _r82_jobs(
        failed_jobs,
        run_id=R91_FAILED_ID,
        job_id=R91_FAILED_JOB,
        conclusion="failure",
        executed=R91_FAILED_EXECUTED,
        step_numbers=R91_STEP_NUMBERS,
    )
    _r82_jobs(
        witness_jobs,
        run_id=R91_WITNESS_ID,
        job_id=R91_WITNESS_JOB,
        conclusion="success",
        executed=R91_WITNESS_EXECUTED,
        step_numbers=R91_STEP_NUMBERS,
    )


def main(argv: list[str]) -> int:
    try:
        _expect(os.environ.get("GITHUB_RUN_ID", "").isdigit())
        run_id = int(os.environ["GITHUB_RUN_ID"])
        source = os.environ["GITHUB_SHA"]
        if len(argv) > 1 and argv[1] == "--r91":
            verify_r91(argv[2:], run_id=run_id, source=source)
        elif len(argv) > 1 and argv[1] == "--r87":
            verify_r87(argv[2:], run_id=run_id, source=source)
        elif len(argv) > 1 and argv[1] == "--r82":
            verify_r82(argv[2:], run_id=run_id, source=source)
        else:
            verify(argv[1:], run_id=run_id, source=source)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        print("BOCA_WORKER_RECOVERY_GATE state=NO_GO reason=UNVERIFIED")
        return 1
    if len(argv) > 1 and argv[1] == "--r91":
        print(
            "BOCA_WORKER_RECOVERY_GATE state=PASS incident=42368541950 "
            "witness=42370005970 release=42361009081 open_prs=0 "
            "dispatch=UNIQUE_R91 main=VERIFIED prior=READ_ONLY_NO_EFFECT host_writes=0"
        )
    elif len(argv) > 1 and argv[1] == "--r87":
        print(
            "BOCA_WORKER_RECOVERY_GATE state=PASS incident=42353468231 "
            "witness=42355552701 release=42352641660 open_prs=0 "
            "dispatch=UNIQUE_R87 main=VERIFIED prior=READ_ONLY_NO_EFFECT host_writes=0"
        )
    elif len(argv) > 1 and argv[1] == "--r82":
        print(
            "BOCA_WORKER_RECOVERY_GATE state=PASS incident=42341290485 "
            "witness=42342822240 release=42340930071 open_prs=0 "
            "dispatch=UNIQUE_R82 main=VERIFIED prior=READ_ONLY_NO_EFFECT host_writes=0"
        )
    else:
        print(
            "BOCA_WORKER_RECOVERY_GATE state=PASS incident=42329475083 "
            "witness=42337103473 release=42329201039 open_prs=0 "
            "dispatch=UNIQUE main=VERIFIED prior=PRE_SSH_NO_EFFECT host_writes=0"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
