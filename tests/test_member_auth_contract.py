"""Offline Boca login boundary: SQLite + encrypted vault + supplied provider bytes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

import pytest

from boca_socios.security.credential_vault import CredentialVault
from boca_socios.security.enrollment import MemberEnrollmentService
from boca_socios.storage.database import Database

AT = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


class OfflineTransport:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def login(self, *, email: str, password: str) -> bytes:
        self.calls.append((email, password))
        return self.payload


def _api() -> object:
    # New module is resolved at test runtime for an explicit TDD RED.
    return import_module("boca_socios.security.member_auth_contract")


def _enrolled(tmp_path: Path) -> tuple[Database, CredentialVault, str]:
    database = Database(tmp_path / "boca.sqlite3")
    database.migrate()
    vault = CredentialVault(b"d" * 32)
    member_id = MemberEnrollmentService(database, vault).enroll(
        email="SOCIO@example.invalid",
        password="existing-encrypted-credential",
        consent_recorded_at=AT,
    )
    return database, vault, member_id


def test_real_sqlite_vault_roundtrip_feeds_only_supplied_transport_response(tmp_path: Path) -> None:
    api = _api()
    database, vault, member_id = _enrolled(tmp_path)
    raw = b'{"token":"observed-access-fixture","refreshToken":"observed-refresh-fixture"}'
    transport = OfflineTransport(raw)
    monitor = api.PrivateBocaAuthMonitor(max_observations=2)
    service = api.BocaMemberAuthService(
        database, vault, transport=transport, monitor=monitor, now=lambda: AT
    )

    received = service.authenticate(member_id)

    assert transport.calls == [("socio@example.invalid", "existing-encrypted-credential")]
    assert b"existing-encrypted-credential" not in database.get_credential(member_id).ciphertext
    assert received.summary().state == "observed_unverified"
    assert "observed-access-fixture" not in repr(received)
    assert "observed-refresh-fixture" not in repr(monitor.list_summaries())
    details = monitor.owner_details(member_id, owner_authenticated=True)
    assert details.copy_full_token() == "observed-access-fixture"
    assert details.copy_full_refresh_token() == "observed-refresh-fixture"
    with pytest.raises(PermissionError):
        monitor.owner_details(member_id, owner_authenticated=False)


def test_absent_transport_cannot_attempt_login_or_create_sqlite(tmp_path: Path) -> None:
    api = _api()
    path = tmp_path / "not-installed.sqlite3"
    with pytest.raises(api.BocaAuthUnavailable, match="not configured"):
        api.BocaMemberAuthService(Database(path), CredentialVault(b"d" * 32)).authenticate(
            "00000000-0000-0000-0000-000000000001"
        )
    assert not path.exists()


def test_unknown_revoked_or_wrong_key_never_reaches_transport(tmp_path: Path) -> None:
    api = _api()
    database, vault, member_id = _enrolled(tmp_path)
    transport = OfflineTransport(b'{"token":"x","refreshToken":"y"}')
    service = api.BocaMemberAuthService(database, vault, transport=transport, now=lambda: AT)

    with pytest.raises(api.BocaAuthUnavailable):
        service.authenticate("00000000-0000-0000-0000-000000000002")
    MemberEnrollmentService(database, vault).revoke_credential(member_id)
    with pytest.raises(api.BocaAuthUnavailable):
        service.authenticate(member_id)
    assert transport.calls == []

    second_database, _, second_member = _enrolled(tmp_path / "second")
    with pytest.raises(api.BocaAuthUnavailable):
        api.BocaMemberAuthService(
            second_database, CredentialVault(b"z" * 32), transport=transport
        ).authenticate(second_member)
    assert transport.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        b"{}",
        b'{"token":"only-access"}',
        b'{"refreshToken":"only-refresh"}',
        b'{"token":"","refreshToken":"y"}',
        b'{"token":23,"refreshToken":"y"}',
        b'{"token":"x","refreshToken":null}',
        b'{"token":"a","token":"b","refreshToken":"c"}',
        b'{"access_token":"a","refresh_token":"b"}',
        b"not-json",
    ],
)
def test_partial_or_unrecognized_response_is_never_fabricated(payload: bytes) -> None:
    api = _api()
    with pytest.raises(api.BocaAuthUnavailable, match="unverified"):
        api.BocaAuthObservation.from_provider_response(
            member_id="member-1", provider_payload=payload, observed_at=AT
        )


def test_failed_transport_does_not_store_or_echo_credentials(tmp_path: Path) -> None:
    api = _api()
    database, vault, member_id = _enrolled(tmp_path)
    monitor = api.PrivateBocaAuthMonitor()

    class LeakyTransport:
        def login(self, *, email: str, password: str) -> bytes:
            raise RuntimeError("PRIVATE_SECRET_FROM_PROVIDER")

    service = api.BocaMemberAuthService(
        database, vault, transport=LeakyTransport(), monitor=monitor
    )
    with pytest.raises(api.BocaAuthUnavailable) as raised:
        service.authenticate(member_id)
    assert "PRIVATE_SECRET_FROM_PROVIDER" not in str(raised.value)
    assert monitor.list_summaries() == ()


def test_provider_response_with_extra_metadata_does_not_infer_expiry() -> None:
    api = _api()
    payload = json.dumps(
        {"token": "actual-response-fixture", "refreshToken": "refresh-fixture", "expires_in": 99}
    ).encode()
    received = api.BocaAuthObservation.from_provider_response(
        member_id="member-1", provider_payload=payload, observed_at=AT
    )
    assert received.summary().observed_at == AT
    assert not hasattr(received.summary(), "expires_at")
