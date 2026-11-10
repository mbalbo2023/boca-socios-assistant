"""Offline authenticated dispatch/replay gate; never GitHub or host I/O."""

from __future__ import annotations

import importlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def gate() -> Any:
    spec = importlib.util.find_spec("check_boca_deploy_dispatch")
    assert spec is not None, "single-dispatch verifier must exist before V3 can reach SSH"
    return importlib.import_module("check_boca_deploy_dispatch")


def evidence() -> tuple[dict[str, str], dict[str, Any]]:
    env = {
        "GITHUB_REPOSITORY": "mbalbo2023/boca-socios-assistant",
        "GITHUB_ACTOR": "mbalbo2023",
        "GITHUB_TRIGGERING_ACTOR": "mbalbo2023",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": "a" * 40,
        "GITHUB_RUN_ID": "100",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_WORKFLOW_REF": "mbalbo2023/boca-socios-assistant/.github/workflows/boca-first-deploy.yml@refs/heads/main",
        "BOCA_OPERATION": "cutover-a-apply",
    }
    run = {
        "id": 100,
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "head_sha": "a" * 40,
        "head_branch": "main",
        "path": ".github/workflows/boca-first-deploy.yml",
        "display_title": "BOCA-SIMULATION-DEPLOY-V3",
        "status": "in_progress",
        "conclusion": None,
        "repository": {"full_name": env["GITHUB_REPOSITORY"]},
        "head_repository": {"full_name": env["GITHUB_REPOSITORY"]},
        "actor": {"login": "mbalbo2023"},
        "triggering_actor": {"login": "mbalbo2023"},
    }
    proof = {
        "run": run,
        "main": {"object": {"sha": "a" * 40}},
        "pulls": [],
        "history": [{"total_count": 1, "workflow_runs": [deepcopy(run)]}],
        "checks": [
            {
                "total_count": 2,
                "check_runs": [
                    {
                        "name": name,
                        "head_sha": "a" * 40,
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                        "check_suite": {"id": 700},
                    }
                    for name in ("quality-and-tests", "image-build")
                ],
            }
        ],
        "ci": [
            {
                "total_count": 1,
                "workflow_runs": [
                    {
                        **run,
                        "id": 90,
                        "event": "push",
                        "path": ".github/workflows/ci.yml",
                        "status": "completed",
                        "conclusion": "success",
                        "check_suite_id": 700,
                    }
                ],
            }
        ],
        "event": {
            "inputs": {
                "operation": "cutover-a-apply",
                "service": "controller",
                "resource_budget": "0.5cpu-256m-64pids",
            }
        },
    }
    return env, proof


def test_owner_dispatch_needs_no_prepare_or_manual_go() -> None:
    env, proof = evidence()
    gate().verify_dispatch(env, proof)


def test_owner_rerun_of_same_green_ci_suite_is_admitted() -> None:
    env, proof = evidence()
    proof["ci"][0]["workflow_runs"][0]["run_attempt"] = 2
    gate().verify_dispatch(env, proof)


@pytest.mark.parametrize("attempt", [None, False, "2", 0, -1, 3, 50])
def test_invalid_ci_attempt_is_rejected(attempt: Any) -> None:
    env, proof = evidence()
    proof["ci"][0]["workflow_runs"][0]["run_attempt"] = attempt
    with pytest.raises(ValueError):
        gate().verify_dispatch(env, proof)


@pytest.mark.parametrize("triggering_actor", [{"login": "other"}, None, {}])
def test_ci_rerun_by_non_owner_does_not_authorize_cutover(triggering_actor: Any) -> None:
    env, proof = evidence()
    ci = proof["ci"][0]["workflow_runs"][0]
    ci["run_attempt"] = 2
    ci["triggering_actor"] = triggering_actor
    with pytest.raises(ValueError):
        gate().verify_dispatch(env, proof)


@pytest.mark.parametrize("violation", ["failed", "suite", "missing", "duplicate", "ci-failed"])
def test_ci_rerun_cannot_replace_bad_suite_checks(violation: str) -> None:
    env, proof = evidence()
    ci = proof["ci"][0]["workflow_runs"][0]
    ci["run_attempt"] = 2
    checks = proof["checks"][0]["check_runs"]
    if violation == "failed":
        checks[0]["conclusion"] = "failure"
    elif violation == "suite":
        checks[0]["check_suite"]["id"] = 800
    elif violation == "missing":
        proof["checks"][0]["check_runs"] = checks[:1]
        proof["checks"][0]["total_count"] = 1
    elif violation == "duplicate":
        checks.append(deepcopy(checks[0]))
        proof["checks"][0]["total_count"] = 3
    else:
        ci["conclusion"] = "failure"
    with pytest.raises(ValueError):
        gate().verify_dispatch(env, proof)


def test_ci_rerun_does_not_permit_cutover_rerun() -> None:
    env, proof = evidence()
    proof["ci"][0]["workflow_runs"][0]["run_attempt"] = 2
    env["GITHUB_RUN_ATTEMPT"] = "2"
    proof["run"]["run_attempt"] = 2
    with pytest.raises(ValueError):
        gate().verify_dispatch(env, proof)


def test_cutover_reads_only_latest_ci_checks_in_both_admission_passes() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    assert (
        workflow.count(
            'gh api --paginate "repos/$GITHUB_REPOSITORY/commits/$GITHUB_SHA/check-runs?filter=latest&per_page=100"'
        )
        == 2
    )


def test_foreign_actions_same_named_checks_do_not_authorize_deploy() -> None:
    env, proof = evidence()
    for check in proof["checks"][0]["check_runs"]:
        check["check_suite"] = {"id": 800}
    with pytest.raises(ValueError):
        gate().verify_dispatch(env, proof)


def test_api_cap_of_1000_is_not_complete_replay_evidence() -> None:
    env, proof = evidence()
    runs = [
        {**proof["run"], "id": 1000 + index, "display_title": "readonly"} for index in range(999)
    ]
    runs.append(proof["run"])
    proof["history"] = [
        {"total_count": 1000, "workflow_runs": runs[i : i + 100]} for i in range(0, 1000, 100)
    ]
    with pytest.raises(ValueError):
        gate().verify_dispatch(env, proof)


@pytest.mark.parametrize(
    "key,value",
    [
        ("GITHUB_REF", "refs/heads/feature"),
        ("GITHUB_ACTOR", "other"),
        ("GITHUB_TRIGGERING_ACTOR", "other"),
        ("GITHUB_RUN_ATTEMPT", "2"),
        ("GITHUB_EVENT_NAME", "push"),
        ("GITHUB_SHA", "b" * 40),
        ("GITHUB_WORKFLOW_REF", "unreviewed"),
    ],
)
def test_wrong_dispatch_identity_is_rejected(key: str, value: str) -> None:
    env, proof = evidence()
    env[key] = value
    with pytest.raises(ValueError):
        gate().verify_dispatch(env, proof)


@pytest.mark.parametrize(
    "case",
    [
        "prior_run",
        "missing_page",
        "open_pr",
        "failed_check",
        "missing_check",
        "context",
        "manual_image",
        "run_actor",
        "main_moved",
    ],
)
def test_incomplete_ambiguous_or_replayed_evidence_is_rejected(case: str) -> None:
    env, proof = evidence()
    if case == "prior_run":
        prior = {**proof["run"], "id": 99}
        proof["history"][0] = {"total_count": 2, "workflow_runs": [prior, proof["run"]]}
    elif case == "missing_page":
        proof["history"][0]["total_count"] = 2
    elif case == "open_pr":
        proof["pulls"] = [{"number": 7}]
    elif case == "failed_check":
        proof["checks"][0]["check_runs"][0]["conclusion"] = "failure"
    elif case == "missing_check":
        proof["checks"][0] = {"total_count": 1, "check_runs": proof["checks"][0]["check_runs"][:1]}
    elif case == "context":
        proof["event"]["inputs"]["protected_action_context"] = "99"
    elif case == "manual_image":
        proof["event"]["inputs"]["image_ref"] = "some-image"
    elif case == "run_actor":
        proof["run"]["triggering_actor"]["login"] = "other"
    else:
        proof["main"]["object"]["sha"] = "b" * 40
    with pytest.raises(ValueError):
        gate().verify_dispatch(env, proof)


def test_cli_validates_downloaded_evidence_without_writing_host_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, proof = evidence()
    for name, data in proof.items():
        (tmp_path / (name + ".json")).write_text(json.dumps(data))
    monkeypatch.setattr("os.environ", env)
    assert gate().main([str(tmp_path)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(name + ".json" for name in proof)


def test_cli_accepts_complete_adjacent_gh_pages_without_slurp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env, proof = evidence()
    other = {**proof["run"], "id": 99, "display_title": "Boca readonly"}
    proof["history"] = [
        {"total_count": 2, "workflow_runs": [other]},
        {"total_count": 2, "workflow_runs": [proof["run"]]},
    ]
    for name, data in proof.items():
        raw = (
            "\n".join(json.dumps(page, indent=2) for page in data)
            if name in ("history", "checks")
            else json.dumps(data)
        )
        (tmp_path / (name + ".json")).write_text(raw)
    monkeypatch.setattr("os.environ", env)
    assert gate().main([str(tmp_path)]) == 0
    # Missing second page must never masquerade as a complete anti-replay read.
    (tmp_path / "history.json").write_text(json.dumps(proof["history"][0]))
    assert gate().main([str(tmp_path)]) == 1
