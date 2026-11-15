"""No Docker calls: prove exact maintenance profiles and selective provisioning."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_first_deploy as deploy
from boca_socios import host_telegram_maintenance as host
from boca_socios.telegram_maintenance_contract import MOUNTS

IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64
NAME = "boca-socios-telegram-maint-111-" + "b" * 16


def test_fixed_maintenance_profiles_never_log_private_pipe_and_only_new_volume_is_root():
    for operation, mounts in MOUNTS.items():
        argv = deploy._telegram_container(
            IMAGE, "telegram_maintenance", operation, writable=False, maintenance_name=NAME
        )
        assert argv[:3] == ("docker", "create", "--interactive")
        assert argv[argv.index("--log-driver") + 1] == "none"
        assert argv[argv.index("--network") + 1] == "none"
        assert argv[argv.index("--user") + 1] == (
            "0:0" if operation == "initialize-volume" else "10001:10001"
        )
        assert ("--cap-add" in argv) == (operation == "initialize-volume")
        assert argv.count("--mount") == len(mounts)
        assert argv[-5:] == (IMAGE, "python", "-m", "boca_socios.telegram_maintenance", operation)
    with pytest.raises(deploy.PreflightError):
        deploy._telegram_container(
            IMAGE, "telegram_maintenance", "arbitrary", writable=True, maintenance_name=NAME
        )


@pytest.mark.parametrize("existing", [False, True])
def test_provision_never_reinitializes_existing_volume_and_failure_keeps_persistent_data(
    monkeypatch, existing
):
    volume = "boca-socios_boca_telegram"
    network = "boca-socios_boca_telegram_egress"
    state = {"volumes": [SimpleNamespace(name=volume)] if existing else [], "networks": []}
    effects = []

    class Reader:
        def inventory(self):
            return SimpleNamespace(**state)

        def field(self, kind, name, field):
            assert kind == "volume" and name == volume
            return {
                "Name": volume,
                "Labels": {
                    "com.docker.compose.project": "boca-socios",
                    "com.docker.compose.volume": "boca_telegram",
                },
                "Mountpoint": "/home/boca-deploy/.local/share/docker/volumes/" + volume + "/_data",
            }[field]

    context = SimpleNamespace(
        reader=Reader(), volumes=(), stopped=lambda: None, check_binding=lambda: None
    )

    def docker(*args):
        effects.append(args)
        if args[:2] == ("volume", "create"):
            state["volumes"].append(SimpleNamespace(name=volume))
            return volume
        if args[:2] == ("network", "create"):
            state["networks"].append(SimpleNamespace(name=network, ident="c" * 64, attached_ids=()))
            return "c" * 64
        if args == ("network", "rm", "c" * 64):
            state["networks"].clear()
            return "c" * 64
        pytest.fail("unexpected effect")

    monkeypatch.setattr(cleanup, "_docker", docker)
    monkeypatch.setattr(deploy, "_telegram_egress", lambda **kwargs: None)
    monkeypatch.setattr(deploy, "_telegram_volume", lambda: None)
    adapter = host.InstalledMaintenance(context)
    monkeypatch.setattr(
        adapter,
        "call",
        lambda operation, request: effects.append((operation,)) or {"initialized": True},
    )
    adapter.provision()
    assert (
        ("initialize-volume",) in effects if not existing else ("initialize-volume",) not in effects
    )
    adapter.cleanup_failed_provision()
    assert state["networks"] == [] and len(state["volumes"]) == 1
    assert not any(effect[:2] == ("volume", "rm") for effect in effects)


def test_initialize_operation_cannot_be_invoked_for_existing_volume():
    adapter = host.InstalledMaintenance(SimpleNamespace())
    with pytest.raises(host.MaintenanceError, match="existing_volume_initialization_forbidden"):
        adapter.call("initialize-volume", {"new_empty_volume": "boca-socios_boca_telegram"})


@pytest.mark.parametrize(
    "tamper",
    ["none", "logging", "uid", "volume_source", "foreign_network", "extra_mount", "privileged"],
)
def test_exact_helper_attestation_rejects_privacy_or_mount_drift(monkeypatch, tamper):
    from copy import deepcopy

    cid = "d" * 64
    volume = "boca-socios_boca_telegram"
    path = "/home/boca-deploy/.local/share/docker/volumes/" + volume + "/_data"
    record = {
        "Id": cid,
        "Name": "/" + NAME,
        "Config": {
            "Image": IMAGE,
            "User": "10001:10001",
            "Cmd": ["python", "-m", "boca_socios.telegram_maintenance", "prepare"],
            "Labels": {"com.docker.compose.project": "boca-socios"},
        },
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "LogConfig": {"Type": "none"},
            "CapDrop": ["ALL"],
            "CapAdd": None,
            "PidsLimit": 16,
            "Memory": 67108864,
            "NanoCpus": 250000000,
            "PublishAllPorts": False,
            "PortBindings": {},
            "RestartPolicy": {"Name": "no"},
            "SecurityOpt": ["no-new-privileges"],
        },
        "Mounts": [
            {
                "Type": "volume",
                "Name": volume,
                "Source": path,
                "Destination": "/run/telegram",
                "RW": True,
                "Driver": "local",
            }
        ],
        "NetworkSettings": {"Networks": {"none": {}}},
        "State": {"Restarting": False},
    }
    if tamper == "logging":
        record["HostConfig"]["LogConfig"]["Type"] = "json-file"
    if tamper == "uid":
        record["Config"]["User"] = "0:0"
    if tamper == "volume_source":
        record["Mounts"][0]["Source"] = "/foreign/data"
    if tamper == "foreign_network":
        record["NetworkSettings"]["Networks"]["foreign"] = {}
    if tamper == "extra_mount":
        record["Mounts"].append(deepcopy(record["Mounts"][0]))
    if tamper == "privileged":
        record["HostConfig"]["Privileged"] = True
    monkeypatch.setattr(host, "_inspect", lambda _id: record)
    if tamper == "none":
        assert host._attest(cid, NAME, IMAGE, "prepare", {volume: path}) is record
    else:
        with pytest.raises(host.MaintenanceError):
            host._attest(cid, NAME, IMAGE, "prepare", {volume: path})


def test_existing_bind_option_volume_rejected_before_any_maintenance_effect(monkeypatch):
    import json

    volume = "boca-socios_boca_telegram"
    record = {
        "Name": volume,
        "Driver": "local",
        "Scope": "local",
        "Options": {"type": "none", "o": "bind", "device": "/foreign"},
        "Mountpoint": "/home/boca-deploy/.local/share/docker/volumes/" + volume + "/_data",
        "Labels": {
            "com.docker.compose.project": "boca-socios",
            "com.docker.compose.volume": "boca_telegram",
        },
    }
    monkeypatch.setattr(
        deploy,
        "_run",
        lambda *args: (
            json.dumps(record) if args[1] == "volume" else "/home/boca-deploy/.local/share/docker"
        ),
    )
    monkeypatch.setattr(cleanup, "_docker", lambda *args: pytest.fail("must fail before effects"))
    context = SimpleNamespace(check_binding=lambda: None)
    with pytest.raises(deploy.PreflightError, match="identity is unsafe"):
        host.InstalledMaintenance(context).call("recipient", {})


@pytest.mark.parametrize("running,restarting", [(True, False), (False, True)])
def test_healthy_preflight_refuses_worker_before_controller_stop(monkeypatch, running, restarting):
    from boca_socios.host_telegram_installed_context import (
        InstalledTelegramContext,
        TelegramContextError,
    )

    reader = SimpleNamespace(
        field=lambda _kind, _ident, field: {
            "State.Running": running,
            "State.Restarting": restarting,
        }[field]
    )
    context = SimpleNamespace(
        check_binding=lambda: None, reader=reader, installation=SimpleNamespace(worker_id="a" * 64)
    )
    monkeypatch.setattr(cleanup, "_docker", lambda *args: pytest.fail("controller must not stop"))
    with pytest.raises(TelegramContextError, match="worker_must_be_stopped"):
        InstalledTelegramContext.healthy(context)


def _migration_helper(monkeypatch, *, failure="", execute=None):
    import subprocess

    cid = "d" * 64
    volume = "boca-socios_boca_data"
    path = "/home/boca-deploy/.local/share/docker/volumes/" + volume + "/_data"
    effects = []
    state = {"exists": False, "running": False, "created": False}
    record = {
        "Id": cid,
        "Name": "",
        "Config": {
            "Image": IMAGE,
            "User": "10001:10001",
            "Cmd": ["python", "-m", "boca_socios.telegram_storage_gate", "migrate"],
            "Labels": {"com.docker.compose.project": "boca-socios"},
        },
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "LogConfig": {"Type": "none"},
            "CapDrop": ["ALL"],
            "CapAdd": None,
            "PidsLimit": 16,
            "Memory": 67108864,
            "NanoCpus": 250000000,
            "PublishAllPorts": False,
            "PortBindings": {},
            "RestartPolicy": {"Name": "no"},
            "SecurityOpt": ["no-new-privileges"],
        },
        "Mounts": [
            {
                "Type": "volume",
                "Name": volume,
                "Source": path,
                "Destination": "/data",
                "RW": True,
                "Driver": "local",
            }
        ],
        "NetworkSettings": {"Networks": {"none": {}}},
        "State": {"Restarting": False, "Running": False, "ExitCode": 0},
    }

    def docker(*args):
        effects.append(args)
        if args[0] == "create":
            state.update(exists=True, created=True)
            record["Name"] = "/" + args[args.index("--name") + 1]
            if failure == "create":
                raise RuntimeError("lost create acknowledgement")
            if failure == "cid":
                return "uncertain"
            return cid
        assert args[-1] == cid, "mutations must use exact CID"
        if args[0] == "stop":
            state["running"] = record["State"]["Running"] = False
            if failure == "stop":
                raise RuntimeError("lost stop acknowledgement")
            return cid
        if args[0] == "rm":
            if failure == "rm":
                raise RuntimeError("lost remove acknowledgement")
            state["exists"] = False
            return cid
        pytest.fail("unexpected Docker call")

    inspected = []

    def inspect(ident):
        assert ident == cid
        inspected.append(ident)
        if (
            failure == "attest-before"
            or (failure == "attest-after" and len(inspected) >= 2)
            or (failure == "attest-transient" and len(inspected) == 2)
        ):
            raise ValueError("identity drift")
        return record

    def run(argv, **kwargs):
        effects.append(("START", *argv))
        assert argv[-1] == cid and "--attach" in argv and "--interactive" in argv
        assert kwargs["input"] == b"{}" and kwargs["timeout"] == 30
        assert kwargs["env"]["DOCKER_HOST"] == cleanup.DOCKER_SOCKET
        if failure in {"timeout", "stop", "signal"}:
            state["running"] = record["State"]["Running"] = True
            if failure == "signal":
                import signal

                from boca_socios.host_telegram_cli import _interrupted

                previous = {
                    number: signal.getsignal(number) for number in (signal.SIGTERM, signal.SIGHUP)
                }
                try:
                    _interrupted(15, None)
                finally:
                    for number, handler in previous.items():
                        signal.signal(number, handler)
            raise subprocess.TimeoutExpired(argv, 30)
        if execute is not None:
            return execute()
        return subprocess.CompletedProcess(
            argv,
            1 if failure == "exit" else 0,
            b"wrong"
            if failure == "stdout"
            else b"BOCA_TELEGRAM_STORAGE state=MIGRATED schema=0007\n",
            b"bad" if failure == "stderr" else b"",
        )

    def inventory():
        present = state["exists"] or failure == "inventory-present"
        if failure == "inventory-error":
            raise ValueError("inventory lost")
        return SimpleNamespace(containers=[SimpleNamespace(ident=cid)] if present else [])

    context = SimpleNamespace(
        attempt_id="111",
        installation=SimpleNamespace(controller_image=IMAGE),
        volumes=((volume, path),),
        check_binding=lambda: effects.append(("BINDING",)),
        stopped=lambda: effects.append(("STOPPED",)),
        reader=SimpleNamespace(inventory=inventory),
    )
    monkeypatch.setattr(cleanup, "_docker", docker)
    monkeypatch.setattr(host, "_inspect", inspect)
    monkeypatch.setattr(host.subprocess, "run", run)
    return host.InstalledMaintenance(context), effects, state


def test_installed_migration_uses_existing_image_cli_and_exact_boundary(monkeypatch):
    adapter, effects, state = _migration_helper(monkeypatch)
    assert adapter.call("migrate-schema", {}) == {"schema": 7}
    created = next(item for item in effects if item[0] == "create")
    assert created[-5:] == (IMAGE, "python", "-m", "boca_socios.telegram_storage_gate", "migrate")
    assert "--rm" not in created and created[created.index("--log-driver") + 1] == "none"
    assert created.count("--mount") == 1
    assert (
        created[created.index("--mount") + 1]
        == "type=volume,source=boca-socios_boca_data,target=/data,volume-nocopy"
    )
    assert effects[-2:] == [("rm", "d" * 64), ("BINDING",)]
    assert not state["exists"] and adapter.migration_helper_retired


@pytest.mark.parametrize(
    "payload", [{"path": "/foreign"}, {"sql": "DROP TABLE x"}, {"args": []}, None, []]
)
def test_installed_migration_refuses_arbitrary_request_before_effect(monkeypatch, payload):
    adapter, effects, state = _migration_helper(monkeypatch)
    with pytest.raises(host.MaintenanceError):
        adapter.call("migrate-schema", payload)
    assert effects == [] and not state["created"]


@pytest.mark.parametrize("failure", ["timeout", "exit", "stdout", "stderr", "signal"])
def test_installed_migration_failures_preserve_and_restore(monkeypatch, failure):
    adapter, effects, state = _migration_helper(monkeypatch, failure=failure)
    with pytest.raises(host.MaintenanceError) as caught:
        adapter.call("migrate-schema", {})
    assert not state["exists"] and adapter.migration_helper_retired
    assert caught.value.primary_error is not None and caught.value.cleanup_error is None
    assert ("rm", "d" * 64) in effects


@pytest.mark.parametrize(
    "failure",
    [
        "create",
        "cid",
        "attest-before",
        "attest-after",
        "attest-transient",
        "stop",
        "rm",
        "inventory-present",
        "inventory-error",
    ],
)
def test_installed_migration_uncertain_helper_blocks_restore(monkeypatch, failure):
    adapter, effects, state = _migration_helper(monkeypatch, failure=failure)
    with pytest.raises(host.MaintenanceError) as caught:
        adapter.call("migrate-schema", {})
    assert not adapter.migration_helper_retired
    assert caught.value.cleanup_error is not None
    if failure == "stop":
        assert caught.value.primary_error is not None
    if failure in {"create", "cid", "attest-before", "attest-after", "attest-transient"}:
        assert not any(item[0] == "rm" for item in effects)


@pytest.mark.parametrize("optional_four", [False, True])
def test_installed_migration_adds_only_seven_and_is_idempotent(
    tmp_path, monkeypatch, optional_four
):
    import contextlib
    import io
    import sqlite3
    import subprocess

    from boca_socios import telegram_storage_gate as gate
    from test_telegram_one_shot import _database

    path = tmp_path / "boca.sqlite3"
    _database(path)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE telegram_delivery_attempts")
        connection.execute("DELETE FROM schema_migrations WHERE version=7")
        if not optional_four:
            connection.execute("DELETE FROM schema_migrations WHERE version=4")
        connection.execute(
            "INSERT INTO members(member_id,email,consent_recorded_at) VALUES ('member','synthetic@example.invalid','2026-01-01')"
        )
        connection.execute(
            "INSERT INTO audit_events(audit_id,action,member_id) VALUES ('audit','historical_stop','member')"
        )
        connection.execute(
            "INSERT INTO notification_outbox(idempotency_key,kind,priority,state,created_at,expires_at,next_attempt_at) VALUES ('historical_notice','state_changed',1,'pending',1,100,2)"
        )
        before_ledger = connection.execute(
            "SELECT * FROM schema_migrations ORDER BY version"
        ).fetchall()
        before_data = tuple(connection.iterdump())
    identity = path.stat().st_dev, path.stat().st_ino
    monkeypatch.setattr(gate, "DATABASE", path)
    monkeypatch.setattr(gate, "_identity", lambda path: (path.stat().st_dev, path.stat().st_ino))
    original_migrate = gate.migrate
    monkeypatch.setattr(gate, "migrate", lambda: original_migrate(path))

    def execute():
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = gate.main(("migrate",))
        return subprocess.CompletedProcess(
            [], code, stdout.getvalue().encode(), stderr.getvalue().encode()
        )

    adapter, _, _ = _migration_helper(monkeypatch, execute=execute)
    assert adapter.call("migrate-schema", {}) == {"schema": 7}
    with sqlite3.connect(path) as connection:
        after_ledger = connection.execute(
            "SELECT * FROM schema_migrations ORDER BY version"
        ).fetchall()
        after_data = tuple(connection.iterdump())
    assert [row for row in after_ledger if row[0] != 7] == before_ledger
    assert [row[0] for row in after_ledger] == sorted([row[0] for row in before_ledger] + [7])
    assert all(line in after_data for line in before_data)
    assert (path.stat().st_dev, path.stat().st_ino) == identity
    assert adapter.call("migrate-schema", {}) == {"schema": 7}
    with sqlite3.connect(path) as connection:
        assert tuple(connection.iterdump()) == after_data


@pytest.mark.parametrize(
    "failure",
    [
        "",
        "timeout",
        "exit",
        "stdout",
        "signal",
        "create",
        "cid",
        "attest-before",
        "attest-after",
        "attest-transient",
        "stop",
        "rm",
        "inventory-present",
        "inventory-error",
    ],
)
def test_real_installed_writer_controls_backend_restoration(monkeypatch, failure):
    from boca_socios import host_telegram_backend as backend

    adapter, effects, state = _migration_helper(monkeypatch, failure=failure)
    context = adapter.context
    context.installation.pair = SimpleNamespace(sender_running=False)
    context.healthy = lambda: effects.append(("HEALTHY",))
    context.stop = lambda: effects.append(("CONTROLLER_STOP",))
    context.restore = lambda: effects.append(("RESTORE",))
    original_call = adapter.call

    def call(operation, request):
        if operation == "verify-schema":
            effects.append(("READONLY_VERIFY",))
            return (
                {"schema": 7}
                if ("RESTORE",) in effects
                else {"prerequisite": "SCHEMA_0007_REQUIRED"}
            )
        return original_call(operation, request)

    monkeypatch.setattr(adapter, "call", call)
    monkeypatch.setattr(backend, "resolve_installed_context", lambda *args, **kwargs: context)
    monkeypatch.setattr(backend, "InstalledMaintenance", lambda context: adapter)
    kwargs = dict(lease=object(), expected_source_sha="a" * 40, workflow_sha="b" * 40)
    if failure:
        with pytest.raises(backend.TelegramBackendError) as caught:
            backend.migrate_installed_telegram("111", **kwargs)
        receipt = caught.value.receipt
        if failure in {"rm", "inventory-present", "inventory-error"}:
            assert caught.value.primary_error is None
        else:
            assert caught.value.primary_error is not None
            assert not isinstance(caught.value.primary_error, host.MigrationMaintenanceError)
    else:
        receipt = backend.migrate_installed_telegram("111", **kwargs)
        assert receipt.state == "SCHEMA_READY"
    uncertain = failure in {
        "create",
        "cid",
        "attest-before",
        "attest-after",
        "attest-transient",
        "stop",
        "rm",
        "inventory-present",
        "inventory-error",
    }
    assert (("RESTORE",) in effects) is not uncertain
    assert receipt.restoration == (
        "INDETERMINATE" if uncertain else "CONTROLLER_HEALTHY_ENGINE_OFF"
    )
    if uncertain:
        assert receipt.state == "CLEANUP_INDETERMINATE"
        assert caught.value.cleanup_error is not None
    else:
        assert not state["exists"]


def _r303_retirement_boundary(
    monkeypatch, *, migration, acknowledgement="portable", identity_uncertain=False
):
    import json
    import os
    import subprocess

    cid = "d" * 64
    volume = "boca-socios_boca_data"
    path = "/home/boca-deploy/.local/share/docker/volumes/" + volume + "/_data"
    commands = []
    state = {"exists": False, "started": False}
    operation = "migrate-schema" if migration else "verify-schema"
    record = {
        "Id": cid,
        "Name": "",
        "Config": {
            "Image": IMAGE,
            "User": "10001:10001",
            "Cmd": [
                "python",
                "-m",
                "boca_socios.telegram_storage_gate"
                if migration
                else "boca_socios.telegram_maintenance",
                "migrate" if migration else operation,
            ],
            "Labels": {"com.docker.compose.project": "boca-socios"},
        },
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "LogConfig": {"Type": "none"},
            "CapDrop": ["ALL"],
            "CapAdd": None,
            "PidsLimit": 16,
            "Memory": 67108864,
            "NanoCpus": 250000000,
            "PublishAllPorts": False,
            "PortBindings": {},
            "RestartPolicy": {"Name": "no"},
            "SecurityOpt": ["no-new-privileges"],
        },
        "Mounts": [
            {
                "Type": "volume",
                "Name": volume,
                "Source": path,
                "Destination": "/data",
                "RW": migration,
                "Driver": "local",
            }
        ],
        "NetworkSettings": {"Networks": {"none": {}}},
        "State": {"Restarting": False, "Running": False, "ExitCode": 0},
    }
    context = SimpleNamespace(
        attempt_id="111",
        installation=SimpleNamespace(controller_image=IMAGE),
        volumes=((volume, path),),
        check_binding=lambda: None,
        stopped=lambda: None,
        reader=SimpleNamespace(
            inventory=lambda: SimpleNamespace(
                containers=[SimpleNamespace(ident=cid)] if state["exists"] else []
            )
        ),
    )
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
        args = argv[3:]
        commands.append(args)
        command = args[0]
        if command == "create":
            record["Name"] = "/" + args[args.index("--name") + 1]
            state["exists"] = True
            output = cid + "\n"
        elif command == "inspect":
            assert args[-1] == cid
            if identity_uncertain and state["started"]:
                record["Name"] = "/foreign-container"
            output = json.dumps(record)
        elif command == "start":
            assert args[-1] == cid and kwargs["input"] == b"{}"
            state["started"] = record["State"]["Running"] = True
            raise subprocess.TimeoutExpired(argv, 30)
        elif command == "stop":
            assert args[-2:] == ["5", cid]
            record["State"]["Running"] = False
            output = {
                "portable": ("warning: deprecated --time\n" if "--time" in args else "")
                + cid
                + "\n",
                "warning": "warning even with portable flag\n" + cid + "\n",
                "empty": "",
                "foreign": "f" * 64 + "\n",
                "multiline": cid + "\n" + cid + "\n",
                "exit": cid + "\n",
            }[acknowledgement]
        elif command == "rm":
            assert args == ["rm", cid]
            state["exists"] = False
            output = cid + "\n"
        else:
            pytest.fail("unexpected Docker effect")
        assert kwargs["text"] is True and kwargs["timeout"] == 45
        return subprocess.CompletedProcess(
            argv, 1 if command == "stop" and acknowledgement == "exit" else 0, output, ""
        )

    monkeypatch.setattr(cleanup.subprocess, "run", run)
    return host.InstalledMaintenance(context), commands, state


@pytest.mark.parametrize("migration", [False, True], ids=["ordinary", "writer"])
def test_r303_portable_stop_retires_exact_helper_after_primary_timeout(monkeypatch, migration):
    import subprocess

    adapter, commands, state = _r303_retirement_boundary(monkeypatch, migration=migration)
    with pytest.raises(host.MaintenanceError) as caught:
        adapter.call("migrate-schema" if migration else "verify-schema", {})
    if migration:
        assert isinstance(caught.value.primary_error, subprocess.TimeoutExpired)
        assert caught.value.cleanup_error is None
        assert adapter.migration_helper_retired
    else:
        assert str(caught.value) == "telegram_maintenance_failed_state_preserved"
    assert not state["exists"], commands
    assert [args for args in commands if args[0] == "stop"] == [["stop", "-t", "5", "d" * 64]]
    assert [args for args in commands if args[0] == "rm"] == [["rm", "d" * 64]]


@pytest.mark.parametrize("migration", [False, True], ids=["ordinary", "writer"])
@pytest.mark.parametrize("acknowledgement", ["warning", "empty", "foreign", "multiline", "exit"])
def test_r303_portable_helper_ack_uncertainty_forbids_removal(
    monkeypatch, migration, acknowledgement
):
    import subprocess

    adapter, commands, state = _r303_retirement_boundary(
        monkeypatch, migration=migration, acknowledgement=acknowledgement
    )
    with pytest.raises(
        host.MaintenanceError if migration or acknowledgement != "exit" else cleanup.CleanupError
    ) as caught:
        adapter.call("migrate-schema" if migration else "verify-schema", {})
    assert state["exists"] and not any(args[0] == "rm" for args in commands)
    assert sum(args[0] == "stop" for args in commands) == 1
    if migration:
        assert not adapter.migration_helper_retired
        assert isinstance(caught.value.primary_error, subprocess.TimeoutExpired)
        assert caught.value.cleanup_error is not None


@pytest.mark.parametrize("migration", [False, True], ids=["ordinary", "writer"])
def test_r303_uncertain_helper_identity_forbids_stop_and_removal(monkeypatch, migration):
    adapter, commands, state = _r303_retirement_boundary(
        monkeypatch, migration=migration, identity_uncertain=True
    )
    with pytest.raises(host.MaintenanceError):
        adapter.call("migrate-schema" if migration else "verify-schema", {})
    assert state["exists"] and not any(args[0] in {"stop", "rm"} for args in commands)
    if migration:
        assert not adapter.migration_helper_retired


def test_r303_uncertain_writer_stop_ack_blocks_backend_restore(monkeypatch):
    import subprocess

    from boca_socios import host_telegram_backend as backend

    adapter, commands, state = _r303_retirement_boundary(
        monkeypatch, migration=True, acknowledgement="warning"
    )
    context, events = adapter.context, []
    context.installation.pair = SimpleNamespace(sender_running=False)
    context.healthy = lambda: events.append("HEALTHY")
    context.stop = lambda: events.append("CONTROLLER_STOP")
    context.restore = lambda: events.append("RESTORE")
    original_call = adapter.call

    def call(operation, payload):
        if operation == "verify-schema":
            return {"prerequisite": "SCHEMA_0007_REQUIRED"}
        return original_call(operation, payload)

    monkeypatch.setattr(adapter, "call", call)
    monkeypatch.setattr(backend, "resolve_installed_context", lambda *args, **kwargs: context)
    monkeypatch.setattr(backend, "InstalledMaintenance", lambda checked: adapter)
    with pytest.raises(backend.TelegramBackendError) as caught:
        backend.migrate_installed_telegram(
            "111", lease=object(), expected_source_sha="a" * 40, workflow_sha="b" * 40
        )
    assert caught.value.receipt.state == "CLEANUP_INDETERMINATE"
    assert caught.value.receipt.restoration == "INDETERMINATE"
    assert caught.value.receipt.sender_state == "OFF"
    assert isinstance(caught.value.primary_error, subprocess.TimeoutExpired)
    assert caught.value.cleanup_error is not None
    assert "RESTORE" not in events and state["exists"]
    assert sum(args[0] == "stop" for args in commands) == 1
    assert not any(args[0] == "rm" for args in commands)
