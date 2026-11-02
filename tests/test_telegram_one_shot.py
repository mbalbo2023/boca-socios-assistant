"""A protected Telegram test may send exactly one synthetic notice."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import sqlite3
from importlib.resources import files
from pathlib import Path
from uuid import UUID

import pytest

from boca_socios import telegram_one_shot as shot
from boca_socios.notify.outbox import NoticeKind, NotificationRequest
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.notify.telegram_transport import (
    TelegramAck,
    TelegramNotice,
    TelegramTransport,
    TelegramUnconfirmed,
)
from boca_socios.telegram_storage_gate import MIGRATIONS

TOKEN = "12345:synthetic-bot-token-for-tests"
CHAT = "123456789"
SHA = "a" * 40


def _assertion(chat: str) -> str:
    return hmac.new(TOKEN.encode(), chat.encode(), hashlib.sha256).hexdigest()


class _Response:
    def __init__(self, data: dict[str, object], status: int = 200) -> None:
        self.status = status
        self.data = json.dumps(data).encode()

    def read(self, length: int) -> bytes:
        return self.data[:length]


class _Connection:
    def __init__(self, response: _Response, calls: list[tuple[str, str]]) -> None:
        self.response = response
        self.calls = calls

    def request(self, method: str, url: str, body: bytes, headers: dict[str, str]) -> None:
        self.calls.append((method, url))
        assert not body and headers["Accept"] == "application/json"

    def getresponse(self) -> _Response:
        return self.response

    def close(self) -> None:
        pass


def _transport(tmp_path: Path, chat: str = CHAT) -> TelegramTransport:
    token = tmp_path / "bot_token"
    destination = tmp_path / "chat_id"
    token.write_text(TOKEN)
    destination.write_text(chat)
    token.chmod(0o400)
    destination.chmod(0o400)
    return TelegramTransport(token, destination)


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        for version, filename in enumerate(MIGRATIONS, 1):
            sql = files("boca_socios.storage.migrations").joinpath(filename).read_text()
            connection.executescript(sql)
            connection.execute(
                "INSERT INTO schema_migrations(version, checksum) VALUES (?, ?)",
                (version, hashlib.sha256(sql.encode()).hexdigest()),
            )
    path.chmod(0o600)


def test_identity_checks_bot_and_exact_owner_private_chat(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    responses = iter(
        [
            _Response({"ok": True, "result": {"id": 12345, "is_bot": True}}),
            _Response({"ok": True, "result": {"id": int(CHAT), "type": "private"}}),
        ]
    )
    transport = _transport(tmp_path)
    shot.check_identity(
        transport,
        12345,
        _assertion(CHAT),
        connection_factory=lambda **_kwargs: _Connection(next(responses), calls),
    )
    assert [method for method, _url in calls] == ["GET", "GET"]
    assert calls[0][1].endswith("/getMe") and calls[1][1].endswith("/getChat?chat_id=" + CHAT)
    (tmp_path / "chat_id").chmod(0o600)
    (tmp_path / "chat_id").write_text("987654321")
    (tmp_path / "chat_id").chmod(0o400)
    with pytest.raises(TelegramUnconfirmed, match="configuration changed"):
        transport.preflight()


@pytest.mark.parametrize(
    ("chat", "result"),
    [
        ("-100123", {"id": -100123, "type": "supergroup"}),
        (CHAT, {"id": int(CHAT) + 1, "type": "private"}),
        (CHAT, {"id": int(CHAT), "type": "group"}),
    ],
)
def test_group_or_mismatched_destination_never_sends(
    tmp_path: Path, chat: str, result: dict[str, object]
) -> None:
    calls: list[tuple[str, str]] = []
    responses = iter(
        [
            _Response({"ok": True, "result": {"id": 12345, "is_bot": True}}),
            _Response({"ok": True, "result": result}),
        ]
    )
    with pytest.raises(shot.OneShotError):
        shot.check_identity(
            _transport(tmp_path, chat),
            12345,
            _assertion(chat),
            connection_factory=lambda **_kwargs: _Connection(next(responses), calls),
        )
    assert all("sendMessage" not in url for _method, url in calls)


def test_owner_hmac_mismatch_blocks_before_any_bot_api_request(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    with pytest.raises(shot.OneShotError, match="owner_destination_mismatch"):
        shot.check_identity(
            _transport(tmp_path),
            12345,
            "f" * 64,
            connection_factory=lambda **_kwargs: _Connection(
                _Response({"ok": True, "result": {}}), calls
            ),
        )
    assert calls == []


def test_wrong_bot_id_or_redirect_blocks_before_chat_or_send(tmp_path: Path) -> None:
    for index, response in enumerate(
        (
            _Response({"ok": True, "result": {"id": 54321, "is_bot": True}}),
            _Response({"ok": True, "result": {"id": 12345, "is_bot": True}}, status=302),
        )
    ):
        directory = tmp_path / str(index)
        directory.mkdir()
        calls: list[tuple[str, str]] = []
        with pytest.raises(shot.OneShotError):
            shot.check_identity(
                _transport(directory),
                12345,
                _assertion(CHAT),
                connection_factory=lambda response=response, calls=calls, **_kwargs: _Connection(
                    response, calls
                ),
            )
        assert len(calls) == 1 and calls[0][1].endswith("/getMe")


def test_effective_worker_limits_are_required_before_any_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shot, "CGROUP_ROOT", tmp_path)
    monkeypatch.setattr(shot, "SELF_CGROUP", tmp_path / "self")
    for name, value in (
        ("cgroup.controllers", "cpu memory pids"),
        ("self", "0::/"),
        ("cpu.max", "25000 100000"),
        ("memory.max", "134217728"),
        ("pids.max", "32"),
    ):
        (tmp_path / name).write_text(value)
    shot.require_effective_limits()
    (tmp_path / "pids.max").write_text("max")
    with pytest.raises(shot.OneShotError, match="effective_worker_budget_unverified"):
        shot.require_effective_limits()


class _Sender:
    def __init__(self, *, ambiguous: bool = False) -> None:
        self.calls: list[TelegramNotice] = []
        self.ambiguous = ambiguous

    def preflight(self) -> None:
        pass

    async def send(self, notice: TelegramNotice) -> TelegramAck:
        self.calls.append(notice)
        if self.ambiguous:
            raise TimeoutError("synthetic timeout")
        return TelegramAck(42)


def test_one_synthetic_notice_is_fenced_and_never_replayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "boca.sqlite3"
    _database(path)
    monkeypatch.setattr(shot, "verify_storage", lambda _path: None)
    sender = _Sender()
    receipt = asyncio.run(shot.deliver_once(path, sender, SHA, clock=lambda: 1000.0))
    assert receipt == "API_ACCEPTED" and len(sender.calls) == 1
    assert sender.calls[0].kind is NoticeKind.HEARTBEAT
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT idempotency_key, state, provider_message_id FROM telegram_delivery_attempts"
        ).fetchall()
    assert len(rows) == 1 and UUID(rows[0][0]) == sender.calls[0].idempotency_key
    assert rows[0][1:] == ("api_accepted", 42)
    with pytest.raises(shot.OneShotError):
        asyncio.run(shot.deliver_once(path, sender, SHA, clock=lambda: 1001.0))
    assert len(sender.calls) == 1


def test_ambiguous_send_is_terminal_and_never_replayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "boca.sqlite3"
    _database(path)
    monkeypatch.setattr(shot, "verify_storage", lambda _path: None)
    sender = _Sender(ambiguous=True)
    with pytest.raises(shot.OneShotError):
        asyncio.run(shot.deliver_once(path, sender, SHA, clock=lambda: 1000.0))
    with pytest.raises(shot.OneShotError):
        asyncio.run(shot.deliver_once(path, sender, SHA, clock=lambda: 1001.0))
    assert len(sender.calls) == 1
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT state FROM telegram_delivery_attempts").fetchone() == (
            "ambiguous",
        )


def test_readiness_requires_the_same_pinned_identity_and_prior_api_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "boca.sqlite3"
    _database(path)
    monkeypatch.setattr(shot, "verify_storage", lambda _path: None)
    transport = _transport(tmp_path)
    notice_id = shot.acceptance_notice_id(transport, SHA, 12345, _assertion(CHAT))
    assert notice_id != shot.NOTICE_ID
    assert notice_id == shot.acceptance_notice_id(transport, SHA, 12345, _assertion(CHAT))
    with pytest.raises(shot.OneShotError, match="api_acceptance_unverified"):
        shot.verify_ready(path, transport, SHA, 12345, _assertion(CHAT))
    sender = _Sender()
    assert (
        asyncio.run(shot.deliver_once(path, sender, SHA, notice_id=notice_id, clock=lambda: 1000.0))
        == "API_ACCEPTED"
    )
    shot.verify_ready(path, transport, SHA, 12345, _assertion(CHAT))
    # A fresh process proves the same acceptance without any HTTP request.
    restarted = TelegramTransport(
        tmp_path / "bot_token",
        tmp_path / "chat_id",
        connection_factory=lambda **_kwargs: pytest.fail("readiness must stay offline"),
    )
    shot.verify_ready(path, restarted, SHA, 12345, _assertion(CHAT))
    assert len(sender.calls) == 1 and sender.calls[0].idempotency_key == notice_id
    with pytest.raises(shot.OneShotError, match="api_acceptance_unverified"):
        shot.verify_ready(path, restarted, "b" * 40, 12345, _assertion(CHAT))
    with pytest.raises(shot.OneShotError, match="bot_identity_mismatch"):
        shot.verify_ready(path, restarted, SHA, 54321, _assertion(CHAT))
    with pytest.raises(shot.OneShotError, match="owner_destination_mismatch"):
        shot.verify_ready(path, restarted, SHA, 12345, "f" * 64)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM telegram_delivery_attempts").fetchone() == (
            1,
        )


@pytest.mark.parametrize("historical", [True, False])
def test_generic_acceptance_and_ambiguous_identity_proof_do_not_enable_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, historical: bool
) -> None:
    path = tmp_path / "boca.sqlite3"
    _database(path)
    monkeypatch.setattr(shot, "verify_storage", lambda _path: None)
    transport = _transport(tmp_path)
    bound = shot.acceptance_notice_id(transport, SHA, 12345, _assertion(CHAT))
    sender = _Sender(ambiguous=not historical)
    if historical:
        asyncio.run(shot.deliver_once(path, sender, SHA, clock=lambda: 1000.0))
    else:
        with pytest.raises(shot.OneShotError):
            asyncio.run(shot.deliver_once(path, sender, SHA, notice_id=bound, clock=lambda: 1000.0))
    with pytest.raises(shot.OneShotError, match="api_acceptance_unverified"):
        shot.verify_ready(path, transport, SHA, 12345, _assertion(CHAT))
    assert len(sender.calls) == 1


@pytest.mark.parametrize("replacement", ["token", "destination"])
def test_readiness_pins_before_first_claim_and_refuses_replaced_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    path = tmp_path / "boca.sqlite3"
    _database(path)
    monkeypatch.setattr(shot, "verify_storage", lambda _path: None)
    transport = _transport(tmp_path)
    bound = shot.acceptance_notice_id(transport, SHA, 12345, _assertion(CHAT))
    asyncio.run(shot.deliver_once(path, _Sender(), SHA, notice_id=bound, clock=lambda: 1000.0))
    shot.verify_ready(path, transport, SHA, 12345, _assertion(CHAT))
    selected = tmp_path / ("bot_token" if replacement == "token" else "chat_id")
    selected.chmod(0o600)
    selected.write_text(
        "12345:different-synthetic-token" if replacement == "token" else "987654321"
    )
    selected.chmod(0o400)
    with pytest.raises(TelegramUnconfirmed, match="configuration changed"):
        transport.preflight()


@pytest.mark.parametrize("replacement", ["token", "destination"])
def test_old_acceptance_cannot_authorize_a_new_private_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    path = tmp_path / "boca.sqlite3"
    _database(path)
    monkeypatch.setattr(shot, "verify_storage", lambda _path: None)
    transport = _transport(tmp_path)
    bound = shot.acceptance_notice_id(transport, SHA, 12345, _assertion(CHAT))
    asyncio.run(shot.deliver_once(path, _Sender(), SHA, notice_id=bound, clock=lambda: 1000.0))
    token = "12345:different-synthetic-token" if replacement == "token" else TOKEN
    chat = "987654321" if replacement == "destination" else CHAT
    for filename, content in (("bot_token", token), ("chat_id", chat)):
        selected = tmp_path / filename
        selected.chmod(0o600)
        selected.write_text(content)
        selected.chmod(0o400)
    restarted = TelegramTransport(tmp_path / "bot_token", tmp_path / "chat_id")
    assertion = hmac.new(token.encode(), chat.encode(), hashlib.sha256).hexdigest()
    with pytest.raises(shot.OneShotError, match="api_acceptance_unverified"):
        shot.verify_ready(path, restarted, SHA, 12345, assertion)


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE notification_outbox SET state='exhausted', accepted_at=NULL",
        "UPDATE notification_outbox SET kind='state_changed'",
        "UPDATE notification_outbox SET attempts=2",
        "UPDATE telegram_delivery_attempts SET attempt_number=2",
        "UPDATE telegram_delivery_attempts SET state='prepared', settled_at=NULL, "
        "provider_message_id=NULL",
        "DELETE FROM telegram_delivery_attempts",
    ],
)
def test_readiness_rejects_incomplete_or_inconsistent_api_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    path = tmp_path / "boca.sqlite3"
    _database(path)
    monkeypatch.setattr(shot, "verify_storage", lambda _path: None)
    transport = _transport(tmp_path)
    bound = shot.acceptance_notice_id(transport, SHA, 12345, _assertion(CHAT))
    asyncio.run(shot.deliver_once(path, _Sender(), SHA, notice_id=bound, clock=lambda: 1000.0))
    with sqlite3.connect(path) as connection:
        connection.execute(change)
    with pytest.raises(shot.OneShotError, match="api_acceptance_unverified"):
        shot.verify_ready(path, transport, SHA, 12345, _assertion(CHAT))


def test_readiness_refuses_unresolved_attempt_without_claiming_pending_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "boca.sqlite3"
    _database(path)
    monkeypatch.setattr(shot, "verify_storage", lambda _path: None)
    transport = _transport(tmp_path)
    bound = shot.acceptance_notice_id(transport, SHA, 12345, _assertion(CHAT))
    asyncio.run(shot.deliver_once(path, _Sender(), SHA, notice_id=bound, clock=lambda: 1000.0))
    pending = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
    outbox = SqliteNotificationOutbox(path)
    outbox.enqueue(NotificationRequest(pending, NoticeKind.HEARTBEAT), now=1001.0)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO telegram_delivery_attempts "
            "(idempotency_key,attempt_number,state,prepared_at) VALUES (?,1,'prepared',1001)",
            (str(pending),),
        )
    with pytest.raises(shot.OneShotError, match="api_acceptance_unverified"):
        shot.verify_ready(path, transport, SHA, 12345, _assertion(CHAT))
    assert outbox.get(pending).attempts == 0


def test_verify_ready_cli_never_calls_identity_or_delivery_api(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []
    for key, value in {
        "BOCA_ENVIRONMENT": "staging",
        "BOCA_RUNTIME_MODE": "simulation",
        "BOCA_ENGINE_MODE": "off",
        "BOCA_TELEGRAM_DISPATCH_MODE": "explicit",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(shot, "require_effective_limits", lambda: calls.append("limits"))
    monkeypatch.setattr(shot, "verify_custody", lambda: calls.append("custody"))
    monkeypatch.setattr(shot, "verify_ready", lambda *_args: calls.append("ready"))
    monkeypatch.setattr(shot, "check_identity", lambda *_args: pytest.fail("network forbidden"))
    monkeypatch.setattr(shot, "deliver_once", lambda *_args: pytest.fail("send forbidden"))
    assert shot.main(("verify-ready", SHA, "12345", _assertion(CHAT))) == 0
    assert calls == ["limits", "custody", "ready"]
    assert capsys.readouterr().out == (
        f"BOCA_TELEGRAM_READY state=VERIFIED source_sha={SHA} api_accepted=1 identity=pinned\n"
    )


def test_one_shot_cli_records_the_identity_bound_acceptance_and_cannot_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "boca.sqlite3"
    _database(path)
    transport = _transport(tmp_path)
    sender = _Sender()
    monkeypatch.setattr(shot, "DATABASE", path)
    monkeypatch.setattr(shot, "verify_storage", lambda _path: None)
    monkeypatch.setattr(shot, "verify_custody", lambda: None)
    monkeypatch.setattr(shot, "require_effective_limits", lambda: None)
    monkeypatch.setattr(shot, "TelegramTransport", lambda *_args: transport)
    monkeypatch.setattr(transport, "send", sender.send)
    monkeypatch.setattr(shot, "check_identity", lambda *_args: None)
    for key, value in {
        "BOCA_ENVIRONMENT": "staging",
        "BOCA_RUNTIME_MODE": "simulation",
        "BOCA_ENGINE_MODE": "off",
        "BOCA_TELEGRAM_DISPATCH_MODE": "explicit",
    }.items():
        monkeypatch.setenv(key, value)
    args = ("test", SHA, "12345", _assertion(CHAT))
    assert shot.main(args) == 0
    assert sender.calls[0].idempotency_key == shot.acceptance_notice_id(
        transport, SHA, 12345, _assertion(CHAT)
    )
    shot.verify_ready(path, transport, SHA, 12345, _assertion(CHAT))
    assert shot.main(args) == 1
    assert len(sender.calls) == 1
    output = capsys.readouterr()
    assert output.out == (
        f"BOCA_TELEGRAM_TEST state=API_ACCEPTED source_sha={SHA} synthetic=1 human_receipt=unverified\n"
    )
    assert output.err == "BOCA_TELEGRAM_TEST state=NO_GO\n"
