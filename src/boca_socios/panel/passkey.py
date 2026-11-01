"""Owner passkey assertion verification; credential registration is out of band.

The public credential and RP ID are server configuration. No password, private
key or client-supplied identity header can create an owner session.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from boca_socios.owner_origin import owner_rp_host
from boca_socios.panel.owner_sessions import OwnerIdentity

_BASE64URL = re.compile(r"[A-Za-z0-9_-]+")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: object, *, limit: int) -> bytes:
    if not isinstance(value, str) or not value or len(value) > limit * 2:
        raise ValueError("invalid passkey field")
    if _BASE64URL.fullmatch(value) is None:
        raise ValueError("invalid passkey encoding")
    result = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if len(result) > limit or _encode(result) != value:
        raise ValueError("invalid passkey field")
    return result


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate client data key")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True, repr=False)
class PasskeyAssertion:
    credential_id: str
    client_data_json: str
    authenticator_data: str
    signature: str


class PasskeyOwnerAuthentication:
    """Verify ES256 WebAuthn assertions with exact origin, RP and user verification.

    A credential public key must be enrolled using a separately reviewed,
    owner-controlled ceremony and installed as Boca-only configuration. This
    verifier does not accept a bootstrap token or enroll credentials itself.
    """

    def __init__(
        self,
        *,
        credential_id: bytes,
        public_key_der: bytes,
        rp_id: str,
        origin: str,
        owner_subject: str,
        permissions: frozenset[str],
        clock: Callable[[], float] = monotonic,
    ) -> None:
        parsed = urlsplit(origin)
        if (
            parsed.hostname != rp_id
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or not rp_id
            or not owner_subject
            or not permissions
            or not isinstance(credential_id, bytes)
            or not 16 <= len(credential_id) <= 1024
        ):
            raise ValueError("passkey requires an exact trustworthy RP and owner configuration")
        try:
            if owner_rp_host(origin) != rp_id:
                raise ValueError("RP mismatch")
        except ValueError:
            raise ValueError("passkey requires an exact trustworthy RP") from None
        key = serialization.load_der_public_key(public_key_der)
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
            key.curve, ec.SECP256R1
        ):
            raise ValueError("only ES256 passkeys are supported")
        self._credential_id = credential_id
        self._key = key
        self._rp_id_hash = hashlib.sha256(rp_id.encode("utf-8")).digest()
        self._origin = origin
        self._owner = owner_subject
        self._permissions = permissions
        self._clock = clock
        self._lock = Lock()
        self._challenges: dict[bytes, float] = {}
        self._next_challenge = 0.0
        self._last_counter = 0

    @property
    def credential_id(self) -> str:
        return _encode(self._credential_id)

    def challenge(self) -> str | None:
        import secrets

        with self._lock:
            now = self._clock()
            self._challenges = {
                item: expiry for item, expiry in self._challenges.items() if expiry > now
            }
            if now < self._next_challenge or len(self._challenges) >= 8:
                return None
            self._next_challenge = now + 1.0
            challenge = secrets.token_bytes(32)
            self._challenges[challenge] = now + 120.0
            return _encode(challenge)

    def verify(self, proof: object) -> OwnerIdentity | None:
        if not isinstance(proof, PasskeyAssertion):
            return None
        try:
            credential_id = _decode(proof.credential_id, limit=1024)
            client_data = _decode(proof.client_data_json, limit=4096)
            authenticator_data = _decode(proof.authenticator_data, limit=1024)
            signature = _decode(proof.signature, limit=256)
            if not hmac.compare_digest(credential_id, self._credential_id):
                return None
            data = json.loads(client_data, object_pairs_hook=_unique_pairs)
            if (
                not isinstance(data, dict)
                or data.get("type") != "webauthn.get"
                or data.get("origin") != self._origin
                or data.get("crossOrigin", False) is not False
                or "topOrigin" in data
            ):
                return None
            challenge = _decode(data.get("challenge"), limit=32)
            if len(challenge) != 32:
                return None
            with self._lock:
                expiry = self._challenges.pop(challenge, 0)
                if expiry <= self._clock():
                    return None
            if (
                not 37 <= len(authenticator_data) <= 1024
                or not hmac.compare_digest(authenticator_data[:32], self._rp_id_hash)
                or authenticator_data[32] & 0x05 != 0x05  # user present and verified
            ):
                return None
            self._key.verify(
                signature,
                authenticator_data + hashlib.sha256(client_data).digest(),
                ec.ECDSA(hashes.SHA256()),
            )
            counter = int.from_bytes(authenticator_data[33:37], "big")
            with self._lock:
                # A nonzero authenticator counter must advance in this process.
                if counter and self._last_counter and counter <= self._last_counter:
                    return None
                self._last_counter = max(self._last_counter, counter)
            return OwnerIdentity(self._owner, self._permissions)
        except (ValueError, TypeError, KeyError, InvalidSignature, UnicodeError):
            return None
