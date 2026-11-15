"""Credential authority and ciphertext share SQLite custody; transport stays offline."""

from __future__ import annotations

import asyncio
import os
import sqlite3
from threading import Event

import pytest

from boca_socios.browser.boca_auth_protocol import BocaAuthReadiness, BocaAuthReply
from boca_socios.integration.boca_login import authenticate_member
from boca_socios.security.enrollment import MemberEnrollmentService
from boca_socios.security.member_auth_contract import BocaAuthUnavailable, BocaMemberAuthService
from test_automatic_observer_ipc import observation
from test_boca_auth_continuation import OPERATION
from test_member_auth_contract import OfflineTransport, _enrolled

PAYLOAD = b'{"token":"fixture-access","refreshToken":"fixture-refresh"}'


def authorities(database, member_id):
    original = database.get_credential(member_id)
    expected = (original.key_id, original.nonce, original.ciphertext)

    def read(connection, requested):
        row = connection.execute(
            "SELECT key_id,nonce,ciphertext FROM credentials WHERE member_id=?", (requested,)
        ).fetchone()
        return requested == member_id and row == expected

    def exchange():
        with database.connection() as connection:
            return read(connection, member_id)

    return read, exchange


def test_unchanged_credential_passes_authorities_without_holding_sqlite_during_exchange(tmp_path):
    database, vault, member = _enrolled(tmp_path)
    read, exchange = authorities(database, member)
    connections = []

    def checked(connection, selected):
        connections.append(connection)
        assert connection.in_transaction
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM credentials")
        return read(connection, selected)

    class Transport(OfflineTransport):
        def login(self, **credentials):
            with pytest.raises(sqlite3.ProgrammingError):
                connections[0].execute("SELECT 1")
            # A concurrent writer is not blocked by network exchange.
            MemberEnrollmentService(database, vault).rotate_password(member, "rotated-fixture")
            return super().login(**credentials)

    transport = Transport(PAYLOAD)
    service = BocaMemberAuthService(
        database,
        vault,
        transport=transport,
        credential_read_authority=checked,
        exchange_authority=exchange,
    )
    result = service.authenticate(member)
    assert result.member_id == member
    assert transport.calls == [("socio@example.invalid", "existing-encrypted-credential")]


def test_authority_and_ciphertext_selection_use_one_read_snapshot(tmp_path):
    database, vault, member = _enrolled(tmp_path)
    read, _ = authorities(database, member)

    def rotate_after_authority_read(connection, selected):
        accepted = read(connection, selected)
        # WAL permits this real writer while the auth reader holds its snapshot.
        MemberEnrollmentService(database, vault).rotate_password(member, "rotated-fixture")
        return accepted

    transport = OfflineTransport(PAYLOAD)
    service = BocaMemberAuthService(
        database,
        vault,
        transport=transport,
        credential_read_authority=rotate_after_authority_read,
    )
    service.authenticate(member)
    # Without BEGIN, the second SELECT silently reads the replacement ciphertext.
    assert transport.calls == [("socio@example.invalid", "existing-encrypted-credential")]
    assert vault.open(database.get_credential(member), member_id=member) == "rotated-fixture"


@pytest.mark.parametrize("mutation", ["rotate", "revoke"])
def test_changed_authority_before_read_never_decrypts_for_transport(tmp_path, mutation):
    database, vault, member = _enrolled(tmp_path)
    read, exchange = authorities(database, member)
    service = MemberEnrollmentService(database, vault)
    if mutation == "rotate":
        service.rotate_password(member, "rotated-fixture")
    else:
        service.revoke_credential(member)
    transport = OfflineTransport(PAYLOAD)
    auth = BocaMemberAuthService(
        database,
        vault,
        transport=transport,
        credential_read_authority=read,
        exchange_authority=exchange,
    )
    with pytest.raises(BocaAuthUnavailable):
        auth.authenticate(member)
    assert transport.calls == []


@pytest.mark.parametrize("mutation", ["rotate", "revoke"])
def test_rotation_or_revocation_after_snapshot_before_exchange_is_rejected(
    tmp_path, monkeypatch, mutation
):
    database, vault, member = _enrolled(tmp_path)
    read, exchange = authorities(database, member)
    real_open = vault.open

    # The vault remains real; this hook controls only the read/decrypt/exchange
    # boundary where a concurrent credential mutation can occur.
    def decrypt_then_mutate(sealed, *, member_id):
        plaintext = real_open(sealed, member_id=member_id)
        if mutation == "rotate":
            database.save_credential(member, vault.seal("rotated-fixture", member_id=member))
        else:
            MemberEnrollmentService(database, vault).revoke_credential(member)
        return plaintext

    monkeypatch.setattr(vault, "open", decrypt_then_mutate)
    transport = OfflineTransport(PAYLOAD)
    auth = BocaMemberAuthService(
        database,
        vault,
        transport=transport,
        credential_read_authority=read,
        exchange_authority=exchange,
    )
    with pytest.raises(BocaAuthUnavailable):
        auth.authenticate(member)
    assert transport.calls == []


def test_replaced_source_inode_is_rejected_before_exchange(tmp_path):
    database, vault, member = _enrolled(tmp_path / "original")
    replacement, _, _ = _enrolled(tmp_path / "replacement")
    read, _ = authorities(database, member)

    def replace_after_read(connection, selected):
        accepted = read(connection, selected)
        os.replace(replacement.path, database.path)
        return accepted

    transport = OfflineTransport(PAYLOAD)
    service = BocaMemberAuthService(
        database,
        vault,
        transport=transport,
        credential_read_authority=replace_after_read,
    )
    with pytest.raises(BocaAuthUnavailable):
        service.authenticate(member)
    assert transport.calls == []


@pytest.mark.parametrize("allowed", [False, True])
def test_threaded_authentication_forwards_read_and_exchange_authorities(
    tmp_path, monkeypatch, allowed
):
    database, vault, member = _enrolled(tmp_path)
    read, exchange = authorities(database, member)
    entered, proceed = Event(), Event()
    original = BocaMemberAuthService._read_member

    def delayed(path, selected, *, authority=None):
        entered.set()
        assert proceed.wait(2)
        return original(path, selected, authority=authority)

    monkeypatch.setattr(BocaMemberAuthService, "_read_member", staticmethod(delayed))
    requests = []

    class Worker:
        async def login_boca(self, request):
            requests.append(request)
            return BocaAuthReply(request.operation_id, request.nonce, PAYLOAD)

    async def exercise():
        readiness = BocaAuthReadiness(OPERATION, observation(), "a" * 64, 15)
        task = asyncio.create_task(
            authenticate_member(
                database,
                vault,
                Worker(),
                member,
                readiness,
                credential_read_authority=read,
                exchange_authority=exchange,
            )
        )
        async with asyncio.timeout(1):
            while not entered.is_set():
                await asyncio.sleep(0.001)
        if not allowed:
            MemberEnrollmentService(database, vault).rotate_password(member, "rotated-fixture")
        proceed.set()
        if allowed:
            assert (await task).member_id == member
            assert len(requests) == 1 and requests[0].password == "existing-encrypted-credential"
        else:
            with pytest.raises(BocaAuthUnavailable):
                await task
            assert requests == []

    asyncio.run(exercise())
