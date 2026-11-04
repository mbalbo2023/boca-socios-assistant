"""Offline Bot API pairing-contract tests: no token, network, or host effects."""

from __future__ import annotations

import json

import pytest

from boca_socios.telegram_private_chat_discovery import (
    DiscoveryError,
    discover_private_chat,
)

PAIRING = "aB_0123456789-Zxyz123456789"
NOW = 1793823000
CHAT = 123456789


def api_update(
    *,
    chat_id: int = CHAT,
    sender_id: int = CHAT,
    chat_type: str = "private",
    text: str = "/start " + PAIRING,
    date: int = NOW - 15,
    update_id: int = 12,
    is_bot: bool = False,
) -> dict[str, object]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 5,
            "date": date,
            "text": text,
            "from": {"id": sender_id, "is_bot": is_bot},
            "chat": {"id": chat_id, "type": chat_type},
        },
    }


def payload(*updates: dict[str, object]) -> bytes:
    return json.dumps({"ok": True, "result": list(updates)}, separators=(",", ":")).encode()


def test_pairing_binds_single_recent_private_start_to_its_sender() -> None:
    receipt = discover_private_chat(
        payload(api_update()), pairing_code=PAIRING, not_before=NOW - 90, now=NOW
    )
    assert receipt.chat_id == CHAT
    assert receipt.update_id == 12
    assert receipt.pairing_confirmed
    assert not hasattr(receipt, "token")


def test_irrelevant_bot_updates_are_not_selected() -> None:
    receipt = discover_private_chat(
        payload(
            api_update(text="/help", update_id=9),
            api_update(chat_type="group", text="/start unrelated", update_id=10),
            api_update(update_id=11),
        ),
        pairing_code=PAIRING,
        not_before=NOW - 90,
        now=NOW,
    )
    assert receipt.update_id == 11


@pytest.mark.parametrize(
    "updates",
    [
        (),
        (api_update(chat_type="group"),),
        (api_update(chat_type="supergroup"),),
        (api_update(sender_id=CHAT + 1),),
        (api_update(is_bot=True),),
        (api_update(text="/start"),),
        (api_update(text="/start wrong-code"),),
        (api_update(date=NOW - 3601),),
        (api_update(date=NOW + 31),),
        (api_update(chat_id=-100123),),
        (api_update(sender_id=0, chat_id=0),),
        (api_update(update_id=12), api_update(update_id=13)),
    ],
)
def test_pairing_never_guesses_missing_or_ambiguous_identity(
    updates: tuple[dict[str, object], ...],
) -> None:
    with pytest.raises(DiscoveryError):
        discover_private_chat(payload(*updates), pairing_code=PAIRING, not_before=NOW - 90, now=NOW)


@pytest.mark.parametrize(
    "bad_code",
    ["", "short", "contains spaces", "bad/route", "a" * 65, "a" * 22 + "é", "a" * 24 + "="],
)
def test_pairing_code_must_be_canonical_and_nontrivial(bad_code: str) -> None:
    with pytest.raises(DiscoveryError):
        discover_private_chat(
            payload(api_update()), pairing_code=bad_code, not_before=NOW - 90, now=NOW
        )


@pytest.mark.parametrize(
    ("not_before", "now"),
    [(NOW + 1, NOW), (-1, NOW), (NOW - 7200, NOW), (NOW - 90, -1)],
)
def test_invalid_trusted_time_window_is_rejected(not_before: int, now: int) -> None:
    with pytest.raises(DiscoveryError):
        discover_private_chat(
            payload(api_update()), pairing_code=PAIRING, not_before=not_before, now=now
        )


@pytest.mark.parametrize(
    "data",
    [
        b'{"ok":true,"ok":true,"result":[]}',
        b'{"ok":true,"result":[{"update_id":1,"update_id":2}]}',
        b'{"ok":true,"result":[]}{"ok":true}',
        b'{"ok":true,"result":[}',
        b'{"ok":false,"result":[]}',
        b'{"ok":1,"result":[]}',
        b'{"ok":true,"result":{}}',
        b'{"ok":true,"result":null}',
        b'{"ok":true,"result":[]}',
        b"a" * 16385,
    ],
)
def test_invalid_or_duplicate_json_and_no_matching_message_fail_closed(data: bytes) -> None:
    with pytest.raises(DiscoveryError):
        discover_private_chat(data, pairing_code=PAIRING, not_before=NOW - 90, now=NOW)


def test_bogus_integer_booleans_and_duplicate_update_ids_are_rejected() -> None:
    malformed = api_update(update_id=True)
    with pytest.raises(DiscoveryError):
        discover_private_chat(
            payload(malformed), pairing_code=PAIRING, not_before=NOW - 90, now=NOW
        )
    duplicate = payload(api_update(update_id=7), api_update(text="/help", update_id=7))
    with pytest.raises(DiscoveryError):
        discover_private_chat(duplicate, pairing_code=PAIRING, not_before=NOW - 90, now=NOW)


def test_rejected_receipts_do_not_include_sensitive_pairing_values() -> None:
    try:
        discover_private_chat(
            payload(api_update(text="/start wrong")),
            pairing_code=PAIRING,
            not_before=NOW - 90,
            now=NOW,
        )
    except DiscoveryError as exc:
        assert PAIRING not in str(exc)
        assert str(CHAT) not in str(exc)
