"""Signed owner-passkey evidence for an encrypted, offline Telegram V2 stage.

This verifies only a human-confirmed WebAuthn assertion bound to a particular
ciphertext. It does not supply the host lease, cutover GO, recipient custody,
Telegram GET permission, or a sender authorization.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from uuid import UUID

from boca_socios.panel.passkey import PasskeyAssertion, PasskeyOwnerAuthentication

_PURPOSE = "boca-telegram-owner-webauthn-stage-v1"
_DOMAIN = b"boca-telegram-owner-webauthn-stage-v1:\0"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_WITNESS_FIELDS = frozenset(
    {
        "version",
        "operation_id",
        "request_nonce",
        "challenged_at",
        "verifier_binding",
        "assertion",
    }
)
_ASSERTION_FIELDS = frozenset(
    {"credential_id", "client_data_json", "authenticator_data", "signature"}
)


class TelegramOwnerWitnessError(ValueError):
    """Fail closed without disclosing token, envelope, credential or nonce."""


@dataclass(frozen=True, slots=True, repr=False)
class TelegramStageOwnerWitness:
    operation_id: str
    request_nonce: str
    challenged_at: int
    verifier_binding: str
    assertion: PasskeyAssertion


def _valid_operation(value: object) -> bool:
    if not isinstance(value, str) or _UUID.fullmatch(value) is None:
        return False
    try:
        return str(UUID(value)) == value and UUID(value).int != 0
    except ValueError:
        return False


def stage_owner_challenge(
    *,
    envelope_sha256: str,
    operation_id: str,
    request_nonce: str,
    challenged_at: int,
    verifier_binding: str,
) -> bytes:
    """Deterministic signed challenge, independently reproducible on the host."""
    if (
        type(envelope_sha256) is not str
        or _DIGEST.fullmatch(envelope_sha256) is None
        or not _valid_operation(operation_id)
        or type(request_nonce) is not str
        or _DIGEST.fullmatch(request_nonce) is None
        or type(challenged_at) is not int
        or not 0 < challenged_at <= 2**63 - 1
        or type(verifier_binding) is not str
        or _DIGEST.fullmatch(verifier_binding) is None
    ):
        raise TelegramOwnerWitnessError("telegram_owner_webauthn_unverified")
    transcript = {
        "version": 1,
        "purpose": _PURPOSE,
        "envelope_sha256": envelope_sha256,
        "operation_id": operation_id,
        "request_nonce": request_nonce,
        "challenged_at": challenged_at,
        "verifier_binding": verifier_binding,
    }
    canonical = json.dumps(transcript, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(_DOMAIN + canonical).digest()


def witness_document(witness: TelegramStageOwnerWitness) -> dict[str, object]:
    """Strict, public-only assertion metadata stored WITH encrypted stage."""
    if not isinstance(witness, TelegramStageOwnerWitness):
        raise TelegramOwnerWitnessError("telegram_owner_webauthn_unverified")
    return {
        "version": 1,
        "operation_id": witness.operation_id,
        "request_nonce": witness.request_nonce,
        "challenged_at": witness.challenged_at,
        "verifier_binding": witness.verifier_binding,
        "assertion": {
            "credential_id": witness.assertion.credential_id,
            "client_data_json": witness.assertion.client_data_json,
            "authenticator_data": witness.assertion.authenticator_data,
            "signature": witness.assertion.signature,
        },
    }


def parse_witness_document(value: object) -> TelegramStageOwnerWitness:
    """Parse a bounded, exact-shape assertion; never regard parsing as GO."""
    try:
        if not isinstance(value, dict) or set(value) != _WITNESS_FIELDS:
            raise ValueError("fields")
        assertion = value["assertion"]
        if (
            type(value["version"]) is not int
            or value["version"] != 1
            or not isinstance(assertion, dict)
            or set(assertion) != _ASSERTION_FIELDS
            or not all(isinstance(v, str) for v in assertion.values())
            or len(assertion["credential_id"]) > 2048
            or len(assertion["client_data_json"]) > 8192
            or len(assertion["authenticator_data"]) > 2048
            or len(assertion["signature"]) > 512
        ):
            raise ValueError("assertion")
        witness = TelegramStageOwnerWitness(
            operation_id=value["operation_id"],
            request_nonce=value["request_nonce"],
            challenged_at=value["challenged_at"],
            verifier_binding=value["verifier_binding"],
            assertion=PasskeyAssertion(**assertion),
        )
        stage_owner_challenge(
            envelope_sha256="0" * 64,
            operation_id=witness.operation_id,
            request_nonce=witness.request_nonce,
            challenged_at=witness.challenged_at,
            verifier_binding=witness.verifier_binding,
        )
        return witness
    except (ValueError, TypeError, KeyError):
        raise TelegramOwnerWitnessError("telegram_owner_webauthn_unverified") from None


def verify_stage_owner_witness(
    witness: TelegramStageOwnerWitness | None,
    sealed_envelope: bytes,
    verifier: PasskeyOwnerAuthentication,
    *,
    staged_at: int,
) -> bool:
    """Offline ES256/UV proof under trusted passkey PUBLIC configuration.

    This check must be repeated by the future same-lease physical host caller.
    It proves no PID, container, lock, Bot API response or authorization GO.
    """
    if (
        not isinstance(witness, TelegramStageOwnerWitness)
        or type(sealed_envelope) is not bytes
        or not 0 < len(sealed_envelope) <= 4096
        or not isinstance(verifier, PasskeyOwnerAuthentication)
        or type(staged_at) is not int
        or type(witness.challenged_at) is not int
        or not 0 <= staged_at - witness.challenged_at <= 120
    ):
        return False
    if not hmac.compare_digest(witness.verifier_binding, verifier.authorization_binding.hex()):
        return False
    try:
        challenge = stage_owner_challenge(
            envelope_sha256=hashlib.sha256(sealed_envelope).hexdigest(),
            operation_id=witness.operation_id,
            request_nonce=witness.request_nonce,
            challenged_at=witness.challenged_at,
            verifier_binding=witness.verifier_binding,
        )
    except TelegramOwnerWitnessError:
        return False
    return verifier.verify_public_telegram_stage_signature(witness.assertion, challenge)
