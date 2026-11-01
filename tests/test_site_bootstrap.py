"""Synthetic sealed Site bootstrap; no real token, host or network access."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from boca_socios import site_bootstrap as boot

TOKEN = "synthetic-site-service-token-for-tests-only"
KEY = bytes(range(32))


def _owner(tmp_path: Path) -> Path:
    directory = tmp_path / "owner"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    return directory


def test_sealed_pair_installs_once_without_plaintext_in_receipts(tmp_path: Path) -> None:
    directory = _owner(tmp_path)
    receipt = boot.prepare(directory, uid=os.geteuid())
    assert receipt.state == "PREPARED"
    assert len(receipt.public_key) == 43
    assert len(receipt.fingerprint) == 64
    assert stat.S_IMODE((directory / "site_recipient_x25519.key").stat().st_mode) == 0o400
    assert boot.prepare(directory, uid=os.geteuid()).state == "ALREADY_PREPARED"

    envelope = boot.seal_for_recipient(receipt, TOKEN, KEY)
    assert TOKEN.encode() not in envelope and KEY not in envelope
    assert boot.install(directory, envelope, uid=os.geteuid()) == receipt.fingerprint
    assert (directory / "site_bypass_token").read_bytes() == TOKEN.encode()
    assert (directory / "site_bridge_hmac_key").read_bytes() == KEY
    for name in ("site_bypass_token", "site_bridge_hmac_key"):
        file = directory / name
        assert stat.S_IMODE(file.stat().st_mode) == 0o400
        assert file.stat().st_uid == os.geteuid()
    assert boot.verify(directory, uid=os.geteuid()) == receipt.fingerprint
    with pytest.raises(boot.BootstrapError, match="already_configured"):
        boot.install(directory, envelope, uid=os.geteuid())


def test_wrong_recipient_and_tampering_cannot_write(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = _owner(tmp_path / "a")
    b = _owner(tmp_path / "b")
    ra = boot.prepare(a, uid=os.geteuid())
    boot.prepare(b, uid=os.geteuid())
    envelope = boot.seal_for_recipient(ra, TOKEN, KEY)
    with pytest.raises(boot.BootstrapError):
        boot.install(b, envelope, uid=os.geteuid())
    data = json.loads(envelope)
    for changed in (
        {**data, "purpose": "other-purpose"},
        {**data, "site_origin": "https://other.example.test"},
        {**data, "nonce": "AAAAAAAAAAAAAAAA"},
    ):
        with pytest.raises(boot.BootstrapError):
            boot.install(a, json.dumps(changed).encode(), uid=os.geteuid())
    assert not (a / "site_bypass_token").exists()
    assert not (b / "site_bypass_token").exists()


def test_unsafe_directory_symlink_and_partial_state_preserved(tmp_path: Path) -> None:
    directory = _owner(tmp_path)
    receipt = boot.prepare(directory, uid=os.geteuid())
    envelope = boot.seal_for_recipient(receipt, TOKEN, KEY)
    directory.chmod(0o755)
    with pytest.raises(boot.BootstrapError, match="owner_directory_unsafe"):
        boot.install(directory, envelope, uid=os.geteuid())
    directory.chmod(0o700)
    (directory / "site_bypass_token").symlink_to(tmp_path / "outside")
    with pytest.raises(boot.BootstrapError, match="already_configured"):
        boot.install(directory, envelope, uid=os.geteuid())
    assert not (tmp_path / "outside").exists()
    (directory / "site_bypass_token").unlink()
    (directory / "site_bypass_token").write_bytes(b"partial")
    with pytest.raises(boot.BootstrapError, match="already_configured"):
        boot.install(directory, envelope, uid=os.geteuid())
    assert (directory / "site_bypass_token").read_bytes() == b"partial"
    with pytest.raises(boot.BootstrapError, match="pair_unverified"):
        boot.verify(directory, uid=os.geteuid())


def test_rejects_malformed_envelope_and_invalid_secret_material(tmp_path: Path) -> None:
    directory = _owner(tmp_path)
    receipt = boot.prepare(directory, uid=os.geteuid())
    with pytest.raises(boot.BootstrapError):
        boot.seal_for_recipient(receipt, "bad\nheader", KEY)
    with pytest.raises(boot.BootstrapError):
        boot.seal_for_recipient(receipt, TOKEN, b"short")
    for envelope in (
        b"{" + b"a" * 9000,
        b'{"version":1,"version":1}',
        b"not-json",
    ):
        with pytest.raises(boot.BootstrapError):
            boot.install(directory, envelope, uid=os.geteuid())
    assert not (directory / "site_bypass_token").exists()


def test_partial_second_write_is_preserved_and_blocks_retry(tmp_path: Path) -> None:
    directory = _owner(tmp_path)
    receipt = boot.prepare(directory, uid=os.geteuid())
    envelope = boot.seal_for_recipient(receipt, TOKEN, KEY)
    original = boot._write_new

    def fail_second(parent: int, name: str, content: bytes, uid: int) -> None:
        if name == boot.HMAC_FILE:
            raise boot.BootstrapError("synthetic_second_write_failed")
        original(parent, name, content, uid)

    with patch.object(boot, "_write_new", side_effect=fail_second):
        with pytest.raises(boot.BootstrapError, match="synthetic_second_write_failed"):
            boot.install(directory, envelope, uid=os.geteuid())
    assert (directory / boot.BYPASS_FILE).read_bytes() == TOKEN.encode()
    assert not (directory / boot.HMAC_FILE).exists()
    with pytest.raises(boot.BootstrapError, match="already_configured"):
        boot.install(directory, envelope, uid=os.geteuid())
    with pytest.raises(boot.BootstrapError, match="pair_unverified"):
        boot.verify(directory, uid=os.geteuid())


def test_redirected_owner_directory_or_recipient_key_is_rejected(tmp_path: Path) -> None:
    directory = _owner(tmp_path)
    receipt = boot.prepare(directory, uid=os.geteuid())
    redirected = tmp_path / "redirected"
    redirected.symlink_to(directory, target_is_directory=True)
    with pytest.raises(boot.BootstrapError, match="owner_directory_unsafe"):
        boot.prepare(redirected, uid=os.geteuid())
    private = directory / boot.PRIVATE_KEY
    private.unlink()
    private.symlink_to(tmp_path / "missing")
    with pytest.raises(boot.BootstrapError, match="owner_entry_unsafe"):
        boot.install(directory, boot.seal_for_recipient(receipt, TOKEN, KEY), uid=os.geteuid())
    assert not (directory / boot.BYPASS_FILE).exists()
