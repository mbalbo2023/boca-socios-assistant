"""A protected Telegram test may send exactly one synthetic notice."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from importlib.resources import files
from pathlib import Path
from uuid import UUID

import pytest

from boca_socios import telegram_one_shot as shot
from boca_socios.notify.outbox import NoticeKind
from boca_socios.notify.telegram_transport import TelegramAck, TelegramNotice, TelegramTransport
from boca_socios.telegram_storage_gate import MIGRATIONS

TOKEN = "12345:synthetic-bot-token-for-tests"
CHAT = "123456789"
SHA = "a" * 40


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
        hashlib.sha256(CHAT.encode()).hexdigest(),
        connection_factory=lambda **_kwargs: _Connection(next(responses), calls),
    )
    assert [method for method, _url in calls] == ["GET", "GET"]
    assert calls[0][1].endswith("/getMe") and calls[1][1].endswith("/getChat?chat_id=" + CHAT)


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
            hashlib.sha256(chat.encode()).hexdigest(),
            connection_factory=lambda **_kwargs: _Connection(next(responses), calls),
        )
    assert all("sendMessage" not in url for _method, url in calls)


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
