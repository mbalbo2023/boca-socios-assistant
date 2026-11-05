"""Fresh owner WebAuthn UV bound to ciphertext; synthetic/offline only."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios.panel.passkey import PasskeyAssertion, PasskeyOwnerAuthentication
from boca_socios.panel.telegram_pairing_staging import (
    STAGING_FILENAME,
    PairingStageRequest,
    stage_private_telegram_pairing,
)
from boca_socios.telegram_owner_webauthn import (
    TelegramOwnerWitnessError,
    TelegramStageOwnerWitness,
    parse_witness_document,
    stage_owner_challenge,
    verify_stage_owner_witness,
    witness_document,
)
from test_telegram_pairing_ui import _recipient, _run

_ORIGIN = "https://owner.example.test:8443"
_RP = "owner.example.test"
_OPERATION = "123e4567-e89b-42d3-a456-426614174000"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _verifier(
    clock: list[float],
) -> tuple[PasskeyOwnerAuthentication, ec.EllipticCurvePrivateKey, bytes]:
    key = ec.generate_private_key(ec.SECP256R1())
    credential_id = b"boca-telegram-passkey-credential"
    verifier = PasskeyOwnerAuthentication(
        credential_id=credential_id,
        public_key_der=key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
        rp_id=_RP,
        origin=_ORIGIN,
        owner_subject="owner",
        permissions=frozenset({"local-status:read"}),
        clock=lambda: clock[0],
    )
    return verifier, key, credential_id


def _signed(
    challenge: bytes,
    key: ec.EllipticCurvePrivateKey,
    credential_id: bytes,
    *,
    origin: str = _ORIGIN,
    rp_id: str = _RP,
    flags: int = 0x05,
) -> PasskeyAssertion:
    client = json.dumps(
        {"type": "webauthn.get", "challenge": _b64(challenge), "origin": origin},
        separators=(",", ":"),
    ).encode()
    authenticator = hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + bytes(4)
    signature = key.sign(
        authenticator + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256())
    )
    return PasskeyAssertion(
        _b64(credential_id), _b64(client), _b64(authenticator), _b64(signature)
    )


def _envelope() -> bytes:
    _, _, fragment = _recipient()
    return bootstrap._unb64(_run(fragment)["output"], maximum=4096)


def _witness(
    envelope: bytes,
    verifier: PasskeyOwnerAuthentication,
    key: ec.EllipticCurvePrivateKey,
    credential: bytes,
    *,
    issued: int,
) -> TelegramStageOwnerWitness:
    digest = hashlib.sha256(envelope).hexdigest()
    nonce = secrets.token_hex(32)
    binding = verifier.authorization_binding.hex()
    challenge = stage_owner_challenge(
        envelope_sha256=digest,
        operation_id=_OPERATION,
        request_nonce=nonce,
        challenged_at=issued,
        verifier_binding=binding,
    )
    assert verifier.issue_telegram_stage_challenge(challenge)
    return TelegramStageOwnerWitness(
        _OPERATION, nonce, issued, binding, _signed(challenge, key, credential)
    )


def test_real_es256_owner_signature_is_fresh_uses_once_and_survives_offline_verify() -> None:
    clock = [100.0]
    verifier, key, credential = _verifier(clock)
    envelope = _envelope()
    issued = int(datetime.now(UTC).timestamp())
    witness = _witness(envelope, verifier, key, credential, issued=issued)
    challenge = stage_owner_challenge(
        envelope_sha256=hashlib.sha256(envelope).hexdigest(),
        operation_id=witness.operation_id,
        request_nonce=witness.request_nonce,
        challenged_at=witness.challenged_at,
        verifier_binding=witness.verifier_binding,
    )
    assert verifier.verify_telegram_stage_assertion(witness.assertion, challenge) is not None
    assert verifier.verify_telegram_stage_assertion(witness.assertion, challenge) is None
    assert verify_stage_owner_witness(witness, envelope, verifier, staged_at=issued + 1)
    assert not verify_stage_owner_witness(witness, envelope, verifier, staged_at=issued + 121)


def test_stage_persists_signed_proof_in_one_atomic_encrypted_file(tmp_path: Path) -> None:
    verifier, key, credential = _verifier([100.0])
    envelope = _envelope()
    issued = int(datetime.now(UTC).timestamp())
    witness = _witness(envelope, verifier, key, credential, issued=issued)
    path = tmp_path / STAGING_FILENAME
    receipt = stage_private_telegram_pairing(path, PairingStageRequest(envelope, witness))
    stored = json.loads(path.read_bytes())
    assert receipt.envelope_sha256 == hashlib.sha256(envelope).hexdigest()
    assert set(stored["owner_witness"]) == set(witness_document(witness))
    recovered = parse_witness_document(stored["owner_witness"])
    assert verify_stage_owner_witness(recovered, envelope, verifier, staged_at=stored["staged_at"])
    assert len(path.read_bytes()) <= 8192
    assert b"synthetic_token_for_offline_test" not in path.read_bytes()
    assert b"pairing_code" not in path.read_bytes()
    with pytest.raises(ValueError, match="pairing_stage_exists"):
        stage_private_telegram_pairing(path, PairingStageRequest(envelope, witness))


@pytest.mark.parametrize(
    "mutation",
    [
        "other_envelope",
        "other_operation",
        "other_nonce",
        "other_owner",
        "wrong_signature",
        "wrong_origin",
        "wrong_rp",
        "missing_uv",
        "future_stage",
    ],
)
def test_stage_witness_is_bound_to_exact_human_key_and_ciphertext(mutation: str) -> None:
    verifier, key, credential = _verifier([100.0])
    envelope = _envelope()
    issued = int(datetime.now(UTC).timestamp())
    witness = _witness(envelope, verifier, key, credential, issued=issued)
    _, wrong_key, _ = _verifier([100.0])
    kwargs = asdict(witness)
    kwargs["assertion"] = witness.assertion
    at = issued
    staged_envelope = envelope
    if mutation == "other_envelope":
        staged_envelope = envelope + b" "
    elif mutation == "other_operation":
        kwargs["operation_id"] = str(uuid4())
    elif mutation == "other_nonce":
        kwargs["request_nonce"] = secrets.token_hex(32)
    elif mutation == "other_owner":
        kwargs["verifier_binding"] = secrets.token_hex(32)
    elif mutation == "wrong_signature":
        challenge = stage_owner_challenge(
            envelope_sha256=hashlib.sha256(envelope).hexdigest(),
            operation_id=witness.operation_id,
            request_nonce=witness.request_nonce,
            challenged_at=issued,
            verifier_binding=witness.verifier_binding,
        )
        kwargs["assertion"] = _signed(challenge, wrong_key, credential)
    elif mutation == "wrong_origin":
        challenge = stage_owner_challenge(
            envelope_sha256=hashlib.sha256(envelope).hexdigest(),
            operation_id=witness.operation_id,
            request_nonce=witness.request_nonce,
            challenged_at=issued,
            verifier_binding=witness.verifier_binding,
        )
        kwargs["assertion"] = _signed(challenge, key, credential, origin="https://evil.test")
    elif mutation == "wrong_rp":
        challenge = stage_owner_challenge(
            envelope_sha256=hashlib.sha256(envelope).hexdigest(),
            operation_id=witness.operation_id,
            request_nonce=witness.request_nonce,
            challenged_at=issued,
            verifier_binding=witness.verifier_binding,
        )
        kwargs["assertion"] = _signed(challenge, key, credential, rp_id="evil.test")
    elif mutation == "missing_uv":
        challenge = stage_owner_challenge(
            envelope_sha256=hashlib.sha256(envelope).hexdigest(),
            operation_id=witness.operation_id,
            request_nonce=witness.request_nonce,
            challenged_at=issued,
            verifier_binding=witness.verifier_binding,
        )
        kwargs["assertion"] = _signed(challenge, key, credential, flags=0x01)
    elif mutation == "future_stage":
        at = issued - 1
    mutated = TelegramStageOwnerWitness(**kwargs)
    assert not verify_stage_owner_witness(mutated, staged_envelope, verifier, staged_at=at)


def test_malformed_webauthn_fields_rejected_without_any_host_effect() -> None:
    verifier, key, credential = _verifier([100.0])
    envelope = _envelope()
    issued = int(datetime.now(UTC).timestamp())
    witness = _witness(envelope, verifier, key, credential, issued=issued)
    document = witness_document(witness)
    assert parse_witness_document(document) == witness
    with pytest.raises(TelegramOwnerWitnessError):
        parse_witness_document({**document, "owner_authorized": True})
    with pytest.raises(TelegramOwnerWitnessError):
        parse_witness_document({**document, "request_nonce": "x" * 64})
    with pytest.raises(TelegramOwnerWitnessError):
        stage_owner_challenge(
            envelope_sha256=hashlib.sha256(envelope).hexdigest(),
            operation_id="forged",
            request_nonce=witness.request_nonce,
            challenged_at=issued,
            verifier_binding=witness.verifier_binding,
        )
    assert verifier.verify_public_telegram_stage_signature(witness.assertion, bytes(32)) is False
