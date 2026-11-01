"""Synthetic WebAuthn creation and proof; no owner device or host bundle is used."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from boca_socios.panel.passkey import PasskeyAssertion, PasskeyOwnerAuthentication
from boca_socios.panel.passkey_registration import (
    CreationResponse,
    OwnerPasskeyRegistration,
)

ORIGIN = "https://owner.example.test:8443"
RP_ID = "owner.example.test"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _der(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def _cose(key: ec.EllipticCurvePrivateKey) -> bytes:
    numbers = key.public_key().public_numbers()
    return (
        b"\xa5\x01\x02\x03\x26\x20\x01\x21\x58\x20"
        + numbers.x.to_bytes(32, "big")
        + b"\x22\x58\x20"
        + numbers.y.to_bytes(32, "big")
    )


def _creation(
    challenge: str,
    key: ec.EllipticCurvePrivateKey,
    credential_id: bytes,
    *,
    origin: str = ORIGIN,
    rp_id: str = RP_ID,
    flags: int = 0x45,
    public_key: ec.EllipticCurvePrivateKey | None = None,
    algorithm: int = -7,
    client_data_json: bytes | None = None,
) -> CreationResponse:
    client = (
        client_data_json
        or json.dumps(
            {"type": "webauthn.create", "challenge": challenge, "origin": origin},
            separators=(",", ":"),
        ).encode()
    )
    authenticator = (
        hashlib.sha256(rp_id.encode()).digest()
        + bytes([flags])
        + b"\x00\x00\x00\x00"
        + bytes(16)
        + len(credential_id).to_bytes(2, "big")
        + credential_id
        + _cose(key)
    )
    return CreationResponse(
        credential_id=_b64(credential_id),
        client_data_json=_b64(client),
        authenticator_data=_b64(authenticator),
        public_key_der=_b64(_der(public_key or key)),
        public_key_algorithm=algorithm,
    )


def _assertion(
    challenge: str,
    key: ec.EllipticCurvePrivateKey,
    credential_id: bytes,
    *,
    origin: str = ORIGIN,
    rp_id: str = RP_ID,
    flags: int = 0x05,
) -> PasskeyAssertion:
    client = json.dumps(
        {"type": "webauthn.get", "challenge": challenge, "origin": origin},
        separators=(",", ":"),
    ).encode()
    authenticator = hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + bytes(4)
    signature = key.sign(authenticator + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
    return PasskeyAssertion(_b64(credential_id), _b64(client), _b64(authenticator), _b64(signature))


def _registration(clock: list[float]) -> OwnerPasskeyRegistration:
    return OwnerPasskeyRegistration(
        origin=ORIGIN, rp_id=RP_ID, owner_subject="owner", clock=lambda: clock[0]
    )


def test_two_step_registration_proves_key_before_public_bundle() -> None:
    clock = [100.0]
    registration = _registration(clock)
    key = ec.generate_private_key(ec.SECP256R1())
    credential_id = b"synthetic-credential-id-for-proof"

    creation = registration.begin()
    assert creation is not None
    assert creation.rp_id == RP_ID
    assert (
        len(base64.urlsafe_b64decode(creation.challenge + "=" * (-len(creation.challenge) % 4)))
        == 32
    )
    assert registration.begin() is None
    proof = registration.accept_creation(
        creation.operation_id, _creation(creation.challenge, key, credential_id)
    )
    assert proof is not None
    assert proof.credential_id == _b64(credential_id)
    assert registration.begin() is None
    material = registration.finish(
        creation.operation_id, _assertion(proof.challenge, key, credential_id)
    )
    assert material is not None
    assert material.credential_id == credential_id
    assert material.public_key_der == _der(key)
    assert (
        registration.finish(creation.operation_id, _assertion(proof.challenge, key, credential_id))
        is None
    )

    # The exact returned bytes are accepted by the existing panel verifier.
    verifier = PasskeyOwnerAuthentication(
        credential_id=material.credential_id,
        public_key_der=material.public_key_der,
        rp_id=RP_ID,
        origin=ORIGIN,
        owner_subject="owner",
        permissions=frozenset({"members:enroll"}),
    )
    login_challenge = verifier.challenge()
    assert login_challenge is not None
    assert verifier.verify(_assertion(login_challenge, key, credential_id)) is not None


@pytest.mark.parametrize(
    "change",
    [
        {"origin": "https://other.example.test"},
        {"rp_id": "other.example.test"},
        {"flags": 0x41},  # no user verification
        {"flags": 0x05},  # no attested credential data
        {"algorithm": -257},
    ],
)
def test_creation_denies_wrong_origin_rp_uv_attestation_or_algorithm(
    change: dict[str, object],
) -> None:
    clock = [100.0]
    registration = _registration(clock)
    creation = registration.begin()
    assert creation is not None
    key = ec.generate_private_key(ec.SECP256R1())
    response = _creation(creation.challenge, key, b"synthetic-credential-id-for-proof", **change)
    assert registration.accept_creation(creation.operation_id, response) is None
    assert registration.accept_creation(creation.operation_id, response) is None


def test_creation_denies_mismatched_public_key_and_duplicate_client_data() -> None:
    registration = _registration([100.0])
    creation = registration.begin()
    assert creation is not None
    key = ec.generate_private_key(ec.SECP256R1())
    wrong_key = ec.generate_private_key(ec.SECP256R1())
    credential_id = b"synthetic-credential-id-for-proof"
    response = _creation(creation.challenge, key, credential_id, public_key=wrong_key)
    assert registration.accept_creation(creation.operation_id, response) is None

    second = registration.begin()
    assert second is not None
    duplicate = (
        b'{"type":"webauthn.create","type":"webauthn.create","challenge":"'
        + second.challenge.encode()
        + b'","origin":"https://owner.example.test:8443"}'
    )
    response = _creation(second.challenge, key, credential_id, client_data_json=duplicate)
    assert registration.accept_creation(second.operation_id, response) is None


def test_proof_denies_wrong_signature_replay_and_expired_challenges() -> None:
    clock = [100.0]
    registration = _registration(clock)
    creation = registration.begin()
    assert creation is not None
    key = ec.generate_private_key(ec.SECP256R1())
    credential_id = b"synthetic-credential-id-for-proof"
    proof = registration.accept_creation(
        creation.operation_id, _creation(creation.challenge, key, credential_id)
    )
    assert proof is not None
    wrong_key = ec.generate_private_key(ec.SECP256R1())
    assert (
        registration.finish(
            creation.operation_id, _assertion(proof.challenge, wrong_key, credential_id)
        )
        is None
    )
    assert (
        registration.finish(creation.operation_id, _assertion(proof.challenge, key, credential_id))
        is None
    )

    expired = registration.begin()
    assert expired is not None
    clock[0] += timedelta(seconds=121).total_seconds()
    assert (
        registration.accept_creation(
            expired.operation_id, _creation(expired.challenge, key, credential_id)
        )
        is None
    )


def test_creation_rejects_cross_origin_and_malformed_cose_and_consumes_challenge() -> None:
    registration = _registration([100.0])
    creation = registration.begin()
    assert creation is not None
    key = ec.generate_private_key(ec.SECP256R1())
    credential_id = b"synthetic-credential-id-for-proof"
    client = json.dumps(
        {
            "type": "webauthn.create",
            "challenge": creation.challenge,
            "origin": ORIGIN,
            "crossOrigin": True,
        }
    ).encode()
    response = _creation(creation.challenge, key, credential_id, client_data_json=client)
    assert registration.accept_creation(creation.operation_id, response) is None
    assert registration.accept_creation(creation.operation_id, response) is None

    second = registration.begin()
    assert second is not None
    response = _creation(second.challenge, key, credential_id)
    authenticator = base64.urlsafe_b64decode(
        response.authenticator_data + "=" * (-len(response.authenticator_data) % 4)
    )
    algorithm_offset = 55 + len(credential_id) + 4
    corrupted = authenticator[:algorithm_offset] + b"\x25" + authenticator[algorithm_offset + 1 :]
    response = CreationResponse(
        response.credential_id,
        response.client_data_json,
        _b64(corrupted),
        response.public_key_der,
        response.public_key_algorithm,
    )
    assert registration.accept_creation(second.operation_id, response) is None


def test_operation_id_cannot_rebind_creation_or_proof_and_proof_expires() -> None:
    clock = [100.0]
    registration = _registration(clock)
    creation = registration.begin()
    assert creation is not None
    key = ec.generate_private_key(ec.SECP256R1())
    credential_id = b"synthetic-credential-id-for-proof"
    response = _creation(creation.challenge, key, credential_id)
    assert registration.accept_creation("wrong", response) is None
    proof = registration.accept_creation(creation.operation_id, response)
    assert proof is not None
    assert registration.finish("wrong", _assertion(proof.challenge, key, credential_id)) is None
    clock[0] += 121
    assert (
        registration.finish(creation.operation_id, _assertion(proof.challenge, key, credential_id))
        is None
    )
    assert registration.begin() is not None


@pytest.mark.parametrize(
    "origin,rp_id",
    [
        ("", RP_ID),
        ("http://owner.example.test", RP_ID),
        (ORIGIN, "bad.test"),
        ("https://owner.example.test:8443/", RP_ID),
    ],
)
def test_absent_or_mismatched_https_origin_fails_closed(origin: str, rp_id: str) -> None:
    with pytest.raises(ValueError, match="exact HTTPS"):
        OwnerPasskeyRegistration(origin=origin, rp_id=rp_id, owner_subject="owner")
