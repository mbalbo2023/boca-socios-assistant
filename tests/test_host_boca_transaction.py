"""One protected host transaction contract, offline fake backend only."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from boca_socios import host_boca_attempt as attempt
from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_transaction as tx

ATTEMPT = "41897569929"
SOURCE = "a" * 40
IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64
BASE = b"name: boca-socios\nservices:\n  controller: {}\n"
ID = "c" * 64


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    monkeypatch.setattr(attempt, "MARKER_DIR", tmp_path)
    monkeypatch.setattr(attempt, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(cleanup, "LEASE_DIR", tmp_path)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())


def _coords() -> tx.Coordinates:
    return tx.Coordinates(
        "beta-install",
        ATTEMPT,
        IMAGE,
        SOURCE,
        hashlib.sha256(BASE).hexdigest(),
        "http://localhost:8443",
        "owner",
    )


class FakeBackend:
    def __init__(
        self,
        *,
        fail: bool = False,
        observed: tuple[str, bool] | None = (ID, True),
        raise_observe: bool = False,
    ) -> None:
        self.fail = fail
        self.observed = observed
        self.raise_observe = raise_observe
        self.events: list[str] = []

    def install(
        self, coordinates: tx.Coordinates, base: bytes, overlay: bytes, lease: cleanup.BocaJobLease
    ) -> None:
        cleanup.verify_protected_boca_job_lease(lease, coordinates.attempt_id)
        self.events.append("install")
        assert base == BASE
        assert f'boca.socios.beta-install-attempt: "{ATTEMPT}"'.encode() in overlay
        assert attempt.read_intent(ATTEMPT, lease=lease)[0].attempt_id == ATTEMPT
        if self.fail:
            raise tx.TransactionError("synthetic host phase failure")

    def observe(
        self, coordinates: tx.Coordinates, lease: cleanup.BocaJobLease
    ) -> tuple[str, bool] | None:
        cleanup.verify_protected_boca_job_lease(lease, coordinates.attempt_id)
        self.events.append("observe")
        if self.raise_observe:
            raise tx.TransactionError("host state ambiguous")
        return self.observed

    def stop_exact(
        self, coordinates: tx.Coordinates, ident: str, lease: cleanup.BocaJobLease
    ) -> None:
        cleanup.verify_protected_boca_job_lease(lease, coordinates.attempt_id)
        assert ident == ID
        self.events.append("stop_exact")

    def finish_stage(
        self,
        coordinates: tx.Coordinates,
        *,
        installed: bool,
        cleanup_status: str,
        lease: cleanup.BocaJobLease,
    ) -> None:
        cleanup.verify_protected_boca_job_lease(lease, coordinates.attempt_id)
        self.events.append("stage_clean")
        assert type(installed) is bool and cleanup_status in ("ACCEPT", "NO_GO", "INDETERMINATE")


def _fake_finalizer(monkeypatch: pytest.MonkeyPatch, events: list[str]) -> None:
    def finalize(
        result: attempt.Result, *, lease: cleanup.BocaJobLease, preserve_images: frozenset[str]
    ) -> cleanup.CleanupReceipt:
        cleanup.verify_protected_boca_job_lease(lease, result.attempt_id)
        assert attempt.read_result(result.attempt_id, lease=lease) == result
        assert not preserve_images
        events.append("finalize_" + result.outcome)
        disk = cleanup.DiskInodes(10000, 100)
        return cleanup.CleanupReceipt(
            result.outcome, result.attempt_id, "ACCEPT", disk, disk, (), (), ()
        )

    monkeypatch.setattr(tx, "finalize_attempt", finalize)


def test_success_one_lease_before_install_until_finalizer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _setup(monkeypatch, tmp_path)
    backend = FakeBackend()
    events: list[str] = []
    _fake_finalizer(monkeypatch, events)
    receipt = tx.run_transaction(_coords(), BASE, backend=backend)
    assert receipt.accepted
    assert (receipt.outcome, receipt.cleanup, receipt.controller_id) == ("SUCCESS", "ACCEPT", ID)
    assert backend.events == ["install", "observe", "stage_clean"]
    assert events == ["finalize_SUCCESS"]


def test_failure_without_created_controller_still_attempts_postflight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _setup(monkeypatch, tmp_path)
    backend = FakeBackend(fail=True, observed=None)
    events: list[str] = []
    _fake_finalizer(monkeypatch, events)
    receipt = tx.run_transaction(_coords(), BASE, backend=backend)
    assert not receipt.accepted
    assert receipt.outcome == "FAILURE" and receipt.cleanup == "ACCEPT"
    assert backend.events == ["install", "observe", "stage_clean"]
    assert events == ["finalize_FAILURE"]


def test_failed_created_running_controller_is_stopped_by_exact_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _setup(monkeypatch, tmp_path)
    backend = FakeBackend(fail=True)
    events: list[str] = []
    _fake_finalizer(monkeypatch, events)
    receipt = tx.run_transaction(_coords(), BASE, backend=backend)
    assert receipt.outcome == "FAILURE" and not receipt.accepted
    assert backend.events == ["install", "observe", "stop_exact", "stage_clean"]
    assert events == ["finalize_FAILURE"]


def test_ambiguous_host_observation_does_not_guess_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _setup(monkeypatch, tmp_path)
    backend = FakeBackend(fail=True, raise_observe=True)
    events: list[str] = []
    _fake_finalizer(monkeypatch, events)
    receipt = tx.run_transaction(_coords(), BASE, backend=backend)
    assert receipt.outcome == "FAILURE" and receipt.cleanup == "NO_GO"
    assert events == []
    assert backend.events == ["install", "observe", "stage_clean"]
    assert not (tmp_path / f"boca-postdeploy-{ATTEMPT}-result.json").exists()


@pytest.mark.parametrize("invalid", ["sha", "image", "operation", "origin"])
def test_invalid_coordinates_rejected_before_any_host_effect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invalid: str
) -> None:
    _setup(monkeypatch, tmp_path)
    coords = _coords()
    values = {**coords.__dict__}
    if invalid == "sha":
        values["compose_sha"] = "d" * 64
    elif invalid == "image":
        values["image"] = "docker.io/foreign/image:latest"
    elif invalid == "operation":
        values["operation"] = "update"
    else:
        values["origin"] = ""
    backend = FakeBackend()
    with pytest.raises(tx.TransactionError, match="coordinates"):
        tx.run_transaction(tx.Coordinates(**values), BASE, backend=backend)
    assert backend.events == []
    assert not (tmp_path / f"boca-postdeploy-{ATTEMPT}-intent.json").exists()
