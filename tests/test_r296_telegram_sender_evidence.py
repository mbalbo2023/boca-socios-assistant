"""Image-only exact original acceptance evidence; synthetic delivery, no network."""

import asyncio
import json
import sqlite3
from dataclasses import asdict
from uuid import uuid4

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_telegram_backend as backend
from boca_socios import telegram_bootstrap as bootstrap
from boca_socios import telegram_maintenance as maintenance
from boca_socios import telegram_one_shot as shot
from boca_socios.notify.outbox import NoticeKind, NotificationRequest
from boca_socios.notify.sqlite_outbox import SqliteNotificationOutbox
from boca_socios.notify.telegram_transport import TelegramTransport
from boca_socios.telegram_pairing_install import MARKER, _marker_bytes
from test_r296_telegram_backend import _transaction
from test_telegram_one_shot import _Sender
from test_telegram_pairing_resolver import SOURCE


def _committed(tmp_path, monkeypatch):
    ctx, events, api, data, custody, recipient, stage = _transaction(tmp_path, monkeypatch)
    with cleanup.protected_boca_job_lease(ctx.attempt_id) as lease:
        kwargs = dict(lease=lease, expected_source_sha=SOURCE, workflow_sha=SOURCE)
        backend.prepare_installed_telegram(ctx.attempt_id, **kwargs)
        stage()
        backend.activate_installed_telegram(ctx.attempt_id, **kwargs)
    request = {
        "coordinates": asdict(ctx.coordinates),
        "owner_subject": "owner",
        "installation_fingerprint": ctx.installation.fingerprint(),
    }
    return ctx, api, data, custody, request


@pytest.mark.parametrize("state", ["NOT_ATTEMPTED", "API_ACCEPTED", "INDETERMINATE"])
def test_original_attempt_evidence_exact_outbox_and_no_provider(tmp_path, monkeypatch, state):
    ctx, api, data, custody, request = _committed(tmp_path, monkeypatch)
    database = data / "boca.sqlite3"
    # A later dispatch must retain the consumed original acceptance identity.
    request["coordinates"]["attempt_id"] = "999999"
    request["coordinates"]["lease_digest"] = "c" * 64
    bot, chat_hmac = shot.verified_v2_assertion(custody, expected_source_sha=SOURCE)
    transport = TelegramTransport(custody / bootstrap.TOKEN_FILE, custody / bootstrap.CHAT_FILE)
    notice = shot.acceptance_notice_id(transport, SOURCE, bot, chat_hmac, attempt_id=ctx.attempt_id)
    outbox = SqliteNotificationOutbox(database)
    unrelated = uuid4()
    outbox.enqueue(NotificationRequest(unrelated, NoticeKind.HEARTBEAT), now=1, ttl_seconds=1)
    if state == "API_ACCEPTED":
        assert (
            asyncio.run(shot.deliver_once(database, _Sender(), SOURCE, notice_id=notice))
            == "API_ACCEPTED"
        )
    elif state == "INDETERMINATE":
        outbox.enqueue(NotificationRequest(notice, NoticeKind.HEARTBEAT), now=1, ttl_seconds=1)
        with sqlite3.connect(database) as conn:
            conn.execute(
                "INSERT INTO telegram_delivery_attempts(idempotency_key,attempt_number,state,prepared_at) VALUES(?,1,'prepared',1)",
                (str(notice),),
            )
    before = database.read_bytes()
    monkeypatch.setattr(backend.time, "time", lambda: 4_000_000_000)
    assert maintenance.execute("sender-evidence", request) == {
        "source_sha": SOURCE,
        "original_attempt_id": ctx.attempt_id,
        "acceptance_state": state,
    }
    assert database.read_bytes() == before and len(api.calls) == 4


@pytest.mark.parametrize(
    "damage", ["missing_nonce", "partial_nonce", "different_commit", "owner", "installation"]
)
def test_evidence_refuses_unlinked_stage_or_custody(tmp_path, monkeypatch, damage):
    ctx, api, data, custody, request = _committed(tmp_path, monkeypatch)
    if damage == "missing_nonce":
        next(data.glob("boca_telegram_owner_nonce_v2_*")).unlink()
    elif damage == "partial_nonce":
        next(data.glob("boca_telegram_owner_nonce_v2_*")).write_bytes(b"{")
    elif damage == "different_commit":
        path = custody / MARKER
        fields = json.loads(path.read_bytes())
        fields.pop("commit_tag")
        fields["one_time_fence"] = "a" * 64
        path.chmod(0o600)
        path.write_bytes(_marker_bytes(fields, (custody / bootstrap.TOKEN_FILE).read_bytes()))
        path.chmod(0o400)
    elif damage == "owner":
        request["owner_subject"] = "other-owner"
    else:
        request["installation_fingerprint"] = "b" * 64
    with pytest.raises(ValueError):
        maintenance.execute("sender-evidence", request)
    assert len(api.calls) == 4


def test_prepare_refuses_lone_partial_commit_before_recipient_publication(tmp_path, monkeypatch):
    ctx, events, api, data, custody, recipient, stage = _transaction(tmp_path, monkeypatch)
    partial = custody / "telegram_pairing_pending_v2"
    partial.write_bytes(b"partial")
    with cleanup.protected_boca_job_lease(ctx.attempt_id) as lease:
        with pytest.raises(backend.TelegramBackendError):
            backend.prepare_installed_telegram(
                ctx.attempt_id, lease=lease, expected_source_sha=SOURCE, workflow_sha=SOURCE
            )
    assert "publish-recipient" not in events and "publish-status" not in events
    assert partial.read_bytes() == b"partial" and not api.calls


def test_publication_failure_preserves_healthy_restoration_and_refuses_success(
    tmp_path, monkeypatch
):
    ctx, events, api, data, custody, recipient, stage = _transaction(
        tmp_path, monkeypatch, fail="publish-status"
    )
    with cleanup.protected_boca_job_lease(ctx.attempt_id) as lease:
        with pytest.raises(backend.TelegramBackendError) as caught:
            backend.prepare_installed_telegram(
                ctx.attempt_id, lease=lease, expected_source_sha=SOURCE, workflow_sha=SOURCE
            )
    assert caught.value.receipt.state == "FAILED_STATE_PRESERVED"
    assert caught.value.receipt.restoration == "CONTROLLER_HEALTHY_ENGINE_OFF"
    assert events[-2:] == ["RESTORE", "publish-status"]


@pytest.mark.parametrize(
    "operation,present", [("publish-status", True), ("publish-status-absent", False)]
)
def test_status_operation_selects_only_its_fixed_custody_mount(monkeypatch, operation, present):
    from boca_socios import telegram_status_publication

    monkeypatch.setattr(bootstrap, "_identity", lambda uid: None)
    request = {"host_proof": "synthetic"}
    result = {
        "state": "STATUS_PUBLISHED",
        "sha256": "a" * 64,
        "configured": "ABSENT",
        "paired": "NOT_PAIRED",
    }

    def publish(data, custody, received):
        assert data == maintenance.DATA
        assert custody == (maintenance.CUSTODY if present else None)
        assert received is request
        return result

    monkeypatch.setattr(telegram_status_publication, "publish", publish)
    assert maintenance.execute(operation, request) == result


def test_complete_receipt_requires_verified_sender_and_healthy_restoration():
    receipt = backend.TelegramBackendReceipt(
        "complete", "111", SOURCE, "READY", "CONTROLLER_HEALTHY_ENGINE_OFF", "VERIFIED"
    )
    assert backend.verify_backend_receipt(
        receipt.redacted_json(), attempt_id="111", expected_source_sha=SOURCE, operation="complete"
    )
    from dataclasses import replace

    for invalid in (
        replace(receipt, sender_state="OFF"),
        replace(receipt, restoration="INDETERMINATE"),
    ):
        with pytest.raises(ValueError):
            backend.verify_backend_receipt(
                invalid.redacted_json(),
                attempt_id="111",
                expected_source_sha=SOURCE,
                operation="complete",
            )
