"""Offline protected-pairing proposal: no Bot API, host or real token access."""

from __future__ import annotations

import hashlib
import hmac
import json
import ssl
from dataclasses import dataclass
from typing import Any

import pytest

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios import telegram_pairing_resolver as resolver
from test_telegram_pairing_ui import TOKEN, _recipient, _run

SOURCE = "a" * 40
CHAT = 1_234_567_890
NOW = 1_700_000_100
NOT_BEFORE = NOW - 300


def _encoded(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


@dataclass
class _FakeBotApi:
    code: str
    matching: list[dict[str, object]] | None = None
    bot: dict[str, object] | None = None
    webhook: dict[str, object] | None = None
    chat: dict[str, object] | None = None
    failure_method: str = ""

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, int | None]] = []

    def __call__(self, token: str, method: str, chat_id: int | None) -> bytes:
        assert token == TOKEN  # Synthetic only, never printed.
        self.calls.append((method, chat_id))
        if method == self.failure_method:
            raise ConnectionError("never surface a token-bearing URL: " + token)
        if method == "getMe":
            return _encoded({"ok": True, "result": self.bot or {"id": 123456, "is_bot": True}})
        if method == "getWebhookInfo":
            return _encoded(
                {"ok": True, "result": self.webhook or {"url": "", "pending_update_count": 1}}
            )
        if method == "getUpdates":
            return _encoded(
                {
                    "ok": True,
                    "result": self.matching if self.matching is not None else [_message(self.code)],
                }
            )
        assert method == "getChat" and chat_id == CHAT
        return _encoded({"ok": True, "result": self.chat or {"id": CHAT, "type": "private"}})


def _message(
    code: str, *, chat: int = CHAT, sender: int = CHAT, date: int = NOW
) -> dict[str, object]:
    return {
        "update_id": 200,
        "message": {
            "message_id": 40,
            "date": date,
            "text": "/start " + code,
            "chat": {"id": chat, "type": "private"},
            "from": {"id": sender, "is_bot": False},
        },
    }


def _prepared() -> tuple[bytes, bootstrap.RecipientReceipt, bytes, str]:
    private, receipt, fragment = _recipient()
    result = _run(fragment)
    return (
        private,
        receipt,
        bootstrap._unb64(result["output"], maximum=4096),
        result["command"][7:],
    )


def test_offline_plan_binds_one_realistic_private_update_to_existing_v1_sealed_custody() -> None:
    private, receipt, envelope, code = _prepared()
    api = _FakeBotApi(code)
    plan = resolver.plan_private_telegram_pairing(
        envelope,
        private,
        receipt,
        SOURCE,
        not_before=NOT_BEFORE,
        now=NOW,
        api_fetch=api,
    )
    assert api.calls == [
        ("getMe", None),
        ("getWebhookInfo", None),
        ("getUpdates", None),
        ("getChat", CHAT),
    ]
    assert bootstrap._decrypt(plan.sealed_v1_envelope, private, receipt) == (
        TOKEN.encode(),
        str(CHAT).encode(),
    )
    assert TOKEN.encode() not in plan.sealed_v1_envelope
    assert str(CHAT).encode() not in plan.sealed_v1_envelope
    assert plan.receipt.state == "READY_FOR_PROTECTED_INSTALL"
    assert plan.receipt.notification_receipt == "UNVERIFIED"
    assert plan.receipt.source_sha == SOURCE
    assert plan.receipt.recipient_fingerprint == receipt.fingerprint
    assert plan.receipt.discovery_update_id == 200
    assert plan.receipt.bot_id == 123456
    assert (
        plan.receipt.expected_chat_hmac
        == hmac.new(TOKEN.encode(), str(CHAT).encode(), hashlib.sha256).hexdigest()
    )
    assert len(plan.receipt.one_time_fence) == 64
    assert TOKEN not in repr(plan) and str(CHAT) not in repr(plan)
    assert plan.receipt.expected_chat_hmac not in repr(plan)
    assert plan.receipt.one_time_fence not in repr(plan)


def test_distinct_source_and_update_bind_different_replay_fences() -> None:
    private, receipt, envelope, code = _prepared()
    api = _FakeBotApi(code)
    first = resolver.plan_private_telegram_pairing(
        envelope,
        private,
        receipt,
        SOURCE,
        not_before=NOT_BEFORE,
        now=NOW,
        api_fetch=api,
    )
    second = resolver.plan_private_telegram_pairing(
        envelope,
        private,
        receipt,
        "b" * 40,
        not_before=NOT_BEFORE,
        now=NOW,
        api_fetch=api,
    )
    assert first.receipt.one_time_fence != second.receipt.one_time_fence
    assert first.receipt.expected_chat_hmac == second.receipt.expected_chat_hmac


@pytest.mark.parametrize(
    "source,not_before,now",
    [
        ("bad", NOT_BEFORE, NOW),
        (SOURCE, NOW + 1, NOW),
        (SOURCE, NOW - 3601, NOW),
        (SOURCE, 0, True),
        (SOURCE, -1, NOW),
    ],
)
def test_invalid_host_source_or_time_fails_before_any_api_call(
    source: str, not_before: int, now: int
) -> None:
    private, receipt, envelope, code = _prepared()
    api = _FakeBotApi(code)
    with pytest.raises(resolver.PairingResolutionError, match="telegram_source_unverified"):
        resolver.plan_private_telegram_pairing(
            envelope,
            private,
            receipt,
            source,
            not_before=not_before,
            now=now,
            api_fetch=api,
        )
    assert api.calls == []


def test_invalid_ciphertext_fails_before_any_api_call() -> None:
    private, receipt, _envelope, code = _prepared()
    api = _FakeBotApi(code)
    with pytest.raises(resolver.PairingResolutionError, match="telegram_v2_envelope_unverified"):
        resolver.plan_private_telegram_pairing(
            b"plaintext-token-is-never-accepted",
            private,
            receipt,
            SOURCE,
            not_before=NOT_BEFORE,
            now=NOW,
            api_fetch=api,
        )
    assert api.calls == []


@pytest.mark.parametrize(
    "bot",
    [
        {"id": 123457, "is_bot": True},
        {"id": 123456, "is_bot": False},
        {"id": "123456", "is_bot": True},
        {"id": True, "is_bot": True},
    ],
)
def test_wrong_get_me_identity_fails_before_updates_or_chat(bot: dict[str, object]) -> None:
    private, receipt, envelope, code = _prepared()
    api = _FakeBotApi(code, bot=bot)
    with pytest.raises(resolver.PairingResolutionError, match="telegram_bot_identity_unverified"):
        resolver.plan_private_telegram_pairing(
            envelope,
            private,
            receipt,
            SOURCE,
            not_before=NOT_BEFORE,
            now=NOW,
            api_fetch=api,
        )
    assert api.calls == [("getMe", None)]


@pytest.mark.parametrize("url", ["https://example.com/webhook", None, 42])
def test_any_active_or_malformed_webhook_refuses_to_touch_updates(url: object) -> None:
    private, receipt, envelope, code = _prepared()
    api = _FakeBotApi(code, webhook={"url": url})
    with pytest.raises(
        resolver.PairingResolutionError, match="telegram_webhook_active_or_unverified"
    ):
        resolver.plan_private_telegram_pairing(
            envelope,
            private,
            receipt,
            SOURCE,
            not_before=NOT_BEFORE,
            now=NOW,
            api_fetch=api,
        )
    assert api.calls == [("getMe", None), ("getWebhookInfo", None)]


@pytest.mark.parametrize("candidates", [[], ["stale"], ["duplicate"], ["forged"]])
def test_missing_stale_ambiguous_or_forged_private_start_fails_before_get_chat(
    candidates: list[str],
) -> None:
    private, receipt, envelope, code = _prepared()
    if not candidates:
        updates: list[dict[str, object]] = []
    elif candidates == ["stale"]:
        updates = [_message(code, date=NOT_BEFORE - 1)]
    elif candidates == ["duplicate"]:
        updates = [_message(code), {**_message(code), "update_id": 201}]
    else:
        updates = [_message(code, sender=CHAT + 1)]
    api = _FakeBotApi(code, matching=updates)
    with pytest.raises(
        resolver.PairingResolutionError, match="telegram_private_pairing_unverified"
    ):
        resolver.plan_private_telegram_pairing(
            envelope,
            private,
            receipt,
            SOURCE,
            not_before=NOT_BEFORE,
            now=NOW,
            api_fetch=api,
        )
    assert api.calls == [("getMe", None), ("getWebhookInfo", None), ("getUpdates", None)]


@pytest.mark.parametrize(
    "chat",
    [
        {"id": CHAT, "type": "group"},
        {"id": CHAT + 1, "type": "private"},
        {"id": str(CHAT), "type": "private"},
    ],
)
def test_get_chat_mismatch_blocks_offline_custody_envelope(chat: dict[str, object]) -> None:
    private, receipt, envelope, code = _prepared()
    api = _FakeBotApi(code, chat=chat)
    with pytest.raises(resolver.PairingResolutionError, match="telegram_destination_unverified"):
        resolver.plan_private_telegram_pairing(
            envelope,
            private,
            receipt,
            SOURCE,
            not_before=NOT_BEFORE,
            now=NOW,
            api_fetch=api,
        )
    assert api.calls[-1] == ("getChat", CHAT)


def test_transport_error_never_exposes_token_or_chat() -> None:
    private, receipt, envelope, code = _prepared()
    api = _FakeBotApi(code, failure_method="getUpdates")
    with pytest.raises(resolver.PairingResolutionError) as info:
        resolver.plan_private_telegram_pairing(
            envelope,
            private,
            receipt,
            SOURCE,
            not_before=NOT_BEFORE,
            now=NOW,
            api_fetch=api,
        )
    assert str(info.value) == "telegram_api_unverified"
    assert TOKEN not in str(info.value) and str(CHAT) not in str(info.value)


@pytest.mark.parametrize(
    "bad_result",
    [
        b'{"ok":false,"description":"secret/token-bearing debug data"}',
        b'{"ok":true,"result":{"id":123456,"is_bot":true,"id":123456}}',
        b'{"ok":true,"result":{"id":123456,"is_bot":NaN}}',
        b"not-json",
        b"x" * 4097,
    ],
)
def test_identity_api_payload_rejected_before_any_followup(
    bad_result: bytes,
) -> None:
    private, receipt, envelope, code = _prepared()
    api = _FakeBotApi(code)

    def fetch(token: str, method: str, chat_id: int | None) -> bytes:
        if method == "getMe":
            api.calls.append((method, chat_id))
            return bad_result
        return api(token, method, chat_id)

    with pytest.raises(resolver.PairingResolutionError) as info:
        resolver.plan_private_telegram_pairing(
            envelope,
            private,
            receipt,
            SOURCE,
            not_before=NOT_BEFORE,
            now=NOW,
            api_fetch=fetch,
        )
    assert str(info.value) == "telegram_identity_unverified"
    assert api.calls == [("getMe", None)]


class _Response:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self.status = status
        self.payload = payload

    def read(self, amount: int) -> bytes:
        return self.payload[:amount]


class _Connection:
    def __init__(self, response: _Response, calls: list[tuple[Any, ...]]) -> None:
        self.response = response
        self.calls = calls

    def request(self, method: str, url: str, body: bytes, headers: dict[str, str]) -> None:
        self.calls.append((method, url, body, headers))

    def getresponse(self) -> _Response:
        return self.response

    def close(self) -> None:
        self.calls.append(("close",))


class _CloseFailingConnection(_Connection):
    def close(self) -> None:
        raise RuntimeError("secret token in transport shutdown: " + TOKEN)


def test_real_tls_transport_shape_is_read_only_allowlisted_and_no_offset() -> None:
    calls: list[tuple[Any, ...]] = []

    def factory(*, host: str, timeout: float, context: ssl.SSLContext) -> _Connection:
        assert host == "api.telegram.org" and timeout == 3.0
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
        return _Connection(_Response(b'{"ok":true,"result":[]}'), calls)

    for method, chat_id in (
        ("getMe", None),
        ("getWebhookInfo", None),
        ("getUpdates", None),
        ("getChat", CHAT),
    ):
        assert (
            resolver.read_only_telegram_api(TOKEN, method, chat_id, connection_factory=factory)
            == b'{"ok":true,"result":[]}'
        )
    requests = [call for call in calls if len(call) == 4]
    assert [call[1].split("/")[-1].split("?")[0] for call in requests] == [
        "getMe",
        "getWebhookInfo",
        "getUpdates",
        "getChat",
    ]
    assert all(call[0] == "GET" and call[2] == b"" for call in requests)
    assert all(
        "offset=" not in call[1]
        and "allowed_updates=" not in call[1]
        and "sendMessage" not in call[1]
        for call in requests
    )
    assert all(call[3]["Accept"] == "application/json" for call in requests)
    assert len([call for call in calls if call == ("close",)]) == 4


@pytest.mark.parametrize(
    "method,chat_id",
    [
        ("sendMessage", None),
        ("deleteWebhook", None),
        ("setWebhook", None),
        ("getUpdates", CHAT),
        ("getChat", None),
        ("getChat", -123),
    ],
)
def test_network_transport_never_calls_disallowed_methods_or_destinations(
    method: str, chat_id: int | None
) -> None:
    with pytest.raises(resolver.PairingResolutionError, match="telegram_api_contract_invalid"):
        resolver.read_only_telegram_api(
            TOKEN,
            method,
            chat_id,
            connection_factory=lambda **_kwargs: pytest.fail("network must stay disabled"),
        )


@pytest.mark.parametrize(
    "status,payload",
    [
        (301, b'{"ok":true,"result":[]}'),
        (200, b"x" * 16_385),
        (401, b"token-abuse"),
    ],
)
def test_transport_rejects_redirect_oversize_and_denial_without_token_in_exception(
    status: int, payload: bytes
) -> None:
    calls: list[tuple[Any, ...]] = []
    with pytest.raises(resolver.PairingResolutionError) as info:
        resolver.read_only_telegram_api(
            TOKEN,
            "getUpdates",
            None,
            connection_factory=lambda **_kwargs: _Connection(_Response(payload, status), calls),
        )
    assert str(info.value) == "telegram_api_unverified"
    assert TOKEN not in str(info.value)
    assert ("close",) in calls


def test_connection_close_failure_is_redacted_even_after_valid_api_response() -> None:
    with pytest.raises(resolver.PairingResolutionError) as info:
        resolver.read_only_telegram_api(
            TOKEN,
            "getMe",
            None,
            connection_factory=lambda **_kwargs: _CloseFailingConnection(
                _Response(b'{"ok":true,"result":{}}'), []
            ),
        )
    assert str(info.value) == "telegram_api_unverified"
    assert TOKEN not in str(info.value)
