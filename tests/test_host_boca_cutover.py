"""Fail-closed host-free cutover-A state machine, never Docker or BLACKBOX."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cutover as cutover


def _plan() -> cutover.CutoverPlan:
    return cutover.CutoverPlan(
        attempt_id="41949228860",
        legacy_id="a" * 64,
        legacy_sha="b" * 40,
        legacy_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "c" * 64,
        legacy_compose_sha="d" * 64,
        target_sha="e" * 40,
        target_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "f" * 64,
        browser_image="ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "1" * 64,
        target_compose_sha="2" * 64,
        overlay_sha="3" * 64,
        seccomp_sha="4" * 64,
        owner_subject="owner",
    )


class FakeHost:
    def __init__(
        self, *, failure: str = "", recovered: bool = True, cleanup_result: str = "ACCEPT"
    ):
        self.failure = failure
        self.recovered = recovered
        self.cleanup_result = cleanup_result
        self.events: list[str] = []

    def _phase(self, phase: str, plan: cutover.CutoverPlan, lease: cleanup.BocaJobLease) -> None:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        self.events.append(phase)
        if self.failure == phase:
            raise cutover.CutoverError("fake injected host failure")
        if self.failure == f"interrupt_{phase}":
            raise KeyboardInterrupt()

    def attest_original(self, plan: cutover.CutoverPlan, lease: cleanup.BocaJobLease) -> None:
        self._phase("attest", plan, lease)

    def stage(self, plan: cutover.CutoverPlan, lease: cleanup.BocaJobLease) -> None:
        self._phase("stage", plan, lease)

    def prepare_worker(self, plan: cutover.CutoverPlan, lease: cleanup.BocaJobLease) -> str:
        self._phase("worker", plan, lease)
        return "5" * 64 if self.failure != "bad_worker" else plan.legacy_id

    def park_original(self, plan: cutover.CutoverPlan, lease: cleanup.BocaJobLease) -> None:
        self._phase("park", plan, lease)

    def bootstrap_owner_session(
        self, plan: cutover.CutoverPlan, lease: cleanup.BocaJobLease
    ) -> None:
        self._phase("bootstrap", plan, lease)
        # This is the only schema-related callback. A fake never opens
        # the legacy database, nor writes a new file in tests.

    def activate_candidate(
        self, plan: cutover.CutoverPlan, worker_id: str, lease: cleanup.BocaJobLease
    ) -> str:
        assert worker_id == "5" * 64
        self._phase("activate", plan, lease)
        return "6" * 64 if self.failure != "bad_candidate" else worker_id

    def accept_candidate(
        self,
        plan: cutover.CutoverPlan,
        candidate_id: str,
        worker_id: str,
        lease: cleanup.BocaJobLease,
    ) -> None:
        assert candidate_id == "6" * 64 and worker_id == "5" * 64
        self._phase("accept", plan, lease)

    def retire_original(
        self,
        plan: cutover.CutoverPlan,
        candidate_id: str,
        worker_id: str,
        lease: cleanup.BocaJobLease,
    ) -> None:
        assert candidate_id == "6" * 64 and worker_id == "5" * 64
        self._phase("retire", plan, lease)

    def recover_original(self, plan: cutover.CutoverPlan, lease: cleanup.BocaJobLease) -> bool:
        self._phase("recover", plan, lease)
        return self.recovered

    def finalize(
        self,
        plan: cutover.CutoverPlan,
        *,
        commit_started: bool,
        candidate_id: str | None,
        worker_id: str | None,
        lease: cleanup.BocaJobLease,
    ) -> cutover.CleanupStatus:
        self._phase("finalize", plan, lease)
        if commit_started:
            assert candidate_id == "6" * 64 and worker_id == "5" * 64
        return self.cleanup_result  # type: ignore[return-value]


@pytest.fixture(autouse=True)
def _fake_lease(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    monkeypatch.setattr(cleanup, "LEASE_DIR", tmp_path)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())


def test_cutover_single_lease_order_and_accepted_only_after_cleanup() -> None:
    host = FakeHost()
    result = cutover.run_cutover_a(_plan(), backend=host)
    assert result.accepted and result.state == "ACCEPTED"
    assert result.failed_phase == "NONE"
    assert result.irreversible_commit_started and not result.original_restored
    assert host.events == [
        "attest",
        "stage",
        "worker",
        "park",
        "bootstrap",
        "activate",
        "accept",
        "retire",
        "finalize",
    ]


@pytest.mark.parametrize(
    "failure",
    ["stage", "worker", "bad_worker", "park", "bootstrap", "activate", "bad_candidate", "accept"],
)
def test_precommit_failure_recovers_before_selective_postflight(failure: str) -> None:
    host = FakeHost(failure=failure)
    receipt = cutover.run_cutover_a(_plan(), backend=host)
    assert receipt.state == "RECOVERED" and not receipt.accepted
    assert not receipt.irreversible_commit_started
    assert (
        receipt.failed_phase
        == {
            "stage": "STAGE",
            "worker": "PREPARE_WORKER",
            "bad_worker": "PREPARE_WORKER",
            "park": "PARK_ORIGINAL",
            "bootstrap": "BOOTSTRAP_SESSION",
            "activate": "ACTIVATE_CANDIDATE",
            "bad_candidate": "ACTIVATE_CANDIDATE",
            "accept": "ACCEPT_CANDIDATE",
        }[failure]
    )
    assert host.events[-2:] == ["recover", "finalize"]
    if failure == "bootstrap":
        assert host.events.index("park") < host.events.index("bootstrap")


def test_worker_primary_and_compensation_are_preserved_without_private_exception() -> None:
    from boca_socios.host_first_deploy import CutoverWorkerPhaseError

    class FailedWorker(FakeHost):
        def prepare_worker(self, plan: cutover.CutoverPlan, lease: cleanup.BocaJobLease) -> str:
            self.events.append("worker-failed")
            raise CutoverWorkerPhaseError("CREATE", "INDETERMINATE")

    receipt = cutover.run_cutover_a(_plan(), backend=FailedWorker(recovered=False))
    assert receipt.failed_phase == "PREPARE_WORKER"
    assert receipt.worker_primary_phase == "CREATE"
    assert receipt.worker_compensation == "INDETERMINATE"
    assert receipt.state == "NO_GO" and not receipt.accepted


def test_ambiguous_recovery_never_claims_legacy_restored() -> None:
    host = FakeHost(failure="activate", recovered=False)
    receipt = cutover.run_cutover_a(_plan(), backend=host)
    assert receipt.state == "NO_GO" and not receipt.original_restored
    assert host.events[-2:] == ["recover", "finalize"]


def test_irreversible_retirement_receipt_loss_never_restarts_original() -> None:
    host = FakeHost(failure="retire")
    receipt = cutover.run_cutover_a(_plan(), backend=host)
    assert receipt.state == "NO_GO" and receipt.irreversible_commit_started
    assert receipt.failed_phase == "RETIRE_ORIGINAL"
    assert "recover" not in host.events
    assert host.events[-1] == "finalize"


@pytest.mark.parametrize("interrupted", ["interrupt_activate", "interrupt_retire"])
def test_process_interruption_attempts_finalizer_without_trusted_receipt(interrupted: str) -> None:
    host = FakeHost(failure=interrupted)
    with pytest.raises(KeyboardInterrupt):
        cutover.run_cutover_a(_plan(), backend=host)
    assert host.events[-1] == "finalize"
    if interrupted == "interrupt_activate":
        assert host.events[-2] == "recover"
    else:
        # Once retirement *started*, no blind resurrection of the old ID.
        assert "recover" not in host.events


@pytest.mark.parametrize("cleanup", ["NO_GO", "INDETERMINATE", "UNTRUSTED"])
def test_successful_candidate_requires_positive_cleanup(cleanup: str) -> None:
    host = FakeHost(cleanup_result=cleanup)
    receipt = cutover.run_cutover_a(_plan(), backend=host)
    assert not receipt.accepted and receipt.state == "NO_GO"
    assert receipt.failed_phase == "FINALIZE"


def test_postflight_failure_is_no_go_without_restart() -> None:
    host = FakeHost(failure="finalize")
    receipt = cutover.run_cutover_a(_plan(), backend=host)
    assert receipt.state == "NO_GO" and receipt.cleanup == "NO_GO"
    assert receipt.failed_phase == "FINALIZE"
    assert "recover" not in host.events


def test_attestation_failure_has_no_staging_recovery_or_cleanup() -> None:
    host = FakeHost(failure="attest")
    receipt = cutover.run_cutover_a(_plan(), backend=host)
    assert receipt.state == "NO_GO"
    assert receipt.failed_phase == "ATTEST_ORIGINAL"
    assert host.events == ["attest"]


@pytest.mark.parametrize(
    "bad",
    [
        "attempt_id",
        "legacy_id",
        "legacy_sha",
        "target_sha",
        "target_image",
        "origin",
        "owner_subject",
        "overlay_sha",
    ],
)
def test_invalid_coordinates_cause_zero_host_calls(bad: str) -> None:
    plan = _plan()
    changed = {**plan.__dict__}
    changed[bad] = "not allowed!"
    host = FakeHost()
    with pytest.raises(cutover.CutoverError, match="coordinates"):
        cutover.run_cutover_a(cutover.CutoverPlan(**changed), backend=host)
    assert host.events == []


def test_cutover_dispatch_v3_preserves_exact_binding_and_terminal_guard() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text(encoding="utf-8")
    assert "cutover-a-observe" in workflow
    assert "cutover-a-apply" in workflow
    assert (
        "BOCA_CUTOVER_A_GO_BINDING_SHA256: ${{ vars.BOCA_CUTOVER_A_GO_BINDING_SHA256 }}"
        not in workflow
    )
    assert (
        'check_boca_deploy_dispatch.py "$RUNNER_TEMP/boca-dispatch-v3" --write-invocation'
        in workflow
    )
    assert "python scripts/check_cutover_a_go.py --from-actions" not in workflow
    assert "check_legacy_go_dispatch.py apply" in workflow
    assert "BOCA_CUTOVER_A_DISPATCH_BINDING_SHA256" in workflow
    assert "Fail closed on absent or ambiguous Cutover A host terminal receipt" in workflow
    # PR-only pytest/build/if:always cannot become a live apply switch.
    assert "BOCA_CUTOVER_A_PR_VERIFY state=SOURCE_ONLY" in workflow
    assert "boca-cutover-a-host.receipt" in workflow
    assert "run_cutover_a" not in workflow


def test_prepared_go_consumes_under_same_lease_after_attestation_before_stage() -> None:
    host = FakeHost()
    consume_events: list[str] = []

    def consume(
        plan: cutover.CutoverPlan, prepare_run_id: str, lease: cleanup.BocaJobLease
    ) -> None:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        assert prepare_run_id == "50000000001"
        assert host.events == ["attest"]
        consume_events.append("prepared-once")

    accepted = cutover.run_cutover_a(
        _plan(),
        backend=host,
        prepare_run_id="50000000001",
        prepared_go_consumer=consume,
    )
    assert accepted.accepted
    assert consume_events == ["prepared-once"]
    assert host.events[:2] == ["attest", "stage"]


def test_prepared_go_missing_or_failing_consumer_never_stages() -> None:
    host = FakeHost()
    with pytest.raises(cutover.CutoverError, match="consumer"):
        cutover.run_cutover_a(_plan(), backend=host, prepare_run_id="50000000001")
    assert host.events == []
    failed = cutover.run_cutover_a(
        _plan(),
        backend=host,
        prepare_run_id="50000000001",
        prepared_go_consumer=lambda *_args: (_ for _ in ()).throw(
            cutover.CutoverError("prepared GO marker ambiguous")
        ),
    )
    assert not failed.accepted
    assert failed.failed_phase == "CONSUME_PREPARE"
    assert host.events == ["attest"]
