"""Offline successor journal: genuine same-lease witness, no live Docker or Actions."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_repeatable_journal as repeatable
from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios import host_cutover_stage as stage

ATTEMPT = "44000000003"
RUN = "44000000001"
RELEASE = "44000000002"
CONTROLLER = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "1" * 64
WORKER = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "2" * 64


def plan() -> transaction.PairCoordinates:
    return transaction.PairCoordinates(
        ATTEMPT,
        RUN,
        "43217075287",
        "b" * 40,
        "c" * 64,
        "d" * 64,
        "sha256:" + "e" * 64,
        "sha256:" + "f" * 64,
        "a" * 40,
        RELEASE,
        CONTROLLER,
        WORKER,
    )


def release() -> adapters.ReleaseEvidence:
    return adapters.ReleaseEvidence(
        "a" * 40,
        RELEASE,
        CONTROLLER,
        WORKER,
        "6" * 64,
        "7" * 64,
    )


def pins() -> adapters.ResourcePins:
    return adapters.ResourcePins(
        "42806447101",
        "3" * 64,
        "43217075287",
        "4" * 64,
        "43217075287",
        "5" * 64,
    )


def observed() -> repeatable.FreshPairWitness:
    expected = plan()
    return repeatable.FreshPairWitness(
        observation_run_id=expected.observation_run_id,
        old_attempt_id=expected.old_attempt_id,
        old_source_sha=expected.old_source_sha,
        controller_id=expected.old_controller_id,
        worker_id=expected.old_worker_id,
        controller_image_id=expected.old_controller_image_id,
        worker_image_id=expected.old_worker_image_id,
        retained=pins(),
        control_inode_sha256="8" * 64,
    )


@pytest.fixture(autouse=True)
def folders(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lease_dir = tmp_path / "lease"
    lease_dir.mkdir(mode=0o700)
    monkeypatch.setattr(cleanup, "LEASE_DIR", lease_dir)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    root = tmp_path / "stage"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(stage, "ROOT", root)
    monkeypatch.setattr(stage, "UID", os.geteuid())
    monkeypatch.setattr(stage, "GID", os.getegid())


def journal(*, capture: Any = None, evidence: Any = None) -> repeatable.SuccessorPairJournal:
    return repeatable.SuccessorPairJournal(
        release() if evidence is None else evidence,
        pins(),
        (lambda _plan, _lease: observed()) if capture is None else capture,
    )


def test_same_lease_two_observations_create_immutable_evidence_intent_and_terminal() -> None:
    found: list[Any] = []

    def capture(current: transaction.PairCoordinates, lease: cleanup.BocaJobLease) -> Any:
        cleanup.verify_protected_boca_job_lease(lease, current.attempt_id)
        found.append((lease, current))
        return observed()

    record = journal(capture=capture)
    current = plan()
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        record.intent(current, lease)
        record.commit(current, lease)
        receipt = transaction.PairUpgradeReceipt(
            ATTEMPT, "NO_GO", "INDETERMINATE", False, True, None, None, "RETIRE_OLD"
        )
        record.terminal(current, receipt, lease)

    assert len(found) == 2
    assert found == [(found[0][0], current), (found[0][0], current)]
    root = stage.ROOT
    prefix = f".boca-pair-upgrade-{ATTEMPT}."
    payload = (root / (prefix + "evidence")).read_bytes()
    intent = (root / (prefix + "intent")).read_bytes()
    contents = json.loads(payload)
    assert contents["witness"]["retained"]["ipc_creator_attempt"] == "42806447101"
    assert contents["release"]["paired_manifest_sha256"] == "7" * 64
    assert contents["plan"]["old_source_sha"] == "b" * 40
    assert json.loads(intent)["evidence_sha256"] == hashlib.sha256(payload).hexdigest()
    assert (root / (prefix + "commit")).read_text() == hashlib.sha256(intent).hexdigest()
    assert (root / (prefix + "terminal")).read_bytes().startswith(b"BOCA_PAIR_UPGRADE ")
    assert all(
        (root / (prefix + name)).stat().st_mode & 0o777 == 0o600
        for name in ("evidence", "intent", "commit", "terminal")
    )
    with pytest.raises(stage.StageError):
        with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
            journal().intent(current, lease)


def test_active_intent_rechecked_from_disk_before_any_cleanup_effect() -> None:
    current = plan()
    record = journal()
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        with pytest.raises(repeatable.SuccessorJournalNoGo):
            record.attest_active_intent(current, lease)
        record.intent(current, lease)
        record.attest_active_intent(current, lease)
        with pytest.raises(repeatable.SuccessorJournalNoGo):
            journal().attest_active_intent(current, lease)
        with pytest.raises(repeatable.SuccessorJournalNoGo):
            record.attest_active_intent(replace(current, old_controller_id="9" * 64), lease)
        name = stage.ROOT / f".boca-pair-upgrade-{ATTEMPT}.intent"
        name.write_bytes(b"corrupted-intent")
        with pytest.raises(repeatable.SuccessorJournalNoGo):
            record.attest_active_intent(current, lease)


@pytest.mark.parametrize(
    "bad",
    ("source", "run", "controller", "worker", "image", "creator", "inode", "control", "release"),
)
def test_drift_rejected_prior_to_any_journal_effect(bad: str) -> None:
    witness = observed()
    current = plan()
    release_evidence = release()
    if bad == "source":
        witness = replace(witness, old_source_sha="0" * 40)
    elif bad == "run":
        witness = replace(witness, observation_run_id="44000000009")
    elif bad == "controller":
        witness = replace(witness, controller_id="9" * 64)
    elif bad == "worker":
        witness = replace(witness, worker_id="9" * 64)
    elif bad == "image":
        witness = replace(witness, controller_image_id="sha256:" + "9" * 64)
    elif bad == "creator":
        witness = replace(witness, retained=replace(pins(), ipc_creator_attempt="44000000009"))
    elif bad == "inode":
        witness = replace(witness, retained=replace(pins(), site_inode_sha256="9" * 64))
    elif bad == "control":
        witness = replace(witness, control_inode_sha256="invalid")
    elif bad == "release":
        release_evidence = replace(release_evidence, worker_ref=CONTROLLER)
    record = journal(capture=lambda *_: witness, evidence=release_evidence)
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        with pytest.raises(repeatable.SuccessorJournalNoGo):
            record.intent(current, lease)
    assert list(stage.ROOT.iterdir()) == []


def test_unequal_sequential_witnesses_fail_without_file_writes() -> None:
    items = [observed(), replace(observed(), control_inode_sha256="9" * 64)]
    record = journal(capture=lambda *_: items.pop(0))
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        with pytest.raises(repeatable.SuccessorJournalNoGo):
            record.intent(plan(), lease)
    assert list(stage.ROOT.iterdir()) == []


def test_stale_lease_and_wrong_plan_do_not_write() -> None:
    record = journal()
    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        with pytest.raises(repeatable.SuccessorJournalNoGo):
            record.intent(replace(plan(), attempt_id="44000000009"), lease)
    assert list(stage.ROOT.iterdir()) == []


def test_failed_capture_never_creates_intent() -> None:
    def crash(*_args: object) -> object:
        raise OSError("bad transport secrets must not escape")

    with cleanup.protected_boca_job_lease(ATTEMPT) as lease:
        with pytest.raises(repeatable.SuccessorJournalNoGo, match="Boca successor evidence"):
            journal(capture=crash).intent(plan(), lease)
    assert list(stage.ROOT.iterdir()) == []
