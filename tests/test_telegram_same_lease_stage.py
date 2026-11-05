"""Offline Telegram stage -> host lease -> durable one-use nonce contract.

All credentials and provider replies are invented; no Docker, SSH, Telegram or
host workflow is used. The canonical Boca lease is exercised as a real flock.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import telegram_pairing_cutover as cutover
from boca_socios import telegram_pairing_issuer as issuer
from boca_socios.panel.telegram_pairing_staging import stage_private_telegram_pairing
from boca_socios.telegram_pairing_install import PairingCustodyReceipt
from boca_socios.telegram_same_lease_stage import (
    SameLeasePairingError,
    consume_telegram_owner_nonce,
    execute_staged_pairing_under_lease,
    read_encrypted_telegram_stage,
)
from test_telegram_pairing_resolver import (
    NOT_BEFORE,
    NOW,
    SOURCE,
    _FakeBotApi,
    _message,
    _prepared,
)
from test_telegram_pairing_ui import TOKEN

KEY = bytes(range(32))


@pytest.fixture
def lease_volume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    lease_root = tmp_path / "private-runtime"
    lease_root.mkdir(mode=0o700)
    data_root = tmp_path / "data"
    data_root.mkdir(mode=0o700)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(cleanup, "EXPECTED_GID", os.getegid())
    monkeypatch.setattr(cleanup, "LEASE_DIR", lease_root)
    return lease_root, data_root


def _setup(data: Path, monkeypatch: pytest.MonkeyPatch):
    private, recipient, v2, code = _prepared()
    coords = cutover.CutoverCoordinates(
        attempt_id="41937000001",
        target_sha=SOURCE,
        image_digest="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64,
        owner_digest="b" * 64,
        lease_digest="c" * 64,
        controller_id="d" * 64,
        recipient_fingerprint=recipient.fingerprint,
    )
    monkeypatch.setattr("boca_socios.panel.telegram_pairing_staging.time.time", lambda: NOT_BEFORE)
    receipt = stage_private_telegram_pairing(data / "boca_telegram_pairing_stage_v2.json", v2)
    assert receipt.envelope_sha256 == hashlib.sha256(v2).hexdigest()
    grant = issuer.issue_owner_pairing_receipt(
        coords, v2, KEY, NOT_BEFORE, discovery_not_before=NOT_BEFORE
    )
    return private, recipient, v2, code, coords, grant


def _host(phase: str, coords: cutover.CutoverCoordinates):
    return cutover.HostRecheckReceipt(
        coordinates=coords,
        phase=phase,
        observed_at=NOW,
        rootless_uid=10001,
        owner_authenticated=True,
        singleton_controller_stopped=True,
        sender_off=True,
        schema_0007_ready=True,
        exclusive_lease_held=True,
        dedicated_telegram_egress=True,
        no_competing_poller=True,
        recipient_custody_verified=True,
        unrelated_services_untouched=True,
    )


def test_stage_and_nonce_are_distinct_and_custody_commit_is_sender_off(
    lease_volume: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, data = lease_volume
    private, recipient, v2, code, coords, grant = _setup(data, monkeypatch)
    stored = json.loads((data / "boca_telegram_pairing_stage_v2.json").read_text())
    assert stored["stage_id"] != grant.nonce
    methods: list[str] = []
    phases: list[str] = []
    api = _FakeBotApi(code)
    fake_commit = PairingCustodyReceipt(SOURCE, recipient.fingerprint, 123456)
    monkeypatch.setattr(cutover, "install_v2_plan", lambda *_a, **_k: fake_commit)
    monkeypatch.setattr(cutover, "verify_v2_custody", lambda *_a, **_k: fake_commit)

    def observer(phase, value):
        phases.append(phase)
        return _host(phase, value)

    def fetch(token, method, chat):
        methods.append(method)
        return api(token, method, chat)

    with cleanup.protected_boca_job_lease(coords.attempt_id) as lease:
        loaded = read_encrypted_telegram_stage(data, coordinates=coords, lease=lease)
        assert loaded.envelope_sha256 == stored["envelope_sha256"]
        assert loaded.envelope == v2
        assert loaded.stage_id == stored["stage_id"]
        result = execute_staged_pairing_under_lease(
            stage_directory=data,
            custody_directory=tmp_path / "telegram",
            coordinates=coords,
            owner_receipt=grant,
            owner_receipt_key=KEY,
            recipient=recipient,
            private_key=private,
            lease=lease,
            trusted_clock=lambda: NOW,
            inspect_host=observer,
            api_fetch=fetch,
        )
        assert result.state == "CUSTODY_COMMITTED_NO_SEND"
        assert result.sender_state == "OFF"
        assert result.human_notification_receipt == "UNVERIFIED"
        assert methods == ["getMe", "getWebhookInfo", "getUpdates", "getChat"]
        assert phases == [
            "BEFORE_API",
            "BEFORE_getMe",
            "BEFORE_getWebhookInfo",
            "BEFORE_getUpdates",
            "BEFORE_getChat",
            "BEFORE_COMMIT",
            "AFTER_COMMIT",
        ]
        assert len(list(data.glob("boca_telegram_owner_nonce_v2_*.json"))) == 1
        assert TOKEN not in repr(result)
        assert TOKEN not in repr(loaded)
        assert code not in repr(loaded)
        with pytest.raises(cutover.TelegramCutoverError, match="nonce_unverified"):
            execute_staged_pairing_under_lease(
                stage_directory=data,
                custody_directory=tmp_path / "telegram",
                coordinates=coords,
                owner_receipt=grant,
                owner_receipt_key=KEY,
                recipient=recipient,
                private_key=private,
                lease=lease,
                trusted_clock=lambda: NOW,
                inspect_host=observer,
                api_fetch=fetch,
            )
        assert methods == ["getMe", "getWebhookInfo", "getUpdates", "getChat"]


@pytest.mark.parametrize("case", ["unknown", "cross_attempt", "expired", "wrong_dir"])
def test_bad_owner_or_lease_aborts_without_nonce_or_provider(
    lease_volume: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: str
) -> None:
    _, data = lease_volume
    private, recipient, _, _, coords, grant = _setup(data, monkeypatch)
    calls: list[str] = []

    def observer(phase, value):
        calls.append(phase)
        return _host(phase, value)

    with cleanup.protected_boca_job_lease(coords.attempt_id) as lease:
        if case == "unknown":
            grant = replace(grant, auth_tag=b"x" * 32)
        if case == "cross_attempt":
            coords = replace(coords, attempt_id="41937000002")

        def clock():
            return NOT_BEFORE + 601 if case == "expired" else NOW

        with pytest.raises((SameLeasePairingError, cutover.TelegramCutoverError)):
            execute_staged_pairing_under_lease(
                stage_directory=data if case != "wrong_dir" else tmp_path / "missing",
                custody_directory=tmp_path / "telegram",
                coordinates=coords,
                owner_receipt=grant,
                owner_receipt_key=KEY,
                recipient=recipient,
                private_key=private,
                lease=lease,
                trusted_clock=clock,
                inspect_host=observer,
                api_fetch=lambda *_: b"{}",
            )
    assert list(data.glob("boca_telegram_owner_nonce_v2_*.json")) == []
    assert calls == []


def test_durable_nonce_fail_closed_on_replay_after_lease_release(
    lease_volume: tuple[Path, Path],
) -> None:
    _, data = lease_volume
    coords = cutover.CutoverCoordinates(
        "41937000001",
        SOURCE,
        "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64,
        "b" * 64,
        "c" * 64,
        "d" * 64,
        "e" * 64,
    )
    nonce = "f" * 64
    with cleanup.protected_boca_job_lease(coords.attempt_id) as lease:
        assert consume_telegram_owner_nonce(data, nonce, coords, lease=lease) is True
        assert consume_telegram_owner_nonce(data, nonce, coords, lease=lease) is False
    with pytest.raises(SameLeasePairingError):
        consume_telegram_owner_nonce(data, "e" * 64, coords, lease=lease)
    with cleanup.protected_boca_job_lease(coords.attempt_id) as fresh:
        assert consume_telegram_owner_nonce(data, nonce, coords, lease=fresh) is False
        assert consume_telegram_owner_nonce(data, "e" * 64, coords, lease=fresh) is True
    files = sorted(data.glob("boca_telegram_owner_nonce_v2_*.json"))
    assert len(files) == 2
    assert all(f.stat().st_mode & 0o777 == 0o600 for f in files)
    assert all(nonce not in f.read_text() for f in files)


@pytest.mark.parametrize(
    "case",
    ["symlink", "hardlink", "bad_mode", "bad_digest", "bad_header", "bad_stage_id", "future"],
)
def test_untrusted_stage_is_rejected_read_only_before_any_nonce(
    lease_volume: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    _, data = lease_volume
    _, _, _, _, coords, _ = _setup(data, monkeypatch)
    stage = data / "boca_telegram_pairing_stage_v2.json"
    if case == "symlink":
        stage.rename(data / "untouched")
        stage.symlink_to("untouched")
    elif case == "hardlink":
        os.link(stage, data / "alias")
    elif case == "bad_mode":
        stage.chmod(0o644)
    else:
        doc = json.loads(stage.read_text())
        if case == "bad_digest":
            doc["envelope_sha256"] = "f" * 64
        elif case == "bad_header":
            doc["recipient_fingerprint"] = "f" * 64
        elif case == "bad_stage_id":
            doc["stage_id"] = "not-a-nonce"
        else:
            doc["staged_at"] = NOW + 1000
        stage.write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")))
    with cleanup.protected_boca_job_lease(coords.attempt_id) as lease:
        with pytest.raises(SameLeasePairingError):
            read_encrypted_telegram_stage(data, coordinates=coords, lease=lease, trusted_now=NOW)
    assert list(data.glob("boca_telegram_owner_nonce_v2_*.json")) == []


def test_stage_replacement_during_authoritative_recheck_aborts_before_provider(
    lease_volume: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, data = lease_volume
    private, recipient, _, code, coords, grant = _setup(data, monkeypatch)
    calls: list[str] = []
    api = _FakeBotApi(code)

    def observer(phase, value):
        calls.append(phase)
        if phase == "BEFORE_API":
            stage = data / "boca_telegram_pairing_stage_v2.json"
            stage.rename(data / "quarantined")
            stage.write_bytes((data / "quarantined").read_bytes())
            stage.chmod(0o600)
        return _host(phase, value)

    with cleanup.protected_boca_job_lease(coords.attempt_id) as lease:
        with pytest.raises((SameLeasePairingError, cutover.TelegramCutoverError)):
            execute_staged_pairing_under_lease(
                stage_directory=data,
                custody_directory=tmp_path / "telegram",
                coordinates=coords,
                owner_receipt=grant,
                owner_receipt_key=KEY,
                recipient=recipient,
                private_key=private,
                lease=lease,
                trusted_clock=lambda: NOW,
                inspect_host=observer,
                api_fetch=lambda token, method, chat: api(token, method, chat),
            )
    assert calls == ["BEFORE_API"]


@pytest.mark.parametrize("case", ["symlink_directory", "world_writable_directory", "forged_lease"])
def test_untrusted_volume_or_forged_lease_cannot_consume_nonce(
    lease_volume: tuple[Path, Path], case: str, tmp_path: Path
) -> None:
    _, data = lease_volume
    coords = cutover.CutoverCoordinates(
        "41937000001",
        SOURCE,
        "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64,
        "b" * 64,
        "c" * 64,
        "d" * 64,
        "e" * 64,
    )
    directory = data
    if case == "symlink_directory":
        directory = tmp_path / "linked-data"
        directory.symlink_to(data, target_is_directory=True)
    elif case == "world_writable_directory":
        data.chmod(0o777)
    with cleanup.protected_boca_job_lease(coords.attempt_id) as lease:
        if case == "forged_lease":
            with (tmp_path / "not-the-canonical-lease").open("wb+") as other:
                fake = cleanup.BocaJobLease(coords.attempt_id, other.fileno(), os.getpid(), True)
                with pytest.raises(SameLeasePairingError):
                    consume_telegram_owner_nonce(data, "f" * 64, coords, lease=fake)
        else:
            with pytest.raises(SameLeasePairingError):
                consume_telegram_owner_nonce(directory, "f" * 64, coords, lease=lease)
    assert not list(data.glob("boca_telegram_owner_nonce_v2_*.json"))


def test_inode_survives_failed_fsync_and_blocks_replay(
    lease_volume: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, data = lease_volume
    coords = cutover.CutoverCoordinates(
        "41937000001",
        SOURCE,
        "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64,
        "b" * 64,
        "c" * 64,
        "d" * 64,
        "e" * 64,
    )
    from boca_socios import telegram_same_lease_stage as target

    original = target.os.fsync

    def fail_once(fd: int) -> None:
        monkeypatch.setattr(target.os, "fsync", original)
        raise OSError("synthetic interrupted fsync")

    with cleanup.protected_boca_job_lease(coords.attempt_id) as lease:
        monkeypatch.setattr(target.os, "fsync", fail_once)
        with pytest.raises(SameLeasePairingError, match="nonce_uncertain"):
            consume_telegram_owner_nonce(data, "f" * 64, coords, lease=lease)
        assert consume_telegram_owner_nonce(data, "f" * 64, coords, lease=lease) is False
    marker_files = list(data.glob("boca_telegram_owner_nonce_v2_*.json"))
    assert len(marker_files) == 1
    assert marker_files[0].stat().st_mode & 0o777 == 0o600


def test_delayed_protected_activation_respects_pre_receipt_start_message(
    lease_volume: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Chrome stages first, then /start arrives, then Actions signs a new lease."""
    _, data = lease_volume
    private, recipient, v2, code, coords, _ = _setup(data, monkeypatch)
    # The receipt may only be issued after the protected job obtains its own
    # lease. Its HMAC now binds the earlier server-authored staging timestamp.
    delayed = issuer.issue_owner_pairing_receipt(
        coords, v2, KEY, NOW - 30, discovery_not_before=NOT_BEFORE
    )
    chat_at = NOW - 120
    assert NOT_BEFORE < chat_at < delayed.issued_at < NOW
    api = _FakeBotApi(code, matching=[_message(code, date=chat_at)])
    fake_commit = PairingCustodyReceipt(SOURCE, recipient.fingerprint, 123456)
    monkeypatch.setattr(cutover, "install_v2_plan", lambda *_a, **_k: fake_commit)
    monkeypatch.setattr(cutover, "verify_v2_custody", lambda *_a, **_k: fake_commit)

    with cleanup.protected_boca_job_lease(coords.attempt_id) as lease:
        result = execute_staged_pairing_under_lease(
            stage_directory=data,
            custody_directory=tmp_path / "telegram",
            coordinates=coords,
            owner_receipt=delayed,
            owner_receipt_key=KEY,
            recipient=recipient,
            private_key=private,
            lease=lease,
            trusted_clock=lambda: NOW,
            inspect_host=_host,
            api_fetch=api,
        )
    assert result.state == "CUSTODY_COMMITTED_NO_SEND"
    assert result.sender_state == "OFF"
    assert result.human_notification_receipt == "UNVERIFIED"
    assert [method for method, _ in api.calls] == [
        "getMe",
        "getWebhookInfo",
        "getUpdates",
        "getChat",
    ]


@pytest.mark.parametrize("case", ["unsigned", "changed_time", "future_time", "stale"])
def test_staged_discovery_window_must_be_signed_exact_and_fresh(
    lease_volume: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case: str,
) -> None:
    _, data = lease_volume
    private, recipient, v2, _, coords, _ = _setup(data, monkeypatch)
    if case == "future_time":
        with pytest.raises(issuer.PairingIssuerError):
            issuer.issue_owner_pairing_receipt(coords, v2, KEY, NOW - 30, discovery_not_before=NOW)
        return
    if case == "stale":
        with pytest.raises(issuer.PairingIssuerError):
            issuer.issue_owner_pairing_receipt(
                coords, v2, KEY, NOT_BEFORE + 3601, discovery_not_before=NOT_BEFORE
            )
        return
    grant = issuer.issue_owner_pairing_receipt(
        coords, v2, KEY, NOW - 30, discovery_not_before=NOT_BEFORE
    )
    if case == "unsigned":
        grant = issuer.issue_owner_pairing_receipt(coords, v2, KEY, NOW - 30)
    elif case == "changed_time":
        grant = replace(grant, discovery_not_before=NOT_BEFORE + 1)
    provider_calls: list[str] = []

    def unexpected_provider(_token: str, method: str, _chat: int | None) -> bytes:
        provider_calls.append(method)
        return b"{}"

    with cleanup.protected_boca_job_lease(coords.attempt_id) as lease:
        with pytest.raises(SameLeasePairingError, match="owner_stage_binding"):
            execute_staged_pairing_under_lease(
                stage_directory=data,
                custody_directory=tmp_path / "telegram",
                coordinates=coords,
                owner_receipt=grant,
                owner_receipt_key=KEY,
                recipient=recipient,
                private_key=private,
                lease=lease,
                trusted_clock=lambda: NOW,
                inspect_host=_host,
                api_fetch=unexpected_provider,
            )
    assert not provider_calls
    assert not list(data.glob("boca_telegram_owner_nonce_v2_*.json"))
