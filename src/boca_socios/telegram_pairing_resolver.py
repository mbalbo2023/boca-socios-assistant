"""Read-only Telegram Bot API pairing evidence and an offline V1 install plan.

This module has **no CLI, host entry point or database/file writes**. A future
protected, exact-SHA Boca host operation must first prove stopped controller,
authenticated owner, dedicated volume, recipient identity, image, network and
CPU/memory budgets. Only then may it call ``plan_private_telegram_pairing``
with the explicitly injected ``read_only_telegram_api`` transport.

No production call is made merely by importing this module. The output is a
sealed V1 envelope for the existing offline custody installer, not a claim of
installation, sender activation or human notification receipt.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import re
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios.telegram_pairing_bootstrap import PairingEnvelopeError, unseal_pairing
from boca_socios.telegram_private_chat_discovery import DiscoveryError, discover_private_chat

_BOT_API_HOST = "api.telegram.org"
_METHODS = frozenset({"getMe", "getWebhookInfo", "getUpdates", "getChat"})
_MAX_IDENTITY = 4096
_MAX_UPDATES = 16_384
_SOURCE_SHA = re.compile(r"[0-9a-f]{40}\Z")


class PairingResolutionError(ValueError):
    """Fixed failure code; never holds the Telegram token or private chat ID."""


class _Response(Protocol):
    status: int

    def read(self, amount: int) -> bytes: ...


class _Connection(Protocol):
    def request(self, method: str, url: str, body: bytes, headers: dict[str, str]) -> None: ...

    def getresponse(self) -> _Response: ...

    def close(self) -> None: ...


TelegramApiFetch = Callable[[str, str, int | None], bytes]


@dataclass(frozen=True, slots=True)
class PairingInstallReceipt:
    """Redacted, provisional evidence; NOT a physical owner delivery receipt."""

    source_sha: str
    recipient_fingerprint: str
    bot_id: int
    discovery_update_id: int
    pairing_observed_at: int
    state: str = "READY_FOR_PROTECTED_INSTALL"
    notification_receipt: str = "UNVERIFIED"
    expected_chat_hmac: str = field(default="", repr=False)
    one_time_fence: str = field(default="", repr=False)


@dataclass(frozen=True, slots=True)
class PairingInstallPlan:
    """Sealed in-memory handoff; its repr is safe for generic host receipts."""

    receipt: PairingInstallReceipt
    sealed_v1_envelope: bytes = field(repr=False)


def read_only_telegram_api(
    token: str,
    method: str,
    chat_id: int | None,
    *,
    connection_factory: Callable[..., _Connection] = http.client.HTTPSConnection,
) -> bytes:
    """One fixed TLS Bot API read; no webhook edits, offsets or sendMessage.

    A Bot API token necessarily appears in the TLS-encrypted request target.
    Never log this target or any transport exception. Test callers inject a
    fake connection; only a protected dedicated egress may use the real one.
    """
    if (
        not isinstance(token, str)
        or re.fullmatch(r"[1-9][0-9]{0,15}:[A-Za-z0-9_-]{8,128}", token) is None
        or int(token.split(":", 1)[0]) >= 2**52
        or not isinstance(method, str)
        or method not in _METHODS
        or (method == "getChat") != (type(chat_id) is int and 0 < chat_id < 2**52)
        or (method != "getChat" and chat_id is not None)
    ):
        raise PairingResolutionError("telegram_api_contract_invalid")
    connection: _Connection | None = None
    failed = False
    result: bytes | None = None
    try:
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
            raise PairingResolutionError("telegram_tls_unverified")
        connection = connection_factory(host=_BOT_API_HOST, timeout=3.0, context=context)
        suffix = f"?chat_id={chat_id}" if chat_id is not None else ""
        target = f"/bot{token}/{method}{suffix}"
        connection.request(
            "GET",
            target,
            b"",
            {"Accept": "application/json", "Cache-Control": "no-store", "Connection": "close"},
        )
        response = connection.getresponse()
        limit = _MAX_UPDATES if method == "getUpdates" else _MAX_IDENTITY
        raw = response.read(limit + 1)
        if response.status != 200 or not isinstance(raw, bytes) or not 0 < len(raw) <= limit:
            raise PairingResolutionError("telegram_api_unverified")
        result = raw
    except Exception:
        # Transport exceptions may contain the token-bearing URL or private ID.
        failed = True
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                failed = True
    if failed or result is None:
        raise PairingResolutionError("telegram_api_unverified") from None
    return result


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PairingResolutionError("telegram_identity_unverified")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise PairingResolutionError("telegram_identity_unverified")


def _result(raw: bytes) -> dict[str, object]:
    try:
        if not isinstance(raw, bytes) or not 0 < len(raw) <= _MAX_IDENTITY:
            raise ValueError("size")
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique,
            parse_constant=_reject_constant,
        )
        if (
            not isinstance(payload, dict)
            or payload.get("ok") is not True
            or not isinstance(payload.get("result"), dict)
        ):
            raise ValueError("bad result")
        return cast(dict[str, object], payload["result"])
    except (ValueError, UnicodeError, TypeError):
        raise PairingResolutionError("telegram_identity_unverified") from None


def plan_private_telegram_pairing(
    v2_envelope: bytes,
    private_key: bytes,
    recipient: bootstrap.RecipientReceipt,
    source_sha: str,
    *,
    not_before: int,
    now: int,
    api_fetch: TelegramApiFetch,
) -> PairingInstallPlan:
    """Resolve uniquely paired private chat; return sealed V1 install plan.

    Caller must supply a trusted host time window <=3600s and exactly pinned
    source SHA. No read/write of `/run/telegram`, DB, Docker or owner panel here.
    A future protected adapter MUST consume ``one_time_fence`` atomically in
    custody and separately obtain physical Telegram-human delivery receipt.
    """
    if (
        not isinstance(source_sha, str)
        or _SOURCE_SHA.fullmatch(source_sha) is None
        or not callable(api_fetch)
        or type(not_before) is not int
        or type(now) is not int
        or not_before < 0
        or now < not_before
        or now - not_before > 3600
    ):
        raise PairingResolutionError("telegram_source_unverified")
    try:
        token_bytes, code = unseal_pairing(v2_envelope, private_key, recipient)
    except PairingEnvelopeError:
        raise PairingResolutionError("telegram_v2_envelope_unverified") from None
    token = token_bytes.decode("ascii")
    bot_id = int(token.split(":", 1)[0])

    def fetch(method: str, chat_id: int | None = None) -> bytes:
        try:
            raw = api_fetch(token, method, chat_id)
        except Exception:
            # An injected transport is also untrusted; never reflect details.
            raise PairingResolutionError("telegram_api_unverified") from None
        if not isinstance(raw, bytes):
            raise PairingResolutionError("telegram_api_unverified")
        return raw

    me = _result(fetch("getMe"))
    if type(me.get("id")) is not int or me["id"] != bot_id or me.get("is_bot") is not True:
        raise PairingResolutionError("telegram_bot_identity_unverified")

    webhook = _result(fetch("getWebhookInfo"))
    # A nonempty webhook must be diagnosed, not silently deleted/modified.
    if webhook.get("url") != "":
        raise PairingResolutionError("telegram_webhook_active_or_unverified")

    try:
        found = discover_private_chat(
            fetch("getUpdates"), pairing_code=code, not_before=not_before, now=now
        )
    except DiscoveryError:
        raise PairingResolutionError("telegram_private_pairing_unverified") from None

    chat = _result(fetch("getChat", found.chat_id))
    if (
        type(chat.get("id")) is not int
        or chat["id"] != found.chat_id
        or chat.get("type") != "private"
    ):
        raise PairingResolutionError("telegram_destination_unverified")

    chat_hmac = hmac.new(
        token_bytes, str(found.chat_id).encode("ascii"), hashlib.sha256
    ).hexdigest()
    fence = hmac.new(
        token_bytes,
        (f"boca-telegram-pairing-consumed-v2:{source_sha}:{found.update_id}:{code}").encode(
            "ascii"
        ),
        hashlib.sha256,
    ).hexdigest()
    legacy_envelope = bootstrap.seal_for_recipient(recipient, token, str(found.chat_id))
    return PairingInstallPlan(
        receipt=PairingInstallReceipt(
            source_sha=source_sha,
            recipient_fingerprint=recipient.fingerprint,
            bot_id=bot_id,
            discovery_update_id=found.update_id,
            pairing_observed_at=now,
            expected_chat_hmac=chat_hmac,
            one_time_fence=fence,
        ),
        sealed_v1_envelope=legacy_envelope,
    )
