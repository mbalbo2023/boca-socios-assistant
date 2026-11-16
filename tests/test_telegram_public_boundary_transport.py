"""R311: one protected installed selector, closed frame and no host helper."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from boca_socios import host_telegram_backend as backend
from boca_socios import host_telegram_cli as cli
from boca_socios import host_telegram_maintenance as maintenance
from boca_socios import host_telegram_status as status
from test_r309_telegram_prepare_diagnose import (
    ADMIN,
    PUBLIC,
    RUN,
    SOURCE,
    WORKFLOW,
    Runtime,
)
from test_r309_telegram_prepare_transport import _cli, _enabled, _run, _shell

ROOT = Path(__file__).resolve().parents[1]
FLOW = ROOT / ".github/workflows/boca-first-deploy.yml"
OPERATION = "telegram-public-boundary-observe"
STEP = "Execute installed Telegram transaction under one protected lease"


def _run_observation(tmp_path, monkeypatch, *, fault="", parent_valid=True):
    fixture = Runtime(tmp_path, monkeypatch, volume=True)
    fixture.reader.fields[("container", fixture.item.worker_id, "State.Status")] = "created"
    fixture.reader.fields[("container", fixture.item.worker_id, "State.Pid")] = 0
    fixture.fs.write(PUBLIC, b"secret-invalid-json", mode=0o400)
    fixture.fs.write(ADMIN, b"secret-invalid-json", mode=0o600)
    if not parent_valid:
        fixture.fs.data.chmod(0o755)
    calls = []

    def bound_pipe(command):
        assert command == (
            "exec",
            "--user",
            "10001:10001",
            fixture.item.controller_id,
            "/app/.venv/bin/python",
            "-I",
            "-B",
            "-c",
            status.BOUNDARY_OBSERVE_PROGRAM,
        )
        calls.append(command)
        if fault == "drift" and len(calls) == 2:
            fixture.fs.data.chmod(0o750)
        if fault == "pipe" and len(calls) == 2:
            raise RuntimeError("synthetic transport failure")
        if fault == "search-unsupported":
            with monkeypatch.context() as scoped:
                scoped.setattr(os, "supports_effective_ids", set())
                return fixture.literal(status.BOUNDARY_OBSERVE_PROGRAM)
        return fixture.literal(status.BOUNDARY_OBSERVE_PROGRAM)

    with fixture.installed() as lease:
        with monkeypatch.context() as scoped:
            scoped.setattr(maintenance, "_diagnostic_pipe", bound_pipe)
            raw = status.diagnose_public_boundary(
                RUN,
                lease=lease,
                reader=fixture.reader,
                expected_source_sha=SOURCE,
                workflow_sha=WORKFLOW,
            )
    return (
        fixture,
        calls,
        status.verify_public_boundary(
            raw,
            attempt_id=RUN,
            source_sha=SOURCE,
            workflow_sha=WORKFLOW,
            allow_failure=True,
        ),
        raw,
    )


def test_real_lease_guard_two_samples_no_helper_and_parse_not_inspected(tmp_path, monkeypatch):
    fixture, calls, value, raw = _run_observation(tmp_path, monkeypatch)
    assert len(calls) == 2
    assert value["state"] == "OBSERVED_NO_GO"
    assert (value["guards"], value["samples"], value["phase"]) == ("BEFORE_AFTER", 2, "COMPLETE")
    assert value["parent"]["state"] == "VALID"
    assert value["parent"]["mode_octal"] == "0700"
    assert value["parent"]["controller_search"] == "PASS"
    assert value["recipient"]["state"] == "METADATA_VALID_PARSE_UNVERIFIED"
    assert value["admin"]["state"] == "METADATA_VALID_PARSE_UNVERIFIED"
    assert value["parse"] == value["custody"] == value["stage"] == "NOT_INSPECTED"
    assert value["historical_cause"] == "UNDETERMINED"
    assert value["helper_created"] is value["pair_restarted"] is False
    assert (
        value["prepare_authorized"]
        is value["adopt_authorized"]
        is value["repair_authorized"]
        is False
    )
    assert (value["data_writes"], value["custody_writes"], value["status_writes"]) == (0, 0, 0)
    assert fixture.events == [] and fixture.helper is None
    assert not fixture.fs.secret_reads
    assert b"secret" not in raw and len(raw) <= 4096


@pytest.mark.parametrize("fault,complete", [("", True), ("drift", False), ("pipe", False)])
def test_second_snapshot_drift_or_pipe_never_claims_complete(
    tmp_path, monkeypatch, fault, complete
):
    _, calls, value, _ = _run_observation(tmp_path, monkeypatch, fault=fault)
    assert len(calls) == 2
    assert (value["state"] == "OBSERVED_NO_GO") is complete
    assert value["prepare_authorized"] is False
    if not complete:
        assert value["state"] == "INCOMPLETE_NO_GO"
        assert value["reason"] != "NONE"


def test_invalid_parent_can_be_completely_observed_without_leaf_access(tmp_path, monkeypatch):
    fixture, _, value, _ = _run_observation(tmp_path, monkeypatch, parent_valid=False)
    assert value["state"] == "OBSERVED_NO_GO"
    assert value["parent"]["state"] == "INVALID"
    assert value["parent"]["mode_octal"] == "0755"
    assert value["recipient"]["state"] == value["admin"]["state"] == "NOT_ATTEMPTED"
    assert fixture.fs.opens.count("data") == 0


def test_closed_frame_rejects_mutation_duplicate_key_and_oversize(tmp_path, monkeypatch):
    _, _, value, raw = _run_observation(tmp_path, monkeypatch)
    prefix = status.BOUNDARY_PREFIX
    duplicate = prefix + b'{"version":1,"version":1}\n'
    for bad in (duplicate, raw[:-1], raw + b"extra", b"x" * 4097):
        with pytest.raises(ValueError):
            status.verify_public_boundary(
                bad,
                attempt_id=RUN,
                source_sha=SOURCE,
                workflow_sha=WORKFLOW,
                allow_failure=True,
            )
    fixed_fields = {
        "version",
        "operation",
        "source_sha",
        "workflow_source_sha",
        "attempt_id",
        "installation_run_id",
        "controller_id",
        "worker_id",
        "helper_created",
        "helper_retirement",
        "pair_restarted",
        "prepare_authorized",
        "adopt_authorized",
        "repair_authorized",
        "data_writes",
        "custody_writes",
        "status_writes",
        "parse",
        "custody",
        "stage",
        "historical_cause",
        "recommendation",
    }
    dynamic_fields = {
        "state",
        "phase",
        "reason",
        "guards",
        "samples",
        "binding_fingerprint",
        "parent",
        "recipient",
        "admin",
        "engine",
        "sender",
    }
    assert len(fixed_fields) == 22
    assert fixed_fields == set(status._boundary_initial(RUN, WORKFLOW)) - dynamic_fields
    assert set(value) == fixed_fields | dynamic_fields
    for key in sorted(fixed_fields):
        original = value[key]
        if type(original) is bool:
            mutations = (not original, int(original))
        elif type(original) is int:
            mutations = (original + 1, bool(original))
        else:
            assert type(original) is str
            mutations = (original + "_mutated", False)
        for replacement in mutations:
            changed = {**value, key: replacement}
            damaged = (
                prefix + json.dumps(changed, sort_keys=True, separators=(",", ":")).encode() + b"\n"
            )
            with pytest.raises(ValueError, match="telegram_public_boundary_unverified"):
                status.verify_public_boundary(
                    damaged,
                    attempt_id=RUN,
                    source_sha=SOURCE,
                    workflow_sha=WORKFLOW,
                    allow_failure=True,
                )
    for key, replacement in (
        ("guards", "BEFORE"),
        ("parent", {**value["parent"], "state": "METADATA_VALID_PARSE_UNVERIFIED"}),
        ("parent", {**value["parent"], "mode_octal": "0701"}),
        ("parent", {**value["parent"], "mode_octal": "700"}),
        ("parent", {**value["parent"], "mode_octal": None}),
        ("parent", {**value["parent"], "controller_search": "YES"}),
        ("parent", {**value["parent"], "controller_search": "NOT_READ"}),
        ("recipient", {**value["recipient"], "state": "VALID"}),
        (
            "recipient",
            {
                **value["recipient"],
                "state": "NOT_ATTEMPTED",
                "witness": None,
                "checks": dict.fromkeys(value["recipient"]["checks"], "NOT_READ"),
            },
        ),
    ):
        changed = {**value, key: replacement}
        damaged = (
            prefix + json.dumps(changed, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
        with pytest.raises(ValueError):
            status.verify_public_boundary(
                damaged,
                attempt_id=RUN,
                source_sha=SOURCE,
                workflow_sha=WORKFLOW,
                allow_failure=True,
            )


def test_cli_isolated_verifier_preserves_diagnosis_v1(tmp_path, monkeypatch):
    _, _, _, frame = _run_observation(tmp_path, monkeypatch)
    validated = _run(_cli("verify-receipt", OPERATION, SOURCE, WORKFLOW, RUN), tmp_path, raw=frame)
    assert validated.returncode == 0 and validated.stdout == frame
    refused = _run(_cli(OPERATION, SOURCE, WORKFLOW, RUN), tmp_path)
    assert refused.returncode == 3
    result = status.verify_public_boundary(
        refused.stdout,
        attempt_id=RUN,
        source_sha=SOURCE,
        workflow_sha=WORKFLOW,
        allow_failure=True,
    )
    assert result["phase"] == "LEASE" and result["state"] == "INCOMPLETE_NO_GO"
    assert "telegram-prepare-diagnose" in cli.OPERATIONS
    assert backend.DIAGNOSIS_PREFIX != status.BOUNDARY_PREFIX


def test_workflow_installed_route_and_legacy_exclusions():
    source = FLOW.read_text()
    options = source.split("        options: [", 1)[1].split("]", 1)[0].split(", ")
    assert OPERATION in options
    assert _enabled("Prove Telegram release ancestry and build installed transaction", OPERATION)
    assert _enabled(STEP, OPERATION)
    for name in (
        "Recheck current main before Telegram post-install custody",
        "Mark Telegram host attempt before starting existing Boca daemon",
        "Start only stopped existing dedicated Boca daemon",
        "Execute protected Telegram schema, custody or one-shot test",
        "Stop positively identified Boca services after Telegram custody",
    ):
        assert not _enabled(name, OPERATION)
    assert OPERATION not in _shell("Execute protected Telegram schema, custody or one-shot test")
    assert (
        OPERATION in source.split("        if: inputs.operation == 'telegram-schema-observe'", 1)[1]
    )
    assert "BOCA_TELEGRAM_PUBLIC_BOUNDARY_V2" in _shell(STEP)
    assert "BOCA_TELEGRAM_PUBLIC_BOUNDARY_V1" not in _shell(STEP)
    assert "TRANSPORT_UNVERIFIED" in _shell(STEP)
    assert "verification_rc" in _shell(STEP) and "remote_rc" in _shell(STEP)


def test_no_new_freeform_inputs_to_metadata_selector():
    mapping = FLOW.read_text().split("      BOCA_SOURCE_SHA: ", 1)[1].splitlines()[0]
    assert OPERATION not in mapping and mapping.endswith("|| inputs.source_sha }}")
    assert OPERATION in cli.OPERATIONS
    assert re.fullmatch(r"[a-f0-9]{40}", SOURCE)


def test_r313_unsupported_effective_access_cannot_claim_complete(tmp_path, monkeypatch):
    _, calls, value, raw = _run_observation(tmp_path, monkeypatch, fault="search-unsupported")
    assert len(calls) == 2
    assert value["parent"]["state"] == "VALID"
    assert value["parent"]["controller_search"] == "NOT_READ"
    assert value["state"] == "INCOMPLETE_NO_GO"
    assert value["reason"] == "PUBLIC_UNVERIFIED"
    assert value["guards"] == "BEFORE_AFTER" and value["samples"] == 2
    assert len(raw) <= 4096


def test_r313_historical_v1_is_explicit_only_and_cannot_enter_v2(tmp_path, monkeypatch):
    # Fixed historical R311 fixture, independent of the new V2 constructor/encoder.
    old = {
        "version": 1,
        "operation": "telegram-public-boundary-observe",
        "source_sha": "845f31abfb1762dff27e6fc3274fcc40507f3f18",
        "workflow_source_sha": WORKFLOW,
        "attempt_id": RUN,
        "installation_run_id": "43704768556",
        "controller_id": "b0dd0fed57c55dbdeb9a6e833d913cb86c0868ae1587394a934450342114bfa1",
        "worker_id": "c9c882ff12666fb6cac130879925879cfc0c5c23173a843434adee96b4339dce",
        "state": "INCOMPLETE_NO_GO",
        "phase": "PREFLIGHT",
        "reason": "GUARD_UNVERIFIED",
        "guards": "NOT_READ",
        "samples": 0,
        "binding_fingerprint": None,
        "parent": {
            "state": "NOT_READ",
            "checks": {"type": "NOT_READ", "mode": "NOT_READ", "owner": "NOT_READ"},
            "witness": None,
        },
        "recipient": {
            "state": "NOT_ATTEMPTED",
            "checks": {key: "NOT_READ" for key in ("type", "mode", "owner", "nlink", "size")},
            "witness": None,
        },
        "admin": {
            "state": "NOT_ATTEMPTED",
            "checks": {key: "NOT_READ" for key in ("type", "mode", "owner", "nlink", "size")},
            "witness": None,
        },
        "engine": "NOT_READ",
        "sender": "NOT_READ",
        "helper_created": False,
        "helper_retirement": "NOT_APPLICABLE",
        "pair_restarted": False,
        "prepare_authorized": False,
        "adopt_authorized": False,
        "repair_authorized": False,
        "data_writes": 0,
        "custody_writes": 0,
        "status_writes": 0,
        "parse": "NOT_INSPECTED",
        "custody": "NOT_INSPECTED",
        "stage": "NOT_INSPECTED",
        "historical_cause": "UNDETERMINED",
        "recommendation": "PRESERVE_NO_RETRY",
    }
    raw = (
        status.BOUNDARY_PREFIX_V1
        + json.dumps(old, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )
    assert raw.startswith(status.BOUNDARY_PREFIX_V1)
    assert (
        status.verify_public_boundary(
            raw,
            attempt_id=RUN,
            source_sha=SOURCE,
            workflow_sha=WORKFLOW,
            version=1,
            allow_failure=True,
        )
        == old
    )
    with pytest.raises(ValueError):
        status.verify_public_boundary(
            raw, attempt_id=RUN, source_sha=SOURCE, workflow_sha=WORKFLOW, allow_failure=True
        )
    _, _, _, new = _run_observation(tmp_path, monkeypatch)
    assert new.startswith(status.BOUNDARY_PREFIX)
    with pytest.raises(ValueError):
        status.verify_public_boundary(
            new,
            attempt_id=RUN,
            source_sha=SOURCE,
            workflow_sha=WORKFLOW,
            version=1,
            allow_failure=True,
        )


@pytest.mark.parametrize("invalid", [True, False, 0, 3, "1", 1.0, None])
def test_r313_version_parameter_is_exact_int_one_or_two(tmp_path, monkeypatch, invalid):
    _, _, _, raw = _run_observation(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        status.verify_public_boundary(
            raw,
            attempt_id=RUN,
            source_sha=SOURCE,
            workflow_sha=WORKFLOW,
            version=invalid,
            allow_failure=True,
        )


@pytest.mark.parametrize(
    "scenario,remote_rc,verification_rc,expected_rc",
    [
        ("complete", 0, 0, 0),
        ("remote", 7, 0, 1),
        ("verifier", 0, 2, 1),
        ("cross-prefix", 0, 0, 1),
        ("incomplete", 0, 0, 1),
    ],
)
def test_actual_protected_bash_tail_requires_remote_and_verifier_ack(
    tmp_path, monkeypatch, scenario, remote_rc, verification_rc, expected_rc
):
    _, _, value, frame = _run_observation(tmp_path, monkeypatch)
    if scenario == "cross-prefix":
        frame = backend._diagnosis_frame(backend._diagnosis_initial(RUN, WORKFLOW))
    elif scenario == "incomplete":
        frame = status._boundary_frame(
            {**value, "state": "INCOMPLETE_NO_GO", "phase": "PUBLIC_B", "reason": "PUBLIC_CHANGED"}
        )
    shell = _shell(STEP)
    tail = shell[shell.index('if [[ "$verification_rc"') :]
    summary = tmp_path / "summary"
    execution = _run(
        ["/bin/bash", "-euo", "pipefail", "-c", tail],
        tmp_path,
        env={
            "PATH": "/usr/bin:/bin",
            "BOCA_OPERATION": OPERATION,
            "remote_rc": str(remote_rc),
            "verification_rc": str(verification_rc),
            "verified": frame.decode("ascii").rstrip("\n"),
            "GITHUB_STEP_SUMMARY": str(summary),
        },
    )
    assert execution.returncode == expected_rc, execution.stderr.decode()
    written = summary.read_text()
    assert "OWNER_ACCEPTANCE" not in written and "state=PREPARED" not in written
    assert '"prepare_authorized":true' not in written
    assert '"adopt_authorized":true' not in written
    assert '"repair_authorized":true' not in written
    if scenario == "complete":
        assert frame.decode("ascii") in written
        assert "BOCA_TELEGRAM_PUBLIC_BOUNDARY state=OBSERVED_NO_GO" in written
    elif scenario == "remote":
        assert written.splitlines()[0].startswith(
            "BOCA_TELEGRAM_PUBLIC_BOUNDARY state=INCOMPLETE_NO_GO reason=TRANSPORT_UNVERIFIED"
        )
        assert written.splitlines()[1].startswith(
            "BOCA_TELEGRAM_BACKEND_EVIDENCE_NON_AUTHORITATIVE transport=UNVERIFIED receipt="
        )
        assert "BOCA_TELEGRAM_PUBLIC_BOUNDARY state=OBSERVED_NO_GO" not in written
    elif scenario in {"verifier", "cross-prefix"}:
        assert "state=INCOMPLETE_NO_GO reason=TRANSPORT_UNVERIFIED" in written
        assert frame.decode("ascii") not in written
    else:
        assert frame.decode("ascii") in written
        assert "BOCA_TELEGRAM_PUBLIC_BOUNDARY state=OBSERVED_NO_GO" not in written
