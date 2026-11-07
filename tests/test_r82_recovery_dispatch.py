"""R82 one-shot REST gate: exact #807 incident, #809 observer and replay denial.

The synthetic documents are deliberately REST-shaped and offline.  They
represent the independently observed Actions runs, not a replay of a host
receipt; a successful observer job is provenance, not permission to delete.
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

REPO = "mbalbo2023/boca-socios-assistant"
DEPLOY_PATH = ".github/workflows/boca-first-deploy.yml"
RELEASE_PATH = ".github/workflows/release-image.yml"

FAILED_ID = 42341290485  # #807: R80 worker preflight left exact stopped probe.
FAILED_SOURCE = "1199c46fee8053e637b220ad9365ce3af15eb8e5"
FAILED_JOB_ID = 128309316427
FAILED_PR_JOB_ID = 128309317334
FAILED_SMOKE_JOB_ID = 128309317470
WITNESS_ID = 42342822240  # #809: protected, SSH READ_ONLY, zero writes.
WITNESS_SOURCE = "8146ab94c1fedf02fbe0ba14e225bbce61339044"
WITNESS_JOB_ID = 128314064855
WITNESS_PR_JOB_ID = 128314065779
WITNESS_SMOKE_JOB_ID = 128314086349
RELEASE_ID = 42340930071  # #723: matching dual-image release.
R79_ID = 42339451485  # #804: historic failed pre-SSH R79 dispatch.
R79_SOURCE = "d9100c6c4666c61ba66fbbefa48e61102a20ce5d"
R80_ID = 42340750343  # #806: historic successful R80 recovery.
CURRENT_ID = 99999999999  # Only a future, distinct main run may consume R82.
CURRENT_SOURCE = "b" * 40

R79_TITLE = "BOCA-R79-WORKER-RECOVER-ONCE"
R80_TITLE = "BOCA-R80-WORKER-RECOVER-ONCE"
R81_TITLE = "BOCA-R81-WORKER-807-READONLY"
R82_TITLE = "BOCA-R82-WORKER-807-RECOVER-ONCE"

# Real Actions #807/#809 manual jobs exposed 154 steps: 1..152, then 304/305.
# These executed names/results come from the pinned REST job histories. Every
# other step was skipped and MUST stay skipped to certify the exact operation.
COMMON_SUCCESSES = {
    1: "Set up job",
    5: "Require verified protected environment and matching main commit",
    6: "Reject legacy install routes without same-lease Boca-only postflight",
    7: "Checkout exact main commit without persisted credentials",
    8: "Confirm current main HEAD before host access",
    19: "Hash reviewed Boca Compose file",
    36: "Configure pinned SSH host key and dedicated identity",
    304: "Post Checkout exact main commit without persisted credentials",
    305: "Complete job",
}
FAILED_EXTRA_SUCCESSES = {
    10: "Validate immutable inputs and successful matching release",
    11: "Require same-run immutable browser companion release manifest",
    18: "Authenticate separate historical controller release and original Compose file",
    20: "Hash reviewed served BETA Compose file",
    21: "Hash reviewed optional browser IPC overlay and seccomp",
    24: "Validate exact optional dual-service IPC Compose model before SSH",
}
FAILED_STEPS = {
    57: "Preflight exact dual GHCR image and rootless worker boundary without PREPARE",
    58: "Require exact Boca rootless worker preflight receipt and bounded cleanup",
}
OBSERVER_STEP = 41
OBSERVER_NAME = "Inspect one failed Boca worker probe READ_ONLY by exact identity"
JOB_STEP_NUMBERS = [*range(1, 153), 304, 305]


def _run(
    run_id: int,
    source: str,
    conclusion: str,
    *,
    path: str = DEPLOY_PATH,
    title: str = "Boca first deploy",
) -> dict[str, Any]:
    return {
        "id": run_id,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": conclusion,
        "run_attempt": 1,
        "head_branch": "main",
        "head_sha": source,
        "path": path,
        "display_title": title,
        "actor": {"login": "mbalbo2023"},
        "repository": {"full_name": REPO},
    }


def _history_run(
    run_id: int, source: str, title: str, *, conclusion: str | None = "success"
) -> dict[str, Any]:
    return {
        **_run(run_id, source, conclusion or "success", title=title),
        "status": "completed" if conclusion is not None else "in_progress",
        "conclusion": conclusion,
    }


def _step(number: int, name: str, conclusion: str) -> dict[str, Any]:
    return {"number": number, "name": name, "status": "completed", "conclusion": conclusion}


def _job_steps(*, observer: bool) -> list[dict[str, Any]]:
    successes = COMMON_SUCCESSES.copy()
    if not observer:
        successes.update(FAILED_EXTRA_SUCCESSES)
    if observer:
        successes[OBSERVER_STEP] = OBSERVER_NAME

    steps: list[dict[str, Any]] = []
    for number in JOB_STEP_NUMBERS:
        name = successes.get(number, f"Skipped phase {number}")
        result = "success" if number in successes else "skipped"
        if not observer and number in FAILED_STEPS:
            name, result = FAILED_STEPS[number], "failure"
        if not observer and number == OBSERVER_STEP:
            name = OBSERVER_NAME
        if observer and number in FAILED_STEPS:
            name = FAILED_STEPS[number]
        steps.append(_step(number, name, result))
    return steps


def _jobs(*, observer: bool) -> dict[str, Any]:
    run_id = WITNESS_ID if observer else FAILED_ID
    job_id = WITNESS_JOB_ID if observer else FAILED_JOB_ID
    pr_id = WITNESS_PR_JOB_ID if observer else FAILED_PR_JOB_ID
    smoke_id = WITNESS_SMOKE_JOB_ID if observer else FAILED_SMOKE_JOB_ID
    return {
        "total_count": 3,
        "jobs": [
            {
                "id": job_id,
                "name": "approved-boca-manual-operation",
                "run_id": run_id,
                "status": "completed",
                "conclusion": "success" if observer else "failure",
                "steps": _job_steps(observer=observer),
            },
            {
                "id": pr_id,
                "name": "first-deploy-pr-validation",
                "run_id": run_id,
                "status": "completed",
                "conclusion": "skipped",
                "steps": None,
            },
            {
                "id": smoke_id,
                "name": "first-deploy-runtime-smoke",
                "run_id": run_id,
                "status": "completed",
                "conclusion": "skipped",
                "steps": None,
            },
        ],
    }


def _evidence() -> dict[str, Any]:
    return {
        "prs": [],
        "failed": _run(FAILED_ID, FAILED_SOURCE, "failure"),
        "witness": _run(WITNESS_ID, WITNESS_SOURCE, "success", title=R81_TITLE),
        "release": _run(RELEASE_ID, FAILED_SOURCE, "success", path=RELEASE_PATH),
        "history": {
            "total_count": 5,
            "workflow_runs": [
                _history_run(FAILED_ID, FAILED_SOURCE, "Boca first deploy", conclusion="failure"),
                _history_run(R79_ID, R79_SOURCE, R79_TITLE, conclusion="failure"),
                _history_run(R80_ID, FAILED_SOURCE, R80_TITLE),
                _history_run(WITNESS_ID, WITNESS_SOURCE, R81_TITLE),
                _history_run(CURRENT_ID, CURRENT_SOURCE, R82_TITLE, conclusion=None),
            ],
        },
        "failed_jobs": _jobs(observer=False),
        "witness_jobs": _jobs(observer=True),
    }


EVIDENCE_ORDER = (
    "prs",
    "failed",
    "witness",
    "release",
    "history",
    "failed_jobs",
    "witness_jobs",
)


def _write_case(
    tmp_path: Path,
    evidence: dict[str, Any],
    *,
    raw_overrides: dict[str, bytes] | None = None,
) -> list[str]:
    paths = []
    for key in EVIDENCE_ORDER:
        path = tmp_path / f"{key}.json"
        if raw_overrides is not None and key in raw_overrides:
            path.write_bytes(raw_overrides[key])
        else:
            path.write_text(json.dumps(evidence[key], separators=(",", ":")), encoding="utf-8")
        paths.append(str(path))
    return paths


def _verify(
    tmp_path: Path,
    evidence: dict[str, Any],
    *,
    run_id: int = CURRENT_ID,
    source: str = CURRENT_SOURCE,
    raw_overrides: dict[str, bytes] | None = None,
) -> None:
    paths = _write_case(tmp_path, evidence, raw_overrides=raw_overrides)
    gate.verify_r82(paths, run_id=run_id, source=source)


def _alter(evidence: dict[str, Any], path: tuple[str | int, ...], value: Any) -> None:
    target: Any = evidence
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


@pytest.mark.parametrize("reference", ["", "@main", "@refs/heads/main"])
def test_exact_seven_rest_receipts_accept_one_current_r82_run(
    tmp_path: Path, reference: str
) -> None:
    evidence = _evidence()
    for key in ("failed", "witness"):
        evidence[key]["path"] = DEPLOY_PATH + reference
    evidence["release"]["path"] = RELEASE_PATH + reference
    _verify(tmp_path, evidence)


@pytest.mark.parametrize("prs", [[{"number": 421}], {}, None, "[]"])
def test_open_pr_or_invalid_open_pr_inventory_denies_pre_ssh(tmp_path: Path, prs: Any) -> None:
    evidence = _evidence()
    evidence["prs"] = prs
    with pytest.raises((ValueError, TypeError)):
        _verify(tmp_path, evidence)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("failed", "id"), FAILED_ID + 1),
        (("failed", "head_sha"), WITNESS_SOURCE),
        (("failed", "conclusion"), "success"),
        (("failed", "status"), "in_progress"),
        (("failed", "event"), "push"),
        (("failed", "run_attempt"), 2),
        (("failed", "head_branch"), "untrusted"),
        (("failed", "actor", "login"), "other"),
        (("failed", "repository", "full_name"), "other/repo"),
        (("witness", "id"), WITNESS_ID + 1),
        (("witness", "head_sha"), FAILED_SOURCE),
        (("witness", "conclusion"), "failure"),
        (("witness", "status"), "in_progress"),
        (("witness", "event"), "push"),
        (("witness", "run_attempt"), 2),
        (("witness", "head_branch"), "untrusted"),
        (("witness", "actor", "login"), "other"),
        (("witness", "repository", "full_name"), "other/repo"),
        (("witness", "display_title"), "Boca first deploy"),
        (("release", "id"), RELEASE_ID + 1),
        (("release", "head_sha"), WITNESS_SOURCE),
        (("release", "conclusion"), "failure"),
        (("release", "status"), "in_progress"),
        (("release", "event"), "push"),
        (("release", "run_attempt"), 2),
        (("release", "head_branch"), "untrusted"),
        (("release", "actor", "login"), "other"),
        (("release", "repository", "full_name"), "other/repo"),
    ],
)
def test_wrong_run_identity_or_provenance_is_never_evidence(
    tmp_path: Path, path: tuple[str | int, ...], value: Any
) -> None:
    evidence = _evidence()
    _alter(evidence, path, value)
    with pytest.raises((ValueError, TypeError)):
        _verify(tmp_path, evidence)


@pytest.mark.parametrize(
    ("target", "path"),
    [
        ("failed", DEPLOY_PATH + "@feature/unsafe"),
        ("witness", DEPLOY_PATH + "@refs/tags/beta"),
        ("failed", ".github/workflows/other.yml"),
        ("witness", DEPLOY_PATH + "/injected"),
        ("release", RELEASE_PATH + "@refs/heads/feature"),
        ("release", DEPLOY_PATH),
    ],
)
def test_untrusted_workflow_ref_or_path_denied(tmp_path: Path, target: str, path: str) -> None:
    evidence = _evidence()
    evidence[target]["path"] = path
    with pytest.raises((ValueError, TypeError)):
        _verify(tmp_path, evidence)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("history", "total_count"), 4),
        (("history", "total_count"), 101),
        (("history", "total_count"), True),
        (("history", "workflow_runs", 4, "id"), CURRENT_ID + 1),
        (("history", "workflow_runs", 4, "display_title"), "Boca first deploy"),
        (("history", "workflow_runs", 4, "head_sha"), WITNESS_SOURCE),
        (("history", "workflow_runs", 4, "run_attempt"), 2),
        (("history", "workflow_runs", 4, "event"), "push"),
        (("history", "workflow_runs", 4, "head_branch"), "untrusted"),
        (("history", "workflow_runs", 4, "actor", "login"), "other"),
        (("history", "workflow_runs", 3, "id"), WITNESS_ID + 1),
        (("history", "workflow_runs", 3, "display_title"), "Boca first deploy"),
        (("history", "workflow_runs", 3, "head_sha"), FAILED_SOURCE),
        (("history", "workflow_runs", 2, "id"), R80_ID + 1),
        (("history", "workflow_runs", 2, "head_sha"), WITNESS_SOURCE),
        (("history", "workflow_runs", 1, "id"), R79_ID + 1),
        (("history", "workflow_runs", 1, "head_sha"), FAILED_SOURCE),
    ],
)
def test_incomplete_or_forged_dispatch_history_denied(
    tmp_path: Path, path: tuple[str | int, ...], value: Any
) -> None:
    evidence = _evidence()
    _alter(evidence, path, value)
    with pytest.raises((ValueError, TypeError)):
        _verify(tmp_path, evidence)


@pytest.mark.parametrize(
    ("run_index", "field", "value"),
    [
        (1, "status", "queued"),  # #804 must be completed failure.
        (1, "conclusion", "success"),
        (2, "status", "in_progress"),  # #806 must be completed success.
        (2, "conclusion", "failure"),
        (3, "status", "waiting"),  # #809 must be completed success.
        (3, "conclusion", "cancelled"),
    ],
)
def test_historical_recovery_markers_require_real_terminal_outcomes(
    tmp_path: Path, run_index: int, field: str, value: str
) -> None:
    evidence = _evidence()
    evidence["history"]["workflow_runs"][run_index][field] = value
    with pytest.raises((ValueError, TypeError)):
        _verify(tmp_path, evidence)


@pytest.mark.parametrize("title", [R79_TITLE, R80_TITLE, R81_TITLE, R82_TITLE])
def test_duplicate_historical_or_current_one_shot_marker_is_replay(
    tmp_path: Path, title: str
) -> None:
    evidence = _evidence()
    evidence["history"]["workflow_runs"].append(
        _history_run(CURRENT_ID + 1, CURRENT_SOURCE, title, conclusion="cancelled")
    )
    evidence["history"]["total_count"] += 1
    with pytest.raises((ValueError, TypeError)):
        _verify(tmp_path, evidence)


def test_unrelated_dispatch_does_not_consume_r82_once_allowance(tmp_path: Path) -> None:
    evidence = _evidence()
    evidence["history"]["workflow_runs"].append(
        _history_run(CURRENT_ID + 1, CURRENT_SOURCE, "Boca first deploy", conclusion="failure")
    )
    evidence["history"]["total_count"] += 1
    _verify(tmp_path, evidence)


def test_current_r82_run_id_and_source_must_equal_current_main(tmp_path: Path) -> None:
    evidence = _evidence()
    with pytest.raises((ValueError, TypeError)):
        _verify(tmp_path, evidence, run_id=CURRENT_ID + 1)
    with pytest.raises((ValueError, TypeError)):
        _verify(tmp_path, evidence, source=WITNESS_SOURCE)
    with pytest.raises((ValueError, TypeError)):
        _verify(tmp_path, evidence, source="too-short")


@pytest.mark.parametrize(
    ("field", "path", "value"),
    [
        ("failed_jobs", ("total_count",), 2),
        ("failed_jobs", ("total_count",), True),
        ("failed_jobs", ("jobs", 0, "id"), FAILED_JOB_ID + 9),
        ("failed_jobs", ("jobs", 0, "run_id"), WITNESS_ID),
        ("failed_jobs", ("jobs", 0, "name"), "other-host-job"),
        ("failed_jobs", ("jobs", 0, "status"), "in_progress"),
        ("failed_jobs", ("jobs", 0, "conclusion"), "success"),
        ("failed_jobs", ("jobs", 1, "conclusion"), "success"),
        ("failed_jobs", ("jobs", 2, "conclusion"), "failure"),
        ("failed_jobs", ("jobs", 0, "steps", 56, "name"), "other remote effect"),
        ("failed_jobs", ("jobs", 0, "steps", 56, "conclusion"), "success"),
        ("failed_jobs", ("jobs", 0, "steps", 57, "name"), "other cleanup"),
        ("failed_jobs", ("jobs", 0, "steps", 57, "conclusion"), "success"),
        ("failed_jobs", ("jobs", 0, "steps", 40, "conclusion"), "success"),
        ("failed_jobs", ("jobs", 0, "steps", 58, "conclusion"), "success"),
        ("failed_jobs", ("jobs", 0, "steps", 152, "conclusion"), "skipped"),
        ("witness_jobs", ("total_count",), 2),
        ("witness_jobs", ("total_count",), True),
        ("witness_jobs", ("jobs", 0, "id"), WITNESS_JOB_ID + 9),
        ("witness_jobs", ("jobs", 0, "run_id"), FAILED_ID),
        ("witness_jobs", ("jobs", 0, "name"), "other-host-job"),
        ("witness_jobs", ("jobs", 0, "status"), "in_progress"),
        ("witness_jobs", ("jobs", 0, "conclusion"), "failure"),
        ("witness_jobs", ("jobs", 1, "conclusion"), "success"),
        ("witness_jobs", ("jobs", 2, "conclusion"), "failure"),
        ("witness_jobs", ("jobs", 0, "steps", 40, "name"), "unverified SSH observer"),
        ("witness_jobs", ("jobs", 0, "steps", 40, "conclusion"), "skipped"),
        ("witness_jobs", ("jobs", 0, "steps", 40, "conclusion"), "failure"),
        ("witness_jobs", ("jobs", 0, "steps", 36, "conclusion"), "success"),
        ("witness_jobs", ("jobs", 0, "steps", 56, "conclusion"), "success"),
        ("witness_jobs", ("jobs", 0, "steps", 57, "conclusion"), "failure"),
        ("witness_jobs", ("jobs", 0, "steps", 152, "conclusion"), "skipped"),
    ],
)
def test_exact_failed_and_observer_job_steps_refuse_invented_host_effects(
    tmp_path: Path, field: str, path: tuple[str | int, ...], value: Any
) -> None:
    evidence = _evidence()
    _alter(evidence[field], path, value)
    with pytest.raises((ValueError, TypeError)):
        _verify(tmp_path, evidence)


@pytest.mark.parametrize("field", ["failed_jobs", "witness_jobs"])
@pytest.mark.parametrize(
    "change", ["remove_step", "duplicate_step", "late_host_step", "extra_host_job"]
)
def test_job_truncation_duplication_or_additional_host_path_denied(
    tmp_path: Path, field: str, change: str
) -> None:
    evidence = _evidence()
    jobs = evidence[field]["jobs"]
    steps = jobs[0]["steps"]
    if change == "remove_step":
        steps.pop(40)
    elif change == "duplicate_step":
        steps.insert(41, copy.deepcopy(steps[40]))
    elif change == "late_host_step":
        steps.insert(-2, _step(200, "Unknown remote effect", "success"))
    else:
        jobs.append(
            {
                "id": jobs[0]["id"] + 3,
                "name": "approved-boca-manual-operation",
                "run_id": jobs[0]["run_id"],
                "status": "completed",
                "conclusion": "success",
                "steps": [_step(38, "Undocumented SSH cleanup", "success")],
            }
        )
        evidence[field]["total_count"] += 1
    with pytest.raises((ValueError, TypeError)):
        _verify(tmp_path, evidence)


@pytest.mark.parametrize(
    ("field", "raw"),
    [
        ("prs", b"not-json"),
        ("failed", b""),
        ("witness", b"{}{}"),
        ("release", b"\xff"),
        ("history", b"x" * 32769),
        ("failed_jobs", b"x" * 131073),
        ("witness_jobs", b"x" * 131073),
    ],
)
def test_missing_malformed_or_oversized_rest_payload_denied(
    tmp_path: Path, field: str, raw: bytes
) -> None:
    with pytest.raises((ValueError, TypeError, UnicodeError)):
        _verify(tmp_path, _evidence(), raw_overrides={field: raw})


@pytest.mark.parametrize("field", ["failed", "history", "failed_jobs", "witness_jobs"])
def test_duplicate_json_keys_cannot_override_github_authority(tmp_path: Path, field: str) -> None:
    evidence = _evidence()
    raw = json.dumps(evidence[field], separators=(",", ":")).encode("ascii")
    if field == "failed":
        original = f'"id":{FAILED_ID}'.encode("ascii")
        duplicate = b'"id":1,' + original
    elif field == "history":
        original = b'"total_count":5'
        duplicate = b'"total_count":1,' + original
    else:
        original = b'"total_count":3'
        duplicate = b'"total_count":1,' + original
    assert original in raw
    raw = raw.replace(original, duplicate, 1)
    with pytest.raises((ValueError, TypeError)):
        _verify(tmp_path, evidence, raw_overrides={field: raw})


def test_exact_seven_paths_are_mandatory_and_no_ambient_api_fetch(tmp_path: Path) -> None:
    paths = _write_case(tmp_path, _evidence())
    for invalid in (paths[:-1], paths + [paths[0]]):
        with pytest.raises((ValueError, TypeError)):
            gate.verify_r82(invalid, run_id=CURRENT_ID, source=CURRENT_SOURCE)
    missing_path = paths.copy()
    missing_path[5] = str(tmp_path / "missing-807-jobs.json")
    with pytest.raises((ValueError, TypeError, OSError)):
        gate.verify_r82(missing_path, run_id=CURRENT_ID, source=CURRENT_SOURCE)


def test_r81_observer_success_step_still_runs_local_receipt_verifier() -> None:
    """Actions success attests a verified observer only while this call exists."""
    workflow = (Path(__file__).resolve().parents[1] / DEPLOY_PATH).read_text(encoding="utf-8")
    marker = f"      - name: {OBSERVER_NAME}\n"
    assert workflow.count(marker) == 1
    body = workflow.split(marker, 1)[1].split("\n      - name:", 1)[0]
    assert "if: inputs.operation == 'cutover-a-worker-inspect'" in body
    assert "< scripts/host_cutover_worker_inspect.py" in body
    assert "python3 scripts/host_cutover_worker_inspect.py verify" in body
    # R86 keeps the same local receipt verifier, now after bounded capture
    # in a private unpredictable directory rather than a fixed runner file.
    assert '< "$inspect_dir/receipt"' in body
    assert "ulimit -f 4 || exit 99" in body
    assert 'mktemp -d "$RUNNER_TEMP/boca-worker-readonly-inspect.' in body
