"""Protected BETA installation must preserve custody and host loopback isolation."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host

SHA = "a" * 40
IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64
ORIGIN = "https://boca.example.test:8443"
OWNER = "synthetic-owner"


def _snapshot() -> host.HostSnapshot:
    return host.HostSnapshot(
        arch="x86_64",
        uid=10001,
        available_memory_kib=853288,
        available_disk_bytes=8 * 1024**3,
        available_inodes=100000,
        docker_disk_bytes=8 * 1024**3,
        docker_inodes=100000,
        root_ready=True,
        boca_containers=False,
        boca_volume=True,
        boca_network=False,
        cpu_headroom=1.0,
    )


def test_beta_preflight_only_accepts_owner_volume_and_empty_app_namespace() -> None:
    host.validate_beta_snapshot(_snapshot(), {host.OWNER_VOLUME}, expected={host.OWNER_VOLUME})
    for volumes in (
        set(),
        {host.OWNER_VOLUME, host.KEY_VOLUME},
        {host.OWNER_VOLUME, "boca-socios_boca_data"},
        {"boca-socios_other"},
    ):
        with pytest.raises(host.PreflightError):
            host.validate_beta_snapshot(_snapshot(), volumes, expected={host.OWNER_VOLUME})
    for changed in ("boca_containers", "boca_network"):
        with pytest.raises(host.PreflightError):
            host.validate_beta_snapshot(
                replace(_snapshot(), **{changed: True}),
                {host.OWNER_VOLUME},
                expected={host.OWNER_VOLUME},
            )


def test_beta_inventory_rejects_unrelated_rootless_container_before_owner_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host, "collect_snapshot", lambda **_kwargs: _snapshot())
    monkeypatch.setattr(host, "_names", lambda *_args: pytest.fail("volume read after rogue"))
    monkeypatch.setattr(
        host, "_validate_owner_volume", lambda: pytest.fail("owner read after rogue")
    )
    monkeypatch.setattr(host, "_run", lambda *_args: "f" * 64)
    with pytest.raises(host.PreflightError, match="daemon must have no containers"):
        host._beta_inventory(staged=False, expected={host.OWNER_VOLUME})


def test_beta_context_rejects_untrusted_origin_and_subject() -> None:
    host._validate_beta_context(ORIGIN, OWNER)
    for origin, owner in (
        ("http://boca.example.test:8443", OWNER),
        ("https://boca.example.test:8443/path", OWNER),
        ("https://user@boca.example.test:8443", OWNER),
        ("https://boca.example.test:99999", OWNER),
        (ORIGIN, ""),
        (ORIGIN, "owner;id"),
    ):
        with pytest.raises(host.PreflightError):
            host._validate_beta_context(origin, owner)


def test_beta_preflight_containers_are_network_free_and_do_not_mount_data() -> None:
    owner = host._beta_check_container(IMAGE, ORIGIN, OWNER, "check-beta-owner")
    assert owner[:5] == ("docker", "run", "--rm", "--pull", "never")
    assert owner[owner.index("--user") + 1] == "10001:10001"
    assert owner[owner.index("--network") + 1] == "none"
    assert owner[owner.index("--cap-drop") + 1] == "ALL"
    assert "--read-only" in owner and "docker.sock" not in " ".join(owner)
    assert (
        f"type=volume,source={host.OWNER_VOLUME},target=/run/owner,volume-nocopy,readonly" in owner
    )
    assert host.KEY_VOLUME not in " ".join(owner)
    assert "boca-socios_boca_data" not in " ".join(owner)
    assert "BOCA_HEALTH_CA_FILE=/run/owner/health-ca.pem" in owner
    assert owner[-4:] == ("python", "-m", "boca_socios.runtime", "check-beta-owner")
    full = host._beta_check_container(IMAGE, ORIGIN, OWNER, "check-beta-config")
    assert (
        f"type=volume,source={host.KEY_VOLUME},target=/run/secrets,volume-nocopy,readonly" in full
    )
    assert "boca-socios_boca_data" not in " ".join(full)
    assert full[-1] == "check-beta-config"


def test_new_only_beta_initializer_uses_private_key_and_data_with_fixed_limits() -> None:
    command = host._beta_init_container(IMAGE)
    assert command[command.index("--user") + 1] == "10001:10001"
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--memory") + 1] == "256m"
    assert command[command.index("--cpus") + 1] == "0.50"
    assert (
        f"type=volume,source={host.KEY_VOLUME},target=/run/secrets,volume-nocopy,readonly"
        in command
    )
    assert "type=volume,source=boca-socios_boca_data,target=/data" in command
    assert host.OWNER_VOLUME not in " ".join(command)
    assert command[-4:] == ("python", "-m", "boca_socios.runtime", "init-beta")


def test_beta_workflow_has_separate_marker_release_and_main_gates() -> None:
    workflow = Path(".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    assert "beta-install" in workflow
    assert 'test "$BOCA_BETA_ENV_READY" = ready' in workflow
    assert "BOCA_BETA_PANEL_ORIGIN: ${{ secrets.BOCA_BETA_PANEL_ORIGIN }}" in workflow
    assert "BOCA_BETA_OWNER_SUBJECT: ${{ secrets.BOCA_BETA_OWNER_SUBJECT }}" in workflow
    assert "python scripts/check_release_run.py" in workflow
    assert "python scripts/check_beta_deploy_contract.py" in workflow
    assert workflow.index("Recheck current main before BETA install") < workflow.index(
        "Initialize new-only BETA and start isolated controller"
    )
    assert "BOCA_SITE_ENVELOPE" in workflow
    assert "BOCA_BETA_TOKEN" not in workflow
    owner_step = workflow.index("python -m boca_socios.runtime check-beta-owner)")
    config_step = workflow.index("python -m boca_socios.runtime check-beta-config)")
    data_step = workflow.index(
        "--label com.docker.compose.volume=boca_data boca-socios_boca_data", owner_step
    )
    assert owner_step < config_step < data_step
    assert "--resolve beta.boca.example.test:8443:127.0.0.1" in workflow
    assert "chown 10001:10001 /run/owner'" in workflow


def test_dormant_and_site_phases_cannot_take_beta_context_before_host_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host, "_validate_docker_boundary", lambda: pytest.fail("host probed"))
    for phase in ("observe", "apply", "site-prepare"):
        with pytest.raises(host.PreflightError):
            host.phase(phase, "" if phase == "observe" else IMAGE, SHA, "d" * 64, ORIGIN, OWNER)


def test_missing_owner_readiness_blocks_key_and_data_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations: list[str] = []
    monkeypatch.setattr(host, "_verify_beta_compose", lambda _sha: None)
    monkeypatch.setattr(host, "_beta_inventory", lambda **_kwargs: _snapshot())
    monkeypatch.setattr(host, "_beta_pull", lambda *_args: None)
    monkeypatch.setattr(host, "_create_key", lambda _image: pytest.fail("key created before owner"))

    def fake_run(*args: str, env: dict[str, str] | None = None) -> str:
        operations.append(" ".join(args))
        if "check-beta-owner" in args:
            return '{"event":"beta_owner_unavailable"}'
        if "volume" in args or "init-beta" in args:
            pytest.fail("data touched before owner proof")
        return ""

    monkeypatch.setattr(host, "_run", fake_run)
    with pytest.raises(host.PreflightError, match="preflight did not confirm"):
        host._beta_phase("beta-apply", IMAGE, SHA, "d" * 64, ORIGIN, OWNER)
    assert any("check-beta-owner" in command for command in operations)


def test_full_config_failure_preserves_absent_data_volume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(host, "_verify_beta_compose", lambda _sha: None)
    monkeypatch.setattr(host, "_beta_inventory", lambda **_kwargs: _snapshot())
    monkeypatch.setattr(host, "_beta_pull", lambda *_args: None)
    monkeypatch.setattr(host, "_create_key", lambda _image: calls.append("key"))

    def fake_run(*args: str, env: dict[str, str] | None = None) -> str:
        if "check-beta-owner" in args:
            calls.append("owner")
            return '{"event":"beta_owner_ready","mode":"simulation","engine":"off"}'
        if "check-beta-config" in args:
            calls.append("config")
            return '{"event":"beta_config_unavailable"}'
        if "volume" in args or "init-beta" in args:
            pytest.fail("data touched before key and config proof")
        return ""

    monkeypatch.setattr(host, "_run", fake_run)
    with pytest.raises(host.PreflightError, match="preflight did not confirm"):
        host._beta_phase("beta-apply", IMAGE, SHA, "d" * 64, ORIGIN, OWNER)
    assert calls == ["owner", "key", "config"]


def test_rollback_rejects_unknown_namespace_before_any_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: str, env: dict[str, str] | None = None) -> str:
        if args[:3] == ("docker", "ps", "-a"):
            return "c" * 64 if "name=^/boca-socios-" in args else "f" * 64
        pytest.fail("no effect allowed for ambiguous Boca inventory")

    monkeypatch.setattr(host, "_run", fake_run)
    with pytest.raises(host.PreflightError, match="inventory is uncertain"):
        host._beta_rollback(IMAGE, SHA)


def test_rollback_stops_only_proven_controller_and_keeps_all_volumes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    container = "c" * 64
    commands: list[tuple[str, ...]] = []
    record = {
        "Id": container,
        "Name": "/boca-socios-controller-1",
        "Config": {
            "Image": IMAGE,
            "User": "10001:10001",
            "Labels": {
                "com.docker.compose.project": "boca-socios",
                "com.docker.compose.service": "controller",
                "org.opencontainers.image.revision": SHA,
            },
        },
        "State": {"Running": True},
    }

    def fake_run(*args: str, env: dict[str, str] | None = None) -> str:
        commands.append(args)
        if args[:3] == ("docker", "ps", "-a"):
            return container
        if args[:2] == ("docker", "inspect"):
            return (
                json.dumps({"Running": False, "Restarting": False})
                if "{{json .State}}" in args
                else json.dumps(record)
            )
        if args[:2] == ("docker", "stop"):
            return container
        pytest.fail("rollback may only inspect or stop its controller")

    monkeypatch.setattr(host, "_run", fake_run)
    monkeypatch.setattr(
        host,
        "_storage_snapshot",
        lambda: type(
            "Storage",
            (),
            {
                "stage_free_bytes": 4 * 1024**3,
                "docker_free_bytes": 4 * 1024**3,
                "stage_inodes": 50000,
                "docker_inodes": 50000,
            },
        )(),
    )
    host._beta_rollback(IMAGE, SHA)
    assert ("docker", "stop", "--time", "30", container) in commands
    assert all(not {"rm", "prune", "down"} & set(command) for command in commands)
    assert "state=STOPPED data=preserved key=preserved owner=preserved" in capsys.readouterr().out


@pytest.mark.parametrize("host_ip", ["127.0.0.1", "0.0.0.0", "::"])  # noqa: S104 - rejected fixture
def test_beta_postflight_proves_actual_private_bind_not_just_compose_model(
    monkeypatch: pytest.MonkeyPatch, host_ip: str
) -> None:
    container = "c" * 64
    ports = {"8443/tcp": [{"HostIp": host_ip, "HostPort": "8443"}]}
    config = {
        "Image": IMAGE,
        "User": "10001:10001",
        "Cmd": ["python", "-m", "boca_socios.runtime", "serve-beta"],
        "Entrypoint": None,
        "Labels": {
            "com.docker.compose.project": host.PROJECT,
            "com.docker.compose.service": "controller",
        },
        "Env": [
            f"{key}={value}"
            for key, value in {
                "BOCA_ENVIRONMENT": "staging",
                "BOCA_DB_PATH": "/data/boca.sqlite3",
                "BOCA_MASTER_KEY_FILE": "/run/secrets/boca_master_key",
                "BOCA_RUNTIME_MODE": "simulation",
                "BOCA_ENGINE_MODE": "off",
                "BOCA_PANEL_ORIGIN": ORIGIN,
                "BOCA_OWNER_SUBJECT": OWNER,
                "BOCA_PASSKEY_CREDENTIAL_ID_FILE": "/run/owner/credential_id",
                "BOCA_PASSKEY_PUBLIC_KEY_DER_FILE": "/run/owner/public_key.der",
                "BOCA_TLS_CERT_FILE": "/run/owner/tls.crt",
                "BOCA_TLS_KEY_FILE": "/run/owner/tls.key",
                "BOCA_HEALTH_CA_FILE": "/run/owner/health-ca.pem",
                "BOCA_HEALTH_MODE": "beta",
                "BOCA_BIND_HOST": "0.0.0.0",  # noqa: S104 - isolated container
                "BOCA_BIND_PORT": "8443",
            }.items()
        ],
    }
    host_config = {
        "NanoCpus": 500_000_000,
        "Memory": 268_435_456,
        "PidsLimit": 64,
        "ReadonlyRootfs": True,
        "Privileged": False,
        "PortBindings": ports,
        "PublishAllPorts": False,
        "NetworkMode": "boca-socios_boca_private",
        "CapDrop": ["ALL"],
        "CapAdd": None,
        "SecurityOpt": ["no-new-privileges:true"],
        "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=16m"},  # noqa: S108 - container tmpfs
        "CgroupnsMode": "private",
        "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
    }

    def fake_run(*args: str, env: dict[str, str] | None = None) -> str:
        if "ps" in args:
            return container
        if args[:3] == ("docker", "image", "inspect"):
            return json.dumps([IMAGE]) if "RepoDigests" in args[4] else SHA
        if args[:2] == ("docker", "inspect"):
            match args[3]:
                case "{{json .Config}}":
                    return json.dumps(config)
                case "{{json .HostConfig}}":
                    return json.dumps(host_config)
                case "{{json .NetworkSettings}}":
                    return json.dumps(
                        {
                            "Networks": {"boca-socios_boca_private": {"NetworkID": "d" * 64}},
                            "Ports": ports,
                        }
                    )
                case "{{json .Mounts}}":
                    return json.dumps(
                        [
                            {
                                "Type": "volume",
                                "Driver": "local",
                                "Name": name,
                                "Destination": destination,
                                "RW": writable,
                            }
                            for name, destination, writable in (
                                (host.DATA_VOLUME, "/data", True),
                                (host.KEY_VOLUME, "/run/secrets", False),
                                (host.OWNER_VOLUME, "/run/owner", False),
                            )
                        ]
                    )
                case "{{.State.Health.Status}}":
                    return "healthy"
        if args[:2] == ("docker", "exec"):
            return "BOCA_KEY_READY"
        pytest.fail("unexpected Docker command")

    monkeypatch.setattr(host, "_run", fake_run)
    monkeypatch.setattr(host, "_validate_boca_network", lambda *_args: None)
    monkeypatch.setattr(
        host,
        "_cgroup_limits",
        lambda _container: host.CgroupLimits(50000, 100000, 268435456, 64),
    )
    monkeypatch.setattr(host.os, "getuid", lambda: 10001)
    if host_ip == "127.0.0.1":
        host.collect_diagnostic(IMAGE, SHA, beta_origin=ORIGIN, beta_owner=OWNER)
    else:
        with pytest.raises(host.PreflightError, match="host loopback port"):
            host.collect_diagnostic(IMAGE, SHA, beta_origin=ORIGIN, beta_owner=OWNER)
