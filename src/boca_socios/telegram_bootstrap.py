"""Offline, explicit sealed custody of a dedicated Boca Telegram bot pair.

The only install input is ciphertext on stdin. This module does not create a
volume, contact Telegram, migrate SQLite or start a worker. A protected host
operation must separately prove the volume, image, owner and destination.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
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
TELEGRAM_DIR = Path("/run/telegram")
REPOSITORY = "mbalbo2023/boca-socios-assistant"
PURPOSE = "boca-telegram-bot-v1"
PRIVATE_KEY = "telegram_recipient_x25519.key"
TOKEN_FILE = "bot_token"  # noqa: S105 - filename, never the token value
CHAT_FILE = "chat_id"
MAX_ENVELOPE = 4096


class BootstrapError(ValueError):
    """Only fixed diagnostic reasons may leave the private process."""


@dataclass(frozen=True, slots=True)
class RecipientReceipt:
    state: str
    public_key: str
    fingerprint: str


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: object, length: int | None = None, *, maximum: int = 2048) -> bytes:
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


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
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
    if not path.is_absolute() or ".." in path.parts or len(path.parts) > 32:
        raise BootstrapError("telegram_directory_unsafe")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        descriptor = os.open("/", flags)
        try:
            for part in path.parts[1:]:
                child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != uid
                or metadata.st_gid != uid
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise BootstrapError("telegram_directory_unsafe")
            result, descriptor = descriptor, -1
            return result
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    except OSError:
        raise BootstrapError("telegram_directory_unsafe") from None


def _exists(directory: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        raise BootstrapError("telegram_entry_unsafe") from None


def _read(directory: int, name: str, uid: int, *, maximum: int) -> bytes:
    try:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=directory
        )
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != uid
                or metadata.st_gid != uid
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != 0o400
                or not 0 < metadata.st_size <= maximum
            ):
                raise BootstrapError("telegram_entry_unsafe")
            content = source.read(maximum + 1)
            if len(content) != metadata.st_size:
                raise BootstrapError("telegram_entry_unsafe")
            return content
    except OSError:
        raise BootstrapError("telegram_entry_unsafe") from None


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
            metadata = os.fstat(target.fileno())
            if (
                metadata.st_uid != uid
                or metadata.st_gid != uid
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != 0o400
            ):
                raise BootstrapError("telegram_entry_unsafe")
        os.fsync(directory)
    except OSError:
        raise BootstrapError("partial_configuration_preserved") from None


def _receipt(private_bytes: bytes, state: str) -> RecipientReceipt:
    try:
        public = (
            X25519PrivateKey.from_private_bytes(private_bytes)
            .public_key()
            .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        )
    except ValueError:
        raise BootstrapError("recipient_key_unsafe") from None
    return RecipientReceipt(state, _b64(public), hashlib.sha256(public).hexdigest())


def prepare(directory: Path = TELEGRAM_DIR, *, uid: int = UID) -> RecipientReceipt:
    """Create only a new recipient key, or verify a previously prepared key."""
    _identity(uid)
    parent = _directory(directory, uid)
    try:
        if _exists(parent, TOKEN_FILE) or _exists(parent, CHAT_FILE):
            raise BootstrapError("already_configured")
        if _exists(parent, PRIVATE_KEY):
            return _receipt(_read(parent, PRIVATE_KEY, uid, maximum=32), "ALREADY_PREPARED")
        private = X25519PrivateKey.generate().private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        _write_new(parent, PRIVATE_KEY, private, uid)
        return _receipt(_read(parent, PRIVATE_KEY, uid, maximum=32), "PREPARED")
    finally:
        os.close(parent)


def _token(value: object) -> bytes:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[0-9]{1,20}:[A-Za-z0-9_-]{8,128}", value) is None
    ):
        raise BootstrapError("invalid_secret_material")
    return value.encode("ascii")


def _chat(value: object) -> bytes:
    if not isinstance(value, str) or re.fullmatch(r"-?[0-9]{1,20}", value) is None:
        raise BootstrapError("invalid_secret_material")
    numeric = int(value)
    if numeric == 0 or str(numeric) != value:
        raise BootstrapError("invalid_secret_material")
    return value.encode("ascii")


def _header(
    public: str, fingerprint: str, ephemeral: str, salt: str, nonce: str
) -> dict[str, object]:
    return {
        "version": 1,
        "repository": REPOSITORY,
        "purpose": PURPOSE,
        "uid": UID,
        "recipient_public_key": public,
        "recipient_fingerprint": fingerprint,
        "ephemeral_public_key": ephemeral,
        "salt": salt,
        "nonce": nonce,
    }


def _key(shared: bytes, salt: bytes, aad: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b"boca-telegram-bot-envelope-v1:" + hashlib.sha256(aad).digest(),
    ).derive(shared)


def seal_for_recipient(receipt: RecipientReceipt, bot_token: str, chat_id: str) -> bytes:
    """Pure offline sender API; output is ciphertext and public recipient data."""
    token, chat = _token(bot_token), _chat(chat_id)
    if not isinstance(receipt, RecipientReceipt):
        raise BootstrapError("recipient_key_unsafe")
    public = _unb64(receipt.public_key, 32)
    fingerprint = hashlib.sha256(public).hexdigest()
    if (
        not isinstance(receipt.fingerprint, str)
        or re.fullmatch(r"[0-9a-f]{64}", receipt.fingerprint) is None
        or not hmac.compare_digest(fingerprint, receipt.fingerprint)
    ):
        raise BootstrapError("recipient_key_unsafe")
    ephemeral = X25519PrivateKey.generate()
    ephemeral_public = ephemeral.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    salt, nonce = os.urandom(16), os.urandom(12)
    header = _header(
        receipt.public_key, fingerprint, _b64(ephemeral_public), _b64(salt), _b64(nonce)
    )
    aad = _canonical(header)
    try:
        shared = ephemeral.exchange(X25519PublicKey.from_public_bytes(public))
    except ValueError:
        raise BootstrapError("recipient_key_unsafe") from None
    ciphertext = AESGCM(_key(shared, salt, aad)).encrypt(
        nonce,
        _canonical({"bot_token": token.decode("ascii"), "chat_id": chat.decode("ascii")}),
        aad,
    )
    return _canonical({**header, "ciphertext": _b64(ciphertext)})


def _decrypt(envelope: bytes, private: bytes, receipt: RecipientReceipt) -> tuple[bytes, bytes]:
    if not 0 < len(envelope) <= MAX_ENVELOPE:
        raise BootstrapError("invalid_envelope")
    try:
        data = json.loads(envelope.decode("utf-8"), object_pairs_hook=_unique)
        if not isinstance(data, dict) or set(data) != set(_header("", "", "", "", "")) | {
            "ciphertext"
        }:
            raise BootstrapError("invalid_envelope")
        header = {name: value for name, value in data.items() if name != "ciphertext"}
        if (
            type(data["version"]) is not int
            or data["version"] != 1
            or data["repository"] != REPOSITORY
            or data["purpose"] != PURPOSE
            or data["uid"] != UID
            or data["recipient_public_key"] != receipt.public_key
            or not isinstance(data["recipient_fingerprint"], str)
            or not hmac.compare_digest(data["recipient_fingerprint"], receipt.fingerprint)
        ):
            raise BootstrapError("invalid_envelope")
        ephemeral = _unb64(data["ephemeral_public_key"], 32)
        salt = _unb64(data["salt"], 16)
        nonce = _unb64(data["nonce"], 12)
        ciphertext = _unb64(data["ciphertext"], maximum=2048)
        if len(ciphertext) < 16:
            raise BootstrapError("invalid_envelope")
        aad = _canonical(header)
        shared = X25519PrivateKey.from_private_bytes(private).exchange(
            X25519PublicKey.from_public_bytes(ephemeral)
        )
        plaintext = AESGCM(_key(shared, salt, aad)).decrypt(nonce, ciphertext, aad)
        payload = json.loads(plaintext.decode("utf-8"), object_pairs_hook=_unique)
        if not isinstance(payload, dict) or set(payload) != {"bot_token", "chat_id"}:
            raise BootstrapError("invalid_envelope")
        return _token(payload["bot_token"]), _chat(payload["chat_id"])
    except (ValueError, TypeError, KeyError, UnicodeError, InvalidTag):
        raise BootstrapError("invalid_envelope") from None


def install(directory: Path, envelope: bytes, *, uid: int = UID) -> str:
    """Decrypt and validate the whole pair before exclusive writes; no retry."""
    _identity(uid)
    parent = _directory(directory, uid)
    try:
        if _exists(parent, TOKEN_FILE) or _exists(parent, CHAT_FILE):
            raise BootstrapError("already_configured")
        private = _read(parent, PRIVATE_KEY, uid, maximum=32)
        receipt = _receipt(private, "PREPARED")
        token, chat = _decrypt(envelope, private, receipt)
        _write_new(parent, TOKEN_FILE, token, uid)
        _write_new(parent, CHAT_FILE, chat, uid)
        if (
            _read(parent, TOKEN_FILE, uid, maximum=150) != token
            or _read(parent, CHAT_FILE, uid, maximum=21) != chat
        ):
            raise BootstrapError("pair_unverified")
        return receipt.fingerprint
    finally:
        os.close(parent)


def verify(directory: Path = TELEGRAM_DIR, *, uid: int = UID) -> str:
    """Only a redacted custody check; does not prove Bot API or owner receipt."""
    _identity(uid)
    parent = _directory(directory, uid)
    try:
        private = _read(parent, PRIVATE_KEY, uid, maximum=32)
        try:
            _token(_read(parent, TOKEN_FILE, uid, maximum=150).decode("ascii"))
            _chat(_read(parent, CHAT_FILE, uid, maximum=21).decode("ascii"))
        except (BootstrapError, UnicodeError):
            raise BootstrapError("pair_unverified") from None
        return _receipt(private, "CONFIGURED").fingerprint
    finally:
        os.close(parent)


def main(argv: tuple[str, ...] | None = None) -> int:
    args = tuple(sys.argv[1:]) if argv is None else argv
    try:
        if args == ("prepare",):
            receipt = prepare()
            print(
                f"BOCA_TELEGRAM_BOOTSTRAP state={receipt.state} public_key={receipt.public_key}"
                f" fingerprint={receipt.fingerprint}"
            )
        elif args == ("install",):
            fingerprint = install(TELEGRAM_DIR, sys.stdin.buffer.read(MAX_ENVELOPE + 1))
            print(f"BOCA_TELEGRAM_BOOTSTRAP state=CONFIGURED fingerprint={fingerprint}")
        elif args == ("verify",):
            fingerprint = verify()
            print(f"BOCA_TELEGRAM_BOOTSTRAP state=VERIFIED fingerprint={fingerprint}")
        else:
            raise BootstrapError("invalid_phase")
    except (BootstrapError, OSError):
        print(
            "BOCA_TELEGRAM_BOOTSTRAP state=NO_GO reason=invalid_envelope_or_custody",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
