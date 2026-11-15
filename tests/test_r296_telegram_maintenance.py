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
