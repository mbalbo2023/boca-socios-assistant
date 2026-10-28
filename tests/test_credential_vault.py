from __future__ import annotations

import base64
import os

import pytest
from cryptography.exceptions import InvalidTag

from boca_socios.security.credential_vault import CredentialVault, SealedCredential


def test_ciphertext_roundtrip_and_nonce_uniqueness() -> None:
    vault = CredentialVault(os.urandom(32))
    first = vault.seal("example-password-not-real", member_id="member-a")
    second = vault.seal("example-password-not-real", member_id="member-a")
    assert vault.open(first, member_id="member-a") == "example-password-not-real"
    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext
    assert b"example-password-not-real" not in first.ciphertext


def test_wrong_member_cannot_decrypt() -> None:
    vault = CredentialVault(os.urandom(32))
    secret = vault.seal("test-only", member_id="member-a")
    with pytest.raises(InvalidTag):
        vault.open(secret, member_id="member-b")


def test_tampering_is_rejected() -> None:
    vault = CredentialVault(os.urandom(32))
    secret = vault.seal("test-only", member_id="member-a")
    modified = SealedCredential(
        secret.key_id,
        secret.nonce,
        secret.ciphertext[:-1] + bytes([secret.ciphertext[-1] ^ 1]),
    )
    with pytest.raises(InvalidTag):
        vault.open(modified, member_id="member-a")


def test_external_master_key_file(tmp_path: object) -> None:
    from pathlib import Path

    path = Path(str(tmp_path)) / "key"
    path.write_bytes(base64.b64encode(os.urandom(32)))
    assert CredentialVault.from_secret_file(path)
