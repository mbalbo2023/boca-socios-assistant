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


def _migration_transaction(monkeypatch, *, failure="", uncertain=False):
    events = []
    context = SimpleNamespace(
        installation=SimpleNamespace(pair=SimpleNamespace(sender_running=False)),
        healthy=lambda: events.append("HEALTHY"),
        stop=lambda: events.append("STOP"),
        stopped=lambda: events.append("STOPPED"),
        check_binding=lambda: events.append("BINDING"),
    )

    def restore():
        events.append("RESTORE")
        if failure == "restore":
            raise ValueError("restore")

    context.restore = restore

    def resolve(*args, **kwargs):
        assert kwargs["expected_source_sha"] == SOURCE
        assert kwargs["workflow_sha"] == "b" * 40
        return context

    class Storage:
        migration_helper_retired = True

        def __init__(self, ctx):
            assert ctx is context

        def call(self, operation, request):
            assert request == {}
            events.append(operation)
            if operation == "migrate-schema":
                self.migration_helper_retired = not uncertain
                if failure == "helper" or uncertain:
                    raise ValueError("migration failed")
                return {"schema": 7}
            assert operation == "verify-schema"
            if "RESTORE" not in events:
                return {"prerequisite": "SCHEMA_0007_REQUIRED"}
            if failure == "postverify":
                raise ValueError("postverify")
            return {"schema": 7}

    monkeypatch.setattr(backend, "resolve_installed_context", resolve)
    monkeypatch.setattr(backend, "InstalledMaintenance", Storage)
    return context, events


@pytest.mark.parametrize(
    "failure,uncertain",
    [("", False), ("helper", False), ("helper", True), ("restore", False), ("postverify", False)],
)
def test_installed_migration_backend_fences_and_final_readonly_probe(
    monkeypatch, failure, uncertain
):
    _, events = _migration_transaction(monkeypatch, failure=failure, uncertain=uncertain)
    kwargs = dict(lease=object(), expected_source_sha=SOURCE, workflow_sha="b" * 40)
    if failure:
        with pytest.raises(backend.TelegramBackendError) as caught:
            backend.migrate_installed_telegram("111", **kwargs)
        receipt = caught.value.receipt
        assert receipt.state == ("CLEANUP_INDETERMINATE" if uncertain else "FAILED_STATE_PRESERVED")
    else:
        receipt = backend.migrate_installed_telegram("111", **kwargs)
        assert receipt.state == "SCHEMA_READY"
        assert events[-2:] == ["HEALTHY", "verify-schema"]
    assert ("RESTORE" in events) is not uncertain
    assert receipt.restoration == (
        "INDETERMINATE" if uncertain or failure == "restore" else "CONTROLLER_HEALTHY_ENGINE_OFF"
    )
    assert receipt.sender_state == "OFF"
    assert events.count("verify-schema") == (
        2 if not uncertain and failure not in {"helper", "restore"} else 1
    )
    assert not any(
        item in events for item in ("publish-status", "owner-identity", "recipient", "PROVISION")
    )


def test_migration_receipt_requires_schema_ready_restored_sender_off():
    import json

    raw = backend.TelegramBackendReceipt(
        "migrate", "111", SOURCE, "SCHEMA_READY", "CONTROLLER_HEALTHY_ENGINE_OFF"
    ).redacted_json()
    kwargs = dict(attempt_id="111", expected_source_sha=SOURCE, operation="migrate")
    assert backend.verify_backend_receipt(raw, **kwargs) == raw
    for key, value in (
        ("state", "PREPARED"),
        ("restoration", "INDETERMINATE"),
        ("sender_state", "VERIFIED"),
        ("human_receipt", "RECEIVED"),
    ):
        changed = json.loads(raw)
        changed[key] = value
        with pytest.raises(ValueError):
            backend.verify_backend_receipt(bootstrap._canonical(changed), **kwargs)


@pytest.mark.parametrize("failure", ["", "missing", "invalid", "health"])
def test_schema_observation_reads_real_storage_without_preparing_or_stopping(
    tmp_path, monkeypatch, failure
):
    import sqlite3

    ctx, events, api, data, custody, _, _ = _transaction(tmp_path, monkeypatch)
    database = data / "boca.sqlite3"
    if failure in {"missing", "invalid"}:
        with sqlite3.connect(database) as connection:
            if failure == "missing":
                connection.execute("DELETE FROM schema_migrations WHERE version=7")
                connection.execute("DROP TABLE telegram_delivery_attempts")
            else:
                connection.execute(
                    "UPDATE schema_migrations SET checksum='invalid' WHERE version=7"
                )
    before = database.read_bytes(), database.stat().st_ino
    custody_before = {item.name: item.read_bytes() for item in custody.iterdir()}
    cleaned = []
    local = backend.InstalledMaintenance

    def cleanup_noop(self):
        assert self._created_network is None
        current = list(events)
        InstalledMaintenance.cleanup_failed_provision(self)
        assert events == current
        cleaned.append(True)

    def forbidden_docker(*args):
        pytest.fail("schema observation must not provision or remove networks")

    def healthy():
        events.append("HEALTHY")
        if failure == "health":
            raise ValueError("synthetic health changed")

    monkeypatch.setattr(local, "cleanup_failed_provision", cleanup_noop)
    monkeypatch.setattr(cleanup, "_docker", forbidden_docker)
    monkeypatch.setattr(ctx, "healthy", healthy)
    with cleanup.protected_boca_job_lease(ctx.attempt_id) as lease:
        kwargs = dict(lease=lease, reader=None, expected_source_sha=SOURCE, workflow_sha="b" * 40)
        if failure:
            with pytest.raises(backend.TelegramBackendError) as caught:
                backend._execute("observe", ctx.attempt_id, **kwargs)
            receipt = caught.value.receipt
        else:
            receipt = backend._execute("observe", ctx.attempt_id, **kwargs)
    assert receipt.state == (
        "SCHEMA_READY"
        if not failure
        else "SCHEMA_0007_REQUIRED"
        if failure == "missing"
        else "FAILED_STATE_PRESERVED"
    )
    assert (receipt.restoration, receipt.sender_state, receipt.human_receipt) == (
        "NOT_NEEDED",
        "OFF",
        "UNVERIFIED",
    )
    assert events == (
        ["verify-schema", "HEALTHY"] if failure in {"", "health"} else ["verify-schema"]
    )
    assert cleaned == ([True] if failure else [])
    assert (database.read_bytes(), database.stat().st_ino) == before
    assert {item.name: item.read_bytes() for item in custody.iterdir()} == custody_before
    assert api.calls == []


@pytest.mark.parametrize(
    "state,restoration,sender,strict,with_failure",
    [
        ("SCHEMA_READY", "NOT_NEEDED", "OFF", True, True),
        ("SCHEMA_0007_REQUIRED", "NOT_NEEDED", "OFF", False, True),
        ("FAILED_STATE_PRESERVED", "NOT_NEEDED", "OFF", False, True),
        ("FAILED_STATE_PRESERVED", "INDETERMINATE", "UNVERIFIED", False, True),
        ("PREFLIGHT_FAILED", "NOT_NEEDED", "UNVERIFIED", False, True),
        ("SCHEMA_READY", "CONTROLLER_HEALTHY_ENGINE_OFF", "OFF", False, False),
        ("SCHEMA_READY", "INDETERMINATE", "OFF", False, False),
        ("SCHEMA_READY", "NOT_NEEDED", "VERIFIED", False, False),
        ("SCHEMA_0007_REQUIRED", "CONTROLLER_HEALTHY_ENGINE_OFF", "OFF", False, False),
        ("SCHEMA_0007_REQUIRED", "INDETERMINATE", "OFF", False, False),
        ("SCHEMA_0007_REQUIRED", "NOT_NEEDED", "VERIFIED", False, False),
        ("FAILED_STATE_PRESERVED", "CONTROLLER_HEALTHY_ENGINE_OFF", "OFF", False, False),
        ("FAILED_STATE_PRESERVED", "INDETERMINATE", "VERIFIED", False, False),
        ("PREPARED", "NOT_NEEDED", "OFF", False, False),
        ("READY", "NOT_NEEDED", "VERIFIED", False, False),
    ],
)
def test_schema_observation_receipt_cannot_claim_restore_or_sender(
    state, restoration, sender, strict, with_failure
):
    raw = backend.TelegramBackendReceipt(
        "observe", "111", SOURCE, state, restoration, sender
    ).redacted_json()
    assert len(raw) < 1024
    for allow_failure, allowed in ((False, strict), (True, with_failure)):
        kwargs = dict(
            attempt_id="111",
            expected_source_sha=SOURCE,
            operation="observe",
            allow_failure=allow_failure,
        )
        if allowed:
            assert backend.verify_backend_receipt(raw, **kwargs) == raw
        else:
            with pytest.raises(ValueError, match="telegram_backend_receipt_unverified"):
                backend.verify_backend_receipt(raw, **kwargs)


@pytest.mark.parametrize("operation,state", [("migrate", "SCHEMA_READY"), ("prepare", "PREPARED")])
def test_schema_observation_does_not_relax_other_success_restoration(operation, state):
    raw = backend.TelegramBackendReceipt(
        operation, "111", SOURCE, state, "NOT_NEEDED"
    ).redacted_json()
    with pytest.raises(ValueError, match="telegram_backend_receipt_unverified"):
        backend.verify_backend_receipt(
            raw,
            attempt_id="111",
            expected_source_sha=SOURCE,
            operation=operation,
            allow_failure=True,
        )


def _r303_controller_stop_boundary(monkeypatch, *, acknowledgement="portable"):
    import subprocess

    from boca_socios.host_telegram_installed_context import TelegramContextError

    cid = "c" * 64
    events, commands = [], []
    context = SimpleNamespace(
        installation=SimpleNamespace(controller_id=cid, pair=SimpleNamespace(sender_running=False)),
        healthy=lambda: events.append("HEALTHY"),
        stopped=lambda: events.append("STOPPED"),
        restore=lambda: events.append("RESTORE"),
    )
    context.stop = InstalledTelegramContext.stop.__get__(context)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    for name in (
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
        "DOCKER_TLS",
        "DOCKER_CONFIG",
    ):
        monkeypatch.delenv(name, raising=False)

    def run(argv, **kwargs):
        assert argv[:3] == ["/usr/bin/docker", "--host", cleanup.DOCKER_SOCKET]
        command = argv[3:]
        commands.append(command)
        assert command[0] == "stop" and command[-2:] == ["10", cid]
        assert kwargs["timeout"] == 45 and kwargs["text"] is True
        assert kwargs["env"]["DOCKER_HOST"] == cleanup.DOCKER_SOCKET
        events.append("DOCKER_STOP")
        outputs = {
            "portable": ("warning: deprecated --time\n" if "--time" in command else "")
            + cid
            + "\n",
            "warning": "warning even with portable flag\n" + cid + "\n",
            "empty": "",
            "foreign": "f" * 64 + "\n",
            "multiline": cid + "\n" + cid + "\n",
            "exit": cid + "\n",
        }
        return subprocess.CompletedProcess(
            argv, 1 if acknowledgement == "exit" else 0, outputs[acknowledgement], ""
        )

    class Storage:
        migration_helper_retired = True

        def __init__(self, checked):
            assert checked is context

        def call(self, operation, payload):
            assert payload == {}
            events.append(operation)
            if operation == "migrate-schema":
                return {"schema": 7}
            assert operation == "verify-schema"
            return (
                {"schema": 7} if "RESTORE" in events else {"prerequisite": "SCHEMA_0007_REQUIRED"}
            )

    monkeypatch.setattr(cleanup.subprocess, "run", run)
    monkeypatch.setattr(backend, "resolve_installed_context", lambda *args, **kwargs: context)
    monkeypatch.setattr(backend, "InstalledMaintenance", Storage)
    try:
        receipt = backend.migrate_installed_telegram(
            "111", lease=object(), expected_source_sha=SOURCE, workflow_sha="b" * 40
        )
        error = None
    except backend.TelegramBackendError as failure:
        receipt, error = failure.receipt, failure
    assert events.count("DOCKER_STOP") == events.count("RESTORE") == 1
    assert len(commands) == 1
    assert receipt.restoration == "CONTROLLER_HEALTHY_ENGINE_OFF"
    assert receipt.sender_state == "OFF" and receipt.human_receipt == "UNVERIFIED"
    if error is not None:
        assert receipt.state == "FAILED_STATE_PRESERVED"
        assert "migrate-schema" not in events
        assert isinstance(error.primary_error, (TelegramContextError, cleanup.CleanupError))
        assert error.cleanup_error is None
    return receipt, events, commands


def test_r303_portable_stop_reaches_migration_after_exact_docker_ack(monkeypatch):
    receipt, events, commands = _r303_controller_stop_boundary(monkeypatch)
    assert receipt.state == "SCHEMA_READY", (receipt, events)
    assert events.count("migrate-schema") == 1
    assert events.index("DOCKER_STOP") < events.index("migrate-schema") < events.index("RESTORE")
    assert commands == [["stop", "-t", "10", "c" * 64]]


@pytest.mark.parametrize("acknowledgement", ["warning", "empty", "foreign", "multiline", "exit"])
def test_r303_portable_controller_stop_preserves_strict_ack_rejection(monkeypatch, acknowledgement):
    receipt, events, _ = _r303_controller_stop_boundary(
        monkeypatch, acknowledgement=acknowledgement
    )
    assert receipt.state == "FAILED_STATE_PRESERVED"
    assert "migrate-schema" not in events
