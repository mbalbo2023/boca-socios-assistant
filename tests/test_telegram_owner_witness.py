"""Telegram owner-stage HMAC *review* only; no passkey or host effects."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace

import pytest

from boca_socios.telegram_owner_witness import (
    OwnerStageContext,
    OwnerStageWitness,
    OwnerWitnessNoGo,
    review_owner_stage_witness,
)

KEY = b"witness-test-key-only-" + b"z" * 10
DIFFERENT_KEY = b"different-test-key--" + b"x" * 12
DOMAIN = b"boca-telegram-owner-stage-witness-v1:\x00"
NOW = 1_790_000_000
STAGED = NOW - 90
PROOF = STAGED - 3
FP = "c" * 64
ENVELOPE_SHA = "d" * 64
OWNER_SHA = "e" * 64
VERIFIER_SHA = "f" * 64
OPERATION_SHA = "1" * 64
CHALLENGE_SHA = "2" * 64
STAGE_ID = "3" * 64
NONCE = "4" * 64


def _context() -> OwnerStageContext:
    return OwnerStageContext(
        stage_id=STAGE_ID,
        staged_at=STAGED,
        envelope_sha256=ENVELOPE_SHA,
        recipient_fingerprint=FP,
        owner_digest=OWNER_SHA,
        verifier_binding_sha256=VERIFIER_SHA,
    )


def _payload(witness: OwnerStageWitness) -> bytes:
    fields = {
        "version": witness.version,
        "purpose": witness.purpose,
        "stage_id": witness.stage_id,
        "staged_at": witness.staged_at,
        "envelope_sha256": witness.envelope_sha256,
        "recipient_fingerprint": witness.recipient_fingerprint,
        "owner_digest": witness.owner_digest,
        "verifier_binding_sha256": witness.verifier_binding_sha256,
        "operation_sha256": witness.operation_sha256,
        "challenge_sha256": witness.challenge_sha256,
        "passkey_verified_at": witness.passkey_verified_at,
        "issued_at": witness.issued_at,
        "nonce": witness.nonce,
    }
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def _witness(*, key: bytes = KEY) -> OwnerStageWitness:
    source = OwnerStageWitness(
        version=1,
        purpose="boca-telegram-owner-stage-witness-v1",
        stage_id=STAGE_ID,
        staged_at=STAGED,
        envelope_sha256=ENVELOPE_SHA,
        recipient_fingerprint=FP,
        owner_digest=OWNER_SHA,
        verifier_binding_sha256=VERIFIER_SHA,
        operation_sha256=OPERATION_SHA,
        challenge_sha256=CHALLENGE_SHA,
        passkey_verified_at=PROOF,
        issued_at=STAGED + 1,
        nonce=NONCE,
        auth_tag=b"\x00" * 32,
    )
    tag = hmac.digest(key, DOMAIN + _payload(source), hashlib.sha256)
    return replace(source, auth_tag=tag)


def _review(
    witness: OwnerStageWitness | object,
    *,
    trusted_now: int = NOW,
    key: bytes = KEY,
    context: OwnerStageContext | None = None,
) -> object:
    return review_owner_stage_witness(
        witness,
        expected=_context() if context is None else context,
        owner_witness_key=key,
        trusted_now=trusted_now,
    )


def test_genuine_hmac_is_only_a_non_authorizing_review() -> None:
    result = _review(_witness())
    assert result.state == "HMAC_VALID_ONLY"
    assert result.authorized is False
    assert result.passkey_proven is False
    assert result.sender_state == "OFF"
    assert result.stage_id == STAGE_ID


@pytest.mark.parametrize(
    ("field", "tamper"),
    [
        ("version", 2),
        ("purpose", "cookie-auth"),
        ("stage_id", "a" * 64),
        ("staged_at", STAGED - 1),
        ("envelope_sha256", "a" * 64),
        ("recipient_fingerprint", "a" * 64),
        ("owner_digest", "a" * 64),
        ("verifier_binding_sha256", "a" * 64),
        ("operation_sha256", "a" * 64),
        ("challenge_sha256", "a" * 64),
        ("passkey_verified_at", PROOF - 1),
        ("issued_at", STAGED + 2),
        ("nonce", "a" * 64),
        ("auth_tag", b"\x01" * 32),
    ],
)
def test_every_signed_field_is_hmac_bound(field: str, tamper: object) -> None:
    with pytest.raises(OwnerWitnessNoGo):
        _review(replace(_witness(), **{field: tamper}))


def test_wrong_key_and_caller_claim_never_authorize() -> None:
    with pytest.raises(OwnerWitnessNoGo):
        _review(_witness(), key=DIFFERENT_KEY)
    with pytest.raises(OwnerWitnessNoGo):
        _review({"owner_authenticated": True, "source_sha": "a" * 40})


@pytest.mark.parametrize("key", [b"", b"a" * 31, "secret", b"\x00" * 32])
def test_missing_or_predictably_empty_key_is_denied(key: object) -> None:
    with pytest.raises(OwnerWitnessNoGo):
        _review(_witness(), key=key)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "context",
    [
        replace(_context(), stage_id="a" * 64),
        replace(_context(), staged_at=STAGED + 1),
        replace(_context(), envelope_sha256="a" * 64),
        replace(_context(), recipient_fingerprint="a" * 64),
        replace(_context(), owner_digest="a" * 64),
        replace(_context(), verifier_binding_sha256="a" * 64),
    ],
)
def test_host_expected_stage_and_owner_binding_are_independent(context: OwnerStageContext) -> None:
    with pytest.raises(OwnerWitnessNoGo):
        _review(_witness(), context=context)


@pytest.mark.parametrize("when", [STAGED - 1, STAGED + 3601, STAGED])
def test_future_or_expired_stage_never_passes(when: int) -> None:
    with pytest.raises(OwnerWitnessNoGo):
        _review(_witness(), trusted_now=when)


@pytest.mark.parametrize(
    ("proof_at", "signed_at"),
    [
        (STAGED - 46, STAGED + 1),
        (STAGED + 1, STAGED + 1),
        (STAGED - 3, STAGED - 1),
        (STAGED - 3, STAGED + 31),
        (0, STAGED + 1),
    ],
)
def test_signed_but_stale_or_inconsistent_owner_event_denied(proof_at: int, signed_at: int) -> None:
    source = replace(_witness(), passkey_verified_at=proof_at, issued_at=signed_at)
    source = replace(source, auth_tag=hmac.digest(KEY, DOMAIN + _payload(source), hashlib.sha256))
    with pytest.raises(OwnerWitnessNoGo):
        _review(source)


def test_hmac_never_proves_a_web_authn_assertion_by_itself() -> None:
    result = _review(_witness())
    assert result.authorized is False and result.passkey_proven is False
    # A witness review is not a Cutover OwnerPairingReceipt or an activation GO.
    assert "CUSTODY_COMMITTED" not in repr(result)
    assert "getUpdates" not in repr(result)


def test_private_nonce_and_mac_are_redacted_in_repr() -> None:
    receipt = _witness()
    assert NONCE not in repr(receipt)
    assert receipt.auth_tag.hex() not in repr(receipt)
    assert KEY.decode("ascii") not in repr(receipt)
