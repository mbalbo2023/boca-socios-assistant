"""No provider, sender, portal or Docker in this test: all Telegram is fake."""

from __future__ import annotations

import json

import pytest

from boca_socios import telegram_readonly_exec as helper
from test_telegram_pairing_ui import TOKEN


def _frame(method: str, chat_id: int | None = None) -> bytes:
    return json.dumps(
        {"version": 1, "method": method, "token": TOKEN, "chat_id": chat_id},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def test_four_allowlisted_methods_use_injected_fake_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int | None]] = []

    def fake(token: str, method: str, chat_id: int | None) -> bytes:
        assert token == TOKEN
        calls.append((method, chat_id))
        return b'{"ok":true,"result":{"id":123}}'

    monkeypatch.setattr(helper, "read_only_telegram_api", fake)
    for method, chat in (
        ("getMe", None),
        ("getWebhookInfo", None),
        ("getUpdates", None),
        ("getChat", 12345),
    ):
        reply = helper.one_read(_frame(method, chat))
        assert reply.startswith(b'{"response_base64url":')
        assert TOKEN.encode() not in reply
    assert [entry[0] for entry in calls] == [
        "getMe",
        "getWebhookInfo",
        "getUpdates",
        "getChat",
    ]


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b'{"version":1,"method":"sendMessage","token":"x","chat_id":123}',
        b'{"version":1,"method":"getMe","token":"x","chat_id":123}',
        b'{"version":1,"method":"getMe","token":"x","chat_id":null, "extra":1}',
        b'{"version":1,"version":1,"method":"getMe","token":"x","chat_id":null}',
        b"x" * 513,
        _frame("getMe") + b" ",
    ],
)
def test_invalid_frames_cannot_reach_provider(
    monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    touched: list[str] = []
    monkeypatch.setattr(helper, "read_only_telegram_api", lambda *_a: touched.append("GET"))
    with pytest.raises(helper.TelegramReadOnlyExecError) as failure:
        helper.one_read(payload)
    assert TOKEN not in str(failure.value)
    assert touched == []


def test_cli_is_inert_without_runtime_proof(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(helper.os, "geteuid", lambda: 999)
    monkeypatch.setattr(helper.os, "getegid", lambda: 999)
    assert helper.main(("get",)) == 2
    assert "RUNTIME_BOUNDARY" in capsys.readouterr().err
