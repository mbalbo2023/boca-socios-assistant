"""Sealed, one-time custody for the real owner's public passkey.

The protected host operation runs this module only in the pinned Boca image,
with a dedicated owner volume, UID 10001, no network and a capped tmpfs.
The sender seals offline; only ciphertext may cross the Actions input boundary.
This module does not register a passkey, choose an origin or start a listener.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from boca_socios.beta_config_preflight import _tls_handshake
from boca_socios.owner_origin import SSH_LOOPBACK_ORIGIN, owner_rp_host

UID = 10001
OWNER_DIR = Path("/run/owner")
REPOSITORY = "mbalbo2023/boca-socios-assistant"
PURPOSE = "boca-owner-passkey-tls-v1"
HTTP_PURPOSE = "boca-owner-passkey-v2"
PRIVATE_KEY = "owner_recipient_x25519.key"
LIMITS = {
    "credential_id": 1024,
    "public_key.der": 512,
    "tls.crt": 8192,
    "tls.key": 4096,
    "health-ca.pem": 8192,
}
HTTP_LIMITS = {"credential_id": 1024, "public_key.der": 512}
MAX_ENVELOPE = 32768


def _bundle_limits(origin: str) -> dict[str, int]:
    return HTTP_LIMITS if origin == SSH_LOOPBACK_ORIGIN else LIMITS


class BootstrapError(ValueError):
    """Only fixed, nonsecret reasons may leave this process."""


@dataclass(frozen=True, slots=True)
class RecipientReceipt:
    state: str
    public_key: str
    fingerprint: str


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: object, *, maximum: int, length: int | None = None) -> bytes:
    if not isinstance(value, str) or not value or len(value) > (maximum * 4 // 3 + 4):
        raise BootstrapError("invalid_envelope")
    try:
        result = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
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


def _coordinates(origin: str, subject: str) -> str:
    if not isinstance(origin, str) or not isinstance(subject, str):
        raise BootstrapError("invalid_coordinates")
    try:
        host = owner_rp_host(origin)
    except ValueError:
        raise BootstrapError("invalid_coordinates") from None
    if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", subject) is None:
        raise BootstrapError("invalid_coordinates")
    return host


def _identity(uid: int) -> None:
    if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (uid, uid, uid, uid):
        raise BootstrapError("dedicated_identity_required")


def _directory(path: Path, uid: int) -> int:
    if not path.is_absolute() or ".." in path.parts:
        raise BootstrapError("owner_directory_unsafe")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != uid
            or metadata.st_gid != uid
            or stat.S_IMODE(metadata.st_mode) != 0o700
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
        raise BootstrapError("owner_entry_unsafe") from None


def _read(directory: int, name: str, uid: int, limit: int) -> bytes:
    try:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=directory
        )
        with os.fdopen(descriptor, "rb") as item:
            metadata = os.fstat(item.fileno())
            parent = os.fstat(directory)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != uid
                or metadata.st_gid != uid
                or metadata.st_dev != parent.st_dev
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != 0o400
                or not 0 < metadata.st_size <= limit
            ):
                raise BootstrapError("owner_entry_unsafe")
            content = item.read(limit + 1)
            if len(content) != metadata.st_size:
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
        with os.fdopen(descriptor, "wb") as item:
            item.write(content)
            item.flush()
            os.fchmod(item.fileno(), 0o400)
            os.fsync(item.fileno())
            metadata = os.fstat(item.fileno())
            if (
                metadata.st_uid != uid
                or metadata.st_gid != uid
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) != 0o400
            ):
                raise BootstrapError("owner_entry_unsafe")
        os.fsync(directory)
    except OSError:
        raise BootstrapError("partial_configuration_preserved") from None


def _receipt(private_bytes: bytes, state: str) -> RecipientReceipt:
    try:
        public = (
            x25519.X25519PrivateKey.from_private_bytes(private_bytes)
            .public_key()
            .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        )
    except ValueError:
        raise BootstrapError("recipient_key_unsafe") from None
    return RecipientReceipt(state, _b64(public), hashlib.sha256(public).hexdigest())


def prepare(owner_dir: Path = OWNER_DIR, *, uid: int = UID) -> RecipientReceipt:
    """Generate only a new recipient key, or re-read an already prepared one."""
    _identity(uid)
    directory = _directory(owner_dir, uid)
    try:
        if any(_exists(directory, name) for name in LIMITS):
            raise BootstrapError("already_configured")
        if _exists(directory, PRIVATE_KEY):
            return _receipt(_read(directory, PRIVATE_KEY, uid, 32), "ALREADY_PREPARED")
        private = x25519.X25519PrivateKey.generate().private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        _write_new(directory, PRIVATE_KEY, private, uid)
        return _receipt(_read(directory, PRIVATE_KEY, uid, 32), "PREPARED")
    finally:
        os.close(directory)


def _validate_bundle(bundle: dict[str, bytes], origin: str, hostname: str) -> None:
    limits = _bundle_limits(origin)
    if (
        set(bundle) != set(limits)
        or any(
            not isinstance(bundle[name], bytes) or not 0 < len(bundle[name]) <= limit
            for name, limit in limits.items()
        )
        or len(bundle["credential_id"]) < 16
    ):
        raise BootstrapError("invalid_owner_material")
    try:
        public = serialization.load_der_public_key(bundle["public_key.der"])
        if (
            not isinstance(public, ec.EllipticCurvePublicKey)
            or not isinstance(public.curve, ec.SECP256R1)
            or public.public_bytes(
                serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            != bundle["public_key.der"]
        ):
            raise ValueError
        if origin != SSH_LOOPBACK_ORIGIN:
            # Legacy HTTPS sender: validate before persistent owner writes.
            with tempfile.TemporaryDirectory(prefix="boca-owner-") as temp:
                paths = {
                    name: Path(temp) / name for name in ("tls.crt", "tls.key", "health-ca.pem")
                }
                for name, path in paths.items():
                    path.write_bytes(bundle[name])
                    path.chmod(0o600)
                _tls_handshake(paths["tls.crt"], paths["tls.key"], paths["health-ca.pem"], hostname)
    except (TypeError, ValueError, OSError):
        raise BootstrapError("invalid_owner_material") from None


def _header(
    receipt: RecipientReceipt, ephemeral: str, salt: str, nonce: str, origin: str, subject: str
) -> dict[str, object]:
    return {
        "version": 1,
        "repository": REPOSITORY,
        "purpose": HTTP_PURPOSE if origin == SSH_LOOPBACK_ORIGIN else PURPOSE,
        "uid": UID,
        "panel_origin": origin,
        "owner_subject": subject,
        "recipient_public_key": receipt.public_key,
        "recipient_fingerprint": receipt.fingerprint,
        "ephemeral_public_key": ephemeral,
        "salt": salt,
        "nonce": nonce,
    }


def _key(shared: bytes, salt: bytes, aad: bytes, origin: str) -> bytes:
    domain = (
        b"boca-owner-passkey-envelope-v2:"
        if origin == SSH_LOOPBACK_ORIGIN
        else b"boca-owner-passkey-tls-envelope-v1:"
    )
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=domain + hashlib.sha256(aad).digest(),
    ).derive(shared)


def seal_for_recipient(
    receipt: RecipientReceipt, bundle: dict[str, bytes], origin: str, subject: str
) -> bytes:
    """Offline sender API: produce canonical ciphertext, never a secret receipt."""
    hostname = _coordinates(origin, subject)
    _validate_bundle(bundle, origin, hostname)
    public = _unb64(receipt.public_key, maximum=32, length=32)
    if not hmac.compare_digest(hashlib.sha256(public).hexdigest(), receipt.fingerprint):
        raise BootstrapError("recipient_key_unsafe")
    ephemeral = x25519.X25519PrivateKey.generate()
    ephemeral_public = ephemeral.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    salt, nonce = os.urandom(16), os.urandom(12)
    header = _header(receipt, _b64(ephemeral_public), _b64(salt), _b64(nonce), origin, subject)
    aad = _canonical(header)
    plaintext = _canonical({name: _b64(value) for name, value in bundle.items()})
    encrypted = AESGCM(
        _key(
            ephemeral.exchange(x25519.X25519PublicKey.from_public_bytes(public)), salt, aad, origin
        )
    ).encrypt(nonce, plaintext, aad)
    envelope = _canonical({**header, "ciphertext": _b64(encrypted)})
    if len(envelope) > MAX_ENVELOPE:
        raise BootstrapError("invalid_owner_material")
    return envelope


def _decrypt(
    envelope: bytes, private: bytes, receipt: RecipientReceipt, origin: str, subject: str
) -> dict[str, bytes]:
    if not 0 < len(envelope) <= MAX_ENVELOPE:
        raise BootstrapError("invalid_envelope")
    try:
        data = json.loads(envelope.decode("ascii"), object_pairs_hook=_unique)
        if not isinstance(data, dict) or set(data) != set(
            _header(receipt, "", "", "", origin, subject)
        ) | {"ciphertext"}:
            raise ValueError
        header = {key: value for key, value in data.items() if key != "ciphertext"}
        if (
            type(data["version"]) is not int
            or data["version"] != 1
            or data["repository"] != REPOSITORY
            or data["purpose"] != (HTTP_PURPOSE if origin == SSH_LOOPBACK_ORIGIN else PURPOSE)
            or type(data["uid"]) is not int
            or data["uid"] != UID
            or data["panel_origin"] != origin
            or data["owner_subject"] != subject
            or data["recipient_public_key"] != receipt.public_key
            or not hmac.compare_digest(data["recipient_fingerprint"], receipt.fingerprint)
            or _canonical(data) != envelope
        ):
            raise ValueError
        ephemeral = _unb64(data["ephemeral_public_key"], maximum=32, length=32)
        salt = _unb64(data["salt"], maximum=16, length=16)
        nonce = _unb64(data["nonce"], maximum=12, length=12)
        ciphertext = _unb64(data["ciphertext"], maximum=MAX_ENVELOPE)
        if len(ciphertext) < 16:
            raise ValueError
        aad = _canonical(header)
        shared = x25519.X25519PrivateKey.from_private_bytes(private).exchange(
            x25519.X25519PublicKey.from_public_bytes(ephemeral)
        )
        plaintext = AESGCM(_key(shared, salt, aad, origin)).decrypt(nonce, ciphertext, aad)
        payload = json.loads(plaintext.decode("ascii"), object_pairs_hook=_unique)
        limits = _bundle_limits(origin)
        if not isinstance(payload, dict) or set(payload) != set(limits):
            raise ValueError
        bundle = {name: _unb64(payload[name], maximum=limit) for name, limit in limits.items()}
        _validate_bundle(bundle, origin, _coordinates(origin, subject))
        return bundle
    except (ValueError, TypeError, KeyError, UnicodeError, InvalidTag):
        raise BootstrapError("invalid_envelope") from None


def install(owner_dir: Path, envelope: bytes, origin: str, subject: str, *, uid: int = UID) -> str:
    """Decrypt and prove material before any exclusive owner-volume file creation."""
    _identity(uid)
    _coordinates(origin, subject)
    directory = _directory(owner_dir, uid)
    try:
        if any(_exists(directory, name) for name in LIMITS):
            raise BootstrapError("already_configured")
        private = _read(directory, PRIVATE_KEY, uid, 32)
        receipt = _receipt(private, "PREPARED")
        bundle = _decrypt(envelope, private, receipt, origin, subject)
        for name, content in bundle.items():
            _write_new(directory, name, content, uid)
        if any(
            _read(directory, name, uid, _bundle_limits(origin)[name]) != content
            for name, content in bundle.items()
        ):
            raise BootstrapError("bundle_unverified")
        return receipt.fingerprint
    finally:
        os.close(directory)


def verify(owner_dir: Path, origin: str, subject: str, *, uid: int = UID) -> str:
    """Check exact custody locally; legacy HTTPS origins also prove TLS."""
    _identity(uid)
    hostname = _coordinates(origin, subject)
    directory = _directory(owner_dir, uid)
    try:
        private = _read(directory, PRIVATE_KEY, uid, 32)
        bundle = {
            name: _read(directory, name, uid, limit)
            for name, limit in _bundle_limits(origin).items()
        }
        if origin == SSH_LOOPBACK_ORIGIN and any(
            _exists(directory, name) for name in ("tls.crt", "tls.key", "health-ca.pem")
        ):
            raise BootstrapError("unexpected_tls_artifact")
        _validate_bundle(bundle, origin, hostname)
        return _receipt(private, "CONFIGURED").fingerprint
    finally:
        os.close(directory)


def main(argv: tuple[str, ...] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Boca sealed owner credential bootstrap")
    parser.add_argument("phase", choices=("prepare", "install", "verify"))
    parser.add_argument("origin")
    parser.add_argument("subject")
    args = parser.parse_args(argv)
    try:
        if args.phase == "prepare":
            _coordinates(args.origin, args.subject)
            receipt = prepare()
            print(
                f"BOCA_OWNER_BOOTSTRAP state={receipt.state} public_key={receipt.public_key} fingerprint={receipt.fingerprint}"
            )
        elif args.phase == "install":
            fingerprint = install(
                OWNER_DIR, sys.stdin.buffer.read(MAX_ENVELOPE + 1), args.origin, args.subject
            )
            print(f"BOCA_OWNER_BOOTSTRAP state=CONFIGURED fingerprint={fingerprint}")
        else:
            fingerprint = verify(OWNER_DIR, args.origin, args.subject)
            print(f"BOCA_OWNER_BOOTSTRAP state=VERIFIED fingerprint={fingerprint}")
    except (BootstrapError, OSError):
        print(
            "BOCA_OWNER_BOOTSTRAP state=NO_GO reason=invalid_envelope_or_custody", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
