"""Offline owner-authenticated Telegram V2 ciphertext staging: no Bot API."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios.panel.telegram_pairing_staging import (
    STAGING_FILENAME,
    PairingStageConflict,
    PairingStageUnavailable,
    stage_private_telegram_pairing,
)
from test_telegram_pairing_ui import TOKEN, _recipient, _run


def _sealed_v2() -> tuple[bytes, str]:
    _, receipt, fragment = _recipient()
    produced = _run(fragment)
    return bootstrap._unb64(produced["output"], maximum=4096), receipt.fingerprint


def test_stages_only_canonical_browser_v2_ciphertext_in_one_private_file(tmp_path: Path) -> None:
    envelope, fingerprint = _sealed_v2()
    path = tmp_path / STAGING_FILENAME

    receipt = stage_private_telegram_pairing(path, envelope)

    assert receipt.state == "STAGED_PENDING_PROTECTED_CUTOVER"
    assert receipt.envelope_sha256 == hashlib.sha256(envelope).hexdigest()
    assert receipt.recipient_fingerprint == fingerprint
    assert path.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.iterdir()) == [path]
    record = json.loads(path.read_bytes())
    assert set(record) == {
        "envelope_base64url",
        "envelope_sha256",
        "purpose",
        "recipient_fingerprint",
        "stage_id",
        "staged_at",
        "version",
    }
    assert bootstrap._unb64(record["envelope_base64url"], maximum=4096) == envelope
    assert len(record["stage_id"]) == 64
    assert TOKEN.encode() not in path.read_bytes()
    assert b"pairing_code" not in path.read_bytes()


def test_rejects_overwrite_without_touching_existing_stage(tmp_path: Path) -> None:
    envelope, _ = _sealed_v2()
    path = tmp_path / STAGING_FILENAME
    stage_private_telegram_pairing(path, envelope)
    before = path.read_bytes()
    with pytest.raises(PairingStageConflict, match="pairing_stage_exists"):
        stage_private_telegram_pairing(path, envelope)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "envelope",
    [
        b"123456:synthetic_token_for_offline_test",
        b"{}",
        b"not json",
        b'{"version":1}',
        b"{}" * 2500,
    ],
)
def test_rejects_plaintext_or_wrong_envelopes_without_creating_file(
    tmp_path: Path, envelope: bytes
) -> None:
    path = tmp_path / STAGING_FILENAME
    with pytest.raises(PairingStageUnavailable, match="pairing_stage_unverified"):
        stage_private_telegram_pairing(path, envelope)
    assert list(tmp_path.iterdir()) == []


def test_rejects_unsafe_directory_and_symlink_target(tmp_path: Path) -> None:
    envelope, _ = _sealed_v2()
    path = tmp_path / STAGING_FILENAME
    unsafe_dir = tmp_path / "unsafe"
    unsafe_dir.mkdir(mode=0o777)
    unsafe_dir.chmod(0o777)
    with pytest.raises(PairingStageUnavailable, match="pairing_stage_unavailable"):
        stage_private_telegram_pairing(unsafe_dir / STAGING_FILENAME, envelope)
    target = tmp_path / "other"
    target.write_text("untouched")
    path.symlink_to(target)
    with pytest.raises(PairingStageConflict, match="pairing_stage_exists"):
        stage_private_telegram_pairing(path, envelope)
    assert target.read_text() == "untouched"
    assert os.readlink(path) == str(target)
