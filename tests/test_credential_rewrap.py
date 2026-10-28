"""Internal key migration with synthetic credentials and no network access."""

from __future__ import annotations

import base64
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from boca_socios.security.credential_rewrap import (
    CredentialKeyRewrapper,
    KeyPolicyMismatch,
    verify_active_credentials,
)
from boca_socios.security.credential_vault import CredentialVault
from boca_socios.security.enrollment import MemberEnrollmentService
from boca_socios.storage.database import Database


def key_file(path: Path) -> Path:
    path.write_bytes(base64.b64encode(os.urandom(32)))
    path.chmod(0o600)
    return path


def setup_rotation(
    tmp_path: Path, *, count: int = 2, max_records: int = 1000
) -> tuple[Database, CredentialVault, CredentialVault, CredentialKeyRewrapper, list[str]]:
    database = Database(tmp_path / "data" / "boca.sqlite3")
    database.migrate()
    old = CredentialVault.from_secret_file(key_file(tmp_path / "old.key"), key_id="v1")
    new = CredentialVault.from_secret_file(key_file(tmp_path / "new.key"), key_id="v2")
    service = MemberEnrollmentService(database, old)
    members = [
        service.enroll(
            email=f"synthetic-{index}@invalid.test",
            password=f"synthetic-secret-{index}",
            consent_recorded_at=datetime(2026, 10, 28, tzinfo=UTC),
        )
        for index in range(count)
    ]
    rewrapper = CredentialKeyRewrapper(database, old, new, max_records=max_records)
    rewrapper.migrate()
    return database, old, new, rewrapper, members


def test_atomic_rotation_restart_verification_and_stale_writer_is_fenced(tmp_path: Path) -> None:
    database, old, new, migration, members = setup_rotation(tmp_path)
    previous = {member: database.get_credential(member) for member in members}
    assert migration.rotate() == len(members)

    for index, member in enumerate(members):
        sealed = database.get_credential(member)
        assert sealed is not None and previous[member] is not None
        assert sealed.key_id == "v2" and sealed.nonce != previous[member].nonce
        assert new.open(sealed, member_id=member) == f"synthetic-secret-{index}"
        with pytest.raises(ValueError, match="unavailable key version"):
            old.open(sealed, member_id=member)
    with database.connection() as connection:
        assert connection.execute("SELECT key_id FROM credential_key_policy").fetchone() == ("v2",)
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone() == (2,)
    assert b"synthetic-secret" not in database.path.read_bytes()

    # The old process may still hold its key, but its next DB write is rejected.
    with pytest.raises(sqlite3.IntegrityError, match="key version"):
        MemberEnrollmentService(database, old).rotate_password(members[0], "stale-writer")
    with pytest.raises(sqlite3.IntegrityError, match="key version"):
        database.save_credential(members[0], old.seal("stale-writer", member_id=members[0]))
    reopened = Database(database.path)
    fresh_key = CredentialVault.from_secret_file(tmp_path / "new.key", key_id="v2")
    assert verify_active_credentials(reopened, fresh_key) == len(members)
    fresh_service = MemberEnrollmentService(reopened, fresh_key)
    fresh_service.rotate_password(members[0], "test-new-password")
    assert verify_active_credentials(reopened, fresh_key) == len(members)


def test_corrupt_later_row_rolls_back_earlier_recipher_and_policy(tmp_path: Path) -> None:
    database, old, new, migration, members = setup_rotation(tmp_path)
    with database.connection() as connection, connection:
        # Sorted by opaque member ID, so corrupt the last row to force a prior update.
        last = max(members)
        connection.execute(
            "UPDATE credentials SET ciphertext=? WHERE member_id=?",
            (b"x" * 20, last),
        )
    before = {member: database.get_credential(member) for member in members}
    with pytest.raises(InvalidTag):
        migration.rotate()
    assert {member: database.get_credential(member) for member in members} == before
    with database.connection() as connection:
        assert connection.execute("SELECT key_id FROM credential_key_policy").fetchone() == ("v1",)
    assert new.key_id == "v2" and old.key_id == "v1"


def test_missing_or_wrong_key_and_oversized_batch_fail_closed(tmp_path: Path) -> None:
    database, old, new, _, members = setup_rotation(tmp_path, max_records=1)
    with pytest.raises(ValueError, match="limit"):
        CredentialKeyRewrapper(database, old, new, max_records=1).rotate()
    assert all(database.get_credential(member).key_id == "v1" for member in members)
    with pytest.raises(KeyPolicyMismatch):
        CredentialKeyRewrapper(database, CredentialVault(os.urandom(32)), new).rotate()
    with pytest.raises(InvalidTag):
        CredentialKeyRewrapper(database, CredentialVault(os.urandom(32), key_id="v1"), new).rotate()
    with pytest.raises(KeyPolicyMismatch):
        verify_active_credentials(database, new)
    with database.connection() as connection:
        assert connection.execute("SELECT key_id FROM credential_key_policy").fetchone() == ("v1",)


def test_same_key_material_or_version_and_mixed_rows_are_rejected(tmp_path: Path) -> None:
    database, old, new, _, members = setup_rotation(tmp_path)
    with pytest.raises(ValueError, match="different key versions"):
        CredentialKeyRewrapper(database, old, CredentialVault(os.urandom(32), key_id="v1"))
    # The same source key under another label is not genuine rotation.
    same_material = CredentialVault.from_secret_file(tmp_path / "old.key", key_id="v3")
    with pytest.raises(ValueError, match="different key material"):
        CredentialKeyRewrapper(database, old, same_material)
    with database.connection() as connection, connection:
        connection.execute("DROP TRIGGER credential_key_update")
        connection.execute("UPDATE credentials SET key_id='v9' WHERE member_id=?", (members[0],))
    with pytest.raises(KeyPolicyMismatch):
        CredentialKeyRewrapper(database, old, new).rotate()
    with pytest.raises(KeyPolicyMismatch):
        verify_active_credentials(database, old)


def test_migration_checksum_and_no_preexisting_mixed_versions(tmp_path: Path) -> None:
    database, old, new, migration, members = setup_rotation(tmp_path)
    with database.connection() as connection, connection:
        connection.execute("UPDATE schema_migrations SET checksum='wrong' WHERE version=4")
    with pytest.raises(ValueError, match="checksum"):
        migration.migrate()
    separate_db = Database(tmp_path / "other.sqlite3")
    separate_db.migrate()
    separate_db.create_member("member-a", "a@invalid.test", "2026-10-28T00:00:00Z")
    separate_db.save_credential("member-a", new.seal("synthetic", member_id="member-a"))
    with pytest.raises(KeyPolicyMismatch):
        CredentialKeyRewrapper(separate_db, old, new).migrate()
    with separate_db.connection() as connection:
        assert connection.execute("SELECT count(*) FROM schema_migrations WHERE version=4").fetchone() == (0,)
    assert len(members) == 2
