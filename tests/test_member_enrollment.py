from __future__ import annotations

import base64
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest

from boca_socios.domain.policy import TicketIntent
from boca_socios.security.credential_vault import CredentialVault
from boca_socios.security.enrollment import (
    EnrollmentConflict,
    MemberEnrollmentService,
    MemberNotFound,
)
from boca_socios.storage.database import Database


def setup_service(tmp_path: Path) -> tuple[Database, CredentialVault, MemberEnrollmentService]:
    db = Database(tmp_path / "boca.sqlite3")
    db.migrate()
    vault = CredentialVault(os.urandom(32))
    return db, vault, MemberEnrollmentService(db, vault)


def test_enrollment_is_atomic_and_ciphertext_only(tmp_path: Path) -> None:
    db, vault, service = setup_service(tmp_path)
    member_id = service.enroll(
        email="  PERSONA@EXAMPLE.TEST ",
        password="synthetic-credential",
        consent_recorded_at=datetime(2026, 10, 28, tzinfo=UTC),
    )
    with db.connection() as connection:
        member = connection.execute(
            "SELECT email, consent_recorded_at FROM members WHERE member_id = ?", (member_id,)
        ).fetchone()
        credential = connection.execute(
            "SELECT key_id, nonce, ciphertext FROM credentials WHERE member_id = ?",
            (member_id,),
        ).fetchone()
        actions = connection.execute("SELECT action FROM audit_events").fetchall()
    assert member == ("persona@example.test", "2026-10-28T00:00:00+00:00")
    assert credential is not None
    assert b"synthetic-credential" not in credential[2]
    saved = db.get_credential(member_id)
    assert saved is not None
    assert vault.open(saved, member_id=member_id) == "synthetic-credential"
    assert actions == [("member.enrolled",)]
    assert b"synthetic-credential" not in db.path.read_bytes()


def test_duplicate_and_invalid_enrollment_leave_no_partial_record(tmp_path: Path) -> None:
    db, _, service = setup_service(tmp_path)
    one = service.enroll(
        email="someone@example.test",
        password="synthetic-one",
        consent_recorded_at=datetime.now(UTC),
    )
    with pytest.raises(EnrollmentConflict) as duplicate:
        service.enroll(
            email="SOMEONE@example.test",
            password="synthetic-two",
            consent_recorded_at=datetime.now(UTC),
        )
    assert "synthetic-two" not in str(duplicate.value)
    assert "someone@" not in str(duplicate.value)
    with pytest.raises(ValueError):
        service.enroll(
            email="invalid",
            password="synthetic-three",
            consent_recorded_at=datetime.now(UTC),
        )
    with db.connection() as connection:
        members = connection.execute("SELECT member_id FROM members").fetchall()
        credentials = connection.execute("SELECT member_id FROM credentials").fetchall()
    assert members == [(one,)]
    assert credentials == [(one,)]


def test_vault_failure_rolls_back_member_and_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db, vault, service = setup_service(tmp_path)

    def fail_seal(_password: str, *, member_id: str) -> None:
        raise ValueError("key unavailable")

    monkeypatch.setattr(vault, "seal", fail_seal)
    with pytest.raises(ValueError, match="key unavailable"):
        service.enroll(
            email="person@example.test",
            password="synthetic-only",
            consent_recorded_at=datetime.now(UTC),
        )
    with db.connection() as connection:
        for table in ("members", "credentials", "audit_events"):
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)


def test_atomic_password_rotation_and_revocation_preserve_ticket_intent(tmp_path: Path) -> None:
    db, vault, service = setup_service(tmp_path)
    member_id = service.enroll(
        email="person@example.test",
        password="synthetic-old",
        consent_recorded_at=datetime.now(UTC),
    )
    previous = db.get_credential(member_id)
    db.create_event("event-a", "Partido ficticio")
    request_id = db.request_ticket(TicketIntent(member_id=member_id, event_id="event-a"))
    service.rotate_password(member_id, "synthetic-new")
    current = db.get_credential(member_id)
    assert previous is not None and current is not None
    assert current.nonce != previous.nonce
    assert current.ciphertext != previous.ciphertext
    assert vault.open(current, member_id=member_id) == "synthetic-new"
    assert service.revoke_credential(member_id) is True
    assert service.revoke_credential(member_id) is False
    assert db.get_credential(member_id) is None
    with db.connection() as connection:
        assert connection.execute(
            "SELECT request_id, quantity FROM ticket_requests WHERE member_id = ?",
            (member_id,),
        ).fetchone() == (request_id, 1)
        assert connection.execute("SELECT count(*) FROM members").fetchone() == (1,)
        assert connection.execute(
            "SELECT action FROM audit_events ORDER BY rowid"
        ).fetchall() == [
            ("member.enrolled",),
            ("credential.rotated",),
            ("credential.revoked",),
        ]
    with pytest.raises(MemberNotFound):
        service.rotate_password("absent-id", "synthetic-value")


def test_restart_uses_external_key_and_invalid_mount_fails_closed(tmp_path: Path) -> None:
    key_path = tmp_path / "key"
    key_path.write_bytes(base64.b64encode(os.urandom(32)))
    key_path.chmod(0o600)
    db = Database(tmp_path / "boca.sqlite3")
    db.migrate()
    service = MemberEnrollmentService(db, CredentialVault.from_secret_file(key_path))
    member_id = service.enroll(
        email="restart@example.test",
        password="synthetic-restart",
        consent_recorded_at=datetime.now(UTC),
    )
    restarted = MemberEnrollmentService(db, CredentialVault.from_secret_file(key_path))
    restarted.rotate_password(member_id, "synthetic-after-restart")
    sealed = db.get_credential(member_id)
    assert sealed is not None
    assert CredentialVault.from_secret_file(key_path).open(
        sealed, member_id=member_id
    ) == "synthetic-after-restart"
    key_path.unlink()
    with pytest.raises(ValueError):
        CredentialVault.from_secret_file(key_path)
    with pytest.raises(ValueError):
        CredentialVault.from_secret_file(db.path)
    with db.connection() as connection:
        assert connection.execute("SELECT count(*) FROM credentials").fetchone() == (1,)


def test_concurrent_duplicate_enrollment_has_one_member_and_credential(tmp_path: Path) -> None:
    db, _, service = setup_service(tmp_path)
    barrier = Barrier(8)

    def attempt(_index: int) -> str:
        barrier.wait()
        try:
            return service.enroll(
                email="shared@example.test",
                password="synthetic-shared",
                consent_recorded_at=datetime.now(UTC),
            )
        except EnrollmentConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert len([value for value in results if value != "conflict"]) == 1
    with db.connection() as connection:
        assert connection.execute("SELECT count(*) FROM members").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM credentials").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone() == (1,)
