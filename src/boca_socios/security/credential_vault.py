"""AES-256-GCM encryption for third-party credentials.

Passwords must be recoverable for user-authorized login, so irreversible
password hashes are not suitable for this particular storage requirement.
Every value gets a fresh nonce and is bound to its member ID as AAD.
"""

from __future__ import annotations

import base64
import binascii
import os
import stat
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
        """Read a bounded key through a non-following file descriptor.

        Owner-only files are required except for the exact Docker-managed
        secret mount, which some Compose implementations expose as 0444.
        In that special case container boundaries and host-source permissions
        must be verified separately before any real credential enrollment.
        """
        if not file_path.is_absolute():
            raise ValueError("master key path must be absolute")
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None:
            raise ValueError("platform cannot securely open master key without no-follow")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | no_follow | getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(file_path, flags)
            with os.fdopen(descriptor, "rb") as source:
                metadata = os.fstat(source.fileno())
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValueError("master key must be a regular file")
                if metadata.st_uid not in {0, os.geteuid()}:
                    raise ValueError("master key file has unexpected owner")
                permissions = stat.S_IMODE(metadata.st_mode)
                if permissions & 0o133:
                    raise ValueError("master key file is writable/executable by others")
                # Only the exact read-only Compose 0444 mount is compatible;
                # never permit a writable 0644/0604 source via this exception.
                docker_secret = cls._is_readonly_docker_secret(file_path, permissions)
                if permissions & 0o044 and not docker_secret:
                    raise ValueError("master key file is readable by other identities")
                encoded = source.read(129)
                if len(encoded) > 128:
                    raise ValueError("master key file is unexpectedly large")
        except OSError as exc:
            raise ValueError("master key file is unavailable or inaccessible") from exc
        try:
            key = base64.b64decode(encoded.strip(), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("invalid master key encoding") from exc
        return cls(key, key_id=key_id)

    @staticmethod
    def _is_readonly_docker_secret(file_path: Path, permissions: int) -> bool:
        """Only one exact path and exact read-only mount mode qualify."""
        return file_path == Path("/run/secrets/boca_master_key") and permissions == 0o444

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
