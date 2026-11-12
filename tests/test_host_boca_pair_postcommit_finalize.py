"""R186 postcommit recovery: prove old journal, claim, no lease impersonation."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from boca_socios import host_boca_pair_postcommit as postcommit
from boca_socios import host_boca_pair_postcommit_finalize as recovery
from boca_socios import host_boca_pair_upgrade as upgrade
from boca_socios import host_boca_pair_upgrade_cli as upgrade_cli
from boca_socios import host_cutover_stage as stage


@pytest.fixture
def incident_journal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "boca"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(stage, "ROOT", root)
    monkeypatch.setattr(stage, "UID", os.geteuid())
    monkeypatch.setattr(stage, "GID", os.getegid())
    intent = {
        "attempt": postcommit.FAILED_ATTEMPT,
        "old_controller": "a" * 64,
        "old_worker": "b" * 64,
        "old_source": "03df9a14bdd78cf768386a865876fed9d5656911",
        "new_source": postcommit.SOURCE_SHA,
        "release": "43215180354",
    }
    raw = json.dumps(intent, sort_keys=True, separators=(",", ":")).encode("ascii")
    terminal = upgrade_cli.encode_upgrade(
        upgrade.PairUpgradeReceipt(
            attempt_id=postcommit.FAILED_ATTEMPT,
            state="NO_GO",
            cleanup="INDETERMINATE",
            old_restored=False,
            commit_started=True,
            controller_id=postcommit.CONTROLLER_ID,
            worker_id=postcommit.WORKER_ID,
            failed_phase="RETIRE_OLD",
        )
    )
    for suffix, data in (
        ("intent", raw),
        ("commit", hashlib.sha256(raw).hexdigest().encode("ascii")),
        ("terminal", terminal),
    ):
        target = root / f".boca-pair-upgrade-{postcommit.FAILED_ATTEMPT}.{suffix}"
        target.write_bytes(data)
        target.chmod(0o600)
    return root


def test_original_incident_journal_is_verified_without_mutation(incident_journal: Path) -> None:
    first = recovery._journal()
    second = recovery._journal()
    assert first == second
    assert first.old_controller_id == "a" * 64
    assert first.old_worker_id == "b" * 64
    assert (
        first.digest
        == hashlib.sha256(
            (
                incident_journal / f".boca-pair-upgrade-{postcommit.FAILED_ATTEMPT}.intent"
            ).read_bytes()
        ).hexdigest()
    )


@pytest.mark.parametrize("tamper", ["missing", "wrong_hash", "wrong_source", "wrong_terminal"])
def test_bad_original_journal_fails_before_any_claim(incident_journal: Path, tamper: str) -> None:
    root = incident_journal
    prefix = f".boca-pair-upgrade-{postcommit.FAILED_ATTEMPT}."
    if tamper == "missing":
        (root / (prefix + "commit")).unlink()
    elif tamper == "wrong_hash":
        (root / (prefix + "commit")).write_bytes(b"0" * 64)
    elif tamper == "wrong_source":
        target = root / (prefix + "intent")
        target.write_bytes(target.read_bytes().replace(postcommit.SOURCE_SHA.encode(), b"f" * 40))
    else:
        target = root / (prefix + "terminal")
        target.write_bytes(target.read_bytes().replace(b"RETIRE_OLD", b"ATTEST"))
    with pytest.raises(recovery.FinalizeNoGo):
        recovery._journal()
    assert not any("postcommit-finalize" in name for name in os.listdir(root))


def test_postcommit_receipt_is_canonical_and_bounded() -> None:
    run = "43299999123"
    raw = recovery.encode(run, "ACCEPTED")
    assert recovery.verify(raw, run) == raw
    with pytest.raises(recovery.FinalizeNoGo):
        recovery.verify(raw.replace(b'"state":"ACCEPTED"', b'"state":"NO_GO"'), run)
    with pytest.raises(recovery.FinalizeNoGo):
        recovery.verify(raw, postcommit.FAILED_ATTEMPT)


def test_one_shot_claim_refuses_replay_before_cleanup(incident_journal: Path) -> None:
    first = recovery._journal()
    recovery._claim("43299999123", first)
    claim = incident_journal / f".boca-postcommit-finalize-{postcommit.FAILED_ATTEMPT}.claim"
    assert claim.is_file()
    contents = claim.read_bytes()
    with pytest.raises(recovery.FinalizeNoGo):
        recovery._claim("43299999124", first)
    assert claim.read_bytes() == contents


def test_symlinked_journal_entry_is_refused(incident_journal: Path) -> None:
    target = incident_journal / f".boca-pair-upgrade-{postcommit.FAILED_ATTEMPT}.intent"
    copy = incident_journal / "copy"
    copy.write_bytes(target.read_bytes())
    copy.chmod(0o600)
    target.unlink()
    target.symlink_to(copy)
    with pytest.raises(recovery.FinalizeNoGo):
        recovery._journal()


@pytest.fixture
def mock_fresh_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextmanager
    def held(_run: str) -> Iterator[object]:
        yield object()

    monkeypatch.setattr(recovery.cleanup, "protected_boca_job_lease", held)
    monkeypatch.setattr(recovery.cleanup, "verify_protected_boca_job_lease", lambda *_: None)


def test_preflight_failure_does_not_claim_or_delete(
    incident_journal: Path, mock_fresh_lease: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    def fail(_run: str) -> Any:
        events.append("preflight")
        raise recovery.FinalizeNoGo("test unverified")

    monkeypatch.setattr(recovery, "_preflight", fail)
    monkeypatch.setattr(
        recovery.replace,
        "commit_binding_postcommit",
        lambda *_: events.append("delete"),
    )
    with pytest.raises(recovery.FinalizeNoGo):
        recovery.finalize("43299999123")
    assert events == ["preflight"]
    assert not any("postcommit-finalize" in name for name in os.listdir(incident_journal))


def test_claim_is_durable_before_cleanup_and_receipt_is_one_shot(
    incident_journal: Path, mock_fresh_lease: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = "43299999123"
    journal = recovery._journal()
    evidence = recovery._Evidence(journal, None, None, None)  # type: ignore[arg-type]
    monkeypatch.setattr(recovery, "_preflight", lambda _: evidence)
    monkeypatch.setattr(recovery, "_postflight", lambda *_: None)
    events: list[str] = []

    def retire(*_: object) -> None:
        assert (
            incident_journal / f".boca-postcommit-finalize-{postcommit.FAILED_ATTEMPT}.claim"
        ).exists()
        events.append("retire")

    monkeypatch.setattr(recovery.replace, "commit_binding_postcommit", retire)
    assert recovery.finalize(run) == recovery.encode(run, "ACCEPTED")
    assert events == ["retire"]
    assert (
        incident_journal / f".boca-postcommit-finalize-{postcommit.FAILED_ATTEMPT}.terminal"
    ).read_bytes() == recovery.encode(run, "ACCEPTED")
    with pytest.raises(recovery.FinalizeNoGo):
        recovery.finalize("43299999124")
    assert events == ["retire"]


def test_postclaim_interruption_remains_indeterminate_and_never_retries(
    incident_journal: Path, mock_fresh_lease: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = "43299999123"
    monkeypatch.setattr(
        recovery, "_preflight", lambda _: recovery._Evidence(recovery._journal(), None, None, None)
    )
    events: list[str] = []

    def interrupted(*_: object) -> None:
        events.append("retire")
        raise OSError("simulated unlink failure")

    monkeypatch.setattr(recovery.replace, "commit_binding_postcommit", interrupted)
    assert recovery.finalize(run) == recovery.encode(run, "INDETERMINATE")
    assert events == ["retire"]
    assert (
        incident_journal / f".boca-postcommit-finalize-{postcommit.FAILED_ATTEMPT}.terminal"
    ).read_bytes() == recovery.encode(run, "INDETERMINATE")
    with pytest.raises(recovery.FinalizeNoGo):
        recovery.finalize(run)
    assert events == ["retire"]
