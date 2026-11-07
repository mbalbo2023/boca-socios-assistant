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


def main(argv: list[str]) -> int:
    try:
        _expect(os.environ.get("GITHUB_RUN_ID", "").isdigit())
        run_id = int(os.environ["GITHUB_RUN_ID"])
        source = os.environ["GITHUB_SHA"]
        verify(argv[1:], run_id=run_id, source=source)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        print("BOCA_WORKER_RECOVERY_GATE state=NO_GO reason=UNVERIFIED")
        return 1
    print(
        "BOCA_WORKER_RECOVERY_GATE state=PASS incident=42329475083 "
        "witness=42337103473 release=42329201039 open_prs=0 "
        "dispatch=UNIQUE main=VERIFIED prior=PRE_SSH_NO_EFFECT host_writes=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
