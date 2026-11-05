"""Crash-consistent V2 visibility fencing over LOCAL synthetic V1 custody."""

from __future__ import annotations

import fcntl
import json
import os
import stat
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

import pytest

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios import telegram_pairing_install as custody
from boca_socios import telegram_pairing_resolver as resolver
from test_telegram_pairing_resolver import CHAT, NOT_BEFORE, NOW, SOURCE, TOKEN, _FakeBotApi
from test_telegram_pairing_ui import _run


def _synthetic_prepared(tmp_path: Path) -> tuple[Path, resolver.PairingInstallPlan]:
    directory = tmp_path / "telegram"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    prepared = bootstrap.prepare(directory, uid=os.geteuid())
    public_fragment = "#recipient=" + bootstrap._b64(bootstrap._canonical(asdict(prepared)))
    owner = _run(public_fragment)
    private_key = (directory / bootstrap.PRIVATE_KEY).read_bytes()
    plan = resolver.plan_private_telegram_pairing(
        bootstrap._unb64(owner["output"], maximum=4096),
        private_key,
        prepared,
        SOURCE,
        not_before=NOT_BEFORE,
        now=NOW,
        api_fetch=_FakeBotApi(owner["command"][7:]),
    )
    return directory, plan


def _install(
    directory: Path, plan: resolver.PairingInstallPlan, **kwargs: object
) -> custody.PairingCustodyReceipt:
    return custody.install_v2_plan(
        directory,
        plan,
        expected_source_sha=SOURCE,
        now=NOW + 1,
        uid=os.geteuid(),
        **kwargs,
    )


def _verify(directory: Path) -> custody.PairingCustodyReceipt:
    return custody.verify_v2_custody(directory, expected_source_sha=SOURCE, uid=os.geteuid())


def test_v2_commit_marker_publishes_once_after_existing_v1_pair_and_never_sends(
    tmp_path: Path,
) -> None:
    directory, plan = _synthetic_prepared(tmp_path)
    assert not (directory / custody.MARKER).exists()
    result = _install(directory, plan)
    assert result == _verify(directory)
    assert result.source_sha == SOURCE
    assert result.bot_id == 123456
    assert result.notification_receipt == "UNVERIFIED"
    assert result.state == "CUSTODY_COMMITTED_NO_SEND"
    assert not (directory / custody.STAGING).exists()
    assert (directory / bootstrap.TOKEN_FILE).read_text() == TOKEN
    assert (directory / bootstrap.CHAT_FILE).read_text() == str(CHAT)
    prepared_fingerprint = bootstrap.verify(directory, uid=os.geteuid())
    assert result.recipient_fingerprint == prepared_fingerprint
    marker = directory / custody.MARKER
    metadata = marker.stat()
    assert stat.S_IMODE(metadata.st_mode) == 0o400
    assert metadata.st_nlink == 1 and metadata.st_uid == os.geteuid()
    raw = marker.read_bytes()
    assert TOKEN.encode() not in raw and str(CHAT).encode() not in raw
    assert plan.receipt.one_time_fence.encode() in raw
    assert json.loads(raw)["purpose"] == custody.PURPOSE
    assert TOKEN not in repr(result) and str(CHAT) not in repr(result)
    with pytest.raises(custody.PairingCustodyError, match="already_or_partially_configured"):
        _install(directory, plan)


@pytest.mark.parametrize(
    "alter",
    [
        {"source_sha": "b" * 40},
        {"bot_id": 123457},
        {"expected_chat_hmac": "f" * 64},
        {"one_time_fence": "INVALID"},
        {"recipient_fingerprint": "a" * 64},
        {"notification_receipt": "APPROVED"},
        {"state": "READY_TO_SEND"},
        {"pairing_observed_at": NOW - 700},
        {"discovery_update_id": -1},
    ],
)
def test_tampered_plan_never_writes_a_legacy_pair(tmp_path: Path, alter: dict[str, object]) -> None:
    directory, plan = _synthetic_prepared(tmp_path)
    changed = replace(plan, receipt=replace(plan.receipt, **alter))
    with pytest.raises(custody.PairingCustodyError):
        _install(directory, changed)
    assert not (directory / bootstrap.TOKEN_FILE).exists()
    assert not (directory / bootstrap.CHAT_FILE).exists()
    assert not (directory / custody.MARKER).exists()


@pytest.mark.parametrize("now", [NOW - 1, NOW + 601, True, -1])
def test_stale_or_invalid_install_time_never_writes(tmp_path: Path, now: int) -> None:
    directory, plan = _synthetic_prepared(tmp_path)
    with pytest.raises(custody.PairingCustodyError, match="prepared_pairing_unverified"):
        custody.install_v2_plan(
            directory, plan, expected_source_sha=SOURCE, now=now, uid=os.geteuid()
        )
    assert not (directory / bootstrap.TOKEN_FILE).exists()


def test_existing_legacy_v1_pair_cannot_be_mistaken_for_v2_commit(tmp_path: Path) -> None:
    directory = tmp_path / "telegram"
    directory.mkdir(mode=0o700)
    prepared = bootstrap.prepare(directory, uid=os.geteuid())
    bootstrap.install(
        directory,
        bootstrap.seal_for_recipient(prepared, TOKEN, str(CHAT)),
        uid=os.geteuid(),
    )
    assert bootstrap.verify(directory, uid=os.geteuid()) == prepared.fingerprint
    with pytest.raises(custody.PairingCustodyError, match="commit_marker_unverified"):
        _verify(directory)


def test_crash_after_v1_pair_before_staging_preserves_partial_and_blocks_replay(
    tmp_path: Path,
) -> None:
    directory, plan = _synthetic_prepared(tmp_path)
    original = bootstrap._write_new

    def fail_marker(parent: int, name: str, content: bytes, uid: int) -> None:
        if name == custody.STAGING:
            raise bootstrap.BootstrapError("synthetic_marker_stage_failure")
        original(parent, name, content, uid)

    with patch.object(bootstrap, "_write_new", side_effect=fail_marker):
        with pytest.raises(custody.PairingCustodyError, match="custody_commit_uncertain"):
            _install(directory, plan)
    assert bootstrap.verify(directory, uid=os.geteuid())
    assert not (directory / custody.MARKER).exists()
    with pytest.raises(custody.PairingCustodyError):
        _verify(directory)
    with pytest.raises(custody.PairingCustodyError, match="already_or_partially_configured"):
        _install(directory, plan)


def test_crash_during_second_v1_secret_write_never_creates_commit_marker(
    tmp_path: Path,
) -> None:
    directory, plan = _synthetic_prepared(tmp_path)
    original = bootstrap._write_new

    def fail_chat(parent: int, name: str, content: bytes, uid: int) -> None:
        if name == bootstrap.CHAT_FILE:
            raise bootstrap.BootstrapError("synthetic_second_v1_file_failed")
        original(parent, name, content, uid)

    with patch.object(bootstrap, "_write_new", side_effect=fail_chat):
        with pytest.raises(custody.PairingCustodyError, match="custody_install_uncertain"):
            _install(directory, plan)
    assert (directory / bootstrap.TOKEN_FILE).exists()
    assert not (directory / bootstrap.CHAT_FILE).exists()
    assert not (directory / custody.MARKER).exists()
    with pytest.raises(custody.PairingCustodyError, match="legacy_pair_unverified"):
        _verify(directory)
    with pytest.raises(custody.PairingCustodyError, match="already_or_partially_configured"):
        _install(directory, plan)


def test_crash_after_staging_before_link_preserves_residue_and_blocks_sender(
    tmp_path: Path,
) -> None:
    directory, plan = _synthetic_prepared(tmp_path)
    with patch.object(custody.os, "link", side_effect=OSError("synthetic link failure")):
        with pytest.raises(custody.PairingCustodyError, match="custody_commit_uncertain"):
            _install(directory, plan)
    assert (directory / custody.STAGING).exists()
    assert not (directory / custody.MARKER).exists()
    with pytest.raises(custody.PairingCustodyError, match="custody_partial_commit_preserved"):
        _verify(directory)
    with pytest.raises(custody.PairingCustodyError, match="already_or_partially_configured"):
        _install(directory, plan)


def test_crash_after_link_before_unlink_keeps_nlink_two_and_blocks_sender(
    tmp_path: Path,
) -> None:
    directory, plan = _synthetic_prepared(tmp_path)
    original = os.unlink

    def fail_staging(name: str, *, dir_fd: int | None = None) -> None:
        if name == custody.STAGING:
            raise OSError("synthetic final unlink failure")
        original(name, dir_fd=dir_fd)

    with patch.object(custody.os, "unlink", side_effect=fail_staging):
        with pytest.raises(custody.PairingCustodyError, match="custody_commit_uncertain"):
            _install(directory, plan)
    assert (directory / custody.STAGING).exists()
    assert (directory / custody.MARKER).exists()
    assert (directory / custody.MARKER).stat().st_nlink == 2
    with pytest.raises(custody.PairingCustodyError, match="custody_partial_commit_preserved"):
        _verify(directory)


def test_corrupted_marker_different_sha_and_hardlink_fail_closed(tmp_path: Path) -> None:
    directory, plan = _synthetic_prepared(tmp_path)
    _install(directory, plan)
    with pytest.raises(custody.PairingCustodyError, match="commit_marker_unverified"):
        custody.verify_v2_custody(directory, expected_source_sha="b" * 40, uid=os.geteuid())
    marker = directory / custody.MARKER
    os.link(marker, directory / "extra-marker-hardlink")
    with pytest.raises(custody.PairingCustodyError):
        _verify(directory)
    (directory / "extra-marker-hardlink").unlink()
    marker.chmod(0o600)
    changed = json.loads(marker.read_text())
    changed["one_time_fence"] = "f" * 64
    marker.write_text(json.dumps(changed, sort_keys=True, separators=(",", ":")))
    marker.chmod(0o400)
    with pytest.raises(custody.PairingCustodyError, match="commit_marker_unverified"):
        _verify(directory)


def test_legacy_pair_tampering_blocks_v2_even_when_marker_exists(tmp_path: Path) -> None:
    directory, plan = _synthetic_prepared(tmp_path)
    _install(directory, plan)
    chat = directory / bootstrap.CHAT_FILE
    chat.chmod(0o600)
    chat.write_text(str(CHAT + 1))
    chat.chmod(0o400)
    with pytest.raises(custody.PairingCustodyError):
        _verify(directory)


def test_wrong_uid_or_unverified_prepared_volume_never_mutates(tmp_path: Path) -> None:
    directory, plan = _synthetic_prepared(tmp_path)
    with pytest.raises(bootstrap.BootstrapError, match="dedicated_identity_required"):
        custody.install_v2_plan(
            directory,
            plan,
            expected_source_sha=SOURCE,
            now=NOW + 1,
            uid=os.geteuid() + 1,
        )
    directory.chmod(0o755)
    with pytest.raises(bootstrap.BootstrapError, match="telegram_directory_unsafe"):
        _install(directory, plan)
    directory.chmod(0o700)
    assert not (directory / bootstrap.TOKEN_FILE).exists()


def test_preexisting_marker_symlink_is_not_followed_or_overwritten(tmp_path: Path) -> None:
    directory, plan = _synthetic_prepared(tmp_path)
    unrelated = tmp_path / "unrelated-private-file"
    unrelated.write_text("outside-untouched")
    (directory / custody.MARKER).symlink_to(unrelated)
    with pytest.raises(custody.PairingCustodyError, match="already_or_partially_configured"):
        _install(directory, plan)
    assert unrelated.read_text() == "outside-untouched"
    assert not (directory / bootstrap.TOKEN_FILE).exists()


def test_shared_verifier_refuses_exclusive_in_progress_custody_lock(tmp_path: Path) -> None:
    directory, plan = _synthetic_prepared(tmp_path)
    _install(directory, plan)
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(custody.PairingCustodyError, match="custody_lock_unavailable"):
            _verify(directory)
    finally:
        os.close(descriptor)


def test_no_public_receipt_can_disclose_token_or_private_chat_id(tmp_path: Path) -> None:
    directory, plan = _synthetic_prepared(tmp_path)
    receipt = _install(directory, plan)
    public = asdict(receipt)
    serialized = json.dumps(public)
    assert set(public) == {
        "source_sha",
        "recipient_fingerprint",
        "bot_id",
        "state",
        "notification_receipt",
    }
    assert TOKEN not in serialized and str(CHAT) not in serialized
    assert "expected_chat_hmac" not in serialized
    assert "one_time_fence" not in serialized
