"""Old schema-0008 cutover path is permanently forbidden under approved Option B."""

from __future__ import annotations

import base64
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import pytest

from boca_socios.config import Settings
from boca_socios.panel import owner_session_cutover_gate as gate
from boca_socios.panel.owner_session_host_attestor import DockerStoppedControllerEvidence
from boca_socios.panel.owner_session_store import OwnerBrowserSessionStore
from boca_socios.panel.owner_session_upgrade import OwnerSessionUpgradeUnavailable
from boca_socios.runtime import initialize_beta
from boca_socios.storage.database import Database

_INSTALLED_SHA = "cabce9f1e452e63ded115f447559a358dc0f4d1b"
_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "c" * 64


@dataclass(frozen=True, slots=True)
class _SyntheticVerifier(gate.LegacyResumeVerifier):
    @contextmanager
    def hold_live_legacy_resume_proof(self) -> Iterator[None]:
        pytest.fail("discontinued schema-0008 proof must never be consumed")
        yield


@pytest.mark.parametrize("legacy_sha", [_INSTALLED_SHA, "f" * 40])
def test_0008_cutover_is_no_go_for_any_legacy_sha(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, legacy_sha: str
) -> None:
    db, key = tmp_path / "boca.sqlite3", tmp_path / "fake.key"
    key.write_bytes(base64.b64encode(b"k" * 32))
    key.chmod(0o400)
    initialize_beta(Settings("staging", "simulation", db, key))
    Database(db).create_member("sentinel", "synthetic@example.invalid", "consented")
    before = db.read_bytes()
    evidence = DockerStoppedControllerEvidence(
        original_id="a" * 64,
        attempt_id="1234",
        legacy_sha=legacy_sha,
        legacy_image=_IMAGE,
        borrowed_lease_fd=8,
    )
    verifier = _SyntheticVerifier(
        original_id=evidence.original_id,
        attempt_id=evidence.attempt_id,
        legacy_sha=evidence.legacy_sha,
        legacy_image=evidence.legacy_image,
        owner_schema_0008_sha256="c" * 64,
    )
    monkeypatch.setattr(
        DockerStoppedControllerEvidence,
        "host_database_path",
        lambda _self: pytest.fail("deprecated gate must never inspect Docker"),
    )
    with pytest.raises(OwnerSessionUpgradeUnavailable, match="prohibited"):
        gate.pre_cutover_upgrade_0008(evidence, verifier)
    with pytest.raises(OwnerSessionUpgradeUnavailable, match="prohibited"):
        gate.owner_schema_0008_checksum()
    assert db.read_bytes() == before
    assert not db.with_name("boca_owner_session.sqlite3").exists()
    with sqlite3.connect(db) as connection:
        assert connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall() == [(1,), (2,), (3,), (5,), (6,)]


def test_option_b_adds_session_to_neighbor_not_legacy_ledger(tmp_path: Path) -> None:
    assert (
        not files("boca_socios.storage.migrations")
        .joinpath("0008_owner_browser_session.sql")
        .is_file()
    )
    db = Database(tmp_path / "boca.sqlite3")
    db.migrate()
    OwnerBrowserSessionStore.migrate_schema(db)
    with sqlite3.connect(db.path) as connection:
        assert connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall() == [(1,)]
        assert (
            connection.execute(
                "SELECT name FROM sqlite_master WHERE name='owner_browser_session'"
            ).fetchone()
            is None
        )
    assert db.path.with_name("boca_owner_session.sqlite3").is_file()
