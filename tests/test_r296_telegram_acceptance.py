"""Acceptance selects its UUID without rewriting old or unrelated notices."""

import asyncio
import sqlite3
from uuid import uuid4

import pytest

from boca_socios import telegram_one_shot as shot
from boca_socios.notify.outbox import NoticeKind, NotificationRequest
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from test_telegram_one_shot import SHA, _database, _Sender


def test_acceptance_preserves_other_pending_expired_and_ambiguous_rows(tmp_path, monkeypatch):
    path = tmp_path / "boca.sqlite3"
    _database(path)
    monkeypatch.setattr(shot, "verify_storage", lambda _path: None)
    outbox = SqliteNotificationOutbox(path)
    old = uuid4()
    outbox.enqueue(NotificationRequest(old, NoticeKind.HEARTBEAT), now=1, ttl_seconds=10)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO telegram_delivery_attempts(idempotency_key,attempt_number,state,prepared_at) VALUES(?,1,'prepared',1)",
            (str(old),),
        )
        before = connection.execute("SELECT * FROM notification_outbox").fetchall()
    sender = _Sender()
    target = uuid4()
    assert (
        asyncio.run(shot.deliver_once(path, sender, SHA, notice_id=target, clock=lambda: 1000))
        == "API_ACCEPTED"
    )
    assert [notice.idempotency_key for notice in sender.calls] == [target]
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT * FROM notification_outbox WHERE idempotency_key=?", (str(old),)
            ).fetchall()
            == before
        )
        assert connection.execute(
            "SELECT state FROM telegram_delivery_attempts WHERE idempotency_key=?", (str(old),)
        ).fetchone() == ("prepared",)
    with pytest.raises(shot.OneShotError):
        asyncio.run(shot.deliver_once(path, sender, SHA, notice_id=target, clock=lambda: 1001))
    assert len(sender.calls) == 1


def test_host_custody_import_needs_no_site_packages():
    import subprocess
    import sys
    from pathlib import Path

    source = str(Path(__file__).resolve().parents[1] / "src")
    script = "import sys,types;sys.path.insert(0," + repr(source) + ");"
    for package in ("panel", "integration", "storage", "domain", "security"):
        script += f"p=types.ModuleType('boca_socios.{package}');p.__path__=[{source!r}+'/boca_socios/{package}'];sys.modules[p.__name__]=p;"
    script += "import boca_socios.host_telegram_protected_custody_caller,boca_socios.host_telegram_backend,boca_socios.host_telegram_maintenance;assert 'cryptography' not in sys.modules"
    result = subprocess.run(  # noqa: S603 - fixed isolated interpreter
        [sys.executable, "-I", "-S", "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_storage_adapters_are_available_without_replacing_pairing_algorithm():
    import inspect

    from boca_socios import host_telegram_protected_custody_caller as caller
    from boca_socios import telegram_pairing_cutover as cutover
    from boca_socios import telegram_pairing_resolver as resolver
    from boca_socios import telegram_same_lease_stage as stage

    for function in (
        caller.run_bound_telegram_staged_custody,
        cutover.execute_protected_pairing,
        stage.execute_staged_pairing_under_lease,
    ):
        assert "storage" in inspect.signature(function).parameters
    assert "unseal" in inspect.signature(resolver.plan_private_telegram_pairing).parameters
    assert "seal" in inspect.signature(resolver.plan_private_telegram_pairing).parameters


def test_v2_sender_refuses_legacy_pair_before_any_network(tmp_path):
    from boca_socios import telegram_one_shot

    assert hasattr(telegram_one_shot, "verified_v2_assertion")
    with pytest.raises(ValueError):
        telegram_one_shot.verified_v2_assertion(tmp_path, expected_source_sha=SHA)


def test_attempt_bound_acceptance_cannot_reuse_other_attempt(tmp_path, monkeypatch):
    from test_telegram_one_shot import CHAT, _assertion, _transport

    transport = _transport(tmp_path)
    first = shot.acceptance_notice_id(transport, SHA, 12345, _assertion(CHAT), attempt_id="111")
    assert first != shot.acceptance_notice_id(
        transport, SHA, 12345, _assertion(CHAT), attempt_id="112"
    )
    assert first != shot.acceptance_notice_id(transport, SHA, 12345, _assertion(CHAT))
    with pytest.raises(shot.OneShotError):
        shot.acceptance_notice_id(transport, SHA, 12345, _assertion(CHAT), attempt_id="../111")
