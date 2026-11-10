"""Redacted acceptance evidence for the cold pair, including lost primary SSH stdout."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cutover as cutover
from boca_socios import host_boca_cutover_cli as cli
from boca_socios import host_boca_cutover_receipt as terminal
from boca_socios import host_cutover_capture_readback as readback
from test_cutover_a_go import _actions_fixture, _file, go
from test_host_boca_cutover import FakeHost
from test_host_boca_cutover_receipt import _accepted, _plan


@pytest.mark.parametrize(
    "recover,cleanup_state", [(True, "ACCEPT"), (True, "INDETERMINATE"), (False, "NO_GO")]
)
def test_failed_cold_acceptance_survives_compensation_and_lost_first_stdout(
    tmp_path, monkeypatch, capsys, recover, cleanup_state
):
    request, env = _actions_fixture(tmp_path)
    plan = request.plan
    home = tmp_path / "private-home"
    home.mkdir(mode=0o700)
    monkeypatch.setattr(cleanup, "LEASE_DIR", home)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(terminal, "_account_home", lambda: home)
    monkeypatch.setattr(terminal, "_persistent_mount", lambda _: None)
    monkeypatch.setattr(
        readback.custody, "read_before_cleanup", lambda _: pytest.fail("no worker receipt")
    )

    class FailedCold(FakeHost):
        def accept_candidate(self, plan, candidate_id, worker_id, lease):
            self.events.append("accept")
            with (
                cutover.candidate_check("CONTROL_INSTALL"),
                cutover.candidate_check("CONTROL_MANAGER_RELOAD"),
            ):
                raise PermissionError("SYNTHETIC_PRIVATE_DETAIL")

    backend = FailedCold(recovered=recover, cleanup_result=cleanup_state)

    def sink(plan, receipt, lease):
        terminal.write_once(
            terminal.TerminalRecord.from_receipt(plan, receipt), plan=plan, lease=lease
        )

    def execute(plan):
        return cutover.run_cutover_a(
            plan,
            backend=backend,
            terminal_preflight=terminal.prepare_destination,
            terminal_sink=sink,
        )

    bundle = request.bundle_path.read_bytes()
    digest = go.authorization_digest(request)
    token = cli.encode_invocation(
        plan,
        bundle_sha256=hashlib.sha256(bundle).hexdigest(),
        go_binding_sha256=digest,
        dispatch_v3=True,
    )
    with os.fdopen(os.memfd_create("candidate-test"), "wb") as archive:
        archive.write(bundle)
        archive.flush()
        monkeypatch.setattr(sys, "argv", [f"/proc/self/fd/{archive.fileno()}"])
        assert (
            cli.run_cli(token, dispatch_v3=True, approved_go_binding_sha256=digest, execute=execute)
            == 3
        )
        primary = capsys.readouterr().out
        assert "SYNTHETIC_PRIVATE_DETAIL" not in primary and "WORKER_FAILURE" not in primary
        assert "candidate_check=CONTROL_MANAGER_RELOAD" in primary
        # The host has zero access to the original SSH stdout during readback.
        assert readback.run_host(token, approved_go_binding_sha256=digest) == 0
    wire = capsys.readouterr().out
    verified = readback.verify(wire.encode(), plan.attempt_id, plan.target_sha)
    assert "receipt=VERIFIED" in verified and "candidate_check=CONTROL_MANAGER_RELOAD" in verified
    assert (
        "candidate_result=PERMISSION_DENIED" in verified and f"cleanup={cleanup_state}" in verified
    )
    restored = "VERIFIED" if recover else "UNVERIFIED"
    assert f"original_restored={restored}" in verified and "retry=NO_GO" in verified
    raw = (
        home / terminal.RECEIPT_DIR_NAME / f"boca-cutover-a-result-{plan.attempt_id}.json"
    ).read_bytes()
    assert json.loads(raw)["version"] == "boca-cutover-a-terminal-v7"
    assert "SYNTHETIC_PRIVATE_DETAIL" not in raw.decode() and "retire" not in backend.events
    _file(Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME, primary.encode())
    summary = go.classify_cutover_ssh_failure({**env, "BOCA_CUTOVER_A_SSH_RC": "3"})
    assert (
        "phase_claim=ACCEPT_CANDIDATE" in summary
        and "candidate_check_claim=CONTROL_MANAGER_RELOAD" in summary
    )
    assert (
        "candidate_result_claim=PERMISSION_DENIED" in summary and "terminal=UNVERIFIED" in summary
    )


def test_candidate_marker_cannot_coexist_with_acceptance_worker_capture_or_commit():
    original = _accepted()
    failed = replace(
        original,
        state="RECOVERED",
        cleanup="ACCEPT",
        original_restored=True,
        irreversible_commit_started=False,
        failed_phase="ACCEPT_CANDIDATE",
        candidate_check="INITIAL_LEDGER",
        candidate_result="MISMATCH",
    )
    rec = terminal.TerminalRecord.from_receipt(_plan(), failed)
    assert json.loads(rec.serialized())["candidate_check"] == "INITIAL_LEDGER"
    for fields in (
        {"state": "ACCEPTED"},
        {"idle_installed": True},
        {"irreversible_commit_started": True},
        {"candidate_id": None},
        {"worker_id": rec.candidate_id},
        {"worker_stderr_observation": "EMPTY"},
        {"candidate_check": "PRIVATE"},
        {"candidate_result": "PRIVATE"},
        {"original_restored": False},
    ):
        with pytest.raises(terminal.TerminalReceiptError):
            replace(rec, **fields).serialized()


@pytest.mark.parametrize(
    "case",
    [
        "run",
        "sha",
        "wrong-phase",
        "duplicate",
        "rewritten",
        "secret",
        "unrestored",
        "accepted",
        "timeout",
        "nonascii",
    ],
)
def test_false_candidate_failure_lines_are_not_trusted(tmp_path, case):
    request, env = _actions_fixture(tmp_path)
    run, sha = request.plan.attempt_id, request.plan.target_sha
    suffix = "candidate_check=RESTART_LEDGER candidate_result=MISMATCH original_restored=VERIFIED cleanup=ACCEPT terminal_state=RECOVERED"
    mutated = {
        "rewritten": suffix.replace("RESTART_LEDGER", "BOGUS"),
        "secret": suffix + " SENSITIVE",
        "unrestored": suffix.replace("original_restored=VERIFIED", "original_restored=UNVERIFIED"),
        "accepted": suffix.replace("RECOVERED", "ACCEPTED"),
    }.get(case, suffix)
    line = f"BOCA_CUTOVER_A_CANDIDATE_FAILURE {mutated} run={run} sha={sha}\n".encode()
    phase = b"BOCA_CUTOVER_A_FAILURE_PHASE phase=ACCEPT_CANDIDATE\n"
    if case == "wrong-phase":
        phase = phase.replace(b"ACCEPT_CANDIDATE", b"PREPARE_WORKER")
    if case == "run":
        line = line.replace(f"run={run} ".encode(), b"run=1 ")
    if case == "sha":
        line = line.replace(sha.encode(), b"0" * 40)
    if case == "duplicate":
        line *= 2
    if case == "nonascii":
        line = line.replace(b"MISMATCH", b"\xffPRIVATE")
    path = Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME
    _file(
        path,
        line + phase + b"BOCA_CUTOVER_A_HOST state=NO_GO receipt=RECORDED runtime=UNVERIFIED\n",
    )
    result = go.classify_cutover_ssh_failure(
        {**env, "BOCA_CUTOVER_A_SSH_RC": "124" if case == "timeout" else "3"}
    )
    assert "candidate_check_claim=" not in result and "phase_claim=UNVERIFIED" in result
    if case in ("rewritten", "secret", "unrestored", "accepted", "nonascii"):
        raw = f"BOCA_CANDIDATE_FAILURE_V1 run={run} sha={sha} {mutated}\n".encode()
        if case == "nonascii":
            raw = raw.replace(b"MISMATCH", b"\xffPRIVATE")
        with pytest.raises(ValueError):
            readback.verify(raw, run, sha)
    assert "PRIVATE" not in result and "SENSITIVE" not in result


@pytest.mark.parametrize(
    "exception,result",
    [
        (TimeoutError(), "TIMEOUT"),
        (PermissionError(), "PERMISSION_DENIED"),
        (RuntimeError(), "UNVERIFIED"),
    ],
)
def test_candidate_stage_preserves_known_cause_type_without_rendering_exception(exception, result):
    from boca_socios.host_first_deploy import PreflightError

    with (
        pytest.raises(cutover.CandidateAcceptanceFailure) as error,
        cutover.candidate_check("PANEL_START_ACK"),
    ):
        raise PreflightError("PRIVATE") from exception
    assert (error.value.check, error.value.result) == ("PANEL_START_ACK", result)
    assert "PRIVATE" not in str(error.value)


def test_primary_ssh_timeout_uses_durable_record_and_malformed_terminal_never_falls_back(
    monkeypatch, capsys
):
    from test_cutover_capture_readback import DIGEST, GO, token

    plan = _plan()
    receipt = replace(
        _accepted(),
        state="RECOVERED",
        failed_phase="ACCEPT_CANDIDATE",
        cleanup="ACCEPT",
        original_restored=True,
        irreversible_commit_started=False,
        candidate_check="PANEL_START_ACK",
        candidate_result="TIMEOUT",
    )
    rec = terminal.TerminalRecord.from_receipt(plan, receipt)
    monkeypatch.setattr(cli, "_bundle_digest", lambda: DIGEST)
    monkeypatch.setattr(terminal, "read_persisted_record", lambda _: rec)
    monkeypatch.setattr(
        readback.custody, "read_before_cleanup", lambda _: pytest.fail("unrelated worker read")
    )
    assert readback.run_host(token(plan), approved_go_binding_sha256=GO) == 0
    wire = capsys.readouterr().out
    assert "candidate_result=TIMEOUT" in readback.verify(
        wire.encode(), plan.attempt_id, plan.target_sha
    )

    def malformed(_):
        raise terminal.TerminalReceiptError("PRIVATE")

    monkeypatch.setattr(terminal, "read_persisted_record", malformed)
    assert readback.run_host(token(plan), approved_go_binding_sha256=GO) == 3
    assert capsys.readouterr() == ("", "")
