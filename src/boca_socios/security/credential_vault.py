"""AES-256-GCM encryption for third-party credentials.

Passwords must be recoverable for user-authorized login, so irreversible
password hashes are not suitable for this particular storage requirement.
Every value gets a fresh nonce and is bound to its member ID as AAD.
"""

from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass(frozen=True, slots=True)
class SealedCredential:
    key_id: str
    nonce: bytes
    ciphertext: bytes


class CredentialVault:
    def __init__(self, key: bytes, *, key_id: str = "v1") -> None:
        if len(key) != 32:
            raise ValueError("expected an AES-256 key with exactly 32 bytes")
        if not key_id or len(key_id) > 64:
            raise ValueError("invalid key identifier")
        self._key = key
        self._key_id = key_id

    @classmethod
    def from_secret_file(cls, file_path: Path, *, key_id: str = "v1") -> CredentialVault:
        # Symlink-following and group/world readable key files are forbidden.
        if file_path.is_symlink() or not file_path.is_file():
            raise ValueError("secret file must be a regular file")
        # Docker Compose secrets may be mounted as 0444, so permission
        # checks are enforced on the host-side source during provisioning.
        try:
            key = base64.b64decode(file_path.read_bytes().strip(), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("invalid master key encoding") from exc
        return cls(key, key_id=key_id)

    @staticmethod
    def _aad(member_id: str) -> bytes:
        if not member_id:
            raise ValueError("member ID is required")
        return f"boca-socios:credential:v1:{member_id}".encode()

    def seal(self, password: str, *, member_id: str) -> SealedCredential:
        if not password:
            raise ValueError("empty password not allowed")
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._key).encrypt(
            nonce, password.encode("utf-8"), self._aad(member_id)
        )
        return SealedCredential(self._key_id, nonce, ciphertext)

    def open(self, sealed: SealedCredential, *, member_id: str) -> str:
        if sealed.key_id != self._key_id:
            raise ValueError("credential encrypted with unavailable key version")
        return (
            AESGCM(self._key)
            .decrypt(sealed.nonce, sealed.ciphertext, self._aad(member_id))
            .decode("utf-8")
        )
