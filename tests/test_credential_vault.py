from __future__ import annotations

import base64
import os
from pathlib import Path

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


def test_external_master_key_file(tmp_path: Path) -> None:
    path = tmp_path / "key"
    path.write_bytes(base64.b64encode(os.urandom(32)))
    path.chmod(0o600)
    assert CredentialVault.from_secret_file(path)


def test_master_key_file_rejects_world_readable_and_symlink(tmp_path: Path) -> None:
    path = tmp_path / "master-key"
    path.write_bytes(base64.b64encode(os.urandom(32)))
    path.chmod(0o644)
    with pytest.raises(ValueError, match="readable by other identities"):
        CredentialVault.from_secret_file(path)

    path.chmod(0o600)
    alias = tmp_path / "symlink"
    alias.symlink_to(path)
    with pytest.raises(ValueError, match="unavailable or inaccessible"):
        CredentialVault.from_secret_file(alias)


def test_master_key_file_fails_closed_on_unexpected_contents(tmp_path: Path) -> None:
    path = tmp_path / "master-key"
    path.write_bytes(b"invalid-base64-content")
    path.chmod(0o600)
    with pytest.raises(ValueError, match="encoding"):
        CredentialVault.from_secret_file(path)

    path.write_bytes(b"A" * 300)
    with pytest.raises(ValueError, match="unexpectedly large"):
        CredentialVault.from_secret_file(path)

    path.write_bytes(base64.b64encode(os.urandom(32)))
    path.chmod(0o622)
    with pytest.raises(ValueError, match="writable/executable"):
        CredentialVault.from_secret_file(path)


def test_master_key_file_requires_absolute_regular_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        CredentialVault.from_secret_file(Path("relative-secret"))
    with pytest.raises(ValueError, match="regular file|unavailable or inaccessible"):
        CredentialVault.from_secret_file(tmp_path)


def test_fifo_secret_path_fails_without_blocking(tmp_path: Path) -> None:
    path = tmp_path / "fake-secret-pipe"
    os.mkfifo(path, mode=0o600)
    with pytest.raises(ValueError, match="regular file"):
        CredentialVault.from_secret_file(path)
