"""Synthetic sealed Telegram credential custody; no Bot API or host access."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from boca_socios import telegram_bootstrap as boot

TOKEN = "12345:synthetic-bot-token-for-tests"
CHAT = "-123456789"


def _private_directory(tmp_path: Path) -> Path:
    directory = tmp_path / "telegram"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    return directory


def test_sealed_pair_installs_once_with_owner_only_files_and_redacted_receipt(
    tmp_path: Path,
) -> None:
    directory = _private_directory(tmp_path)
    receipt = boot.prepare(directory, uid=os.geteuid())
    assert receipt.state == "PREPARED"
    assert len(receipt.public_key) == 43 and len(receipt.fingerprint) == 64
    assert stat.S_IMODE((directory / boot.PRIVATE_KEY).stat().st_mode) == 0o400
    assert boot.prepare(directory, uid=os.geteuid()).state == "ALREADY_PREPARED"

    envelope = boot.seal_for_recipient(receipt, TOKEN, CHAT)
    assert TOKEN.encode() not in envelope and CHAT.encode() not in envelope
    assert b"boca-telegram-bot-v1" in envelope
    assert boot.install(directory, envelope, uid=os.geteuid()) == receipt.fingerprint
    assert (directory / boot.TOKEN_FILE).read_text() == TOKEN
    assert (directory / boot.CHAT_FILE).read_text() == CHAT
    for name in (boot.TOKEN_FILE, boot.CHAT_FILE):
        item = (directory / name).stat()
        assert stat.S_IMODE(item.st_mode) == 0o400
        assert item.st_uid == os.geteuid() and item.st_nlink == 1
    assert boot.verify(directory, uid=os.geteuid()) == receipt.fingerprint
    with pytest.raises(boot.BootstrapError, match="already_configured"):
        boot.install(directory, envelope, uid=os.geteuid())
    with pytest.raises(boot.BootstrapError, match="already_configured"):
        boot.prepare(directory, uid=os.geteuid())


def test_wrong_recipient_duplicate_unknown_field_or_bad_tag_cannot_write(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = _private_directory(tmp_path / "a")
    b = _private_directory(tmp_path / "b")
    receipt = boot.prepare(a, uid=os.geteuid())
    boot.prepare(b, uid=os.geteuid())
    envelope = boot.seal_for_recipient(receipt, TOKEN, CHAT)
    with pytest.raises(boot.BootstrapError):
        boot.install(b, envelope, uid=os.geteuid())
    parsed = json.loads(envelope)
    for changed in (
        {**parsed, "purpose": "boca-site-bridge-machine-v1"},
        {**parsed, "unknown": "field"},
        {**parsed, "ciphertext": "AAAA"},
    ):
        with pytest.raises(boot.BootstrapError, match="invalid_envelope"):
            boot.install(a, json.dumps(changed).encode(), uid=os.geteuid())
    with pytest.raises(boot.BootstrapError, match="invalid_envelope"):
        boot.install(a, b'{"version":1,"version":1}', uid=os.geteuid())
    assert not (a / boot.TOKEN_FILE).exists() and not (b / boot.TOKEN_FILE).exists()


def test_invalid_secret_or_unsafe_directory_and_symlink_refused(tmp_path: Path) -> None:
    directory = _private_directory(tmp_path)
    receipt = boot.prepare(directory, uid=os.geteuid())
    for token, chat in (("invalid", CHAT), (TOKEN, "not-numeric"), (TOKEN, "0")):
        with pytest.raises(boot.BootstrapError, match="invalid_secret_material"):
            boot.seal_for_recipient(receipt, token, chat)
    envelope = boot.seal_for_recipient(receipt, TOKEN, CHAT)
    directory.chmod(0o755)
    with pytest.raises(boot.BootstrapError, match="telegram_directory_unsafe"):
        boot.install(directory, envelope, uid=os.geteuid())
    directory.chmod(0o700)
    redirected = tmp_path / "redirected"
    redirected.symlink_to(directory, target_is_directory=True)
    with pytest.raises(boot.BootstrapError, match="telegram_directory_unsafe"):
        boot.prepare(redirected, uid=os.geteuid())
    private = directory / boot.PRIVATE_KEY
    private.unlink()
    private.symlink_to(tmp_path / "absent")
    with pytest.raises(boot.BootstrapError, match="telegram_entry_unsafe"):
        boot.install(directory, envelope, uid=os.geteuid())
    assert not (directory / boot.TOKEN_FILE).exists()


def test_partial_second_write_is_preserved_and_blocks_replay(tmp_path: Path) -> None:
    directory = _private_directory(tmp_path)
    receipt = boot.prepare(directory, uid=os.geteuid())
    envelope = boot.seal_for_recipient(receipt, TOKEN, CHAT)
    original = boot._write_new

    def fail_second(parent: int, name: str, content: bytes, uid: int) -> None:
        if name == boot.CHAT_FILE:
            raise boot.BootstrapError("synthetic_second_write_failed")
        original(parent, name, content, uid)

    with patch.object(boot, "_write_new", side_effect=fail_second):
        with pytest.raises(boot.BootstrapError, match="synthetic_second_write_failed"):
            boot.install(directory, envelope, uid=os.geteuid())
    assert (directory / boot.TOKEN_FILE).read_text() == TOKEN
    assert not (directory / boot.CHAT_FILE).exists()
    with pytest.raises(boot.BootstrapError, match="already_configured"):
        boot.install(directory, envelope, uid=os.geteuid())
    with pytest.raises(boot.BootstrapError, match="pair_unverified"):
        boot.verify(directory, uid=os.geteuid())


def test_unsafe_configured_file_and_wrong_uid_fail_closed(tmp_path: Path) -> None:
    directory = _private_directory(tmp_path)
    receipt = boot.prepare(directory, uid=os.geteuid())
    boot.install(directory, boot.seal_for_recipient(receipt, TOKEN, CHAT), uid=os.geteuid())
    (directory / boot.CHAT_FILE).chmod(0o644)
    with pytest.raises(boot.BootstrapError, match="pair_unverified"):
        boot.verify(directory, uid=os.geteuid())
    with pytest.raises(boot.BootstrapError, match="dedicated_identity_required"):
        boot.verify(directory, uid=os.geteuid() + 1)
