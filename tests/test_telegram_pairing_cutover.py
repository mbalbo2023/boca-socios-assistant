"""Offline cutover adapter evidence: no real Telegram, host, SSH or sender."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import telegram_pairing_cutover as cutover
from boca_socios.telegram_pairing_install import PairingCustodyReceipt
from test_telegram_pairing_resolver import (
    NOT_BEFORE,
    NOW,
    SOURCE,
    _FakeBotApi,
    _prepared,
)
from test_telegram_pairing_ui import TOKEN

KEY = bytes(range(32))


def _fixture() -> tuple[
    cutover.CutoverCoordinates, cutover.OwnerPairingReceipt, bytes, bytes, object, str
]:
    private, recipient, v2, code = _prepared()
    coords = cutover.CutoverCoordinates(
        attempt_id="41937000001",
        target_sha=SOURCE,
        image_digest="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64,
        owner_digest="b" * 64,
        lease_digest="c" * 64,
        controller_id="d" * 64,
        recipient_fingerprint=recipient.fingerprint,
    )
    grant = cutover.OwnerPairingReceipt(
        coordinates=coords,
        envelope_sha256=hashlib.sha256(v2).hexdigest(),
        issued_at=NOT_BEFORE,
        expires_at=NOT_BEFORE + 600,
        nonce="f" * 64,
        auth_tag=b"",
    )
    grant = replace(
        grant,
        auth_tag=hmac.new(
            KEY, cutover._PURPOSE + cutover._owner_payload(grant), hashlib.sha256
        ).digest(),
    )
    return coords, grant, v2, private, recipient, code


def _host(
    phase: str,
    coordinates: cutover.CutoverCoordinates,
    *,
    owner_authenticated: bool = True,
    lease: bool = True,
    observed_at: int = NOW,
) -> cutover.HostRecheckReceipt:
    return cutover.HostRecheckReceipt(
        coordinates=coordinates,
        phase=phase,
        observed_at=observed_at,
        rootless_uid=10001,
        owner_authenticated=owner_authenticated,
        singleton_controller_stopped=True,
        sender_off=True,
        schema_0007_ready=True,
        exclusive_lease_held=lease,
        dedicated_telegram_egress=True,
        no_competing_poller=True,
        recipient_custody_verified=True,
        unrelated_services_untouched=True,
    )


def _invoke(
    monkeypatch: pytest.MonkeyPatch,
    *,
    change: str = "",
    owner_key: bytes = KEY,
    now: int = NOW,
    failure_phase: str = "",
    fail_nonce: bool = False,
    fail_api: str = "",
    consume_callback: object = None,
) -> tuple[cutover.ProtectedPairingReceipt | Exception, list[str], list[str]]:
    coords, grant, v2, private, recipient, code = _fixture()
    changes = {
        "owner_digest": {"owner_digest": "e" * 64},
        "lease_digest": {"lease_digest": "e" * 64},
        "controller_id": {"controller_id": "e" * 64},
        "attempt_id": {"attempt_id": "9876"},
        "image_digest": {"image_digest": coords.image_digest[:-1] + "e"},
        "recipient_fingerprint": {"recipient_fingerprint": "e" * 64},
        "source_sha": {"target_sha": "e" * 40},
    }
    if change in changes:
        coords = replace(coords, **changes[change])
    elif change == "owner_hmac":
        grant = replace(grant, auth_tag=b"x" * 32)
    elif change == "envelope":
        v2 = b"tampered"
    phases: list[str] = []
    calls: list[str] = []
    api = _FakeBotApi(code, failure_method=fail_api)

    def recheck(phase: str, coordinates: cutover.CutoverCoordinates):
        phases.append(phase)
        return _host(
            phase,
            coordinates,
            owner_authenticated=phase != failure_phase,
        )

    def consume(_nonce: str, _coords: cutover.CutoverCoordinates) -> bool:
        calls.append("consume")
        return not fail_nonce

    def fetch(token: str, method: str, chat: int | None) -> bytes:
        calls.append(method)
        return api(token, method, chat)

    commit = PairingCustodyReceipt(
        source_sha=SOURCE,
        recipient_fingerprint=recipient.fingerprint,
        bot_id=123456,
    )
    monkeypatch.setattr(
        cutover,
        "install_v2_plan",
        lambda *_args, **_kwargs: (calls.append("install"), commit)[1],
    )
    monkeypatch.setattr(
        cutover,
        "verify_v2_custody",
        lambda *_args, **_kwargs: (calls.append("verify"), commit)[1],
    )
    try:
        result: cutover.ProtectedPairingReceipt | Exception = cutover.execute_protected_pairing(
            coordinates=coords,
            owner_receipt=grant,
            owner_receipt_key=owner_key,
            sealed_v2_envelope=v2,
            recipient=recipient,
            private_key=private,
            directory=Path("/run/telegram"),
            trusted_clock=lambda: now,
            recheck_host=recheck,
            consume_owner_nonce=consume_callback if callable(consume_callback) else consume,
            api_fetch=fetch,
        )
    except cutover.TelegramCutoverError as exc:
        result = exc
    return result, phases, calls


def test_owner_signed_receipt_and_same_lease_rechecks_wrap_every_read_and_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, phases, calls = _invoke(monkeypatch)
    assert isinstance(result, cutover.ProtectedPairingReceipt)
    assert result.state == "CUSTODY_COMMITTED_NO_SEND"
    assert result.human_notification_receipt == "UNVERIFIED"
    assert result.sender_state == "OFF"
    assert phases == [
        "BEFORE_API",
        "BEFORE_getMe",
        "BEFORE_getWebhookInfo",
        "BEFORE_getUpdates",
        "BEFORE_getChat",
        "BEFORE_COMMIT",
        "AFTER_COMMIT",
    ]
    assert calls == [
        "consume",
        "getMe",
        "getWebhookInfo",
        "getUpdates",
        "getChat",
        "install",
        "verify",
    ]
    assert TOKEN not in repr(result) and "1234567890" not in repr(result)
    assert cutover.CLEANUP_TARGETS == ()


@pytest.mark.parametrize(
    "change",
    [
        "owner_digest",
        "lease_digest",
        "controller_id",
        "attempt_id",
        "image_digest",
        "recipient_fingerprint",
        "source_sha",
        "envelope",
        "owner_hmac",
        "expired",
        "wrong_key",
    ],
)
def test_invalid_owner_or_source_binding_aborts_before_host_or_provider(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    result, phases, calls = _invoke(
        monkeypatch,
        change=change,
        owner_key=b"x" * 32 if change == "wrong_key" else KEY,
        now=NOT_BEFORE + 601 if change == "expired" else NOW,
    )
    assert isinstance(result, cutover.TelegramCutoverError)
    assert phases == [] and calls == []
    assert TOKEN not in str(result)


@pytest.mark.parametrize(
    "failure_phase",
    [
        "BEFORE_API",
        "BEFORE_getMe",
        "BEFORE_getWebhookInfo",
        "BEFORE_getUpdates",
        "BEFORE_getChat",
        "BEFORE_COMMIT",
        "AFTER_COMMIT",
    ],
)
def test_host_lease_or_owner_recheck_failure_is_redacted_and_blocks_later_effects(
    monkeypatch: pytest.MonkeyPatch, failure_phase: str
) -> None:
    result, phases, calls = _invoke(monkeypatch, failure_phase=failure_phase)
    assert isinstance(result, cutover.TelegramCutoverError)
    assert "cutover_host_recheck_unverified" in str(result) or (
        failure_phase.startswith("BEFORE_get")
        and "telegram_private_discovery_unverified" in str(result)
    )
    assert failure_phase in phases
    if failure_phase not in ("AFTER_COMMIT",):
        assert "install" not in calls
    assert TOKEN not in str(result)


@pytest.mark.parametrize("case", ["nonce", "provider_getMe", "provider_getUpdates"])
def test_replayed_owner_nonce_or_bad_provider_never_installs(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    result, phases, calls = _invoke(
        monkeypatch,
        fail_nonce=case == "nonce",
        fail_api=case.removeprefix("provider_") if case.startswith("provider_") else "",
    )
    assert isinstance(result, cutover.TelegramCutoverError)
    assert "install" not in calls and "verify" not in calls
    assert TOKEN not in str(result)
    assert phases[0] == "BEFORE_API"


def test_atomic_owner_nonce_consumer_denies_replay_before_second_bot_api_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    used: set[str] = set()

    def consume_once(nonce: str, _coords: cutover.CutoverCoordinates) -> bool:
        if nonce in used:
            return False
        used.add(nonce)
        return True

    first, _, first_calls = _invoke(monkeypatch, consume_callback=consume_once)
    assert isinstance(first, cutover.ProtectedPairingReceipt)
    assert "getChat" in first_calls
    second, second_phases, second_calls = _invoke(monkeypatch, consume_callback=consume_once)
    assert isinstance(second, cutover.TelegramCutoverError)
    assert str(second) == "owner_pairing_nonce_unverified"
    assert second_phases == ["BEFORE_API"]
    assert second_calls == []


@pytest.mark.parametrize("phase", ["preflight", "commit", "verify"])
def test_cli_phases_are_inert_until_single_host_cutover_wires_adapter(
    capsys: pytest.CaptureFixture[str], phase: str
) -> None:
    assert cutover.main((phase,)) == 1
    output = capsys.readouterr().out
    assert output == "BOCA_TELEGRAM_V2 state=NO_GO host_authorization=NOT_CONNECTED sender=OFF\n"
    assert cutover.CLEANUP_TARGETS == ()


def test_public_receipts_never_reveal_owner_hmac_or_pairing_nonce() -> None:
    coords, receipt, envelope, private, _, code = _fixture()
    visible = (
        repr(coords)
        + repr(receipt)
        + repr(
            cutover.ProtectedPairingReceipt(
                coords.attempt_id, coords.target_sha, coords.recipient_fingerprint, 123456
            )
        )
    )
    assert TOKEN not in visible
    assert code not in visible
    assert receipt.nonce not in visible
    assert receipt.auth_tag.hex() not in visible
    assert envelope.hex() not in visible and private.hex() not in visible
