"""Pure owner-bound issuer for Chrome Telegram V2 pairing receipts (#315).

This is only the cryptographic half of an eventual authenticated owner gate.
The caller must prove live owner/passkey authorization, acquire the exact
protected Boca lease, source the 32-byte signing key outside the database,
and supply its trusted clock. This module cannot authorize itself, acquire
keys/leases, serve a route, install custody, contact Telegram or send notices.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import replace

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios import telegram_pairing_bootstrap as pairing
from boca_socios import telegram_pairing_cutover as cutover


class PairingIssuerError(ValueError):
    """Constant private issuance failure; never include inputs or credentials."""


_V2_FIELDS = frozenset(
    {
        "version",
        "repository",
        "purpose",
        "uid",
        "recipient_public_key",
        "recipient_fingerprint",
        "ephemeral_public_key",
        "salt",
        "nonce",
        "ciphertext",
    }
)


def _validate_ciphertext_header(
    sealed_v2_envelope: bytes, coordinates: cutover.CutoverCoordinates
) -> None:
    """Bind a canonical *ciphertext header* to the pinned recipient, no decrypt."""
    try:
        data = json.loads(sealed_v2_envelope.decode("ascii"), object_pairs_hook=bootstrap._unique)
        if not isinstance(data, dict) or set(data) != _V2_FIELDS:
            raise ValueError("fields")
        public = bootstrap._unb64(data["recipient_public_key"], 32)
        ephemeral = bootstrap._unb64(data["ephemeral_public_key"], 32)
        salt = bootstrap._unb64(data["salt"], 16)
        nonce = bootstrap._unb64(data["nonce"], 12)
        ciphertext = bootstrap._unb64(data["ciphertext"], maximum=2048)
        if (
            sealed_v2_envelope != bootstrap._canonical(data)
            or type(data["version"]) is not int
            or data["version"] != pairing.VERSION
            or data["repository"] != bootstrap.REPOSITORY
            or data["purpose"] != pairing.PURPOSE
            or type(data["uid"]) is not int
            or data["uid"] != bootstrap.UID
            or not isinstance(data["recipient_fingerprint"], str)
            or not hmac.compare_digest(
                data["recipient_fingerprint"], coordinates.recipient_fingerprint
            )
            or not hmac.compare_digest(
                hashlib.sha256(public).hexdigest(), coordinates.recipient_fingerprint
            )
            or len(ephemeral) != 32
            or len(salt) != 16
            or len(nonce) != 12
            or len(ciphertext) < 16
        ):
            raise ValueError("header")
    except (ValueError, TypeError, KeyError, UnicodeError, bootstrap.BootstrapError):
        raise PairingIssuerError("owner_pairing_issuance_no_go") from None


def issue_owner_pairing_receipt(
    coordinates: cutover.CutoverCoordinates,
    sealed_v2_envelope: bytes,
    owner_receipt_key: bytes,
    issued_at: int,
    *,
    discovery_not_before: int | None = None,
) -> cutover.OwnerPairingReceipt:
    """Sign one V2 envelope after a separate trusted owner/session authorization.

    ``issued_at`` must be the private gate's clock. A fresh 256-bit nonce
    ensures each receipt is distinct, but only the host's durable atomic
    consumer can enforce one-time use. The returned receipt is NOT a host GO.
    """
    if (
        not cutover._coordinates_valid(coordinates)
        or type(sealed_v2_envelope) is not bytes
        or not 0 < len(sealed_v2_envelope) <= bootstrap.MAX_ENVELOPE
        or type(owner_receipt_key) is not bytes
        or len(owner_receipt_key) != 32
        or type(issued_at) is not int
        or not 0 <= issued_at <= 2**63 - 601
        or (
            discovery_not_before is not None
            and (
                type(discovery_not_before) is not int
                or not 0 <= discovery_not_before <= issued_at
                or issued_at - discovery_not_before > 3600
            )
        )
    ):
        raise PairingIssuerError("owner_pairing_issuance_no_go")
    _validate_ciphertext_header(sealed_v2_envelope, coordinates)
    nonce = secrets.token_hex(32)
    if type(nonce) is not str or cutover._DIGEST.fullmatch(nonce) is None:
        raise PairingIssuerError("owner_pairing_issuance_no_go")
    receipt = cutover.OwnerPairingReceipt(
        coordinates=coordinates,
        envelope_sha256=hashlib.sha256(sealed_v2_envelope).hexdigest(),
        issued_at=issued_at,
        expires_at=issued_at + 600,
        nonce=nonce,
        auth_tag=b"",
        discovery_not_before=discovery_not_before,
    )
    tag = hmac.new(
        owner_receipt_key,
        cutover._PURPOSE + cutover._owner_payload(receipt),
        hashlib.sha256,
    ).digest()
    return replace(receipt, auth_tag=tag)
