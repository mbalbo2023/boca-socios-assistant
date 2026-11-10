"""Authenticate current main independently of the already published #810 image."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import check_worker_physical_dispatch as gate  # noqa: E402

SHA = "e" * 40
OLD = "03df9a14bdd78cf768386a865876fed9d5656911"
RELEASE = "31cc6987c30d705113d0323b0700c156fec97eb5"
RUN = "42900000001"
OWNER = {"login": "mbalbo2023"}
REPO = {"full_name": "mbalbo2023/boca-socios-assistant"}
PATH = ".github/workflows/boca-first-deploy.yml"


def _evidence():
    history = [
        {
            "id": int(RUN),
            "workflow_id": 400115324,
            "path": PATH,
            "repository": REPO,
            "event": "workflow_dispatch",
            "head_sha": SHA,
            "head_branch": "main",
            "run_attempt": 1,
            "actor": OWNER,
        }
    ]
    installed = {
        "id": 42806447101,
        "workflow_id": 400115324,
        "path": PATH,
        "repository": REPO,
        "event": "workflow_dispatch",
        "head_sha": OLD,
        "head_branch": "main",
        "run_attempt": 1,
        "actor": OWNER,
        "status": "completed",
        "conclusion": "success",
    }
    release = {
        "id": 42847341532,
        "name": "Boca image release",
        "path": ".github/workflows/release-image.yml@refs/heads/main",
        "repository": REPO,
        "event": "workflow_dispatch",
        "head_sha": RELEASE,
        "head_branch": "main",
        "run_attempt": 1,
        "actor": OWNER,
        "status": "completed",
        "conclusion": "success",
    }
    compare = {
        "status": "ahead",
        "ahead_by": 1,
        "behind_by": 0,
        "base_commit": {"sha": RELEASE},
        "merge_base_commit": {"sha": RELEASE},
        "files": [
            {"filename": "src/boca_socios/host_worker_physical.py", "status": "added"},
            {"filename": ".github/workflows/boca-first-deploy.yml", "status": "modified"},
        ],
    }
    return history, installed, release, compare


def _ci_evidence():
    suite = 999992
    run = {
        "id": 999991,
        "event": "push",
        "head_sha": SHA,
        "head_branch": "main",
        "path": ".github/workflows/ci.yml",
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
        "check_suite_id": suite,
        "repository": REPO,
        "head_repository": REPO,
    }
    checks = [
        {
            "name": name,
            "head_sha": SHA,
            "status": "completed",
            "conclusion": "success",
            "app": {"slug": "github-actions"},
            "check_suite": {"id": suite},
        }
        for name in ("quality-and-tests", "image-build")
    ]
    return (
        [{"total_count": 1, "workflow_runs": [run]}],
        [{"total_count": 2, "check_runs": checks}],
    )


def test_physical_gate_accepts_only_single_owner_dispatch_with_ancestor_release():
    gate.validate(*_evidence(), [], *_ci_evidence(), RUN, SHA)


@pytest.mark.parametrize(
    "mutation",
    [
        "replay",
        "open_pr",
        "release_retry",
        "release_wrong_source",
        "action_not_descended",
        "browser_code_modified",
        "foreign_workflow",
        "other_actor",
        "ci_missing",
        "ci_red",
        "ci_wrong_sha",
        "ci_missing_check",
        "ci_check_red",
    ],
)
def test_physical_gate_rejects_unsafe_release_or_host_dispatch(mutation: str) -> None:
    history, installed, release, compare = copy.deepcopy(_evidence())
    ci_runs, checks = copy.deepcopy(_ci_evidence())
    prs: list[dict[str, str]] = []
    if mutation == "replay":
        history.append(dict(history[0], id=42900000002))
    if mutation == "open_pr":
        prs = [{"number": "123"}]
    if mutation == "release_retry":
        release["run_attempt"] = 2
    if mutation == "release_wrong_source":
        release["head_sha"] = SHA
    if mutation == "action_not_descended":
        compare["merge_base_commit"]["sha"] = "f" * 40
    if mutation == "browser_code_modified":
        compare["files"].append({"filename": "Dockerfile.browser", "status": "modified"})
    if mutation == "foreign_workflow":
        history[0]["path"] = ".github/workflows/ci.yml"
    if mutation == "other_actor":
        history[0]["actor"]["login"] = "another"
    if mutation == "ci_missing":
        ci_runs[0]["workflow_runs"] = []
        ci_runs[0]["total_count"] = 0
    if mutation == "ci_red":
        ci_runs[0]["workflow_runs"][0]["conclusion"] = "failure"
    if mutation == "ci_wrong_sha":
        ci_runs[0]["workflow_runs"][0]["head_sha"] = "b" * 40
    if mutation == "ci_missing_check":
        checks[0]["check_runs"].pop()
        checks[0]["total_count"] = 1
    if mutation == "ci_check_red":
        checks[0]["check_runs"][0]["conclusion"] = "failure"
    with pytest.raises(gate.DispatchUnavailable):
        gate.validate(history, installed, release, compare, prs, ci_runs, checks, RUN, SHA)
