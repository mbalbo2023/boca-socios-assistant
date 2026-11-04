"""Pure strict parser for future private Telegram pairing via Bot API updates.

No token is accepted, stored, logged or placed in a URL by this module. A
future owner-approved protected operation must retrieve `getUpdates` using a
token that *never leaves* isolated Telegram custody, and verify real Bot API
TLS and bot identity separately. Until then this is only a testable contract.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_PAIRING_CODE = re.compile(r"[A-Za-z0-9_-]{24,64}\Z")
_MAX_RESPONSE_BYTES = 16_384
_MAX_UPDATES = 100
_MAX_CHAT_ID = (1 << 52) - 1
_MAX_PAIRING_SECONDS = 3600


class DiscoveryError(ValueError):
    """Fail-closed pairing error with no owner, chat or token details."""


@dataclass(frozen=True)
class PrivateChatDiscovery:
    """In-memory candidate, not a configured bot or confirmed delivery."""

    chat_id: int
    update_id: int
    pairing_confirmed: bool = True


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise DiscoveryError("Telegram update has duplicate fields")
        result[name] = value
    return result


def _reject_non_json_constant(_value: str) -> None:
    raise DiscoveryError("Telegram update uses non-JSON numeric data")


def _positive_id(value: object) -> bool:
    return type(value) is int and 0 < value <= _MAX_CHAT_ID


def discover_private_chat(
    bot_api_response: bytes,
    *,
    pairing_code: str,
    not_before: int,
    now: int,
) -> PrivateChatDiscovery:
    """Require exactly one fresh private `/start <code>` from its chat owner.

    The pairing code must be generated with cryptographic randomness outside
    this helper, sealed with the bot token, and never printed to public CI.
    `not_before`/`now` must come from the protected host, not the API message.
    No update offset is advanced here; this function never contacts Telegram.
    """
    if (
        not isinstance(pairing_code, str)
        or not _PAIRING_CODE.fullmatch(pairing_code)
        or type(not_before) is not int
        or type(now) is not int
        or not_before < 0
        or now < not_before
        or now - not_before > _MAX_PAIRING_SECONDS
    ):
        raise DiscoveryError("Telegram pairing parameters are invalid")
    if type(bot_api_response) is not bytes or not 0 < len(bot_api_response) <= _MAX_RESPONSE_BYTES:
        raise DiscoveryError("Telegram pairing response size is invalid")
    try:
        response = json.loads(
            bot_api_response.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_non_json_constant,
        )
    except (ValueError, UnicodeError, TypeError) as exc:
        raise DiscoveryError("Telegram pairing response cannot be verified") from exc
    if not isinstance(response, dict) or response.get("ok") is not True:
        raise DiscoveryError("Telegram pairing response was not accepted")
    updates = response.get("result")
    if not isinstance(updates, list) or len(updates) > _MAX_UPDATES:
        raise DiscoveryError("Telegram pairing update list is invalid")
    matching: list[PrivateChatDiscovery] = []
    seen_updates: set[int] = set()
    for update in updates:
        if not isinstance(update, dict):
            raise DiscoveryError("Telegram pairing update is not an object")
        update_id = update.get("update_id")
        if type(update_id) is not int or update_id < 0 or update_id in seen_updates:
            raise DiscoveryError("Telegram update identity is ambiguous")
        seen_updates.add(update_id)
        message = update.get("message")
        if not isinstance(message, dict) or message.get("text") != "/start " + pairing_code:
            continue
        sender = message.get("from")
        chat = message.get("chat")
        sent_at = message.get("date")
        if (
            not isinstance(sender, dict)
            or not isinstance(chat, dict)
            or not _positive_id(sender.get("id"))
            or sender.get("is_bot") is not False
            or not _positive_id(chat.get("id"))
            or chat.get("id") != sender.get("id")
            or chat.get("type") != "private"
            or type(sent_at) is not int
            or not_before > sent_at
            or sent_at > now + 30
            or now - sent_at > _MAX_PAIRING_SECONDS
        ):
            raise DiscoveryError("Telegram pairing was not from a verified private chat")
        matching.append(PrivateChatDiscovery(chat_id=chat["id"], update_id=update_id))
    if len(matching) != 1:
        raise DiscoveryError("Telegram pairing requires one unique private confirmation")
    return matching[0]
