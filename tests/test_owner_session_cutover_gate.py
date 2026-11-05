"""Source-only pre-cutover gates. No legacy image, Docker or installed DB touched."""

from __future__ import annotations

import base64
import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from boca_socios.config import Settings
from boca_socios.panel import owner_session_cutover_gate as gate
from boca_socios.panel.owner_session_host_attestor import DockerStoppedControllerEvidence
from boca_socios.panel.owner_session_upgrade import (
    OwnerSessionUpgradeUnavailable,
    UpgradeResult,
)
from boca_socios.runtime import initialize_beta
from boca_socios.storage.database import Database

_INSTALLED_SHA = "cabce9f1e452e63ded115f447559a358dc0f4d1b"
_FUTURE_SHA = "f" * 40  # synthetic only, NOT a claimed legacy image.
_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "c" * 64


@dataclass(frozen=True, slots=True)
class _SyntheticVerifier(gate.LegacyResumeVerifier):
    """Fake contract exerciser; never host authority or recovery evidence."""

    events: list[str] = field(default_factory=list)
    fail: bool = False

    @contextmanager
    def hold_live_legacy_resume_proof(self) -> Iterator[None]:
        self.events.append("proof-enter")
        if self.fail:
            raise OwnerSessionUpgradeUnavailable("synthetic legacy resume verification failed")
        try:
            yield
        finally:
            self.events.append("proof-exit")


def _evidence(legacy_sha: str, *, fd: int | None = 8) -> DockerStoppedControllerEvidence:
    return DockerStoppedControllerEvidence(
        original_id="a" * 64,
        attempt_id="1234",
        legacy_sha=legacy_sha,
        legacy_image=_IMAGE,
        borrowed_lease_fd=fd,
    )


def _verifier(evidence: DockerStoppedControllerEvidence) -> _SyntheticVerifier:
    return _SyntheticVerifier(
        original_id=evidence.original_id,
        attempt_id=evidence.attempt_id,
        legacy_sha=evidence.legacy_sha,
        legacy_image=evidence.legacy_image,
        owner_schema_0008_sha256=gate.owner_schema_0008_checksum(),
    )


def _installed_synthetic_db(tmp_path: Path) -> tuple[Path, Path]:
    path, key = tmp_path / "legacy.sqlite3", tmp_path / "synthetic.key"
    key.write_bytes(base64.b64encode(b"k" * 32))
    key.chmod(0o400)
    initialize_beta(Settings("staging", "simulation", path, key))
    Database(path).create_member("sentinel", "synthetic@example.invalid", "consented")
    return path, key


def _snapshot(path: Path) -> tuple[object, ...]:
    with sqlite3.connect(path) as connection:
        return (
            tuple(
                connection.execute(
                    "SELECT version,checksum FROM schema_migrations ORDER BY version"
                )
            ),
            tuple(connection.execute("SELECT * FROM members")),
            tuple(connection.execute("SELECT * FROM credentials")),
            tuple(connection.execute("SELECT * FROM events")),
        )


def test_installed_cabce_legacy_is_hard_no_go_even_with_forged_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, key = _installed_synthetic_db(tmp_path)
    db_before, key_before, inode = _snapshot(db), key.read_bytes(), db.stat().st_ino
    evidence = _evidence(_INSTALLED_SHA)
    verifier = _verifier(evidence)
    monkeypatch.setattr(
        gate,
        "upgrade_existing_owner_schema_0008",
        lambda *_args, **_kwargs: pytest.fail("known incompatible legacy must not migrate"),
    )
    monkeypatch.setattr(
        DockerStoppedControllerEvidence,
        "host_database_path",
        lambda _self: pytest.fail("known incompatible legacy must not inspect Docker"),
    )
    with pytest.raises(OwnerSessionUpgradeUnavailable, match="cannot resume"):
        gate.pre_cutover_upgrade_0008(evidence, verifier)
    assert verifier.events == []
    assert _snapshot(db) == db_before
    assert key.read_bytes() == key_before
    assert db.stat().st_ino == inode


def test_manifest_alone_or_boolean_receipt_never_authorizes_pre_cutover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = _evidence(_FUTURE_SHA)
    monkeypatch.setattr(
        gate,
        "upgrade_existing_owner_schema_0008",
        lambda *_args, **_kwargs: pytest.fail("unverified legacy must not migrate"),
    )
    for fake in (True, {"resumable": True}, gate.owner_schema_0008_checksum(), None):
        with pytest.raises(OwnerSessionUpgradeUnavailable, match="proof"):
            gate.pre_cutover_upgrade_0008(evidence, fake)  # type: ignore[arg-type]
    with pytest.raises(OwnerSessionUpgradeUnavailable, match="lease"):
        gate.pre_cutover_upgrade_0008(_evidence(_FUTURE_SHA, fd=None), _verifier(evidence))


@pytest.mark.parametrize(
    "field_name",
    ["original_id", "attempt_id", "legacy_sha", "legacy_image", "owner_schema_0008_sha256"],
)
def test_resume_proof_must_bind_exact_image_attempt_and_schema_checksum(
    monkeypatch: pytest.MonkeyPatch, field_name: str
) -> None:
    evidence = _evidence(_FUTURE_SHA)
    verifier = _verifier(evidence)
    changed = {field_name: "d" * (64 if field_name == "original_id" else 40)}
    stale = replace(verifier, **changed)
    monkeypatch.setattr(
        gate,
        "upgrade_existing_owner_schema_0008",
        lambda *_args, **_kwargs: pytest.fail("stale proof must not migrate"),
    )
    with pytest.raises(OwnerSessionUpgradeUnavailable, match="stale or mismatched"):
        gate.pre_cutover_upgrade_0008(evidence, stale)
    assert stale.events == []


def test_proof_must_remain_live_during_exact_pre_cutover_migration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evidence = _evidence(_FUTURE_SHA)
    verifier = _verifier(evidence)
    expected_path = tmp_path / "synthetic-no-file-created.db"
    monkeypatch.setattr(
        DockerStoppedControllerEvidence, "host_database_path", lambda _: expected_path
    )

    def inert_upgrade(actual: DockerStoppedControllerEvidence, *, path: Path) -> UpgradeResult:
        assert actual is evidence and path == expected_path
        verifier.events.append("upgrade-in-proven-window")
        return UpgradeResult.ALREADY_APPLIED

    monkeypatch.setattr(gate, "upgrade_existing_owner_schema_0008", inert_upgrade)
    assert gate.pre_cutover_upgrade_0008(evidence, verifier) is UpgradeResult.ALREADY_APPLIED
    assert verifier.events == ["proof-enter", "upgrade-in-proven-window", "proof-exit"]
    assert not expected_path.exists()


def test_verifier_failure_aborts_before_any_storage_write(monkeypatch: pytest.MonkeyPatch) -> None:
    evidence = _evidence(_FUTURE_SHA)
    verifier = replace(_verifier(evidence), fail=True)
    monkeypatch.setattr(
        gate,
        "upgrade_existing_owner_schema_0008",
        lambda *_args, **_kwargs: pytest.fail("failed proof must not migrate"),
    )
    with pytest.raises(OwnerSessionUpgradeUnavailable, match="verification failed"):
        gate.pre_cutover_upgrade_0008(evidence, verifier)
    assert verifier.events == ["proof-enter"]


def test_proof_checksum_is_exact_packaged_0008_not_user_claim() -> None:
    from importlib.resources import files

    raw = (
        files("boca_socios.storage.migrations")
        .joinpath("0008_owner_browser_session.sql")
        .read_bytes()
    )
    assert gate.owner_schema_0008_checksum() == hashlib.sha256(raw).hexdigest()
