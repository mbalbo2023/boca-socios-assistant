"""Offline installed-controller 0008 upgrade: no host/remote DB is touched."""

from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path

import pytest

from boca_socios.config import Settings
from boca_socios.panel import owner_session_upgrade as upgrade
from boca_socios.panel.owner_session_store import OwnerBrowserSessionStore
from boca_socios.runtime import initialize_beta
from boca_socios.security.credential_vault import SealedCredential
from boca_socios.storage.database import Database


class _SyntheticStoppedController(upgrade.ControllerStoppedEvidence):
    """Only for a disposable test DB; NOT an actual host-stop attestation."""

    def __init__(self, *, fail: bool = False, replace_file: bool = False) -> None:
        self.calls = 0
        self.fail = fail
        self.replace_file = replace_file

    @contextmanager
    def exclusive_stop(self, *, database_path: Path, device: int, inode: int) -> Iterator[None]:
        self.calls += 1
        assert database_path.stat().st_dev == device
        assert database_path.stat().st_ino == inode
        if self.fail:
            raise upgrade.OwnerSessionUpgradeUnavailable("simulated host did not stop")
        if self.replace_file:
            database_path.rename(database_path.with_suffix(".moved"))
            database_path.symlink_to(database_path.with_suffix(".moved"))
        yield


@pytest.fixture
def installed_controller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Real ownerless BETA initializer, not a fabricated migration ledger."""
    path = tmp_path / "boca.sqlite3"
    key = tmp_path / "owner.test.key"
    key.write_bytes(base64.b64encode(b"k" * 32) + b"\n")
    key.chmod(0o400)
    # This fixture must use real SQLite dev/inode/mode and process IDs; only
    # the protected-host constant is moved to a disposable test namespace.
    monkeypatch.setattr(upgrade, "DATABASE", path)
    monkeypatch.setattr(upgrade, "_BOCA_UID", os.getuid())
    monkeypatch.setattr(upgrade, "_BOCA_GID", os.getgid())
    # initialize_beta checks the vault key format in the real first install.
    initialize_beta(Settings("staging", "simulation", path, key))
    return path, key


def _versions(path: Path) -> list[int]:
    with sqlite3.connect(path) as connection:
        return [
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]


def _member_snapshot(path: Path) -> tuple[object, ...]:
    with sqlite3.connect(path) as connection:
        return (
            tuple(connection.execute("SELECT * FROM members ORDER BY member_id")),
            tuple(connection.execute("SELECT * FROM credentials ORDER BY member_id")),
            tuple(connection.execute("SELECT * FROM events ORDER BY event_id")),
            tuple(connection.execute("SELECT * FROM ticket_requests ORDER BY request_id")),
        )


def _add_optional_telegram_0007(path: Path) -> None:
    sql = files("boca_socios.storage.migrations").joinpath("0007_telegram_delivery.sql").read_text()
    with sqlite3.connect(path) as connection:
        connection.executescript(sql)
        connection.execute(
            "INSERT INTO schema_migrations(version,checksum) VALUES (7,?)",
            (hashlib.sha256(sql.encode()).hexdigest(),),
        )


@pytest.mark.parametrize("telegram", [False, True])
def test_existing_controller_0008_only_and_idempotent_preserves_all_data(
    installed_controller: tuple[Path, Path], telegram: bool
) -> None:
    path, key = installed_controller
    database = Database(path)
    assert _versions(path) == [1, 2, 3, 5, 6]
    database.create_member("owner-test", "owner@example.invalid", "consented")
    database.save_credential(
        "owner-test",
        SealedCredential("synthetic-key", b"n" * 12, b"synthetic-encrypted-credential"),
    )
    database.create_event("test-only", "Local synthetic fixture")
    if telegram:
        _add_optional_telegram_0007(path)
    before_rows = _member_snapshot(path)
    key_before = key.read_bytes()
    file_before = path.stat()
    guard = _SyntheticStoppedController()
    assert (
        upgrade.upgrade_existing_owner_schema_0008(guard, path=path)
        is upgrade.UpgradeResult.APPLIED
    )
    assert guard.calls == 1
    assert _versions(path) == ([1, 2, 3, 5, 6, 7, 8] if telegram else [1, 2, 3, 5, 6, 8])
    OwnerBrowserSessionStore(database, owner_subject="owner-test").verify_schema()
    assert _member_snapshot(path) == before_rows
    assert key.read_bytes() == key_before
    assert (path.stat().st_dev, path.stat().st_ino, path.stat().st_mode) == (
        file_before.st_dev,
        file_before.st_ino,
        file_before.st_mode,
    )
    token = hashlib.sha256(b"owner-test-cookie").digest()
    verifier = hashlib.sha256(b"owner-test-passkey").digest()
    store = OwnerBrowserSessionStore(database, owner_subject="owner-test")
    store.replace(token, verifier)
    assert (
        upgrade.upgrade_existing_owner_schema_0008(guard, path=path)
        is upgrade.UpgradeResult.ALREADY_APPLIED
    )
    assert store.matches(token, verifier)
    assert _member_snapshot(path) == before_rows


def test_requires_host_stopped_capability_not_boolean_or_receipt(
    installed_controller: tuple[Path, Path],
) -> None:
    path, _ = installed_controller
    for fake in (True, False, {"controller_stopped": True}, "BOCA_CONTROLLER_STOPPED"):
        with pytest.raises(upgrade.OwnerSessionUpgradeUnavailable, match="evidence"):
            upgrade.upgrade_existing_owner_schema_0008(fake, path=path)  # type: ignore[arg-type]
    assert _versions(path) == [1, 2, 3, 5, 6]
    guard = _SyntheticStoppedController(fail=True)
    with pytest.raises(upgrade.OwnerSessionUpgradeUnavailable, match="did not stop"):
        upgrade.upgrade_existing_owner_schema_0008(guard, path=path)
    assert _versions(path) == [1, 2, 3, 5, 6]


@pytest.mark.parametrize(
    "fault",
    ["ledger6", "unknown9", "partial8", "bad8", "altered8", "missing_telegram_table"],
)
def test_invalid_existing_schema_is_never_repaired(
    installed_controller: tuple[Path, Path], fault: str
) -> None:
    path, _ = installed_controller
    with sqlite3.connect(path) as connection:
        if fault == "ledger6":
            connection.execute("UPDATE schema_migrations SET checksum='changed' WHERE version=6")
        elif fault == "unknown9":
            connection.execute(
                "INSERT INTO schema_migrations(version,checksum) VALUES(9,'unexpected')"
            )
        elif fault == "partial8":
            connection.execute("CREATE TABLE owner_browser_session (singleton INTEGER)")
        elif fault == "altered8":
            sql = files("boca_socios.storage.migrations").joinpath("0008_owner_browser_session.sql")
            connection.execute("CREATE TABLE owner_browser_session (singleton INTEGER)")
            connection.execute(
                "INSERT INTO schema_migrations(version,checksum) VALUES(8,?)",
                (hashlib.sha256(sql.read_bytes()).hexdigest(),),
            )
        elif fault == "missing_telegram_table":
            sql = files("boca_socios.storage.migrations").joinpath("0007_telegram_delivery.sql")
            connection.execute(
                "INSERT INTO schema_migrations(version,checksum) VALUES(7,?)",
                (hashlib.sha256(sql.read_bytes()).hexdigest(),),
            )
        else:
            connection.execute(
                "INSERT INTO schema_migrations(version,checksum) VALUES (8,'tampered')"
            )
    before = _versions(path)
    with pytest.raises(upgrade.OwnerSessionUpgradeUnavailable):
        upgrade.upgrade_existing_owner_schema_0008(_SyntheticStoppedController(), path=path)
    assert _versions(path) == before


def test_rejects_swapped_inode_symlink_wrong_mode_and_wrong_scope(
    installed_controller: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _ = installed_controller
    guard = _SyntheticStoppedController(replace_file=True)
    with pytest.raises(upgrade.OwnerSessionUpgradeUnavailable):
        upgrade.upgrade_existing_owner_schema_0008(guard, path=path)
    assert _versions(path) == [1, 2, 3, 5, 6]
    path.unlink()  # Only a disposable test symlink, never the DB target.
    moved = path.with_suffix(".moved")
    moved.rename(path)
    path.chmod(0o644)
    with pytest.raises(upgrade.OwnerSessionUpgradeUnavailable, match="identity"):
        upgrade.upgrade_existing_owner_schema_0008(_SyntheticStoppedController(), path=path)
    path.chmod(0o600)
    monkeypatch.setattr(upgrade, "_BOCA_UID", 10001 if os.getuid() != 10001 else 10002)
    with pytest.raises(upgrade.OwnerSessionUpgradeUnavailable, match="identity"):
        upgrade.upgrade_existing_owner_schema_0008(_SyntheticStoppedController(), path=path)
    monkeypatch.setattr(upgrade, "_BOCA_UID", os.getuid())
    with pytest.raises(upgrade.OwnerSessionUpgradeUnavailable, match="scope"):
        upgrade.upgrade_existing_owner_schema_0008(
            _SyntheticStoppedController(), path=tmp_path / "other.sqlite3"
        )
    assert _versions(path) == [1, 2, 3, 5, 6]


def test_missing_database_never_created_even_with_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "boca.sqlite3"
    monkeypatch.setattr(upgrade, "DATABASE", path)
    monkeypatch.setattr(upgrade, "_BOCA_UID", os.getuid())
    monkeypatch.setattr(upgrade, "_BOCA_GID", os.getgid())
    with pytest.raises(upgrade.OwnerSessionUpgradeUnavailable):
        upgrade.upgrade_existing_owner_schema_0008(_SyntheticStoppedController(), path=path)
    assert not path.exists()
