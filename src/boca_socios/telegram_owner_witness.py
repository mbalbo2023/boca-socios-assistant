"""Non-authorizing HMAC review of an alleged owner-authenticated Telegram stage.

ADR0164 / #362: no issuer, owner session, passkey verifier, key loader, HTTP,
Telegram API, Docker, dispatcher, clock source or filesystem effects exist here.
A correct HMAC proves only possession of supplied key bytes. It does NOT prove
that the signer checked a fresh real WebAuthn assertion at the stage POST.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from typing import Literal

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_PURPOSE = "boca-telegram-owner-stage-witness-v1"
_DOMAIN = b"boca-telegram-owner-stage-witness-v1:\x00"
_MAX_PASSKEY_TO_STAGE = 45
_MAX_STAGE_TO_ISSUE = 30
_MAX_STAGE_AGE = 3600


class OwnerWitnessNoGo(ValueError):
    """Fixed error only: never include ciphertext, HMAC, nonce or host paths."""


@dataclass(frozen=True, slots=True)
class OwnerStageContext:
    """Nonsecret stage/owner equality pins; still claims until host-attested."""

    stage_id: str
    staged_at: int
    envelope_sha256: str
    recipient_fingerprint: str
    owner_digest: str
    verifier_binding_sha256: str


@dataclass(frozen=True, slots=True)
class OwnerStageWitness:
    """HMAC allegedly issued by a future fresh-passkey-protected stage POST.

    The private stage writer DOES NOT issue this witness today. No HMAC key
    material is present in the current deploy, controller or repository.
    """

    version: int
    purpose: str
    stage_id: str = field(repr=False)
    staged_at: int
    envelope_sha256: str
    recipient_fingerprint: str
    owner_digest: str
    verifier_binding_sha256: str
    operation_sha256: str
    challenge_sha256: str
    passkey_verified_at: int
    issued_at: int
    nonce: str = field(repr=False)
    auth_tag: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class OwnerStageWitnessReview:
    """MAC consistency only; cannot become a GO/HostRecheck/OwnerPairingReceipt."""

    stage_id: str = field(repr=False)
    envelope_sha256: str
    recipient_fingerprint: str
    state: Literal["HMAC_VALID_ONLY"] = "HMAC_VALID_ONLY"
    authorized: Literal[False] = False
    passkey_proven: Literal[False] = False
    sender_state: Literal["OFF"] = "OFF"


def _digest(value: object) -> bool:
    return type(value) is str and _HASH.fullmatch(value) is not None


def _payload(witness: OwnerStageWitness) -> bytes:
    """Canonical signed bytes; exclude only MAC, never the private one-use nonce."""
    return json.dumps(
        {
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
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def review_owner_stage_witness(
    witness: OwnerStageWitness | object,
    *,
    expected: OwnerStageContext,
    owner_witness_key: bytes,
    trusted_now: int,
) -> OwnerStageWitnessReview:
    """Pure constant-time MAC/equality/freshness check, never physical authority.

    The protected caller must independently prove the canonical stage file,
    exact owner credential, **fresh WebAuthn POST** and dedicated signing-key
    custody. None of those capabilities is implemented here. This return
    value must never be transformed into `owner_authenticated=True`.
    """
    if (
        type(witness) is not OwnerStageWitness
        or type(expected) is not OwnerStageContext
        or type(owner_witness_key) is not bytes
        or len(owner_witness_key) != 32
        or owner_witness_key == b"\x00" * 32
        or type(trusted_now) is not int
        or trusted_now <= 0
    ):
        raise OwnerWitnessNoGo("owner_stage_witness_untrusted")
    assert isinstance(witness, OwnerStageWitness)
    assert isinstance(expected, OwnerStageContext)
    if (
        type(witness.version) is not int
        or witness.version != 1
        or type(witness.purpose) is not str
        or witness.purpose != _PURPOSE
        or not all(
            _digest(item)
            for item in (
                witness.stage_id,
                witness.envelope_sha256,
                witness.recipient_fingerprint,
                witness.owner_digest,
                witness.verifier_binding_sha256,
                witness.operation_sha256,
                witness.challenge_sha256,
                witness.nonce,
                expected.stage_id,
                expected.envelope_sha256,
                expected.recipient_fingerprint,
                expected.owner_digest,
                expected.verifier_binding_sha256,
            )
        )
        or type(expected.staged_at) is not int
        or type(witness.staged_at) is not int
        or type(witness.passkey_verified_at) is not int
        or type(witness.issued_at) is not int
        or type(witness.auth_tag) is not bytes
        or len(witness.auth_tag) != hashlib.sha256().digest_size
    ):
        raise OwnerWitnessNoGo("owner_stage_witness_shape_unverified")
    if (
        witness.stage_id != expected.stage_id
        or witness.staged_at != expected.staged_at
        or witness.envelope_sha256 != expected.envelope_sha256
        or witness.recipient_fingerprint != expected.recipient_fingerprint
        or witness.owner_digest != expected.owner_digest
        or witness.verifier_binding_sha256 != expected.verifier_binding_sha256
    ):
        raise OwnerWitnessNoGo("owner_stage_witness_binding_unverified")
    if (
        not 0
        < witness.passkey_verified_at
        <= witness.staged_at
        <= witness.issued_at
        <= trusted_now
        or witness.staged_at - witness.passkey_verified_at > _MAX_PASSKEY_TO_STAGE
        or witness.issued_at - witness.staged_at > _MAX_STAGE_TO_ISSUE
        or trusted_now - witness.staged_at > _MAX_STAGE_AGE
    ):
        raise OwnerWitnessNoGo("owner_stage_witness_freshness_unverified")
    tag = hmac.digest(owner_witness_key, _DOMAIN + _payload(witness), hashlib.sha256)
    if not hmac.compare_digest(witness.auth_tag, tag):
        raise OwnerWitnessNoGo("owner_stage_witness_hmac_unverified")
    return OwnerStageWitnessReview(
        stage_id=expected.stage_id,
        envelope_sha256=expected.envelope_sha256,
        recipient_fingerprint=expected.recipient_fingerprint,
    )
