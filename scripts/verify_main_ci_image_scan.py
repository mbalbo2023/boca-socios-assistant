"""Attest the exact existing main-CI Docker/Trivy scan; never build or publish.

The separate ``Image security`` push workflow used to rebuild the same
controller/browser pair after CI had already built and scanned that exact
main commit.  This verifier checks the authenticated CI Actions run and its
individual mandatory scan steps.  It is *not* a replacement for either scan:
they must have genuinely completed in ``CI / image-build`` before success.
Manual Image security dispatches retain independent builds and scans.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any, cast

REPO = "mbalbo2023/boca-socios-assistant"
SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_RUN_BYTES = 262_144
MAX_JOB_BYTES = 1_048_576
MAX_POLLS = 80
POLL_SECONDS = 10
REQUIRED_SCAN_STEPS = (
    "Require scan aliases to identify the exact built pair",
    "Scan before any image publication",
    "Scan browser image before any publication",
)


class AuditError(ValueError):
    """An exact main CI image-scan attestation could not be established."""


def _require(value: bool, reason: str = "unverified") -> None:
    if not value:
        raise AuditError(reason)


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in fields, "duplicate_metadata")
        fields[key] = value
    return fields


def _records(payload: object, array: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise AuditError("metadata_type")
    items = payload.get(array)
    if not isinstance(items, list):
        raise AuditError("record_type")
    _require(type(payload.get("total_count")) is int, "count_type")
    _require(payload["total_count"] == len(items) and len(items) <= 100, "page_incomplete")
    _require(all(isinstance(item, dict) for item in items), "record_type")
    return cast("list[dict[str, Any]]", items)


def _single_main_run(runs: object, sha: str) -> dict[str, Any]:
    _require(SHA.fullmatch(sha) is not None, "source_sha")
    entries = _records(runs, "workflow_runs")
    _require(len(entries) == 1, "ci_run_not_unique")
    run = entries[0]
    expected: dict[str, object] = {
        "head_sha": sha,
        "head_branch": "main",
        "event": "push",
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
    }
    for field, value in expected.items():
        _require(run.get(field) == value and type(run.get(field)) is type(value), "ci_identity")
    _require(
        run.get("path") in (".github/workflows/ci.yml", ".github/workflows/ci.yml@main"),
        "ci_path",
    )
    for repository_field in ("repository", "head_repository"):
        repository = run.get(repository_field)
        _require(isinstance(repository, dict) and repository.get("full_name") == REPO, "repository")
    for field in ("id", "check_suite_id"):
        _require(type(run.get(field)) is int and run[field] > 0, "ci_run_id")
    return run


def verify_attestation(runs: object, jobs: object, sha: str, role: str) -> tuple[int, int]:
    """Accept only one same-SHA main CI job with both actual scans and aliases PASS."""
    _require(role in ("controller", "browser"), "role")
    run = _single_main_run(runs, sha)
    entries = _records(jobs, "jobs")
    matches = [job for job in entries if job.get("name") == "image-build"]
    _require(len(matches) == 1, "ci_image_job_not_unique")
    image = matches[0]
    expected: dict[str, object] = {
        "run_id": run["id"],
        "head_sha": sha,
        "status": "completed",
        "conclusion": "success",
    }
    for field, value in expected.items():
        _require(image.get(field) == value and type(image.get(field)) is type(value), "image_job")
    _require(type(image.get("id")) is int and image["id"] > 0, "image_job_id")
    steps = image.get("steps")
    if not isinstance(steps, list):
        raise AuditError("image_steps")
    names: list[str] = []
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("name"), str):
            raise AuditError("image_step")
        names.append(step["name"])
    for name in REQUIRED_SCAN_STEPS:
        _require(names.count(name) == 1, "scan_missing_or_duplicated")
        step = steps[names.index(name)]
        _require(
            step.get("status") == "completed" and step.get("conclusion") == "success",
            "scan_not_successful",
        )
    _require(
        [names.index(name) for name in REQUIRED_SCAN_STEPS]
        == sorted(names.index(name) for name in REQUIRED_SCAN_STEPS),
        "scan_step_order",
    )
    return run["id"], image["id"]


def _gh_api(path: str, *, max_size: int) -> object:
    executable = shutil.which("gh")
    if executable is None:
        raise AuditError("github_cli_unavailable")
    try:
        reply = subprocess.run(  # noqa: S603 - no shell; CLI path and repo/SHA are constrained
            (executable, "api", path),
            check=True,
            capture_output=True,
            timeout=25,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise AuditError("github_api_unavailable") from exc
    _require(len(reply.stdout) <= max_size, "api_response_oversized")
    try:
        return json.loads(reply.stdout, object_pairs_hook=_unique_fields)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError("api_response_invalid") from exc


def _input_identity(role: str) -> str:
    expected = {
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
    }
    _require(role in ("controller", "browser"), "role")
    for key, value in expected.items():
        _require(os.environ.get(key) == value, "actions_identity")
    _require(bool(os.environ.get("GH_TOKEN")), "api_auth_missing")
    sha = os.environ.get("GITHUB_SHA", "")
    _require(SHA.fullmatch(sha) is not None, "source_sha")
    return sha


def attest(role: str) -> tuple[str, int, int]:
    sha = _input_identity(role)
    path = f"repos/{REPO}/actions/workflows/ci.yml/runs?event=push&head_sha={sha}&per_page=20"
    for iteration in range(MAX_POLLS):
        runs = _gh_api(path, max_size=MAX_RUN_BYTES)
        entries = _records(runs, "workflow_runs")
        _require(len(entries) <= 1, "ci_run_not_unique")
        if entries:
            run = entries[0]
            _require(run.get("head_sha") == sha and run.get("event") == "push", "ci_identity")
            if run.get("status") == "completed":
                _single_main_run(runs, sha)
                jobs = _gh_api(
                    f"repos/{REPO}/actions/runs/{run['id']}/jobs?per_page=100",
                    max_size=MAX_JOB_BYTES,
                )
                ci_run, image_job = verify_attestation(runs, jobs, sha, role)
                return sha, ci_run, image_job
        if iteration < MAX_POLLS - 1:
            time.sleep(POLL_SECONDS)
    raise AuditError("ci_image_scan_timeout")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: verify_main_ci_image_scan.py controller|browser", file=sys.stderr)
        return 2
    role = args[0]
    try:
        sha, ci_run, image_job = attest(role)
    except AuditError as exc:
        print(f"BOCA_MAIN_SCAN_ATTESTATION state=NO_GO reason={exc}", file=sys.stderr)
        return 1
    print(
        f"BOCA_MAIN_SCAN_ATTESTATION state=PASS source_sha={sha} "
        f"role={role} ci_run_id={ci_run} ci_image_job_id={image_job} "
        "scans=CI_IMAGE_BUILD_EXACT_SOURCE local_image_builds=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
