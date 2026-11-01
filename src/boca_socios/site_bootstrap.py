"""Sealed, Boca-only Site machine credential intake; no network or host discovery.

The protected workflow must invoke prepare/install/verify only in a pinned Boca
image as UID 10001 with its dedicated /run/owner volume. The sender uses the
pure seal_for_recipient function outside GitHub to produce ciphertext. Neither
this module nor its CLI accepts plaintext credentials as command arguments.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import hmac
import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

UID = 10001
OWNER_DIR = Path("/run/owner")
SITE_ORIGIN = "https://boca-socios-consola-demo-20261031.mbalbo14901.chatgpt.site"
REPOSITORY = "mbalbo2023/boca-socios-assistant"
PURPOSE = "boca-site-bridge-machine-v1"
PRIVATE_KEY = "site_recipient_x25519.key"
BYPASS_FILE = "site_bypass_token"
HMAC_FILE = "site_bridge_hmac_key"
MAX_ENVELOPE = 8192


class BootstrapError(ValueError):
    """Only fixed diagnostic reasons may leave the protected operation."""


@dataclass(frozen=True, slots=True)
class RecipientReceipt:
    state: str
    public_key: str
    fingerprint: str


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: object, length: int | None = None, *, maximum: int = 4096) -> bytes:
    if not isinstance(value, str) or not value or len(value) > maximum * 2:
        raise BootstrapError("invalid_envelope")
    try:
        result = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error):
        raise BootstrapError("invalid_envelope") from None
    if (
        len(result) > maximum
        or (length is not None and len(result) != length)
        or _b64(result) != value
    ):
        raise BootstrapError("invalid_envelope")
    return result


def _pairs_unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BootstrapError("invalid_envelope")
        result[key] = value
    return result


def _canonical(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def _identity(uid: int) -> None:
    if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (uid, uid, uid, uid):
        raise BootstrapError("dedicated_identity_required")


def _directory(path: Path, uid: int) -> int:
    if not path.is_absolute() or ".." in path.parts:
        raise BootstrapError("owner_directory_unsafe")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        meta = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(meta.st_mode)
            or meta.st_uid != uid
            or meta.st_gid != uid
            or stat.S_IMODE(meta.st_mode) != 0o700
        ):
            os.close(descriptor)
            raise BootstrapError("owner_directory_unsafe")
        return descriptor
    except OSError:
        raise BootstrapError("owner_directory_unsafe") from None


def _exists(directory: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        raise BootstrapError("owner_entry_unverified") from None


def _read(directory: int, name: str, uid: int, *, maximum: int) -> bytes:
    try:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=directory
        )
        with os.fdopen(descriptor, "rb") as source:
            meta = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(meta.st_mode)
                or meta.st_uid != uid
                or meta.st_gid != uid
                or meta.st_nlink != 1
                or stat.S_IMODE(meta.st_mode) != 0o400
                or not 0 < meta.st_size <= maximum
            ):
                raise BootstrapError("owner_entry_unsafe")
            content = source.read(maximum + 1)
            if len(content) != meta.st_size:
                raise BootstrapError("owner_entry_unsafe")
            return content
    except OSError:
        raise BootstrapError("owner_entry_unsafe") from None


def _write_new(directory: int, name: str, content: bytes, uid: int) -> None:
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "wb") as target:
            target.write(content)
            target.flush()
            os.fchmod(target.fileno(), 0o400)
            os.fsync(target.fileno())
            meta = os.fstat(target.fileno())
            if meta.st_uid != uid or meta.st_gid != uid or stat.S_IMODE(meta.st_mode) != 0o400:
                raise BootstrapError("owner_entry_unsafe")
        os.fsync(directory)
    except OSError:
        raise BootstrapError("partial_configuration_preserved") from None


def _receipt(private_bytes: bytes, state: str) -> RecipientReceipt:
    try:
        public_bytes = (
            X25519PrivateKey.from_private_bytes(private_bytes)
            .public_key()
            .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        )
    except ValueError:
        raise BootstrapError("recipient_key_unsafe") from None
    return RecipientReceipt(state, _b64(public_bytes), hashlib.sha256(public_bytes).hexdigest())


def prepare(owner_dir: Path = OWNER_DIR, *, uid: int = UID) -> RecipientReceipt:
    """Generate only a Boca recipient key, or safely re-read an existing one."""
    _identity(uid)
    directory = _directory(owner_dir, uid)
    try:
        if _exists(directory, BYPASS_FILE) or _exists(directory, HMAC_FILE):
            raise BootstrapError("already_configured")
        if _exists(directory, PRIVATE_KEY):
            return _receipt(_read(directory, PRIVATE_KEY, uid, maximum=32), "ALREADY_PREPARED")
        private_bytes = X25519PrivateKey.generate().private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        _write_new(directory, PRIVATE_KEY, private_bytes, uid)
        return _receipt(_read(directory, PRIVATE_KEY, uid, maximum=32), "PREPARED")
    finally:
        os.close(directory)


def _validate_token(token: object) -> bytes:
    if not isinstance(token, str) or not 20 <= len(token) <= 2048:
        raise BootstrapError("invalid_secret_material")
    try:
        raw = token.encode("ascii")
    except UnicodeError:
        raise BootstrapError("invalid_secret_material") from None
    if any(char <= 32 or char >= 127 for char in raw):
        raise BootstrapError("invalid_secret_material")
    return raw


def _header(
    public_key: str, fingerprint: str, ephemeral: str, salt: str, nonce: str
) -> dict[str, object]:
    return {
        "version": 1,
        "repository": REPOSITORY,
        "purpose": PURPOSE,
        "uid": UID,
        "site_origin": SITE_ORIGIN,
        "recipient_fingerprint": fingerprint,
        "recipient_public_key": public_key,
        "ephemeral_public_key": ephemeral,
        "salt": salt,
        "nonce": nonce,
    }


def _key(shared: bytes, salt: bytes, aad: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"boca-site-bridge-envelope-v1:" + hashlib.sha256(aad).digest(),
    ).derive(shared)


def seal_for_recipient(receipt: RecipientReceipt, bypass_token: str, hmac_key: bytes) -> bytes:
    """Offline sender API: returns ciphertext only, never logs either secret."""
    token = _validate_token(bypass_token)
    if not isinstance(hmac_key, bytes) or len(hmac_key) != 32:
        raise BootstrapError("invalid_secret_material")
    public_bytes = _unb64(receipt.public_key, 32)
    fingerprint = hashlib.sha256(public_bytes).hexdigest()
    if not hmac.compare_digest(fingerprint, receipt.fingerprint):
        raise BootstrapError("recipient_key_unsafe")
    ephemeral = X25519PrivateKey.generate()
    ephemeral_public = ephemeral.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    salt = os.urandom(16)
    nonce = os.urandom(12)
    header = _header(
        receipt.public_key, fingerprint, _b64(ephemeral_public), _b64(salt), _b64(nonce)
    )
    aad = _canonical(header)
    payload = _canonical(
        {"site_bypass_token": token.decode("ascii"), "site_bridge_hmac_key": _b64(hmac_key)}
    )
    ciphertext = AESGCM(
        _key(ephemeral.exchange(X25519PublicKey.from_public_bytes(public_bytes)), salt, aad)
    ).encrypt(nonce, payload, aad)
    return _canonical({**header, "ciphertext": _b64(ciphertext)})


def _decrypt(
    envelope: bytes, private_bytes: bytes, receipt: RecipientReceipt
) -> tuple[bytes, bytes]:
    if not 0 < len(envelope) <= MAX_ENVELOPE:
        raise BootstrapError("invalid_envelope")
    try:
        data = json.loads(envelope.decode("utf-8"), object_pairs_hook=_pairs_unique)
        expected = set(_header("", "", "", "", "")) | {"ciphertext"}
        if not isinstance(data, dict) or set(data) != expected:
            raise BootstrapError("invalid_envelope")
        header = {key: value for key, value in data.items() if key != "ciphertext"}
        if (
            type(data["version"]) is not int
            or data["version"] != 1
            or data["repository"] != REPOSITORY
            or data["purpose"] != PURPOSE
            or data["uid"] != UID
            or data["site_origin"] != SITE_ORIGIN
            or not isinstance(data["recipient_fingerprint"], str)
            or not hmac.compare_digest(data["recipient_fingerprint"], receipt.fingerprint)
            or data["recipient_public_key"] != receipt.public_key
        ):
            raise BootstrapError("invalid_envelope")
        ephemeral = _unb64(data["ephemeral_public_key"], 32)
        salt = _unb64(data["salt"], 16)
        nonce = _unb64(data["nonce"], 12)
        ciphertext = _unb64(data["ciphertext"], maximum=4096)
        if len(ciphertext) < 16:
            raise BootstrapError("invalid_envelope")
        aad = _canonical(header)
        shared = X25519PrivateKey.from_private_bytes(private_bytes).exchange(
            X25519PublicKey.from_public_bytes(ephemeral)
        )
        plaintext = AESGCM(_key(shared, salt, aad)).decrypt(nonce, ciphertext, aad)
        payload = json.loads(plaintext.decode("utf-8"), object_pairs_hook=_pairs_unique)
        if not isinstance(payload, dict) or set(payload) != {
            "site_bypass_token",
            "site_bridge_hmac_key",
        }:
            raise BootstrapError("invalid_envelope")
        token = _validate_token(payload["site_bypass_token"])
        hmac_key = _unb64(payload["site_bridge_hmac_key"], 32)
        return token, hmac_key
    except (ValueError, TypeError, KeyError, UnicodeError, InvalidTag):
        raise BootstrapError("invalid_envelope") from None


def install(owner_dir: Path, envelope: bytes, *, uid: int = UID) -> str:
    """Decrypt before effects; exclusive pair creation, preserving partial state."""
    _identity(uid)
    directory = _directory(owner_dir, uid)
    try:
        if _exists(directory, BYPASS_FILE) or _exists(directory, HMAC_FILE):
            raise BootstrapError("already_configured")
        private_bytes = _read(directory, PRIVATE_KEY, uid, maximum=32)
        receipt = _receipt(private_bytes, "PREPARED")
        token, hmac_key = _decrypt(envelope, private_bytes, receipt)
        _write_new(directory, BYPASS_FILE, token, uid)
        _write_new(directory, HMAC_FILE, hmac_key, uid)
        if (
            _read(directory, BYPASS_FILE, uid, maximum=2048) != token
            or _read(directory, HMAC_FILE, uid, maximum=32) != hmac_key
        ):
            raise BootstrapError("pair_unverified")
        return receipt.fingerprint
    finally:
        os.close(directory)


def verify(owner_dir: Path = OWNER_DIR, *, uid: int = UID) -> str:
    """Read-only custody check, returning public recipient fingerprint only."""
    _identity(uid)
    directory = _directory(owner_dir, uid)
    try:
        private_bytes = _read(directory, PRIVATE_KEY, uid, maximum=32)
        try:
            _validate_token(_read(directory, BYPASS_FILE, uid, maximum=2048).decode("ascii"))
            if len(_read(directory, HMAC_FILE, uid, maximum=32)) != 32:
                raise BootstrapError("pair_unverified")
        except (UnicodeError, BootstrapError):
            raise BootstrapError("pair_unverified") from None
        return _receipt(private_bytes, "CONFIGURED").fingerprint
    finally:
        os.close(directory)


def main(argv: tuple[str, ...] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Boca Site sealed private credential bootstrap")
    parser.add_argument("phase", choices=("prepare", "install", "verify"))
    args = parser.parse_args(argv)
    try:
        if args.phase == "prepare":
            receipt = prepare()
            print(
                f"BOCA_SITE_BOOTSTRAP state={receipt.state} public_key={receipt.public_key}"
                f" fingerprint={receipt.fingerprint}"
            )
        elif args.phase == "install":
            envelope = sys.stdin.buffer.read(MAX_ENVELOPE + 1)
            fingerprint = install(OWNER_DIR, envelope)
            print(f"BOCA_SITE_BOOTSTRAP state=CONFIGURED fingerprint={fingerprint}")
        else:
            fingerprint = verify()
            print(f"BOCA_SITE_BOOTSTRAP state=VERIFIED fingerprint={fingerprint}")
    except (BootstrapError, OSError):
        print("BOCA_SITE_BOOTSTRAP state=NO_GO reason=invalid_envelope_or_custody", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
