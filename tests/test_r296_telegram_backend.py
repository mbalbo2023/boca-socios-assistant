"""Complete offline transaction; real crypto/files/nonce, fake Docker/provider only."""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_telegram_backend as backend
from boca_socios import host_telegram_protected_custody_caller as caller
from boca_socios import telegram_bootstrap as bootstrap
from boca_socios import telegram_maintenance as maintenance
from boca_socios.host_telegram_active_helper_topology import TelegramActiveHelperTopologyWitness
from boca_socios.host_telegram_egress_helper import TelegramHelperPhaseProof
from boca_socios.host_telegram_installed_context import InstalledTelegramContext
from boca_socios.host_telegram_maintenance import InstalledMaintenance
from boca_socios.host_telegram_owner_stage import _OWNER_PERMISSIONS
from boca_socios.panel.passkey import PasskeyOwnerAuthentication
from boca_socios.panel.telegram_pairing_staging import (
    PairingStageRequest,
    stage_private_telegram_pairing,
)
from boca_socios.panel.telegram_recipient import read_prepared_recipient
from boca_socios.telegram_owner_webauthn import TelegramStageOwnerWitness, stage_owner_challenge
from boca_socios.telegram_pairing_install import verify_v2_custody
from test_host_telegram_postcutover import _fake, _pins
from test_telegram_one_shot import _database
from test_telegram_owner_webauthn import _signed
from test_telegram_pairing_resolver import NOW, SOURCE, _FakeBotApi, _message, _prepared


def _transaction(tmp_path, monkeypatch, *, fail=""):
    data, custody, owner, lock = [tmp_path / name for name in ("data", "custody", "owner", "lease")]
    for path in (data, custody, owner, lock):
        path.mkdir(mode=0o700)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(cleanup, "EXPECTED_GID", os.getegid())
    monkeypatch.setattr(cleanup, "LEASE_DIR", lock)
    monkeypatch.setattr(bootstrap, "_identity", lambda _uid: None)
    monkeypatch.setattr(bootstrap, "UID", os.geteuid())
    # UID in envelope is a protocol constant, while filesystem owner is local.
    monkeypatch.setattr(maintenance, "DATA", data)
    monkeypatch.setattr(maintenance, "CUSTODY", custody)
    monkeypatch.setattr(maintenance, "OWNER", owner)
    clock = {"now": NOW}
    monkeypatch.setattr(backend.time, "time", lambda: clock["now"])
    from boca_socios import telegram_storage_gate

    monkeypatch.setattr(
        telegram_storage_gate, "_identity", lambda path: (path.stat().st_dev, path.stat().st_ino)
    )
    _database(data / "boca.sqlite3")
    private, recipient, envelope, code = _prepared()
    (custody / bootstrap.PRIVATE_KEY).write_bytes(private)
    (custody / bootstrap.PRIVATE_KEY).chmod(0o400)
    key = ec.generate_private_key(ec.SECP256R1())
    credential = b"r296-synthetic-owner"
    public = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    (owner / "credential_id").write_bytes(credential)
    (owner / "public_key.der").write_bytes(public)
    pins = _pins()
    pair = SimpleNamespace(
        sender_running=False,
        sender_id="",
        sender_config_hash="",
        sender_attempt_id="",
        controller_config_hash=pins.controller_config_hash,
        worker_config_hash=pins.worker_config_hash,
    )
    installed = SimpleNamespace(
        source_sha=SOURCE,
        controller_id=pins.controller_id,
        controller_image=pins.controller_image,
        worker_id=pins.worker_id,
        worker_image=pins.worker_image,
        installation_run_id=pins.cutover_attempt,
        pair=pair,
        fingerprint=lambda: "f" * 64,
    )
    events = []
    reader = _fake(tmp_path)
    reader.fields[("container", pins.controller_id, "Config.Env")] = [
        "BOCA_PANEL_ORIGIN=http://localhost:8443",
        "BOCA_RUNTIME_MODE=simulation",
        "BOCA_ENGINE_MODE=off",
        "BOCA_TELEGRAM_PAIRING_STAGE_MODE=encrypted-only",
        "BOCA_PASSKEY_CREDENTIAL_ID_FILE=/run/owner/credential_id",
        "BOCA_PASSKEY_PUBLIC_KEY_DER_FILE=/run/owner/public_key.der",
        "BOCA_OWNER_SUBJECT=owner",
    ]

    class Context:
        bind = InstalledTelegramContext.bind
        installation = installed
        binding_digest = "b" * 64
        workflow_sha = SOURCE
        volumes = (("boca-socios_boca_telegram", str(custody)),)
        coordinates = None
        pins = None

        def check_binding(self):
            if fail == "binding":
                raise ValueError("binding drift")

        def healthy(self):
            self.check_binding()

        def stop(self):
            events.append("STOP")

        def stopped(self, **_kw):
            self.check_binding()

        def restore(self):
            events.append("RESTORE")
            if fail == "restore":
                raise ValueError("restore")

    context = Context()
    context.attempt_id = pins.attempt_id
    context.reader = reader

    def resolve(_attempt, **kwargs):
        assert kwargs["expected_source_sha"] == installed.source_sha
        context.lease = kwargs["lease"]
        return context

    monkeypatch.setattr(backend, "resolve_installed_context", resolve)

    class LocalMaintenance(InstalledMaintenance):
        def provision(self):
            events.append("PROVISION")

        def cleanup_failed_provision(self):
            events.append("PROVISION_CLEANUP")

        def call(self, operation, request):
            self.context.check_binding()
            events.append(operation)
            if operation == fail:
                raise PermissionError("synthetic mapped UID access denied")
            return maintenance.execute(operation, request)

    monkeypatch.setattr(backend, "InstalledMaintenance", LocalMaintenance)
    api = _FakeBotApi(code, matching=[_message(code, date=NOW + 5)])

    class Session:
        def __call__(self, *args):
            return api(*args)

        def attest_phase(self, phase):
            return TelegramHelperPhaseProof(context.attempt_id, SOURCE, phase)

        def attest_topology(self, phase):
            return TelegramActiveHelperTopologyWitness(context.attempt_id, SOURCE, phase)

    @contextmanager
    def helper(*args, **kwargs):
        events.append("HELPER_OPEN")
        try:
            yield Session()
        finally:
            events.append("HELPER_REMOVED")

    monkeypatch.setattr(caller, "protected_ephemeral_get_session", helper)
    import sys
    from types import ModuleType

    sender_module = ModuleType("boca_socios.host_telegram_sender")

    def sender(context, **kwargs):
        events.append("SENDER_VERIFIED")
        if fail == "sender":
            raise ValueError("lost sender acknowledgement")
        installed.pair.sender_id = "e" * 64
        installed.pair.sender_running = True
        return SimpleNamespace(state="VERIFIED", source_sha=SOURCE, sender_id="e" * 64)

    sender_module.activate_installed_sender = sender
    monkeypatch.setitem(sys.modules, sender_module.__name__, sender_module)

    # Protocol UID must remain10001; only file checks are adapted for tmp storage.
    original_directory, original_read, original_write = (
        bootstrap._directory,
        bootstrap._read,
        bootstrap._write_new,
    )
    monkeypatch.setattr(bootstrap, "UID", 10001)
    monkeypatch.setattr(
        bootstrap, "_directory", lambda path, uid: original_directory(path, os.geteuid())
    )
    monkeypatch.setattr(
        bootstrap, "_read", lambda fd, name, uid, **kw: original_read(fd, name, os.geteuid(), **kw)
    )
    monkeypatch.setattr(
        bootstrap,
        "_write_new",
        lambda fd, name, content, uid: original_write(fd, name, content, os.geteuid()),
    )

    def stage(new_envelope=None):
        staged_envelope = envelope if new_envelope is None else new_envelope
        staged_at = clock["now"]
        verifier = PasskeyOwnerAuthentication(
            credential_id=credential,
            public_key_der=public,
            rp_id="localhost",
            origin="http://localhost:8443",
            owner_subject="owner",
            permissions=_OWNER_PERMISSIONS,
        )
        op, nonce = str(uuid4()), "a" * 64
        challenge = stage_owner_challenge(
            envelope_sha256=hashlib.sha256(staged_envelope).hexdigest(),
            operation_id=op,
            request_nonce=nonce,
            challenged_at=staged_at,
            verifier_binding=verifier.authorization_binding.hex(),
        )
        witness = TelegramStageOwnerWitness(
            op,
            nonce,
            staged_at,
            verifier.authorization_binding.hex(),
            _signed(challenge, key, credential, origin="http://localhost:8443", rp_id="localhost"),
        )
        stage_private_telegram_pairing(
            data / "boca_telegram_pairing_stage_v2.json",
            PairingStageRequest(staged_envelope, witness),
        )
        clock["now"] = staged_at + 10

    return context, events, api, data, custody, recipient, stage


def test_prepare_stage_four_gets_commit_and_restore(tmp_path, monkeypatch):
    ctx, events, api, data, custody, recipient, stage = _transaction(tmp_path, monkeypatch)
    with cleanup.protected_boca_job_lease(ctx.attempt_id) as lease:
        kwargs = dict(lease=lease, expected_source_sha=SOURCE, workflow_sha=SOURCE)
        prepared = backend.prepare_installed_telegram(ctx.attempt_id, **kwargs)
        assert prepared.state == "PREPARED"
        assert read_prepared_recipient(data, expected_source_sha=SOURCE) == recipient
        stage()
        activated = backend.activate_installed_telegram(ctx.attempt_id, **kwargs)
        assert activated.state == "READY"
        assert activated.restoration == "CONTROLLER_HEALTHY_ENGINE_OFF"
        assert (
            verify_v2_custody(custody, expected_source_sha=SOURCE).recipient_fingerprint
            == recipient.fingerprint
        )
        assert [method for method, _ in api.calls] == [
            "getMe",
            "getWebhookInfo",
            "getUpdates",
            "getChat",
        ]
        assert events[-1] == "publish-status" and events[-2] == "RESTORE"
        import json

        from boca_socios.host_boca_installed_admin import _FILENAME

        observation = json.loads((data / _FILENAME).read_bytes())
        assert observation["sender"] == "RUNNING"
        assert observation["configured"] == observation["paired"] == "VERIFIED"
        assert observation["human_receipt"] == "UNVERIFIED"
        assert len(list(data.glob("boca_telegram_owner_nonce_v2_*"))) == 1
        with pytest.raises(backend.TelegramBackendError):
            backend.activate_installed_telegram(ctx.attempt_id, **kwargs)
        assert len(api.calls) == 4


@pytest.mark.parametrize(
    "failure",
    [
        "verify-schema",
        "binding",
        "prepare",
        "publish-recipient",
        "verify-owner",
        "unseal",
        "install-v2",
        "restore",
    ],
)
def test_failure_preserves_stage_and_restores_only_started_transaction(
    tmp_path, monkeypatch, failure
):
    ctx, events, api, data, custody, recipient, stage = _transaction(
        tmp_path, monkeypatch, fail=failure
    )
    stage()
    operation = (
        backend.prepare_installed_telegram
        if failure in {"verify-schema", "binding", "prepare", "publish-recipient"}
        else backend.activate_installed_telegram
    )
    with cleanup.protected_boca_job_lease(ctx.attempt_id) as lease:
        with pytest.raises(backend.TelegramBackendError) as caught:
            operation(ctx.attempt_id, lease=lease, expected_source_sha=SOURCE, workflow_sha=SOURCE)
    assert ("RESTORE" in events) == (failure not in {"verify-schema", "binding"})
    assert (data / "boca_telegram_pairing_stage_v2.json").exists()
    assert caught.value.receipt.restoration == (
        "INDETERMINATE"
        if failure == "restore"
        else "NOT_NEEDED"
        if failure in {"verify-schema", "binding"}
        else "CONTROLLER_HEALTHY_ENGINE_OFF"
    )
    assert "bot_token" not in caught.value.receipt.redacted_json().decode()


def test_strict_redacted_success_receipt_rejects_forged_go():
    import json

    receipt = backend.TelegramBackendReceipt(
        "activate", "111", SOURCE, "READY", "CONTROLLER_HEALTHY_ENGINE_OFF", "VERIFIED"
    )
    raw = receipt.redacted_json()
    assert (
        backend.verify_backend_receipt(
            raw, attempt_id="111", expected_source_sha=SOURCE, operation="activate"
        )
        == raw
    )
    for key, value in (
        ("source_sha", "b" * 40),
        ("state", "CUSTODY_COMMITTED_NO_SEND"),
        ("restoration", "INDETERMINATE"),
        ("sender_state", "OFF"),
        ("human_receipt", "RECEIVED"),
        ("extra", True),
    ):
        changed = json.loads(raw)
        changed[key] = value
        with pytest.raises(ValueError, match="telegram_backend_receipt_unverified"):
            backend.verify_backend_receipt(
                bootstrap._canonical(changed),
                attempt_id="111",
                expected_source_sha=SOURCE,
                operation="activate",
            )


def test_missing_schema_is_prerequisite_without_migration_or_stop(tmp_path, monkeypatch):
    import sqlite3

    ctx, events, api, data, custody, recipient, stage = _transaction(tmp_path, monkeypatch)
    with sqlite3.connect(data / "boca.sqlite3") as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version=7")
        connection.execute("DROP TABLE telegram_delivery_attempts")
    with cleanup.protected_boca_job_lease(ctx.attempt_id) as lease:
        with pytest.raises(backend.TelegramBackendError) as caught:
            backend.prepare_installed_telegram(
                ctx.attempt_id, lease=lease, expected_source_sha=SOURCE, workflow_sha=SOURCE
            )
    assert caught.value.receipt.state == "SCHEMA_0007_REQUIRED"
    assert "STOP" not in events and "prepare" not in events and not api.calls
    raw = caught.value.receipt.redacted_json()
    assert (
        backend.verify_backend_receipt(
            raw,
            attempt_id=ctx.attempt_id,
            expected_source_sha=SOURCE,
            operation="prepare",
            allow_failure=True,
        )
        == raw
    )
    with pytest.raises(ValueError):
        backend.verify_backend_receipt(
            raw, attempt_id=ctx.attempt_id, expected_source_sha=SOURCE, operation="prepare"
        )


def test_sender_failure_is_not_projected_off(tmp_path, monkeypatch):
    ctx, events, api, data, custody, recipient, stage = _transaction(
        tmp_path, monkeypatch, fail="sender"
    )
    stage()
    with cleanup.protected_boca_job_lease(ctx.attempt_id) as lease:
        with pytest.raises(backend.TelegramBackendError) as caught:
            backend.activate_installed_telegram(
                ctx.attempt_id, lease=lease, expected_source_sha=SOURCE, workflow_sha=SOURCE
            )
    assert caught.value.receipt.sender_state == "UNVERIFIED"
    assert events[-1] == "RESTORE"
    assert (
        verify_v2_custody(custody, expected_source_sha=SOURCE).state == "CUSTODY_COMMITTED_NO_SEND"
    )


@pytest.mark.parametrize("sender", ["OFF", "VERIFIED"])
def test_recovery_receipt_accepts_only_proven_sender_categories(sender):
    raw = backend.TelegramBackendReceipt(
        "recover", "111", SOURCE, "RECOVERED", "CONTROLLER_HEALTHY_ENGINE_OFF", sender
    ).redacted_json()
    assert (
        backend.verify_backend_receipt(
            raw, attempt_id="111", expected_source_sha=SOURCE, operation="recover"
        )
        == raw
    )


@pytest.mark.parametrize(
    "restoration,sender",
    [
        ("NOT_NEEDED", "OFF"),
        ("INDETERMINATE", "OFF"),
        ("NOT_NEEDED", "UNVERIFIED"),
    ],
)
def test_preflight_receipt_is_strictly_no_effect(restoration, sender):
    raw = backend.TelegramBackendReceipt(
        "prepare", "111", SOURCE, "PREFLIGHT_FAILED", restoration, sender
    ).redacted_json()
    kwargs = dict(attempt_id="111", expected_source_sha=SOURCE, operation="prepare")
    with pytest.raises(ValueError):
        backend.verify_backend_receipt(raw, **kwargs)
    if (restoration, sender) == ("NOT_NEEDED", "UNVERIFIED"):
        assert backend.verify_backend_receipt(raw, allow_failure=True, **kwargs) == raw
    else:
        with pytest.raises(ValueError):
            backend.verify_backend_receipt(raw, allow_failure=True, **kwargs)


def test_message_before_owner_stage_is_refused_and_nonce_not_replayed(tmp_path, monkeypatch):
    ctx, events, api, data, custody, recipient, stage = _transaction(tmp_path, monkeypatch)
    api.matching = [_message(api.code, date=NOW - 1)]
    stage()
    with cleanup.protected_boca_job_lease(ctx.attempt_id) as lease:
        kwargs = dict(lease=lease, expected_source_sha=SOURCE, workflow_sha=SOURCE)
        with pytest.raises(backend.TelegramBackendError) as caught:
            backend.activate_installed_telegram(ctx.attempt_id, **kwargs)
        assert caught.value.receipt.restoration == "CONTROLLER_HEALTHY_ENGINE_OFF"
        assert [call[0] for call in api.calls] == ["getMe", "getWebhookInfo", "getUpdates"]
        assert "install-v2" not in events and "SENDER_VERIFIED" not in events
        assert (data / "boca_telegram_pairing_stage_v2.json").exists()
        api.matching = [_message(api.code, date=NOW + 5)]
        with pytest.raises(backend.TelegramBackendError):
            backend.activate_installed_telegram(ctx.attempt_id, **kwargs)
        assert len(api.calls) == 3
