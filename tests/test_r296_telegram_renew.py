"""Explicit renewal preserves old ciphertext and durable replay markers offline."""

import json

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_telegram_backend as backend
from boca_socios.panel.telegram_pairing_staging import STAGING_FILENAME
from test_r296_telegram_backend import _transaction
from test_telegram_pairing_resolver import NOW, SOURCE, _message


def _kwargs(ctx, lease):
    return dict(lease=lease, expected_source_sha=SOURCE, workflow_sha=SOURCE)


def _prepare(ctx, lease):
    backend.prepare_installed_telegram(ctx.attempt_id, **_kwargs(ctx, lease))


def test_consumed_failed_stage_archived_then_new_owner_stage_allowed(tmp_path, monkeypatch):
    ctx, events, api, data, custody, recipient, stage = _transaction(tmp_path, monkeypatch)
    with cleanup.protected_boca_job_lease(ctx.attempt_id) as lease:
        _prepare(ctx, lease)
        stage()
        raw = (data / STAGING_FILENAME).read_bytes()
        api.matching = [_message(api.code, date=NOW - 1)]
        with pytest.raises(backend.TelegramBackendError):
            backend.activate_installed_telegram(ctx.attempt_id, **_kwargs(ctx, lease))
        markers = {p.name: p.read_bytes() for p in data.glob("boca_telegram_owner_nonce_v2_*")}
        assert len(markers) == 1
        receipt = backend.renew_installed_telegram_stage(ctx.attempt_id, **_kwargs(ctx, lease))
        assert receipt.state == "STAGE_ARCHIVED" and receipt.sender_state == "OFF"
        assert backend.verify_backend_receipt(
            receipt.redacted_json(),
            attempt_id=ctx.attempt_id,
            expected_source_sha=SOURCE,
            operation="renew",
        )
        history = list(data.glob("boca_telegram_stage_history_v2_*"))
        assert len(history) == 1 and (history[0] / STAGING_FILENAME).read_bytes() == raw
        assert not (data / STAGING_FILENAME).exists()
        assert {
            p.name: p.read_bytes() for p in data.glob("boca_telegram_owner_nonce_v2_*")
        } == markers
        assert len(api.calls) == 3 and "RESTORE" in events[-2:]
        with pytest.raises(backend.TelegramBackendError):
            backend.renew_installed_telegram_stage(ctx.attempt_id, **_kwargs(ctx, lease))
        from dataclasses import asdict

        from boca_socios import telegram_bootstrap as bootstrap
        from test_telegram_pairing_ui import _run

        fresh = _run("#recipient=" + bootstrap._b64(bootstrap._canonical(asdict(recipient))))
        fresh_code = fresh["command"].removeprefix("/start ")
        assert fresh_code != api.code
        stage(bootstrap._unb64(fresh["output"], maximum=4096))
        assert (data / STAGING_FILENAME).read_bytes() != raw
        api.matching = [_message(fresh_code, date=NOW + 15)]
        assert (
            backend.activate_installed_telegram(ctx.attempt_id, **_kwargs(ctx, lease)).state
            == "READY"
        )
        assert len(api.calls) == 7  # Only the explicit NEW-stage activation performs new GETs.
        assert (history[0] / STAGING_FILENAME).read_bytes() == raw


@pytest.mark.parametrize(
    "case", ["unexpired", "expired", "future", "partial", "collision", "bound"]
)
def test_renew_admission_and_preservation(tmp_path, monkeypatch, case):
    ctx, events, api, data, custody, recipient, stage = _transaction(tmp_path, monkeypatch)
    with cleanup.protected_boca_job_lease(ctx.attempt_id) as lease:
        _prepare(ctx, lease)
        stage()
        raw = (data / STAGING_FILENAME).read_bytes()
        doc = json.loads(raw)
        if case in {"expired", "partial", "collision", "bound"}:
            monkeypatch.setattr(backend.time, "time", lambda: NOW + 3601)
        if case == "future":
            monkeypatch.setattr(backend.time, "time", lambda: NOW - 1)
        if case == "partial":
            (custody / "telegram_pairing_pending_v2").write_bytes(b"partial")
        if case == "collision":
            (data / ("boca_telegram_stage_history_v2_" + doc["stage_id"])).mkdir(mode=0o700)
        if case == "bound":
            for index in range(8):
                (data / ("boca_telegram_stage_history_v2_" + f"{index:064x}")).mkdir(mode=0o700)
        if case in {"unexpired", "expired"}:
            receipt = backend.renew_installed_telegram_stage(ctx.attempt_id, **_kwargs(ctx, lease))
            assert receipt.state == "STAGE_ARCHIVED"
            assert not (data / STAGING_FILENAME).exists()
        else:
            with pytest.raises(backend.TelegramBackendError):
                backend.renew_installed_telegram_stage(ctx.attempt_id, **_kwargs(ctx, lease))
            assert (data / STAGING_FILENAME).read_bytes() == raw
        assert not api.calls and "RESTORE" in events[-2:]


@pytest.mark.parametrize("damage", ["partial", "wrong_source", "wrong_owner", "symlink"])
def test_renew_never_discards_unverified_nonce_marker(tmp_path, monkeypatch, damage):
    ctx, events, api, data, custody, recipient, stage = _transaction(tmp_path, monkeypatch)
    with cleanup.protected_boca_job_lease(ctx.attempt_id) as lease:
        _prepare(ctx, lease)
        stage()
        api.matching = [_message(api.code, date=NOW - 1)]
        with pytest.raises(backend.TelegramBackendError):
            backend.activate_installed_telegram(ctx.attempt_id, **_kwargs(ctx, lease))
        marker = next(data.glob("boca_telegram_owner_nonce_v2_*"))
        if damage == "partial":
            marker.write_bytes(b"{")
        elif damage == "symlink":
            original = marker.read_bytes()
            marker.unlink()
            other = data / "unrelated"
            other.write_bytes(original)
            marker.symlink_to(other)
        else:
            value = json.loads(marker.read_bytes())
            value["target_sha" if damage == "wrong_source" else "owner_digest"] = "b" * (
                40 if damage == "wrong_source" else 64
            )
            from boca_socios import telegram_bootstrap as bootstrap

            marker.write_bytes(bootstrap._canonical(value))
        before = marker.read_bytes()
        with pytest.raises(backend.TelegramBackendError):
            backend.renew_installed_telegram_stage(ctx.attempt_id, **_kwargs(ctx, lease))
        assert (data / STAGING_FILENAME).exists() and marker.read_bytes() == before
        assert not list(data.glob("boca_telegram_stage_history_v2_*"))
        assert len(api.calls) == 3 and "RESTORE" in events[-2:]


@pytest.mark.parametrize("failure", ["rename", "after_rename_sync"])
def test_archive_interruption_preserves_evidence_and_does_not_retry(tmp_path, monkeypatch, failure):
    import os

    from boca_socios import telegram_same_lease_stage as storage

    ctx, events, api, data, custody, recipient, stage = _transaction(tmp_path, monkeypatch)
    with cleanup.protected_boca_job_lease(ctx.attempt_id) as lease:
        _prepare(ctx, lease)
        stage()
        raw = (data / STAGING_FILENAME).read_bytes()
        rename, sync = os.rename, os.fsync
        renamed = False

        def rename_once(*args, **kwargs):
            nonlocal renamed
            if failure == "rename":
                raise OSError("synthetic interruption")
            rename(*args, **kwargs)
            renamed = True

        def fsync(fd):
            if renamed:
                raise OSError("synthetic fsync interruption")
            sync(fd)

        monkeypatch.setattr(storage.os, "rename", rename_once)
        monkeypatch.setattr(storage.os, "fsync", fsync)
        with pytest.raises(backend.TelegramBackendError):
            backend.renew_installed_telegram_stage(ctx.attempt_id, **_kwargs(ctx, lease))
        archive = next(data.glob("boca_telegram_stage_history_v2_*"))
        preserved = archive / STAGING_FILENAME if renamed else data / STAGING_FILENAME
        assert preserved.read_bytes() == raw
        with pytest.raises(backend.TelegramBackendError):
            backend.renew_installed_telegram_stage(ctx.attempt_id, **_kwargs(ctx, lease))
        assert preserved.read_bytes() == raw and not api.calls
