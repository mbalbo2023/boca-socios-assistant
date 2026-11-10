"""R137 runner provenance, read-only admission and physical receipt gates, offline."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from test_boca_deploy_dispatch_v3 import evidence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

gate = importlib.import_module("scripts.check_904_recovery_dispatch")
deploy = importlib.import_module("scripts.check_boca_deploy_dispatch")

WORKFLOW = ROOT / ".github/workflows/boca-first-deploy.yml"
SHA = "a" * 40
RUN, READ = 44000000011, 44000000010


def _run(number, run_id, sha, title, conclusion):
    return {
        "id": run_id,
        "run_number": number,
        "run_attempt": 1,
        "head_branch": "main",
        "head_sha": sha,
        "actor": {"login": "mbalbo2023"},
        "triggering_actor": {"login": "mbalbo2023"},
        "repository": {"full_name": deploy.REPO},
        "head_repository": {"full_name": deploy.REPO},
        "event": "workflow_dispatch",
        "path": deploy.WORKFLOW,
        "display_title": title,
        "status": "completed" if conclusion else "in_progress",
        "conclusion": conclusion,
    }


def _job(run, number, step_names):
    return {
        "id": number,
        "run_id": run["id"],
        "run_attempt": 1,
        "head_sha": run["head_sha"],
        "name": gate.JOB,
        "status": "completed",
        "conclusion": run["conclusion"],
        "steps": [
            {"name": name, "status": "completed", "conclusion": "success"} for name in step_names
        ],
    }


def proof():
    env, base = evidence()
    env.update(
        GITHUB_RUN_ID=str(RUN),
        GITHUB_RUN_NUMBER="915",
        BOCA_OPERATION="cutover-a-stage-recover",
        BOCA_PROTECTED_ACTION_CONTEXT=gate.R904,
    )
    incident = _run(904, int(gate.R904), gate.R904_SHA, deploy.TITLE, "failure")
    historical = _run(908, gate.R908, gate.R908_SHA, "Boca first deploy", "success")
    inventory = _run(914, READ, SHA, gate.INVENTORY, "success")
    current = _run(915, RUN, SHA, "BOCA-V3-STAGE-RECOVER-" + gate.R904, None)
    raw = {
        "run": current,
        "historical": historical,
        "historical_job": _job(historical, gate.JOB908, [gate.AUTH_STEP, gate.READ_STEP]),
        "inventory": inventory,
        "jobs": {
            "total_count": 1,
            "jobs": [_job(inventory, 100, [gate.AUTH_STEP, gate.READ_STEP, gate.PROFILE_STEP])],
        },
        "pulls": [],
        "main": {"object": {"sha": SHA}},
        "ci": base["ci"],
        "checks": base["checks"],
        "event": {
            "inputs": {
                "operation": "cutover-a-stage-recover",
                "protected_action_context": gate.R904,
                "service": "controller",
                "resource_budget": "0.5cpu-256m-64pids",
                "image_ref": "",
            }
        },
    }
    history = {"total_count": 2, "fetched_count": 2, "workflow_runs": [inventory, current]}
    return env, raw, incident, history


def test_only_first_owner_recovery_after_pinned_908_and_new_positive_inventory():
    env, raw, incident, history = proof()
    assert gate.select_inventory(history, SHA, "915") == str(READ)
    gate.verify_recovery(env, raw, incident, history)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("incident", "head_sha"), "b" * 40),
        (("historical", "id"), 123),
        (("historical_job", "id"), 123),
        (("historical_job", "steps", 1, "conclusion"), "skipped"),
        (("historical_job", "head_sha"), "d" * 40),
        (("incident", "conclusion"), "success"),
        (("inventory", "head_sha"), "b" * 40),
        (("inventory", "head_repository", "full_name"), "other/repo"),
        (("jobs", "jobs", 0, "run_id"), gate.R908),
        (("jobs", "jobs", 0, "run_attempt"), 2),
        (("jobs", "jobs", 0, "conclusion"), "failure"),
        (("jobs", "jobs", 0, "steps", 2, "name"), "some other step"),
        (("jobs", "jobs", 0, "steps", 2, "conclusion"), "skipped"),
        (("jobs", "total_count"), 5),
        (("event", "inputs", "image_ref"), "unreviewed"),
        (("event", "inputs", "protected_action_context"), ""),
        (("env", "GITHUB_TRIGGERING_ACTOR"), "another"),
        (("env", "GITHUB_RUN_ATTEMPT"), "2"),
        (("ci", 0, "workflow_runs", 0, "conclusion"), "cancelled"),
        (("checks", 0, "check_runs", 0, "check_suite", "id"), 899),
        (("pulls",), [{"number": 88}]),
        (("main", "object", "sha"), "b" * 40),
    ],
)
def test_changed_evidence_prevents_recovery(path, value):
    env, raw, incident, history = proof()
    raw.update(incident=incident, env=env)
    field = raw
    for key in path[:-1]:
        field = field[key]
    field[path[-1]] = value
    with pytest.raises(ValueError):
        gate.verify_recovery(env, raw, incident, history)


@pytest.mark.parametrize(
    ("status", "conclusion", "number"),
    [
        ("completed", "failure", 915),
        ("queued", None, 915),
        ("completed", "success", 917),
    ],
)
def test_prior_green_inventory_cannot_mask_incomplete_or_later_observation(
    status, conclusion, number
):
    env, raw, incident, history = proof()
    raw["run"]["run_number"] = 916
    env["GITHUB_RUN_NUMBER"] = "916"
    history["workflow_runs"].append(
        dict(raw["inventory"], id=READ + 7, run_number=number, status=status, conclusion=conclusion)
    )
    history["fetched_count"] = history["total_count"] = 3
    with pytest.raises(ValueError):
        gate.verify_recovery(env, raw, incident, history)


def test_prior_recovery_and_ambiguous_successful_steps_are_rejected():
    env, raw, incident, history = proof()
    history["workflow_runs"].append(dict(raw["run"], id=990, head_sha="c" * 40))
    history["fetched_count"] = history["total_count"] = 3
    with pytest.raises(ValueError):
        gate.verify_recovery(env, raw, incident, history)
    env, raw, incident, history = proof()
    steps = raw["jobs"]["jobs"][0]["steps"]
    steps.append(steps[-1])
    with pytest.raises(ValueError):
        gate.verify_recovery(env, raw, incident, history)


def test_receipt_admission_uses_verified_observation_and_keeps_failure_finite(monkeypatch, capsys):
    response = b'{"version":"fixture"}\n'
    seen = []
    candidate = {"verified": True}

    def read(raw, run_id, prepared, *, source_sha):
        assert (raw, run_id, prepared, source_sha) == (response, gate.R904, None, gate.R904_SHA)
        seen.append("verified")
        return candidate

    def profile(record):
        assert record is candidate and seen == ["verified"]
        raise ValueError("sensitive diagnostics")

    from scripts import host_cutover_postapply_reconcile as observer

    monkeypatch.setattr(observer, "verify_runner", read)
    monkeypatch.setattr(observer, "recovery_profile904", profile, raising=False)
    assert gate.verify_profile(response) == 1
    assert "sensitive" not in str(capsys.readouterr())


@pytest.mark.parametrize(
    "profile", ["OLD_ACTIVE", "OLD_PARKED", "OLD_RENAMED", "OLD_STARTED", "private-sentinel"]
)
def test_only_the_reviewed_observer_profiles_can_be_published(profile, monkeypatch, capsys):
    from scripts import host_cutover_postapply_reconcile as observer

    monkeypatch.setattr(observer, "verify_runner", lambda *_a, **_kw: {"valid": True})
    monkeypatch.setattr(observer, "recovery_profile904", lambda _: profile)
    if profile == "private-sentinel":
        assert gate.verify_profile(b"fixture") == 1
        assert profile not in capsys.readouterr().out
    else:
        assert gate.verify_profile(b"fixture") == 0
        assert f"recovery_profile={profile}" in capsys.readouterr().out


def test_workflow_reserves_incident_before_one_transmission_and_verifies_its_phase():
    flow = WORKFLOW.read_text()
    assert gate.INVENTORY in flow.splitlines()[1]
    assert f"- name: {gate.PROFILE_STEP}" in flow
    block = flow.split("- name: Authenticate the Boca incident and its GitHub evidence", 1)[
        1
    ].split("- name: Attest one historical Boca image release", 1)[0]
    assert "inputs.protected_action_context == '42742150879'" in block
    assert block.count('boca-target "$remote_command"') == 1
    assert block.index("check_904_recovery_dispatch authorize") < block.index(
        'boca-target "$remote_command"'
    )
    assert "cutover-stage-recover-904" in block
    assert "deadline=180s" in block and "deadline=900s" in block
    assert "next=READ_ONLY_904_AND_EXACT_LEGACY_HEALTH" in block
    assert 'scripts.host_cutover_904_recovery "$mode"' in block and "mode=verify" in block
    assert "PHYSICAL_ACK_UNVERIFIED" in block
    assert "docker rm" not in block


def test_bundle_dispatches_904_only_to_fixed_host_entrypoint():
    from scripts import boca_protected_memfd_bootstrap as receiver
    from scripts import build_protected_boca_bundle as builder

    target = "scripts/host_cutover_904_recovery.py"
    assert target in builder.SOURCES and target in receiver.EXPECTED_ENTRIES
    assert target not in builder.RECOVERY_SOURCES and target not in builder.PREFLIGHT_SOURCES
    assert b"cutover-stage-recover-904" in builder.MAIN
    assert b"cutover-stage-recover-904" not in builder.RECOVERY_MAIN + builder.PREFLIGHT_MAIN


def _workflow_shell(step):
    description = WORKFLOW.read_text().split("      - name: " + step + "\n", 1)[1]
    block = description.split("      - name: ", 1)[0].split("        run: |\n", 1)[1]
    return textwrap.dedent(block)


@pytest.mark.parametrize(
    ("physical", "host_rc", "outcome", "result", "summary"),
    [
        ("ok", "0", "success", 0, "state=ORIGINAL_RESTORED"),
        ("no_go", "3", "failure", 1, "state=NO_GO step=PREFLIGHT"),
        ("ok", "255", "failure", 1, "step=PHYSICAL_ACK_UNVERIFIED"),
        ("ok", "124", "failure", 1, "step=PHYSICAL_ACK_UNVERIFIED"),
        ("garbled", "0", "success", 1, "step=PHYSICAL_ACK_UNVERIFIED"),
        ("spliced", "0", "success", 1, "step=PHYSICAL_ACK_UNVERIFIED"),
        ("empty", "255", "failure", 1, "step=PHYSICAL_ACK_UNVERIFIED"),
        ("empty", "", "skipped", 1, "step=RUNNER_GATE host_attempted=false"),
    ],
)
def test_actual_summary_shell_requires_matching_transport_and_exact_receipt(
    tmp_path, physical, host_rc, outcome, result, summary
):
    from scripts import host_cutover_904_recovery as recovery

    case = recovery._coordinates([gate.R904, gate.R904_SHA, str(gate.R908), str(RUN), SHA])
    case.update(
        state="ORIGINAL_RESTORED",
        legacy=recovery.LEGACY,
        controller_image="ABSENT",
        worker_image="ABSENT",
    )
    if physical == "no_go":
        case = recovery._coordinates([gate.R904, gate.R904_SHA, str(gate.R908), str(RUN), SHA]) | {
            "state": "NO_GO",
            "step": "PREFLIGHT",
        }
    if physical == "spliced":
        case["current_run_id"] = str(READ)
    raw = recovery._wire(case)
    if physical in ("garbled", "empty"):
        raw = b"sensitive test bytes" if physical == "garbled" else b""
    (tmp_path / "boca-stage-recovery.receipt").write_bytes(raw)
    summary_file = tmp_path / "summary"
    step = _workflow_shell(gate.PLAN_VERIFIED)
    proc = subprocess.run(  # noqa: S603 - exact checked-in workflow with a local fixture
        ["/bin/bash", "-c", step],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": str(Path(sys.executable).parent) + ":" + os.environ["PATH"],
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(summary_file),
            "HOST_RC": host_rc,
            "HOST_OUTCOME": outcome,
            "PYTHONPATH": "src:.",
            "BOCA_PROTECTED_ACTION_CONTEXT": gate.R904,
            "BOCA_V3_STAGE_INCIDENT_SOURCE": gate.R904_SHA,
            "GITHUB_RUN_ID": str(RUN),
            "GITHUB_SHA": SHA,
        },
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == result
    written = summary_file.read_text()
    assert summary in written
    assert b"sensitive test bytes" not in proc.stderr + proc.stdout + written.encode()
    if result:
        assert "state=ORIGINAL_RESTORED" not in written


@pytest.mark.parametrize(
    ("context", "operation", "admitted", "plan_id", "mode"),
    [
        (gate.R904, "cutover-a-stage-recover", False, None, None),
        (gate.R904, "cutover-a-stage-recover", True, None, "cutover-stage-recover-904"),
        (gate.R916, "cutover-a-reconcile", True, None, "cutover-image-plan-916"),
        (gate.R916, "cutover-a-stage-recover", True, str(READ), "cutover-image-finish-916"),
        (gate.R916, "cutover-a-stage-recover", True, None, None),
        (gate.R916, "cutover-a-reconcile", False, None, None),
        (gate.R916, "cutover-a-apply", True, str(READ), None),
        (gate.R916, "cutover-a-stage-recover-844", True, str(READ), None),
    ],
)
def test_actual_dispatch_shell_sends_one_scoped_zip_only_after_admission(
    tmp_path, context, operation, admitted, plan_id, mode
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ssh = bin_dir / "ssh"
    ssh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, shlex, sys\n"
        "from pathlib import Path\n"
        "args=shlex.split(sys.argv[-1])\n"
        "assert args[:2] == ['python3','-c'] and 'def verify(' in args[2]\n"
        "assert sys.stdin.buffer.read() == b'test bundle'\n"
        "with (Path(os.environ['RUNNER_TEMP'])/'called').open('a') as log:\n"
        "    log.write(json.dumps(args[3:])+'\\n')\n"
        "sys.stdout.buffer.write(b'bounded-response\\n')\n"
        "raise SystemExit(3)\n"
    )
    ssh.chmod(0o700)
    (tmp_path / "boca-stage-recovery-reviewed.pyz").write_bytes(b"test bundle")
    env = {
        **os.environ,
        "PATH": str(bin_dir) + ":" + os.environ["PATH"],
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "BOCA_OPERATION": operation,
        "BOCA_PROTECTED_ACTION_CONTEXT": context,
        "BOCA_V3_STAGE_INCIDENT_SOURCE": gate.R904_SHA,
        "GITHUB_RUN_ID": str(RUN),
        "GITHUB_SHA": SHA,
    }
    if admitted:
        env["BOCA_916_ADMITTED" if context == gate.R916 else "BOCA_904_ADMITTED"] = str(RUN)
    if plan_id:
        env.update(BOCA_916_PLAN_RUN=plan_id, BOCA_916_PLAN_SHA="a" * 64)
    step = _workflow_shell(
        "Remove only authenticated uncommitted Cutover stage or recover Boca incident 904 under lease"
    )
    proc = subprocess.run(  # noqa: S603 - exact checked-in workflow with a local fixture
        ["/bin/bash", "-c", step], cwd=ROOT, env=env, capture_output=True, timeout=10, check=False
    )
    called = tmp_path / "called"
    if mode is None:
        assert proc.returncode != 0 and not called.exists()
        return
    assert proc.returncode == 3
    assert (tmp_path / "output").read_text() == "ssh_rc=3\n"
    assert (tmp_path / "boca-stage-recovery.receipt").read_bytes() == b"bounded-response\n"
    calls = called.read_text().splitlines()
    assert len(calls) == 1
    if context == gate.R904:
        coords = [gate.R904, gate.R904_SHA, str(gate.R908), str(RUN), SHA]
    else:
        coords = [gate.R916, gate.SHA916, gate.R917, str(RUN), SHA]
    if mode == "cutover-image-finish-916":
        coords += [plan_id, "a" * 64]
    assert json.loads(calls[0])[1:] == [mode, *coords]


def test_cli_authenticates_paginated_github_proof_and_rejects_raw_event_override(
    tmp_path, monkeypatch, capsys
):
    env, raw, incident, history = proof()
    folder = tmp_path / "proof"
    folder.mkdir()
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    event = tmp_path / "event.json"
    event.write_text(json.dumps(raw.pop("event")))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    for name, value in raw.items():
        if name in ("ci", "checks"):
            (folder / f"{name}.json").write_text("\n".join(json.dumps(page) for page in value))
        else:
            (folder / f"{name}.json").write_text(json.dumps(value))
    historic = tmp_path / "incident.json"
    historic.write_text(json.dumps(incident))
    pages = tmp_path / "history.json"
    history["run_ids"] = [run["id"] for run in history["workflow_runs"]]
    pages.write_text(json.dumps(history))
    assert gate.main(["inventory-run", str(pages), SHA, env["GITHUB_RUN_NUMBER"]]) == 0
    assert capsys.readouterr().out.strip() == str(READ)
    args = ["authorize", str(folder), str(historic), str(pages)]
    assert gate.main(args) == 0
    assert "host_preflight=REQUIRED" in capsys.readouterr().out
    event.write_text(
        '{"inputs":{"operation":"secret-sentinel","operation":"cutover-a-stage-recover"}}'
    )
    assert gate.main(args) == 1
    output = capsys.readouterr()
    assert "state=NO_GO" in output.err and "secret-sentinel" not in output.err


def _proof916(*, observe=False):
    env, common, _, _ = proof()
    historical_sha = "3c7dd8ae08bc5372a01a25701b6c5524ec9b3386"
    plan_title = "BOCA-R138-916-IMAGE-PLAN"
    finish_title = "BOCA-V3-STAGE-RECOVER-42750940352"
    operation = "cutover-a-reconcile" if observe else "cutover-a-stage-recover"
    env.update(
        BOCA_PROTECTED_ACTION_CONTEXT="42750940352",
        BOCA_OPERATION=operation,
        GITHUB_RUN_NUMBER="920",
        GITHUB_RUN_ID=str(RUN),
    )
    current = _run(920, RUN, SHA, plan_title if observe else finish_title, None)
    previous = _run(919, READ, SHA, plan_title, "success")
    data = {name: common[name] for name in ("event", "pulls", "main", "ci", "checks")}
    data["event"]["inputs"].update(operation=operation, protected_action_context="42750940352")
    data.update(run=current, inventory=previous)
    genuine = (
        (915, 42750716605, 129613417052, gate.INVENTORY, "success"),
        (916, 42750940352, 129614147059, gate.TITLE, "failure"),
        (917, 42751222045, 129615059001, gate.INVENTORY, "success"),
    )
    for n, rid, jid, title, state in genuine:
        rec = _run(n, rid, historical_sha, title, state)
        checks = (
            [gate.AUTH_STEP, gate.READ_STEP, gate.PROFILE_STEP]
            if n != 916
            else [
                "Authenticate both historical runs and the latest pinned inventory",
                "Remove only authenticated uncommitted Cutover stage or recover Boca incident 904 under lease",
                "Verify physical outcome and failed subphase of Boca recovery 904",
            ]
        )
        job = _job(rec, jid, checks)
        if n == 916:
            for s in job["steps"][-2:]:
                s["conclusion"] = "failure"
        data["run" + str(n)] = rec
        data["job" + str(n)] = job
    data["jobs"] = {
        "total_count": 1,
        "jobs": [_job(previous, 123, [gate.PLAN_VERIFIED, gate.PLAN_ARTIFACT])],
    }
    history = {"total_count": 2, "fetched_count": 2, "workflow_runs": [previous, current]}
    return env, data, history


@pytest.mark.parametrize("observe", [True, False])
def test_916_route_authenticates_distinct_historical_roles_and_current_ci(monkeypatch, observe):
    env, data, history = _proof916(observe=observe)
    monkeypatch.setattr(
        gate, "validate", lambda *_: pytest.fail("#916 is a recovery, never a failed Cutover")
    )
    gate.verify_916_dispatch(env, data, history=None if observe else history)


@pytest.mark.parametrize(
    ("path", "wrong"),
    [
        (("run915", "head_sha"), "d" * 40),
        (("run916", "display_title"), deploy.TITLE),
        (("job916", "steps", 1, "conclusion"), "success"),
        (("job916", "steps", 2, "conclusion"), "skipped"),
        (("job917", "steps", 2, "conclusion"), "skipped"),
        (("job917", "head_sha"), "d" * 40),
        (("jobs", "jobs", 0, "steps", 0, "conclusion"), "skipped"),
        (("jobs", "jobs", 0, "steps", 1, "name"), "wrong artifact"),
        (("inventory", "run_attempt"), 2),
        (("event", "inputs", "legacy_release_run_id"), "42750940352"),
        (("event", "inputs", "protected_action_context"), gate.R904),
        (("run", "display_title"), gate.TITLE),
        (("pulls",), [{"number": 431}]),
    ],
)
def test_916_rejects_crossed_or_incomplete_evidence(path, wrong):
    env, data, history = _proof916()
    value = data
    for key in path[:-1]:
        value = value[key]
    value[path[-1]] = wrong
    with pytest.raises(ValueError):
        gate.verify_916_dispatch(env, data, history=history)


def test_916_refuses_second_finish_across_different_source_and_explicit_false_latest():
    env, data, history = _proof916()
    history["workflow_runs"].append(dict(data["run"], id=90490, head_sha="c" * 40))
    history["total_count"] = history["fetched_count"] = 3
    with pytest.raises(ValueError):
        gate.verify_916_dispatch(env, data, history=history)
    env, data, history = _proof916()
    history["workflow_runs"][0]["conclusion"] = "failure"
    with pytest.raises(ValueError):
        gate.verify_916_dispatch(env, data, history=history)


def test_916_wire_modes_have_distinct_arity_and_are_outside_legacy_routes():
    from scripts import build_protected_boca_bundle as builder

    steps = WORKFLOW.read_text().split("  deploy:\n", 1)[1].split("      - name: ")[1:]
    by_name = {step.split("\n", 1)[0]: step for step in steps}
    for step in (
        "Authenticate V3 incident and one per-incident recovery before SSH",
        "Plan Boca-only Docker cleanup READ_ONLY without deleting resources",
        "Reconcile exact failed Cutover A attempt on Boca host READ_ONLY",
        "Require verified physical ACK for one exact stage directory",
    ):
        condition = next(
            line for line in by_name[step].splitlines() if line.startswith("        if: ")
        )
        assert "inputs.protected_action_context != '42750940352'" in condition
    for mode in (b"cutover-image-plan-916", b"cutover-image-finish-916"):
        assert mode in builder.MAIN
        assert mode not in builder.RECOVERY_MAIN + builder.PREFLIGHT_MAIN
    assert gate.PLAN_VERIFIED in by_name and gate.PLAN_ARTIFACT in by_name


completion916 = importlib.import_module("test_host_cutover_904_recovery").completion916


def _summary916(folder, operation, record, *, host_rc="0", host_outcome="success"):
    from scripts import host_cutover_904_recovery as core

    (folder / "boca-stage-recovery.receipt").write_bytes(core._wire(record))
    env = {
        **os.environ,
        "PATH": str(Path(sys.executable).parent) + ":" + os.environ["PATH"],
        "RUNNER_TEMP": str(folder),
        "GITHUB_OUTPUT": str(folder / "step.output"),
        "GITHUB_STEP_SUMMARY": str(folder / "step.summary"),
        "HOST_RC": host_rc,
        "HOST_OUTCOME": host_outcome,
        "PYTHONPATH": "src:.",
        "BOCA_OPERATION": operation,
        "BOCA_PROTECTED_ACTION_CONTEXT": gate.R916,
        "GITHUB_RUN_ID": record["current_run_id"],
        "GITHUB_SHA": record["current_source_sha"],
        "BOCA_916_PLAN_RUN": record.get("observation_run_id", ""),
        "BOCA_916_PLAN_SHA": record.get("observation_plan_sha256", ""),
    }
    proc = subprocess.run(  # noqa: S603 - checked-in runner receipt validation, mock Docker fixture
        ["/bin/bash", "-c", _workflow_shell(gate.PLAN_VERIFIED)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=15,
        check=False,
    )
    return proc.returncode, (folder / "step.summary").read_text()


@pytest.mark.parametrize(
    "case", ["valid", "epoch", "absent_as_removed", "missing_plan", "lost_ssh", "valid_no_go"]
)
def test_finish_summary_cannot_accept_host_output_that_disagrees_with_downloaded_plan(
    tmp_path, completion916, case
):
    from scripts import host_cutover_904_recovery as core

    lab = completion916
    if case == "absent_as_removed":
        lab.engines[core.PINS["browser_image_ref"]].present = False
    plan = lab.observe()
    assert plan["state"] == "READY"
    ready = tmp_path / "boca-904-recovery-proof" / "plan" / "boca-916-plan.json"
    ready.parent.mkdir(parents=True)
    if case != "missing_plan":
        ready.write_bytes(core._wire(plan))
    if case == "valid_no_go":
        lab.break_post = True
    result = lab.finish(plan)
    assert result["state"] == ("NO_GO" if case == "valid_no_go" else "COMPLETED")
    if case == "epoch":
        result["process_sha256"] = "a" * 64
    elif case == "absent_as_removed":
        assert plan["images"]["worker"]["status"] == "ABSENT"
        result["images"]["worker"].update(
            status="REMOVED",
            step="POST_DELETE",
            reason="ABSENCE_PROVED",
            id=core._CONFIG_IDS916["worker"],
        )
    if case in ("epoch", "absent_as_removed"):
        # These individually canonical ACKs pass the wire schema. Only the actual plan
        # from the observed run can establish the process and per-image transition.
        coords = (
            *lab.coords[:3],
            result["current_run_id"],
            result["current_source_sha"],
            plan["current_run_id"],
            plan["plan_sha256"],
        )
        assert core.verify_916(core._wire(result), coords, observation=False) == result
    host_rc = {"valid_no_go": "3", "lost_ssh": "255"}.get(case, "0")
    rc, summary = _summary916(
        tmp_path,
        gate.FINISH_OPERATION,
        result,
        host_rc=host_rc,
        host_outcome="success" if host_rc == "0" else "failure",
    )
    if case == "valid":
        assert rc == 0 and "state=COMPLETED" in summary
    else:
        assert rc != 0 and "state=COMPLETED" not in summary and "state=NO_GO" in summary
        if case == "valid_no_go":
            assert "POST_DELETE" in summary
        else:
            expected = "PHYSICAL_ACK_UNVERIFIED" if case == "lost_ssh" else "ACK_PLAN_MISMATCH"
            assert expected in summary and "effects=UNKNOWN" in summary
    assert not (tmp_path / "boca-916-plan.json").exists()


def test_only_accepted_read_only_plan_artifact_can_bind_finish(tmp_path, completion916, capsys):
    from scripts import host_cutover_904_recovery as core

    plan = completion916.observe()
    rc, summary = _summary916(tmp_path, gate.OBSERVE_OPERATION, plan)
    assert rc == 0 and "state=READY" in summary and completion916.changes == []
    emitted = tmp_path / "boca-916-plan.json"
    assert (
        emitted.read_bytes() == core._wire(plan)
        and (tmp_path / "step.output").read_text() == "publish_plan=true\n"
    )
    folder = tmp_path / "download"
    folder.mkdir()
    artifact = folder / emitted.name
    artifact.write_bytes(emitted.read_bytes())
    args = ["plan-digest-916", str(artifact), plan["current_run_id"], plan["current_source_sha"]]
    assert gate.main(args) == 0 and capsys.readouterr().out.strip() == plan["plan_sha256"]
    artifact.write_bytes(emitted.read_bytes() + b"private-sentinel")
    assert gate.main(args) == 1
    assert "private-sentinel" not in str(capsys.readouterr())
    artifact.write_bytes(emitted.read_bytes())
    (folder / "unverified.json").write_text("other file")
    assert gate.main(args) == 1
    (folder / "unverified.json").unlink()
    artifact.unlink()
    artifact.symlink_to(emitted)
    assert gate.main(args) == 1
