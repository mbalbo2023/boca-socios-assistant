"""One synthetic Cutover across the host, custody journal, CLI and Actions runner."""

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
from boca_socios.host_first_deploy import CutoverWorkerPhaseError
from boca_socios.worker_start_receipt import persist_before_cleanup, read_before_cleanup
from test_cutover_a_go import _actions_fixture, _file, go
from test_host_boca_cutover import FakeHost
from test_host_boca_cutover_receipt import _accepted, _plan


@pytest.mark.parametrize("compensated", [True, False])
def test_worker_observation_survives_release_boundaries_without_runtime_go(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    compensated: bool,
) -> None:
    request, env = _actions_fixture(tmp_path)
    plan = request.plan
    cid = "7" * 64
    observation = "PERMISSION_ERROR"
    compensation = "VERIFIED" if compensated else "INDETERMINATE"
    private_root = tmp_path / "fixture-home"
    private_root.mkdir(mode=0o700)
    monkeypatch.setattr(cleanup, "LEASE_DIR", private_root)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(terminal, "_account_home", lambda: private_root)
    monkeypatch.setattr(terminal, "_persistent_mount", lambda _path: None)

    class ExitedWorker(FakeHost):
        def prepare_worker(self, plan: cutover.CutoverPlan, lease: cleanup.BocaJobLease) -> str:
            persist_before_cleanup(plan, lease, cid, observation)
            self.events.append("worker-marker")
            raise CutoverWorkerPhaseError(
                "HEALTH_EXITED",
                compensation,
                exit_code=1,
                oom_killed=False,
                exit_signature="EMPTY.EXITED.EARLY_LT_5S.NOT_RUN",
                capture_result=observation,
                capture_worker_id=cid,
                capture_recorded=True,
            )

    backend = ExitedWorker(recovered=compensated)

    def save(p: cutover.CutoverPlan, receipt: cutover.CutoverReceipt, lease: cleanup.BocaJobLease):
        record = terminal.TerminalRecord.from_receipt(p, receipt)
        terminal.write_once(record, plan=p, lease=lease)

    def execute(p: cutover.CutoverPlan) -> cutover.CutoverReceipt:
        return cutover.run_cutover_a(
            p, backend=backend, terminal_preflight=terminal.prepare_destination, terminal_sink=save
        )

    bundle = request.bundle_path.read_bytes()
    go_digest = go.authorization_digest(request)
    invocation = cli.encode_invocation(
        plan,
        bundle_sha256=hashlib.sha256(bundle).hexdigest(),
        go_binding_sha256=go_digest,
        dispatch_v3=True,
    )
    with os.fdopen(os.memfd_create("boca-qa-capture-test"), "wb") as reviewed:
        reviewed.write(bundle)
        reviewed.flush()
        monkeypatch.setattr(sys, "argv", [f"/proc/self/fd/{reviewed.fileno()}"])
        rc = cli.run_cli(
            invocation, dispatch_v3=True, approved_go_binding_sha256=go_digest, execute=execute
        )
        stdout = capsys.readouterr().out
        assert readback.run_host(invocation, approved_go_binding_sha256=go_digest) == 0
        proof = capsys.readouterr().out.encode("ascii")
    assert rc == 3
    assert f"stderr_observation={observation} run={plan.attempt_id} sha={plan.target_sha}" in stdout
    assert backend.events == ["attest", "stage", "worker-marker", "recover", "finalize"]
    assert read_before_cleanup(plan) == (cid, observation)
    assert terminal.reconcile_persisted(plan) == "RECORD_PRESENT_RUNTIME_UNVERIFIED"

    filename = f"boca-cutover-a-result-{plan.attempt_id}.json"
    record = json.loads((private_root / terminal.RECEIPT_DIR_NAME / filename).read_bytes())
    assert record["version"] == "boca-cutover-a-terminal-v5"
    assert record["worker_stderr_observation"] == observation
    assert record["worker_compensation"] == compensation
    assert record["state"] == ("RECOVERED" if compensated else "NO_GO")
    assert record["irreversible_commit_started"] is False

    _file(Path(env["RUNNER_TEMP"]) / go.HOST_RECEIPT_NAME, stdout.encode("ascii"))
    report = go.classify_cutover_ssh_failure({**env, "BOCA_CUTOVER_A_SSH_RC": str(rc)})
    assert f"worker_stderr_observation_claim={observation}" in report
    assert "worker_internal_cause=UNKNOWN" in report
    assert "host=UNVERIFIED terminal=UNVERIFIED no_retry=true" in report
    verified = readback.verify(proof, env["GITHUB_RUN_ID"], env["GITHUB_SHA"])
    assert f"state=NO_GO receipt=VERIFIED worker_stderr_observation={observation}" in verified
    assert "worker_internal_cause=UNKNOWN cleanup=UNVERIFIED retry=NO_GO" in verified


def test_canonical_v1_through_v4_bytes_match_pre_capture_release() -> None:
    plan = _plan()
    failed = cutover.CutoverReceipt(
        plan.attempt_id,
        "NO_GO",
        "INDETERMINATE",
        False,
        False,
        None,
        None,
        failed_phase="PREPARE_WORKER",
        worker_primary_phase="CREATE",
        worker_compensation="VERIFIED",
    )
    exited = replace(
        failed, worker_primary_phase="HEALTH_EXITED", worker_exit_code=1, worker_oom_killed=False
    )
    signed = replace(exited, worker_exit_signature="EMPTY.EXITED.EARLY_LT_5S.NOT_RUN")
    # Fingerprints of these canonical receipts at 58b597fc (the pre-V5 release).
    for receipt, digest in (
        (_accepted(), "4d5d514e4b2cc64ce7f9af77b09c841707eb15d2969b7e8170492a1b2c94a00b"),
        (failed, "463283e21a55180785f68c69ca67d19c54e224d9af7dc7defde1948aba3f53b9"),
        (exited, "06f7eaeb73a57bf3f9614d1b409a263e9ce981ef5e7732b65b3a5c2a560d04be"),
        (signed, "be3ec049c3f07a39b641ae4fd627f4153d7e7b44bf2b4bce50b210dab227942e"),
    ):
        raw = terminal.TerminalRecord.from_receipt(plan, receipt).serialized()
        assert hashlib.sha256(raw).hexdigest() == digest
