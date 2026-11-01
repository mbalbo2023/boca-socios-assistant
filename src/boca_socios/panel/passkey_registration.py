"""Inert owner WebAuthn registration proof; this is not a bootstrap HTTP route.

The caller must establish a separate, trusted first-owner bootstrap boundary.
Only public credential material is returned. Nothing is written or exposed here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from boca_socios.panel.passkey import (
    PasskeyOwnerAuthentication,
    _decode,
    _encode,
    _unique_pairs,
)


@dataclass(frozen=True, slots=True, repr=False)
class CreationChallenge:
    operation_id: str
    challenge: str
    user_id: str
    rp_id: str
    timeout_ms: int = 120_000


@dataclass(frozen=True, slots=True, repr=False)
class CreationResponse:
    """Fields from AuthenticatorAttestationResponse accessors, encoded base64url."""

    credential_id: str
    client_data_json: str
    authenticator_data: str
    public_key_der: str
    public_key_algorithm: int


@dataclass(frozen=True, slots=True, repr=False)
class ProofChallenge:
    credential_id: str
    challenge: str


@dataclass(frozen=True, slots=True, repr=False)
class PublicCredential:
    """Binary file payloads for credential_id and public_key.der, respectively."""

    credential_id: bytes
    public_key_der: bytes


@dataclass(slots=True, repr=False)
class _Creating:
    operation_id: str
    challenge: bytes
    deadline: float


@dataclass(slots=True, repr=False)
class _Proving:
    operation_id: str
    deadline: float
    credential: PublicCredential
    verifier: PasskeyOwnerAuthentication


def _cbor_header(value: bytes, offset: int) -> tuple[int, int, int]:
    """Read a definite-length CBOR item header in a bounded COSE EC2 key."""
    if offset >= len(value):
        raise ValueError("truncated CBOR")
    initial = value[offset]
    major, additional = initial >> 5, initial & 31
    offset += 1
    if additional < 24:
        return major, additional, offset
    sizes = {24: 1, 25: 2, 26: 4}
    size = sizes.get(additional)
    if size is None or offset + size > len(value):
        raise ValueError("unsupported CBOR length")
    length = int.from_bytes(value[offset : offset + size], "big")
    if length < (24 if size == 1 else 256 if size == 2 else 65536):
        raise ValueError("nonminimal CBOR length")
    return major, length, offset + size


def _cbor_int(value: bytes, offset: int) -> tuple[int, int]:
    major, number, offset = _cbor_header(value, offset)
    if major == 0:
        return number, offset
    if major == 1:
        return -1 - number, offset
    raise ValueError("expected COSE integer")


def _cbor_bytes(value: bytes, offset: int) -> tuple[bytes, int]:
    major, length, offset = _cbor_header(value, offset)
    if major != 2 or offset + length > len(value):
        raise ValueError("expected COSE byte string")
    return value[offset : offset + length], offset + length


def _cose_public_key(value: bytes) -> ec.EllipticCurvePublicKey:
    major, length, offset = _cbor_header(value, 0)
    if major != 5 or length != 5:
        raise ValueError("unsupported COSE key map")
    items: dict[int, int | bytes] = {}
    for _ in range(length):
        label, offset = _cbor_int(value, offset)
        if label in items:
            raise ValueError("duplicate COSE label")
        if label in (-2, -3):
            items[label], offset = _cbor_bytes(value, offset)
        else:
            items[label], offset = _cbor_int(value, offset)
    if (
        offset != len(value)
        or items.get(1) != 2
        or items.get(3) != -7
        or items.get(-1) != 1
        or not isinstance(items.get(-2), bytes)
        or not isinstance(items.get(-3), bytes)
    ):
        raise ValueError("unsupported ES256 COSE key")
    x, y = items[-2], items[-3]
    assert isinstance(x, bytes) and isinstance(y, bytes)
    if len(x) != 32 or len(y) != 32:
        raise ValueError("invalid P-256 point")
    return ec.EllipticCurvePublicNumbers(
        int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1()
    ).public_key()


class OwnerPasskeyRegistration:
    """One in-memory create→get proof for an independently authorized owner.

    The first-owner authorization and HTTPS serving are deliberately outside
    this class. Never wire `begin` to an anonymous route or a client identity
    header. A restart drops the pending ceremony without installing anything.
    """

    def __init__(
        self,
        *,
        origin: str,
        rp_id: str,
        owner_subject: str,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if not all(isinstance(value, str) for value in (origin, rp_id, owner_subject)):
            raise ValueError("registration requires an exact HTTPS RP and owner")
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or parsed.hostname != rp_id
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or not parsed.netloc
            or origin != f"https://{parsed.netloc}"
            or not owner_subject
            or len(owner_subject) > 128
        ):
            raise ValueError("registration requires an exact HTTPS RP and owner")
        # Accessing `port` rejects malformed authorities before any challenge.
        try:
            _ = parsed.port
            rp_id.encode("ascii")
        except (ValueError, UnicodeError) as error:
            raise ValueError("registration requires an exact HTTPS RP and owner") from error
        self._origin = origin
        self._rp_id = rp_id
        self._owner = owner_subject
        self._clock = clock
        self._lock = Lock()
        self._pending: _Creating | _Proving | None = None

    def begin(self) -> CreationChallenge | None:
        with self._lock:
            now = self._clock()
            if not math.isfinite(now):
                return None
            if self._pending is not None and self._pending.deadline > now:
                return None
            operation_id = _encode(secrets.token_bytes(16))
            challenge = secrets.token_bytes(32)
            self._pending = _Creating(operation_id, challenge, now + 120.0)
            return CreationChallenge(
                operation_id, _encode(challenge), _encode(secrets.token_bytes(32)), self._rp_id
            )

    def accept_creation(self, operation_id: str, response: object) -> ProofChallenge | None:
        if not isinstance(operation_id, str) or len(operation_id) != 22:
            return None
        with self._lock:
            pending = self._pending
            now = self._clock()
            if (
                not isinstance(pending, _Creating)
                or not hmac.compare_digest(pending.operation_id, operation_id)
                or not math.isfinite(now)
                or pending.deadline <= now
            ):
                return None
            self._pending = None  # one use, even if validation fails
            try:
                credential = self._verify_creation(pending.challenge, response)
                verifier = PasskeyOwnerAuthentication(
                    credential_id=credential.credential_id,
                    public_key_der=credential.public_key_der,
                    rp_id=self._rp_id,
                    origin=self._origin,
                    owner_subject=self._owner,
                    permissions=frozenset({"members:enroll"}),
                    clock=self._clock,
                )
                challenge = verifier.challenge()
                if challenge is None:
                    return None
                self._pending = _Proving(operation_id, now + 120.0, credential, verifier)
                return ProofChallenge(_encode(credential.credential_id), challenge)
            except (ValueError, TypeError, UnicodeError):
                return None

    def finish(self, operation_id: str, assertion: object) -> PublicCredential | None:
        if not isinstance(operation_id, str) or len(operation_id) != 22:
            return None
        with self._lock:
            pending = self._pending
            now = self._clock()
            if (
                not isinstance(pending, _Proving)
                or not hmac.compare_digest(pending.operation_id, operation_id)
                or not math.isfinite(now)
                or pending.deadline <= now
            ):
                return None
            self._pending = None  # failed proof cannot be retried with the same challenge
            if pending.verifier.verify(assertion) is None:
                return None
            return pending.credential

    def _verify_creation(self, challenge: bytes, response: object) -> PublicCredential:
        if (
            not isinstance(response, CreationResponse)
            or type(response.public_key_algorithm) is not int
        ):
            raise ValueError("invalid creation response")
        credential_id = _decode(response.credential_id, limit=1024)
        client_bytes = _decode(response.client_data_json, limit=4096)
        auth = _decode(response.authenticator_data, limit=4096)
        public_der = _decode(response.public_key_der, limit=512)
        client: Any = json.loads(client_bytes, object_pairs_hook=_unique_pairs)
        if (
            not isinstance(client, dict)
            or client.get("type") != "webauthn.create"
            or client.get("origin") != self._origin
            or client.get("crossOrigin", False) is not False
            or "topOrigin" in client
            or not hmac.compare_digest(_decode(client.get("challenge"), limit=32), challenge)
            or response.public_key_algorithm != -7
            or not 16 <= len(credential_id) <= 1024
            or not 88 <= len(auth) <= 4096
            or not hmac.compare_digest(auth[:32], hashlib.sha256(self._rp_id.encode()).digest())
            or auth[32] & 0x45 != 0x45  # UP, UV and attested credential data
            or auth[32] & 0xA2 != 0  # no reserved bits or unsupported extensions
        ):
            raise ValueError("invalid creation response")
        id_length = int.from_bytes(auth[53:55], "big")
        if id_length != len(credential_id) or not hmac.compare_digest(
            auth[55 : 55 + id_length], credential_id
        ):
            raise ValueError("credential ID mismatch")
        cose = _cose_public_key(auth[55 + id_length :])
        browser_key = serialization.load_der_public_key(public_der)
        if (
            not isinstance(browser_key, ec.EllipticCurvePublicKey)
            or not isinstance(browser_key.curve, ec.SECP256R1)
            or browser_key.public_numbers() != cose.public_numbers()
            or browser_key.public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            != public_der
        ):
            raise ValueError("public key mismatch")
        return PublicCredential(credential_id, public_der)
