"""R112 exact failed Cutover worker event forensics (READ_ONLY, no host)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts import host_cutover_worker_inspect as observer

ATTEMPT = "42422235097"
SHA = "c8bea3eb13695722ae294f454c7811395c159c26"


def _event(action: str, *, exit_code: str | None = None, **attributes: str) -> dict:
    details = {
        "name": "boca-socios-browser-worker-1",
        "com.docker.compose.project": "boca-socios",
        "com.docker.compose.service": "browser-worker",
        "boca.socios.browser-ipc-attempt": ATTEMPT,
        "private_secret": "MUST_NOT_LEAK",
        **attributes,
    }
    if exit_code is not None:
        details["exitCode"] = exit_code
    return {
        "Type": "container",
        "Action": action,
        "Actor": {"ID": "a" * 64, "Attributes": details},
        "time": 1794091665,
        "scope": "local",
        "private_top_level": "ALSO_MUST_NOT_LEAK",
    }


@pytest.mark.parametrize(
    ("events", "state", "exit_code", "oom"),
    [
        ([], "UNKNOWN", None, "UNKNOWN"),
        ([_event("die", exit_code="1")], "OBSERVED", 1, "UNKNOWN"),
        ([_event("die", exit_code="137")], "OBSERVED", 137, "UNKNOWN"),
        ([_event("oom")], "OBSERVED", None, "YES"),
        ([_event("die", exit_code="137"), _event("oom")], "OBSERVED", 137, "YES"),
        (
            [_event("die", exit_code="1"), _event("die", exit_code="2")],
            "AMBIGUOUS",
            None,
            "UNKNOWN",
        ),
    ],
)
def test_event_summary_is_minimal_and_does_not_infer_oom(events, state, exit_code, oom):
    raw = "\n".join(json.dumps(event) for event in events)
    result = observer.summarize_worker_events(raw)
    assert result == {
        "version": "boca-worker-events-r112-v1",
        "attempt": ATTEMPT,
        "state": state,
        "exit_code": exit_code,
        "oom": oom,
        "observer_writes": 0,
        "foreign_resources_touched": False,
        "retry_authorized": False,
    }
    assert "MUST_NOT_LEAK" not in json.dumps(result)
    assert "a" * 64 not in json.dumps(result)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e.update({"Type": "network"}),
        lambda e: e.update({"Action": "start"}),
        lambda e: e["Actor"]["Attributes"].update({"name": "foreign-worker"}),
        lambda e: e["Actor"]["Attributes"].update({"com.docker.compose.project": "porota"}),
        lambda e: e["Actor"]["Attributes"].update({"com.docker.compose.service": "controller"}),
        lambda e: e["Actor"]["Attributes"].update({"boca.socios.browser-ipc-attempt": "999"}),
        lambda e: e["Actor"]["Attributes"].update({"exitCode": "SECRET"}),
        lambda e: e.update({"time": 1794000000}),
    ],
)
def test_rejects_foreign_or_invalid_event_even_if_docker_claims_filter(mutate):
    event = _event("die", exit_code="1")
    mutate(event)
    with pytest.raises(observer.InspectError):
        observer.summarize_worker_events(json.dumps(event))


def test_duplicate_json_fields_rejected():
    line = json.dumps(_event("die", exit_code="1"))
    with pytest.raises(observer.InspectError):
        observer.summarize_worker_events(
            line.replace('"Action": "die"', '"Action": "die", "Action": "start"')
        )


def test_oom_must_belong_to_same_exact_worker_container_id():
    die = _event("die", exit_code="137")
    oom = _event("oom")
    oom["Actor"]["ID"] = "b" * 64
    record = observer.summarize_worker_events("\n".join(json.dumps(e) for e in (die, oom)))
    assert record["state"] == "AMBIGUOUS"
    assert record["exit_code"] is None
    assert record["oom"] == "UNKNOWN"


def test_host_runs_only_one_fixed_rootless_docker_event_command():
    with (
        patch.object(observer.os, "getuid", return_value=observer.UID),
        patch.object(observer, "_runtime_stat", return_value="PRESENT_OWNED"),
        patch.object(
            observer, "_run_bounded", return_value=json.dumps(_event("die", exit_code="1"))
        ) as bounded,
    ):
        record = observer.observe_worker_events()
    assert record["state"] == "OBSERVED"
    args, kwargs = bounded.call_args
    command = args[0]
    assert command[0] == "docker" and command[1] == "events"
    assert command[2:] == observer.R112_EVENT_FLAGS
    assert kwargs == {"stdout_limit": observer.R112_EVENT_OUTPUT_LIMIT}
    assert "--filter=label=boca.socios.browser-ipc-attempt=42422235097" in command


def test_socket_unverified_returns_unknown_and_does_not_run_docker():
    with (
        patch.object(observer.os, "getuid", return_value=observer.UID),
        patch.object(observer, "_runtime_stat", return_value="UNVERIFIED"),
        patch.object(observer, "_run_bounded") as bounded,
    ):
        record = observer.observe_worker_events()
    bounded.assert_not_called()
    assert record["state"] == "INDETERMINATE"


def test_docker_timeout_is_indeterminate_without_raw_errors():
    with (
        patch.object(observer.os, "getuid", return_value=observer.UID),
        patch.object(observer, "_runtime_stat", return_value="PRESENT_OWNED"),
        patch.object(observer, "_run_bounded", side_effect=TimeoutError("private stderr token")),
    ):
        record = observer.observe_worker_events()
    assert record["state"] == "INDETERMINATE"
    assert "private" not in json.dumps(record)


def test_strict_receipt_canonical_and_no_extra_host_fields():
    record = observer.summarize_worker_events(json.dumps(_event("die", exit_code="137")))
    wire = observer.canonical(record) + b"\n"
    assert observer.verify_worker_events(wire) == record
    with pytest.raises(observer.InspectError):
        observer.verify_worker_events(wire.replace(b'"oom":"UNKNOWN"', b'"oom":"NO"'))
    with pytest.raises(observer.InspectError):
        observer.verify_worker_events(wire[:-1] + b' ,"secret":"data"\n')
    with pytest.raises(observer.InspectError):
        observer.verify_worker_events(
            wire.replace(b'"observer_writes":0', b'"observer_writes":false')
        )


def test_indeterminate_receipt_fails_workflow_not_a_false_green():
    wire = observer.canonical(observer._r112_failed_receipt()) + b"\n"
    result = subprocess.run(  # noqa: S603 - local, fixed parser only
        [sys.executable, "scripts/host_cutover_worker_inspect.py", "events-verify"],
        input=wire,
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert result.returncode != 0
    assert b"state=INDETERMINATE" in result.stdout
    assert b"retry=NO_GO cutover=NO_GO" in result.stdout


def test_exact_incident_auth_requires_failed_original_run_not_an_input_selector():
    run = {
        "id": int(ATTEMPT),
        "head_sha": SHA,
        "head_branch": "main",
        "event": "workflow_dispatch",
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "failure",
        "display_title": "BOCA-SIMULATION-DEPLOY-V3",
        "path": ".github/workflows/boca-first-deploy.yml",
        "run_started_at": "2026-11-07T22:47:19Z",
        "updated_at": "2026-11-07T22:48:25Z",
    }
    observer.authenticate_r112_incident(json.dumps(run).encode())
    for key, replacement in (
        ("id", 42422235098),
        ("head_sha", "0" * 40),
        ("head_branch", "feature"),
        ("event", "push"),
        ("run_attempt", 2),
        ("conclusion", "success"),
        ("updated_at", "2026-11-09T00:00:00Z"),
    ):
        bad = {**run, key: replacement}
        with pytest.raises(observer.InspectError):
            observer.authenticate_r112_incident(json.dumps(bad).encode())


def test_workflow_exact_operation_no_release_and_protected_host():
    workflow = Path(".github/workflows/boca-first-deploy.yml").read_text()
    assert "cutover-a-worker-events-r112" in workflow
    assert "Authenticate historical worker-exit incident R112" in workflow
    assert "Inspect one failed Cutover worker Docker event READ_ONLY" in workflow
    assert "boca-target 'python3 - events-host'" in workflow
    assert "scripts/host_cutover_worker_inspect.py events-verify" in workflow
    assert 'gh api "repos/$GITHUB_REPOSITORY/actions/runs/42422235097"' in workflow
