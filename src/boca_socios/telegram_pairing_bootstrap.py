"""Pure V2 Telegram pairing envelope, intentionally not a deployment/install path.

The owner prepares a random code and enters a dedicated bot token in private
Chrome. Both values are sealed to the existing V1 recipient public receipt.
Only a future dedicated protected host adapter may unseal the envelope; neither
the owner panel nor this module calls Telegram, writes secrets or starts a bot.

The separate version and HKDF domain prevent confusion with the existing V1
``bot_token + chat_id`` installation contract.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from boca_socios import telegram_bootstrap as bootstrap

VERSION = 2
PURPOSE = "boca-telegram-pairing-v2"
INFO_PREFIX = b"boca-telegram-pairing-envelope-v2:"
PAIRING_RE = re.compile(r"[A-Za-z0-9_-]{24,64}\Z", re.ASCII)


class PairingEnvelopeError(ValueError):
    """Generic failure without reflection of submitted token or pairing code."""


def _header(
    public: str, fingerprint: str, ephemeral: str, salt: str, nonce: str
) -> dict[str, object]:
    return {
        "version": VERSION,
        "repository": bootstrap.REPOSITORY,
        "purpose": PURPOSE,
        "uid": bootstrap.UID,
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
        info=INFO_PREFIX + hashlib.sha256(aad).digest(),
    ).derive(shared)


def _verify_receipt(receipt: bootstrap.RecipientReceipt) -> None:
    if not isinstance(receipt, bootstrap.RecipientReceipt):
        raise PairingEnvelopeError("invalid_pairing_envelope")
    if receipt.state not in {"PREPARED", "ALREADY_PREPARED"}:
        raise PairingEnvelopeError("invalid_pairing_envelope")
    try:
        public = bootstrap._unb64(receipt.public_key, 32)
    except bootstrap.BootstrapError:
        raise PairingEnvelopeError("invalid_pairing_envelope") from None
    if (
        not isinstance(receipt.fingerprint, str)
        or re.fullmatch(r"[0-9a-f]{64}", receipt.fingerprint) is None
        or not hmac.compare_digest(hashlib.sha256(public).hexdigest(), receipt.fingerprint)
    ):
        raise PairingEnvelopeError("invalid_pairing_envelope")


def _pairing_payload(plaintext: bytes) -> tuple[bytes, str]:
    try:
        payload = json.loads(plaintext.decode("utf-8"), object_pairs_hook=bootstrap._unique)
        if not isinstance(payload, dict) or set(payload) != {"bot_token", "pairing_code"}:
            raise ValueError("bad fields")
        token = payload["bot_token"]
        code = payload["pairing_code"]
        if (
            not isinstance(token, str)
            or re.fullmatch(r"[1-9][0-9]{0,15}:[A-Za-z0-9_-]{8,128}", token) is None
            or int(token.split(":", 1)[0]) >= 2**52
            or not isinstance(code, str)
            or PAIRING_RE.fullmatch(code) is None
            or bootstrap._canonical(payload) != plaintext
        ):
            raise ValueError("bad payload")
        return token.encode("ascii"), code
    except (ValueError, UnicodeError, TypeError, bootstrap.BootstrapError):
        raise PairingEnvelopeError("invalid_pairing_envelope") from None


def unseal_pairing(
    envelope: bytes, private: bytes, receipt: bootstrap.RecipientReceipt
) -> tuple[bytes, str]:
    """Validate V2 envelope and return an in-memory token and pairing code.

    No writes or network calls. Caller must later verify one unique recent
    private ``/start <code>`` update before allowing an install transaction.
    """
    if (
        not isinstance(envelope, bytes)
        or not 0 < len(envelope) <= bootstrap.MAX_ENVELOPE
        or not isinstance(private, bytes)
        or len(private) != 32
    ):
        raise PairingEnvelopeError("invalid_pairing_envelope")
    _verify_receipt(receipt)
    try:
        data = json.loads(envelope.decode("ascii"), object_pairs_hook=bootstrap._unique)
        if not isinstance(data, dict) or set(data) != set(_header("", "", "", "", "")) | {
            "ciphertext"
        }:
            raise ValueError("bad fields")
        if envelope != bootstrap._canonical(data):
            raise ValueError("not canonical")
        if (
            type(data["version"]) is not int
            or data["version"] != VERSION
            or data["repository"] != bootstrap.REPOSITORY
            or data["purpose"] != PURPOSE
            or type(data["uid"]) is not int
            or data["uid"] != bootstrap.UID
            or data["recipient_public_key"] != receipt.public_key
            or not isinstance(data["recipient_fingerprint"], str)
            or not hmac.compare_digest(data["recipient_fingerprint"], receipt.fingerprint)
        ):
            raise ValueError("bad header")
        ephemeral = bootstrap._unb64(data["ephemeral_public_key"], 32)
        salt = bootstrap._unb64(data["salt"], 16)
        nonce = bootstrap._unb64(data["nonce"], 12)
        ciphertext = bootstrap._unb64(data["ciphertext"], maximum=2048)
        if len(ciphertext) < 16:
            raise ValueError("no tag")
        aad = bootstrap._canonical(
            {name: val for name, val in data.items() if name != "ciphertext"}
        )
        shared = X25519PrivateKey.from_private_bytes(private).exchange(
            X25519PublicKey.from_public_bytes(ephemeral)
        )
        plaintext = AESGCM(_key(shared, salt, aad)).decrypt(nonce, ciphertext, aad)
        return _pairing_payload(plaintext)
    except (ValueError, TypeError, KeyError, UnicodeError, InvalidTag, bootstrap.BootstrapError):
        raise PairingEnvelopeError("invalid_pairing_envelope") from None
