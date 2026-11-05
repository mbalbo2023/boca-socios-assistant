"""Owner pairing issuer signs only a valid Chrome V2 envelope, offline."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from unittest.mock import patch

import pytest

from boca_socios import telegram_pairing_cutover as cutover
from boca_socios import telegram_pairing_issuer as issuer
from test_telegram_pairing_resolver import NOT_BEFORE, SOURCE, _prepared

KEY = bytes(range(32))


def _pair() -> tuple[cutover.CutoverCoordinates, bytes]:
    _, receipt, envelope, _ = _prepared()
    return (
        cutover.CutoverCoordinates(
            attempt_id="41942000001",
            target_sha=SOURCE,
            image_digest="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64,
            owner_digest="b" * 64,
            lease_digest="c" * 64,
            controller_id="d" * 64,
            recipient_fingerprint=receipt.fingerprint,
        ),
        envelope,
    )


def test_issuer_receipt_is_accepted_by_real_cutover_verifier_and_redacted() -> None:
    coordinates, envelope = _pair()
    with patch.object(issuer.secrets, "token_hex", return_value="f" * 64):
        receipt = issuer.issue_owner_pairing_receipt(coordinates, envelope, KEY, NOT_BEFORE)
    cutover._verify_owner_receipt(coordinates, receipt, KEY, envelope, NOT_BEFORE + 1)
    assert receipt.nonce == "f" * 64
    assert receipt.envelope_sha256 == hashlib.sha256(envelope).hexdigest()
    assert receipt.expires_at - receipt.issued_at == 600
    assert receipt.nonce not in repr(receipt)
    assert repr(receipt).find("auth_tag") == -1
    assert envelope.hex() not in repr(receipt)


def test_issuer_rejects_invalid_coordinates_owner_key_and_clock_without_signing() -> None:
    coordinates, envelope = _pair()
    invalid = (
        (replace(coordinates, lease_digest="not-a-digest"), envelope, KEY, NOT_BEFORE),
        (coordinates, envelope, b"short", NOT_BEFORE),
        (coordinates, envelope, KEY, True),
        (coordinates, envelope, KEY, -1),
        (coordinates, b"", KEY, NOT_BEFORE),
        (coordinates, envelope + b"garbage", KEY, NOT_BEFORE),
    )
    with patch.object(issuer.secrets, "token_hex") as entropy:
        for args in invalid:
            with pytest.raises(issuer.PairingIssuerError, match="owner_pairing_issuance_no_go"):
                issuer.issue_owner_pairing_receipt(*args)
        entropy.assert_not_called()


def test_issuer_rejects_wrong_recipient_or_noncannonical_v2_envelope() -> None:
    coordinates, envelope = _pair()
    bad_coordinates = replace(coordinates, recipient_fingerprint="0" * 64)
    with pytest.raises(issuer.PairingIssuerError, match="owner_pairing_issuance_no_go"):
        issuer.issue_owner_pairing_receipt(bad_coordinates, envelope, KEY, NOT_BEFORE)
    with pytest.raises(issuer.PairingIssuerError, match="owner_pairing_issuance_no_go"):
        issuer.issue_owner_pairing_receipt(coordinates, b'{"version":2}\n', KEY, NOT_BEFORE)


def test_receipt_cannot_authenticate_different_ciphertext_or_owner_identity() -> None:
    coordinates, envelope = _pair()
    receipt = issuer.issue_owner_pairing_receipt(coordinates, envelope, KEY, NOT_BEFORE)
    for alt_coordinates, alt_envelope in (
        (replace(coordinates, owner_digest="e" * 64), envelope),
        (coordinates, envelope + b"x"),
    ):
        with pytest.raises(cutover.TelegramCutoverError, match="owner_pairing_receipt_unverified"):
            cutover._verify_owner_receipt(
                alt_coordinates, receipt, KEY, alt_envelope, NOT_BEFORE + 1
            )
    with pytest.raises(cutover.TelegramCutoverError, match="owner_pairing_receipt_unverified"):
        cutover._verify_owner_receipt(coordinates, receipt, KEY, envelope, NOT_BEFORE + 601)


def test_issuer_nonce_entropy_is_fresh_per_call_and_strictly_validated() -> None:
    coordinates, envelope = _pair()
    first = issuer.issue_owner_pairing_receipt(coordinates, envelope, KEY, NOT_BEFORE)
    second = issuer.issue_owner_pairing_receipt(coordinates, envelope, KEY, NOT_BEFORE)
    assert first.nonce != second.nonce
    assert first.auth_tag != second.auth_tag
    with patch.object(issuer.secrets, "token_hex", return_value="invalid"):
        with pytest.raises(issuer.PairingIssuerError, match="owner_pairing_issuance_no_go"):
            issuer.issue_owner_pairing_receipt(coordinates, envelope, KEY, NOT_BEFORE)
