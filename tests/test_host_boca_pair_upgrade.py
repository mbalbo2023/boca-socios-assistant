"""R179 Boca dual replacement sequencing: no Docker, systemd, network or SQLite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_upgrade as pair


@pytest.fixture(autouse=True)
def _local_lease(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    monkeypatch.setattr(cleanup, "LEASE_DIR", tmp_path)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())


def _coordinates() -> pair.PairCoordinates:
    return pair.PairCoordinates(
        attempt_id="43080012345",
        observation_run_id="43066120206",
        old_attempt_id="42806447101",
        old_source_sha="03df9a14bdd78cf768386a865876fed9d5656911",
        old_controller_id="c" * 64,
        old_worker_id="d" * 64,
        old_controller_image_id="sha256:" + "e" * 64,
        old_worker_image_id="sha256:" + "f" * 64,
        new_source_sha="a" * 40,
        release_run_id="43090012345",
        controller_ref="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "1" * 64,
        worker_ref="ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "2" * 64,
    )


class Backend:
    requires_persistent_receipt = True

    def __init__(self, failure: str = "", *, restore: bool = True, cleanup: str = "ACCEPT"):
        self.events: list[str] = []
        self.failure = failure
        self.restore = restore
        self.cleanup = cleanup

    def _call(self, name: str, plan: pair.PairCoordinates, lease: cleanup.BocaJobLease) -> None:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        self.events.append(name)
        if self.failure == name:
            raise pair.PairUpgradeError("injected failure")
        if self.failure == "interrupt-" + name:
            raise KeyboardInterrupt()

    def attest(self, plan: pair.PairCoordinates, lease: cleanup.BocaJobLease) -> None:
        self._call("attest", plan, lease)

    def stage(self, plan: pair.PairCoordinates, lease: cleanup.BocaJobLease) -> None:
        self._call("stage", plan, lease)

    def park(self, plan: pair.PairCoordinates, lease: cleanup.BocaJobLease) -> None:
        self._call("park", plan, lease)

    def create_worker(self, plan: pair.PairCoordinates, lease: cleanup.BocaJobLease) -> str:
        self._call("worker", plan, lease)
        return plan.old_worker_id if self.failure == "duplicate-worker" else "3" * 64

    def create_controller(
        self, plan: pair.PairCoordinates, worker_id: str, lease: cleanup.BocaJobLease
    ) -> str:
        if worker_id != "3" * 64:
            raise pair.PairUpgradeError("worker drift")
        self._call("controller", plan, lease)
        return worker_id if self.failure == "duplicate-controller" else "4" * 64

    def accept(
        self,
        plan: pair.PairCoordinates,
        controller_id: str,
        worker_id: str,
        lease: cleanup.BocaJobLease,
    ) -> None:
        self._call("accept", plan, lease)

    def replace_binding(
        self,
        plan: pair.PairCoordinates,
        controller_id: str,
        worker_id: str,
        lease: cleanup.BocaJobLease,
    ) -> None:
        self._call("binding", plan, lease)

    def retire_old(
        self,
        plan: pair.PairCoordinates,
        controller_id: str,
        worker_id: str,
        lease: cleanup.BocaJobLease,
    ) -> None:
        self._call("retire", plan, lease)

    def restore_old(self, plan: pair.PairCoordinates, lease: cleanup.BocaJobLease) -> bool:
        self._call("restore", plan, lease)
        return self.restore

    def finalize(
        self,
        plan: pair.PairCoordinates,
        *,
        commit_started: bool,
        controller_id: str | None,
        worker_id: str | None,
        lease: cleanup.BocaJobLease,
    ) -> str:
        self._call("finalize", plan, lease)
        return self.cleanup


def _transaction(
    host: Backend,
    *,
    failure_at: str = "",
) -> tuple[pair.PairUpgradeReceipt, list[str]]:
    events: list[str] = []

    def preflight(plan: pair.PairCoordinates, lease: cleanup.BocaJobLease) -> None:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        events.append("intent")
        if failure_at == "intent":
            raise OSError("injected")

    def commit(plan: pair.PairCoordinates, lease: cleanup.BocaJobLease) -> None:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        events.append("commit")
        if failure_at == "commit":
            raise OSError("uncertain fsync")

    def terminal(
        plan: pair.PairCoordinates, result: pair.PairUpgradeReceipt, lease: cleanup.BocaJobLease
    ) -> None:
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        events.append("terminal")
        if failure_at == "terminal":
            raise OSError("injected terminal")

    return (
        pair.run_pair_upgrade(
            _coordinates(),
            backend=host,
            terminal_preflight=preflight,
            commit_marker=commit,
            terminal_sink=terminal,
        ),
        events,
    )


def test_dual_pair_accepts_only_after_durable_commit_and_selective_postflight() -> None:
    host = Backend()
    receipt, events = _transaction(host)
    assert receipt.state == "ACCEPTED"
    assert receipt.accepted
    assert receipt.commit_started
    assert receipt.controller_id == "4" * 64
    assert receipt.worker_id == "3" * 64
    assert events == ["intent", "commit", "terminal"]
    assert host.events == [
        "attest",
        "stage",
        "park",
        "worker",
        "controller",
        "accept",
        "binding",
        "retire",
        "finalize",
    ]


@pytest.mark.parametrize(
    "failure",
    [
        "stage",
        "park",
        "worker",
        "duplicate-worker",
        "controller",
        "duplicate-controller",
        "accept",
        "binding",
    ],
)
def test_every_precommit_failure_restores_old_pair_and_binding(failure: str) -> None:
    host = Backend(failure=failure)
    receipt, events = _transaction(host)
    assert receipt.state == "RECOVERED"
    assert receipt.old_restored and not receipt.commit_started
    assert not receipt.accepted
    assert host.events[-2:] == ["restore", "finalize"]
    assert "commit" not in events


def test_first_attestation_failure_has_no_rollback_and_no_writes() -> None:
    host = Backend(failure="attest")
    result, events = _transaction(host)
    assert result.state == "NO_GO"
    assert not result.old_restored
    assert host.events == ["attest", "finalize"]
    assert events == ["intent", "terminal"]


def test_durable_commit_failure_is_indeterminate_and_never_revives_old() -> None:
    host = Backend()
    result, events = _transaction(host, failure_at="commit")
    assert result.state == "NO_GO"
    assert result.commit_started and not result.old_restored
    assert host.events[-1] == "finalize"
    assert "restore" not in host.events and "retire" not in host.events
    assert events == ["intent", "commit", "terminal"]


@pytest.mark.parametrize("failure", ["retire", "finalize", "interrupt-retire"])
def test_after_commit_failure_never_restarts_original(failure: str) -> None:
    host = Backend(failure=failure)
    result, _ = _transaction(host)
    assert result.state == "NO_GO" and result.commit_started
    assert "restore" not in host.events


def test_uncertain_precommit_restoration_stays_no_go() -> None:
    host = Backend(failure="binding", restore=False)
    result, _ = _transaction(host)
    assert result.state == "NO_GO"
    assert not result.old_restored and not result.commit_started


def test_finalizer_rejects_false_accept() -> None:
    host = Backend(cleanup="NO_GO")
    result, _ = _transaction(host)
    assert result.state == "NO_GO" and result.commit_started and not result.accepted


@pytest.mark.parametrize("case", ["intent", "terminal"])
def test_persistent_receipt_failures_are_fail_closed(case: str) -> None:
    host = Backend()
    if case == "intent":
        with pytest.raises(cleanup.CleanupError):
            _transaction(host, failure_at=case)
        assert host.events == []
    else:
        with pytest.raises(cleanup.CleanupError):
            _transaction(host, failure_at=case)


def test_unauthenticated_effectful_backend_not_invoked() -> None:
    host = Backend()
    with pytest.raises(pair.PairUpgradeError):
        pair.run_pair_upgrade(_coordinates(), backend=host)
    assert not host.events


def test_bad_coordinates_have_no_lease_or_backend_effects() -> None:
    from dataclasses import replace

    host = Backend()
    bad = replace(_coordinates(), old_controller_id=_coordinates().old_worker_id)
    with pytest.raises(pair.PairUpgradeError):
        pair.run_pair_upgrade(bad, backend=host)
    assert host.events == []
