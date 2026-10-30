"""Host preflight and failure boundary are testable without Docker or SSH."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host
from boca_socios.host_first_deploy import (
    DiagnosticSnapshot,
    DockerBoundarySnapshot,
    HostSnapshot,
    PreflightError,
    validate_diagnostic,
    validate_docker_boundary,
    validate_snapshot,
)

SOURCE_SHA = "a" * 40
IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64
GOOD_HOST_CONFIG = {
    "NanoCpus": 500_000_000,
    "Memory": 268_435_456,
    "PidsLimit": 64,
    "ReadonlyRootfs": True,
    "Privileged": False,
    "PortBindings": {},
    "PublishAllPorts": False,
}


def safe_boundary() -> DockerBoundarySnapshot:
    return DockerBoundarySnapshot(
        socket_secure=True,
        rootful_socket_inaccessible=True,
        daemon_rootless=True,
        cgroup_version="2",
        cgroup_driver="systemd",
        controllers=frozenset({"cpu", "memory", "pids"}),
    )


def _dedicated_test_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host.os, "getuid", lambda: 10001)
    monkeypatch.setattr(host.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(host.os, "getgid", lambda: 10001)
    monkeypatch.setattr(host.os, "getegid", lambda: 10001)
    monkeypatch.setattr(
        host.pwd, "getpwuid", lambda _uid: type("Account", (), {"pw_name": "boca-deploy"})()
    )


def test_dedicated_rootless_daemon_with_delegated_limits_is_accepted() -> None:
    validate_docker_boundary(safe_boundary())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("socket_secure", False),
        ("rootful_socket_inaccessible", False),
        ("daemon_rootless", False),
        ("cgroup_version", "1"),
        ("cgroup_driver", "none"),
        ("controllers", frozenset({"memory", "pids"})),
        ("controllers", frozenset({"cpu", "memory"})),
    ],
)
def test_unproven_daemon_boundary_is_no_go(field: str, value: object) -> None:
    with pytest.raises(PreflightError):
        validate_docker_boundary(replace(safe_boundary(), **{field: value}))


@pytest.mark.parametrize(
    "info",
    [
        {
            "SecurityOptions": ["name=seccomp,profile=builtin"],
            "CgroupVersion": "2",
            "CgroupDriver": "systemd",
        },
        {"SecurityOptions": ["name=rootless"], "CgroupVersion": "2", "CgroupDriver": "none"},
        {"SecurityOptions": "name=rootless", "CgroupVersion": "2", "CgroupDriver": "systemd"},
        {},
    ],
)
def test_daemon_info_must_prove_rootless_and_cgroups(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, info: dict[str, object]
) -> None:
    _dedicated_test_identity(monkeypatch)
    controllers = tmp_path / "cgroup.controllers"
    controllers.write_text("cpu memory pids\n")
    monkeypatch.setattr(host, "CGROUP_CONTROLLERS", controllers)
    monkeypatch.setattr(host, "_rootless_socket_secure", lambda: True)
    monkeypatch.setattr(host, "_rootful_socket_inaccessible", lambda: True)
    monkeypatch.setattr(host, "_run", lambda *args: json.dumps(info))
    with pytest.raises(PreflightError):
        host._validate_docker_boundary()


def test_rootless_daemon_info_and_delegation_are_checked_together(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _dedicated_test_identity(monkeypatch)
    controllers = tmp_path / "cgroup.controllers"
    controllers.write_text("cpu io memory pids\n")
    monkeypatch.setattr(host, "CGROUP_CONTROLLERS", controllers)
    monkeypatch.setattr(host, "_rootless_socket_secure", lambda: True)
    monkeypatch.setattr(host, "_rootful_socket_inaccessible", lambda: True)
    monkeypatch.setattr(
        host,
        "_run",
        lambda *args: json.dumps(
            {
                "SecurityOptions": ["name=seccomp,profile=builtin", "name=rootless"],
                "CgroupVersion": "2",
                "CgroupDriver": "systemd",
            }
        ),
    )
    host._validate_docker_boundary()


@pytest.mark.parametrize(
    ("identity_method", "value"),
    [("getuid", 0), ("geteuid", 0), ("getgid", 10002), ("getegid", 10002)],
)
def test_docker_boundary_checks_effective_identity_before_private_socket_metadata(
    monkeypatch: pytest.MonkeyPatch, identity_method: str, value: int
) -> None:
    _dedicated_test_identity(monkeypatch)
    monkeypatch.setattr(host.os, identity_method, lambda: value)
    monkeypatch.setattr(host, "_rootless_socket_secure", lambda: pytest.fail("socket read"))
    monkeypatch.setattr(host, "_rootful_socket_inaccessible", lambda: pytest.fail("rootful read"))
    with pytest.raises(PreflightError, match="dedicated Boca identity"):
        host._validate_docker_boundary()


def test_docker_boundary_rejects_wrong_account_before_socket_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _dedicated_test_identity(monkeypatch)
    monkeypatch.setattr(
        host.pwd, "getpwuid", lambda _uid: type("Account", (), {"pw_name": "other"})()
    )
    monkeypatch.setattr(host, "_rootless_socket_secure", lambda: pytest.fail("socket read"))
    with pytest.raises(PreflightError, match="dedicated boca-deploy account"):
        host._validate_docker_boundary()


def test_docker_commands_cannot_use_inherited_rootful_or_remote_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, str]] = []

    def fake_subprocess(*args: object, **kwargs: object) -> object:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        captured.append(environment)
        return type("Result", (), {"stdout": "ok"})()

    monkeypatch.setattr(host.subprocess, "run", fake_subprocess)
    assert (
        host._run(
            "docker",
            "info",
            env={
                "DOCKER_HOST": "tcp://remote:2375",
                "DOCKER_CONTEXT": "rootful",
                "DOCKER_CONFIG": "/var/remote-context",
                "DOCKER_TLS": "1",
                "DOCKER_TLS_VERIFY": "1",
                "DOCKER_CERT_PATH": "/var/remote-certs",
            },
        )
        == "ok"
    )
    assert captured[0]["DOCKER_HOST"] == "unix:///run/user/10001/docker.sock"
    for variable in (
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ):
        assert variable not in captured[0]

    monkeypatch.setenv("DOCKER_HOST", "ssh://remote")
    monkeypatch.setenv("DOCKER_CONTEXT", "rootful")
    monkeypatch.setenv("DOCKER_TLS", "1")
    assert host._run("docker", "info") == "ok"
    assert captured[1]["DOCKER_HOST"] == "unix:///run/user/10001/docker.sock"
    assert "DOCKER_CONTEXT" not in captured[1]
    assert "DOCKER_TLS" not in captured[1]


def safe_snapshot() -> HostSnapshot:
    return HostSnapshot(
        arch="x86_64",
        uid=10001,
        available_memory_kib=1024 * 1024,
        available_disk_bytes=8 * 1024**3,
        available_inodes=100_000,
        root_ready=True,
        boca_containers=False,
        boca_volume=False,
        boca_network=False,
    )


def test_first_deploy_preflight_passes_only_with_free_boca_namespace() -> None:
    validate_snapshot(safe_snapshot())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("arch", "aarch64"),
        ("uid", 0),
        ("available_memory_kib", 400_000),
        ("available_disk_bytes", 2 * 1024**3),
        ("available_inodes", 1_000),
        ("root_ready", False),
        ("boca_containers", True),
        ("boca_volume", True),
        ("boca_network", True),
        ("cpu_headroom", 0.1),
    ],
)
def test_unsafe_host_snapshot_is_no_go(field: str, value: object) -> None:
    with pytest.raises(PreflightError):
        validate_snapshot(replace(safe_snapshot(), **{field: value}))


def _staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    root = tmp_path / "boca-socios"
    root.mkdir(mode=0o700)
    compose = root / "compose.yaml"
    compose.write_text("name: boca-socios\n")
    monkeypatch.setattr(host, "ROOT", root)
    monkeypatch.setattr(host, "COMPOSE", compose)
    monkeypatch.setattr(host, "collect_snapshot", safe_snapshot)
    monkeypatch.setattr(host, "_validate_docker_boundary", lambda: None)
    # The test may run with a different UID; all other staging checks remain real.
    monkeypatch.setattr(host, "_safe_dir", lambda _path: True)
    digest = hashlib.sha256(compose.read_bytes()).hexdigest()

    def verify_compose(expected: str) -> None:
        if hashlib.sha256(compose.read_bytes()).hexdigest() != expected:
            raise PreflightError("staged Compose SHA-256 differs from reviewed file")

    monkeypatch.setattr(host, "_verify_compose", verify_compose)
    return digest


def _docker_root(tmp_path: Path) -> Path:
    root = tmp_path / "rootless-docker"
    (root / "volumes" / host.KEY_VOLUME / "_data").mkdir(parents=True)
    return root


@pytest.mark.parametrize(
    "phase_name", ["preflight", "stage", "config", "apply", "diagnostic-config", "diagnostic"]
)
def test_unverified_docker_boundary_stops_every_host_phase_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase_name: str
) -> None:
    digest = _staged(tmp_path, monkeypatch)
    monkeypatch.setattr(
        host,
        "_validate_docker_boundary",
        lambda: (_ for _ in ()).throw(PreflightError("daemon boundary")),
    )
    monkeypatch.setattr(
        host, "_run", lambda *args, **kwargs: pytest.fail("Docker command executed")
    )
    with pytest.raises(PreflightError, match="daemon boundary"):
        host.phase(phase_name, IMAGE, SOURCE_SHA, digest)
    assert not (host.ROOT / "secrets").exists()


def test_bad_image_revision_fails_before_creating_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    digest = _staged(tmp_path, monkeypatch)
    commands: list[tuple[str, ...]] = []

    def fake_run(*args: str, env: dict[str, str] | None = None) -> str:
        commands.append(args)
        if args[:3] == ("docker", "image", "inspect"):
            return '["' + IMAGE + '"]' if "RepoDigests" in args[4] else "wrong-revision"
        return ""

    monkeypatch.setattr(host, "_run", fake_run)
    with pytest.raises(PreflightError, match="differs from authorization"):
        host.phase("apply", IMAGE, SOURCE_SHA, digest)
    assert not any(command[:3] == ("docker", "volume", "create") for command in commands)
    assert not any("up" in command for command in commands)


def test_key_volume_is_created_once_and_verified_without_host_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands: list[tuple[str, ...]] = []
    root = _docker_root(tmp_path)

    def fake_run(*args: str) -> str:
        commands.append(args)
        if args[:3] == ("docker", "volume", "create"):
            return host.KEY_VOLUME
        if args[:2] == ("docker", "info"):
            return str(root)
        if args[:3] == ("docker", "volume", "inspect"):
            return json.dumps(
                {
                    "Name": host.KEY_VOLUME,
                    "Driver": "local",
                    "Scope": "local",
                    "Options": {},
                    "Mountpoint": str(root / "volumes" / host.KEY_VOLUME / "_data"),
                    "Labels": {
                        "com.docker.compose.project": "boca-socios",
                        "com.docker.compose.volume": "boca_key",
                    },
                }
            )
        if args[:2] == ("docker", "run"):
            return "BOCA_KEY_READY"
        raise AssertionError("unexpected Docker operation")

    monkeypatch.setattr(host, "_run", fake_run)
    host._create_key(IMAGE)
    assert commands[0][:3] == ("docker", "volume", "create")
    init, verify = commands[-2:]
    assert init[-1] == "init" and verify[-1] == "verify"
    assert "--network" in init and init[init.index("--network") + 1] == "none"
    assert "CHOWN" in init and "CHOWN" not in verify
    assert "--user" in verify and verify[verify.index("--user") + 1] == "10001:10001"
    assert "readonly" in verify[verify.index("--mount") + 1]
    assert not any("bind" in value for command in commands for value in command)


def test_existing_or_foreign_key_volume_is_no_go_before_initializer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands: list[tuple[str, ...]] = []
    root = _docker_root(tmp_path)

    def fake_run(*args: str) -> str:
        commands.append(args)
        if args[:3] == ("docker", "volume", "create"):
            return host.KEY_VOLUME
        if args[:2] == ("docker", "info"):
            return str(root)
        if args[:3] == ("docker", "volume", "inspect"):
            return json.dumps(
                {
                    "Name": host.KEY_VOLUME,
                    "Driver": "local",
                    "Scope": "local",
                    "Options": {},
                    "Mountpoint": str(root / "volumes" / host.KEY_VOLUME / "_data"),
                    "Labels": {},
                }
            )
        raise AssertionError("initializer must not run")

    monkeypatch.setattr(host, "_run", fake_run)
    with pytest.raises(PreflightError, match="volume identity"):
        host._create_key(IMAGE)
    assert not any(command[:2] == ("docker", "run") for command in commands)


@pytest.mark.parametrize("escape", ["bind-options", "foreign-mountpoint", "symlink"])
def test_labeled_local_volume_cannot_redirect_key_initialization(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, escape: str
) -> None:
    root = _docker_root(tmp_path)
    expected = root / "volumes" / host.KEY_VOLUME / "_data"
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    if escape == "symlink":
        expected.rmdir()
        expected.symlink_to(foreign, target_is_directory=True)
    commands: list[tuple[str, ...]] = []

    def fake_run(*args: str) -> str:
        commands.append(args)
        if args[:3] == ("docker", "volume", "create"):
            return host.KEY_VOLUME
        if args[:3] == ("docker", "volume", "inspect"):
            return json.dumps(
                {
                    "Name": host.KEY_VOLUME,
                    "Driver": "local",
                    "Scope": "local",
                    "Labels": {
                        "com.docker.compose.project": "boca-socios",
                        "com.docker.compose.volume": "boca_key",
                    },
                    "Options": (
                        {"type": "none", "o": "bind", "device": str(foreign)}
                        if escape == "bind-options"
                        else {}
                    ),
                    "Mountpoint": str(foreign if escape == "foreign-mountpoint" else expected),
                }
            )
        if args[:2] == ("docker", "info"):
            return str(root)
        raise AssertionError("initializer must not run")

    monkeypatch.setattr(host, "_run", fake_run)
    with pytest.raises(PreflightError, match="volume identity|mountpoint"):
        host._create_key(IMAGE)
    assert not any(command[:2] == ("docker", "run") for command in commands)
    assert list(foreign.iterdir()) == []


def test_failed_start_stops_only_controller_and_preserves_key_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    digest = _staged(tmp_path, monkeypatch)
    commands: list[tuple[str, ...]] = []

    def fake_run(*args: str, env: dict[str, str] | None = None) -> str:
        commands.append(args)
        if args[:3] == ("docker", "image", "inspect"):
            return '["' + IMAGE + '"]' if "RepoDigests" in args[4] else SOURCE_SHA
        if "up" in args:
            raise PreflightError("simulated unhealthy controller")
        return ""

    monkeypatch.setattr(host, "_run", fake_run)
    monkeypatch.setattr(
        host, "_create_key", lambda _image: commands.append(("key-volume", "create"))
    )
    with pytest.raises(PreflightError, match="unhealthy"):
        host.phase("apply", IMAGE, SOURCE_SHA, digest)
    assert [command[-2:] for command in commands if "stop" in command] == [("stop", "controller")]
    assert ("key-volume", "create") in commands
    assert not any("down" in command or "prune" in command for command in commands)
    assert not any(command[:3] == ("docker", "volume", "rm") for command in commands)


def test_first_install_requires_strict_postflight_before_reporting_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    digest = _staged(tmp_path, monkeypatch)
    checks: list[str] = []

    def fake_run(*args: str, env: dict[str, str] | None = None) -> str:
        if args[:3] == ("docker", "image", "inspect"):
            return json.dumps([IMAGE]) if "RepoDigests" in args[4] else SOURCE_SHA
        if "ps" in args:
            return "c" * 64
        if args[:2] == ("docker", "inspect"):
            return "healthy"
        return ""

    def verify_files(expected: str) -> None:
        assert expected == digest
        checks.append("key-and-compose")

    def inspect_runtime(image: str, source_sha: str) -> DiagnosticSnapshot:
        assert (image, source_sha) == (IMAGE, SOURCE_SHA)
        checks.append("runtime")
        return healthy_diagnostic()

    monkeypatch.setattr(host, "_run", fake_run)
    monkeypatch.setattr(host, "_create_key", lambda _image: checks.append("key-created"))
    monkeypatch.setattr(host, "_diagnostic_files", verify_files)
    monkeypatch.setattr(host, "collect_diagnostic", inspect_runtime)

    host.phase("apply", IMAGE, SOURCE_SHA, digest)
    assert checks == ["key-created", "key-and-compose", "runtime"]
    assert "BOCA_DEPLOY_PASS" in capsys.readouterr().out


@pytest.mark.parametrize(
    "failure",
    [
        PreflightError("engine on"),
        ValueError("bad JSON"),
        OSError("missing key"),
        TypeError("unexpected Docker metadata type"),
        KeyError("missing Docker metadata field"),
    ],
)
def test_postflight_failure_stops_only_controller_and_preserves_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    digest = _staged(tmp_path, monkeypatch)
    commands: list[tuple[str, ...]] = []

    def fake_run(*args: str, env: dict[str, str] | None = None) -> str:
        commands.append(args)
        if args[:3] == ("docker", "image", "inspect"):
            return json.dumps([IMAGE]) if "RepoDigests" in args[4] else SOURCE_SHA
        if "ps" in args:
            return "c" * 64
        if args[:2] == ("docker", "inspect"):
            return "healthy"
        return ""

    def fail_postflight(_image: str, _sha: str) -> DiagnosticSnapshot:
        raise failure

    monkeypatch.setattr(host, "_run", fake_run)
    monkeypatch.setattr(
        host, "_create_key", lambda _image: commands.append(("key-volume", "create"))
    )
    monkeypatch.setattr(host, "_diagnostic_files", lambda _sha: None)
    monkeypatch.setattr(host, "collect_diagnostic", fail_postflight)
    with pytest.raises(type(failure)):
        host.phase("apply", IMAGE, SOURCE_SHA, digest)
    assert [command[-2:] for command in commands if "stop" in command] == [("stop", "controller")]
    assert ("key-volume", "create") in commands
    assert not any("down" in command or "prune" in command for command in commands)
    assert not any(command[:3] == ("docker", "volume", "rm") for command in commands)


@pytest.mark.parametrize(
    ("field", "payload"),
    [
        ("{{json .Config}}", "{"),
        ("{{json .Config}}", "[]"),
        ("{{json .Config}}", '{"Labels": {}, "Env": [12]}'),
        ("{{json .HostConfig}}", "null"),
        (
            "{{json .HostConfig}}",
            json.dumps(
                {key: value for key, value in GOOD_HOST_CONFIG.items() if key != "PortBindings"}
            ),
        ),
        ("{{json .HostConfig}}", json.dumps({**GOOD_HOST_CONFIG, "PortBindings": None})),
        ("{{json .HostConfig}}", json.dumps({**GOOD_HOST_CONFIG, "PortBindings": []})),
        (
            "{{json .HostConfig}}",
            json.dumps(
                {key: value for key, value in GOOD_HOST_CONFIG.items() if key != "PublishAllPorts"}
            ),
        ),
        ("{{json .HostConfig}}", json.dumps({**GOOD_HOST_CONFIG, "PublishAllPorts": True})),
        ("{{json .HostConfig}}", json.dumps({**GOOD_HOST_CONFIG, "PublishAllPorts": "false"})),
        (
            "{{json .HostConfig}}",
            json.dumps({**GOOD_HOST_CONFIG, "PortBindings": {"80/tcp": [{"HostPort": "8080"}]}}),
        ),
        ("{{json .HostConfig}}", json.dumps({**GOOD_HOST_CONFIG, "NanoCpus": {}})),
    ],
)
def test_malformed_docker_postflight_stops_controller_without_removing_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    field: str,
    payload: str,
) -> None:
    digest = _staged(tmp_path, monkeypatch)
    commands: list[tuple[str, ...]] = []

    def fake_run(*args: str, env: dict[str, str] | None = None) -> str:
        commands.append(args)
        if args[:3] == ("docker", "image", "inspect"):
            return json.dumps([IMAGE]) if "RepoDigests" in args[4] else SOURCE_SHA
        if "ps" in args:
            return "c" * 64
        if args[:2] == ("docker", "inspect"):
            if args[3] == "{{.State.Health.Status}}":
                return "healthy"
            if args[3] == field:
                return payload
            if args[3] == "{{json .Config}}":
                return json.dumps(
                    {
                        "Image": IMAGE,
                        "User": "10001:10001",
                        "Labels": {
                            "com.docker.compose.project": "boca-socios",
                            "com.docker.compose.service": "controller",
                        },
                        "Env": [
                            "BOCA_ENVIRONMENT=staging",
                            "BOCA_DB_PATH=/data/boca.sqlite3",
                            "BOCA_MASTER_KEY_FILE=/run/secrets/boca_master_key",
                            "BOCA_RUNTIME_MODE=simulation",
                            "BOCA_ENGINE_MODE=off",
                        ],
                    }
                )
            if args[3] == "{{json .HostConfig}}":
                return json.dumps(GOOD_HOST_CONFIG)
            if args[3] == "{{json .Mounts}}":
                return json.dumps(
                    [
                        {
                            "Type": "volume",
                            "Driver": "local",
                            "Name": "boca-socios_boca_data",
                            "Destination": "/data",
                            "RW": True,
                        },
                        {
                            "Type": "volume",
                            "Driver": "local",
                            "Name": host.KEY_VOLUME,
                            "Destination": "/run/secrets",
                            "RW": False,
                        },
                    ]
                )
            raise AssertionError("unexpected Docker inspection")
        return ""

    monkeypatch.setattr(host, "_run", fake_run)
    monkeypatch.setattr(
        host, "_create_key", lambda _image: commands.append(("key-volume", "create"))
    )
    monkeypatch.setattr(host, "_diagnostic_files", lambda _sha: None)

    with pytest.raises(ValueError):
        host.phase("apply", IMAGE, SOURCE_SHA, digest)

    assert "BOCA_DEPLOY_PASS" not in capsys.readouterr().out
    assert any(command[3] == field for command in commands if command[:2] == ("docker", "inspect"))
    assert [command[-2:] for command in commands if "stop" in command] == [("stop", "controller")]
    assert ("key-volume", "create") in commands
    assert not any("down" in command or "prune" in command for command in commands)
    assert not any(command[:3] == ("docker", "volume", "rm") for command in commands)


def healthy_diagnostic() -> DiagnosticSnapshot:
    return DiagnosticSnapshot(
        uid=10001,
        key_secure=True,
        mounts_secure=True,
        container_id="c" * 64,
        health="healthy",
        image_ref=IMAGE,
        revision=SOURCE_SHA,
        project="boca-socios",
        service="controller",
        user="10001:10001",
        runtime_mode="simulation",
        engine_mode="off",
        cpu_nano=500_000_000,
        memory_bytes=268_435_456,
        pids_limit=64,
        read_only=True,
        privileged=False,
        has_ports=False,
    )


def test_diagnostic_accepts_only_dormant_healthy_boca_controller() -> None:
    validate_diagnostic(healthy_diagnostic(), IMAGE, SOURCE_SHA)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("uid", 0),
        ("key_secure", False),
        ("mounts_secure", False),
        ("container_id", "unexpected"),
        ("health", "unhealthy"),
        ("image_ref", "other"),
        ("revision", "b" * 40),
        ("project", "other"),
        ("service", "worker"),
        ("user", "0:0"),
        ("runtime_mode", "live"),
        ("engine_mode", "on"),
        ("cpu_nano", 1_000_000_000),
        ("memory_bytes", 1_000_000_000),
        ("pids_limit", 1_000),
        ("read_only", False),
        ("privileged", True),
        ("has_ports", True),
    ],
)
def test_diagnostic_deviation_is_no_go(field: str, value: object) -> None:
    with pytest.raises(PreflightError):
        validate_diagnostic(replace(healthy_diagnostic(), **{field: value}), IMAGE, SOURCE_SHA)


@pytest.mark.parametrize(
    "key_mount",
    [
        {
            "Type": "volume",
            "Driver": "local",
            "Name": host.KEY_VOLUME,
            "Destination": "/run/secrets",
            "RW": True,
        },
        {
            "Type": "bind",
            "Driver": "local",
            "Name": host.KEY_VOLUME,
            "Destination": "/run/secrets",
            "RW": False,
        },
    ],
)
def test_diagnostic_rejects_writable_or_bind_key_before_in_container_probe(
    monkeypatch: pytest.MonkeyPatch, key_mount: dict[str, object]
) -> None:
    container = "c" * 64

    def fake_run(*args: str, env: dict[str, str] | None = None) -> str:
        if args[:2] == ("docker", "exec"):
            pytest.fail("key probe must not run for an unsafe mount")
        if "ps" in args:
            return container
        if args[:2] == ("docker", "inspect"):
            if args[3] == "{{json .Mounts}}":
                return json.dumps(
                    [
                        {
                            "Type": "volume",
                            "Driver": "local",
                            "Name": "boca-socios_boca_data",
                            "Destination": "/data",
                            "RW": True,
                        },
                        key_mount,
                    ]
                )
            if args[3] == "{{json .HostConfig}}":
                return json.dumps(GOOD_HOST_CONFIG)
            return "{}"
        raise AssertionError("unexpected Docker operation")

    monkeypatch.setattr(host, "_run", fake_run)
    with pytest.raises(PreflightError, match="mount|volume boundary"):
        host.collect_diagnostic(IMAGE, SOURCE_SHA)


@pytest.mark.parametrize("engine", ["off", "on"])
def test_diagnostic_phase_uses_only_read_only_boca_queries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    engine: str,
) -> None:
    digest = _staged(tmp_path, monkeypatch)
    monkeypatch.setattr(host, "_diagnostic_files", lambda _sha: None)
    monkeypatch.setattr(host, "collect_snapshot", lambda: pytest.fail("first-install path used"))
    monkeypatch.setattr(host.os, "getuid", lambda: 10001)
    commands: list[tuple[str, ...]] = []

    def fake_run(*args: str, env: dict[str, str] | None = None) -> str:
        commands.append(args)
        if args[0:2] == ("docker", "compose") and "ps" in args:
            return "c" * 64
        if args[0:3] == ("docker", "image", "inspect"):
            return json.dumps([IMAGE]) if "RepoDigests" in args[4] else SOURCE_SHA
        if args[0:2] == ("docker", "inspect"):
            match args[3]:
                case "{{json .Config}}":
                    return json.dumps(
                        {
                            "Image": IMAGE,
                            "User": "10001:10001",
                            "Labels": {
                                "com.docker.compose.project": "boca-socios",
                                "com.docker.compose.service": "controller",
                            },
                            "Env": [
                                "BOCA_ENVIRONMENT=staging",
                                "BOCA_DB_PATH=/data/boca.sqlite3",
                                "BOCA_MASTER_KEY_FILE=/run/secrets/boca_master_key",
                                "BOCA_RUNTIME_MODE=simulation",
                                f"BOCA_ENGINE_MODE={engine}",
                            ],
                        }
                    )
                case "{{json .HostConfig}}":
                    return json.dumps(
                        {
                            "NanoCpus": 500_000_000,
                            "Memory": 268_435_456,
                            "PidsLimit": 64,
                            "ReadonlyRootfs": True,
                            "Privileged": False,
                            "PortBindings": {},
                            "PublishAllPorts": False,
                        }
                    )
                case "{{json .Mounts}}":
                    return json.dumps(
                        [
                            {
                                "Type": "volume",
                                "Driver": "local",
                                "Name": "boca-socios_boca_data",
                                "Destination": "/data",
                                "RW": True,
                            },
                            {
                                "Type": "volume",
                                "Driver": "local",
                                "Name": host.KEY_VOLUME,
                                "Destination": "/run/secrets",
                                "RW": False,
                            },
                        ]
                    )
                case "{{.State.Health.Status}}":
                    return "healthy"
        if args[0:2] == ("docker", "exec"):
            return "BOCA_KEY_READY"
        raise AssertionError("unexpected host command")

    monkeypatch.setattr(host, "_run", fake_run)
    if engine == "off":
        host.phase("diagnostic", IMAGE, SOURCE_SHA, digest)
        assert "BOCA_DIAGNOSTIC_PASS" in capsys.readouterr().out
    else:
        with pytest.raises(PreflightError, match="engine mode"):
            host.phase("diagnostic", IMAGE, SOURCE_SHA, digest)
    assert commands
    assert all(command[0] == "docker" for command in commands)
    assert not any(
        token in command for command in commands for token in ("pull", "up", "stop", "rm")
    )


@pytest.mark.parametrize("mismatch", ["real_uid", "effective_uid", "effective_gid"])
def test_diagnostic_rejects_setid_before_private_metadata(
    monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    uid = 1000 if mismatch == "real_uid" else 10001
    monkeypatch.setattr(host.os, "getuid", lambda: uid)
    monkeypatch.setattr(host.os, "geteuid", lambda: 0 if mismatch == "effective_uid" else uid)
    monkeypatch.setattr(host.os, "getgid", lambda: 10001)
    monkeypatch.setattr(host.os, "getegid", lambda: 0 if mismatch == "effective_gid" else 10001)
    monkeypatch.setattr(host, "_safe_dir", lambda _path: pytest.fail("private path was read"))
    with pytest.raises(PreflightError, match="dedicated Boca identity"):
        host._diagnostic_files("c" * 64)


@pytest.mark.parametrize(
    "labels",
    [None, {"com.docker.compose.project": "other", "com.docker.compose.volume": "boca_key"}],
)
def test_diagnostic_rejects_missing_or_unowned_key_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, labels: object
) -> None:
    digest = _staged(tmp_path, monkeypatch)
    monkeypatch.setattr(host.os, "getuid", lambda: 10001)
    monkeypatch.setattr(host.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(host.os, "getgid", lambda: 10001)
    monkeypatch.setattr(host.os, "getegid", lambda: 10001)
    monkeypatch.setattr(
        host.pwd, "getpwuid", lambda _uid: type("Account", (), {"pw_name": "boca-deploy"})()
    )
    monkeypatch.setattr(
        host,
        "_run",
        lambda *args: json.dumps(
            {
                "Name": host.KEY_VOLUME,
                "Driver": "local",
                "Scope": "local",
                "Labels": labels,
            }
        ),
    )
    with pytest.raises(PreflightError, match="volume identity"):
        host._diagnostic_files(digest)
