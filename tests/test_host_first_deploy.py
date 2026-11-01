"""Host preflight and failure boundary are testable without Docker or SSH."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

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
    "NetworkMode": "boca-socios_boca_private",
    "CapDrop": ["ALL"],
    "CapAdd": None,
    "SecurityOpt": ["no-new-privileges:true"],
    "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=16m"},  # noqa: S108 - container tmpfs
    "CgroupnsMode": "private",
}

GOOD_NETWORK_SETTINGS = {
    "Networks": {"boca-socios_boca_private": {"NetworkID": "d" * 64}},
    "Ports": {},
}
GOOD_NETWORK_INSPECT = {
    "Id": "d" * 64,
    "Name": "boca-socios_boca_private",
    "Driver": "bridge",
    "Scope": "local",
    "Internal": False,
    "Attachable": False,
    "Ingress": False,
    "Labels": {
        "com.docker.compose.project": "boca-socios",
        "com.docker.compose.network": "boca_private",
    },
    "Containers": {"c" * 64: {}},
}
ROOTLESS_INFO = {
    "SecurityOptions": ["name=rootless"],
    "CgroupVersion": "2",
    "CgroupDriver": "systemd",
}

GOOD_CGROUP_RECEIPT = (
    '{"cpu_quota":50000,"cpu_period":100000,"memory_bytes":268435456,"pids_limit":64}'
)


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
        docker_disk_bytes=8 * 1024**3,
        docker_inodes=100_000,
        root_ready=True,
        boca_containers=False,
        boca_volume=False,
        boca_network=False,
    )


def test_first_deploy_preflight_passes_only_with_free_boca_namespace() -> None:
    validate_snapshot(safe_snapshot())


def test_read_only_preflight_needs_no_image_or_release_and_does_not_mutate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    digest = _staged(tmp_path, monkeypatch)
    host.COMPOSE.unlink()  # A preflight precedes staging on the host.
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: pytest.fail("Docker mutation"))
    host.phase("observe", "", SOURCE_SHA, digest)
    assert "BOCA_PREFLIGHT_PASS" in capsys.readouterr().out
    assert not (host.ROOT / "secrets").exists()


def test_observe_uses_only_bounded_read_only_docker_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _dedicated_test_identity(monkeypatch)
    root = tmp_path / "boca-socios"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(host, "ROOT", root)
    monkeypatch.setattr(host, "COMPOSE", root / "compose.yaml")
    # The storage path guard has separate path/backend tests below; keep this
    # regression focused on the actual Docker command inventory in observe.
    monkeypatch.setattr(host, "_checked_docker_storage_dir", lambda: root)
    monkeypatch.setattr(host, "_safe_dir", lambda _path: True)
    monkeypatch.setattr(host, "_rootless_socket_secure", lambda: True)
    monkeypatch.setattr(host, "_rootful_socket_inaccessible", lambda: True)
    controllers = tmp_path / "cgroup.controllers"
    controllers.write_text("cpu memory pids\n")
    monkeypatch.setattr(host, "CGROUP_CONTROLLERS", controllers)
    # Capacity thresholds are covered separately; retain the real collection
    # and daemon boundary while making this test independent of runner load.
    monkeypatch.setattr(host, "validate_snapshot", lambda _snapshot: None)
    allowed = {
        ("docker", "info", "--format", "{{json .}}"): json.dumps(
            {
                "SecurityOptions": ["name=rootless"],
                "CgroupVersion": "2",
                "CgroupDriver": "systemd",
            }
        ),
        ("docker", "version", "--format", "{{.Server.Version}}"): "27.0",
        ("docker", "compose", "version", "--short"): "2.0",
        ("docker", "compose", "up", "--help"): "--no-build --no-deps --wait",
        ("docker", "compose", "config", "--help"): "--format",
        (
            "docker",
            "ps",
            "-a",
            "-q",
            "--filter",
            "label=com.docker.compose.project=boca-socios",
        ): "",
        ("docker", "ps", "-a", "-q", "--filter", "name=^/boca-socios-"): "",
        ("docker", "volume", "ls", "-q", "--filter", "name=^boca-socios_"): "",
        ("docker", "network", "ls", "-q", "--filter", "name=^boca-socios_"): "",
    }
    observed: list[tuple[str, ...]] = []

    def read_only_docker(*args: str) -> str:
        assert args in allowed, f"unexpected Docker operation in read-only preflight: {args}"
        observed.append(args)
        return allowed[args]

    monkeypatch.setattr(host, "_run", read_only_docker)
    monkeypatch.setenv("BOCA_DEPLOY_SSH_KEY", "secret-sentinel")
    host.phase("observe", "", SOURCE_SHA, "c" * 64)
    output = capsys.readouterr().out
    assert "BOCA_PREFLIGHT_PASS" in output
    assert "secret-sentinel" not in output
    assert observed == list(allowed)
    assert list(root.iterdir()) == []


def test_prerequisite_inspection_refuses_uid_1000_before_private_path_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host.os, "getuid", lambda: 1000)
    monkeypatch.setattr(
        host, "_socket_state", lambda _path: pytest.fail("UID1000 probed Boca private path")
    )
    with pytest.raises(PreflightError, match="dedicated Boca identity"):
        host.phase("inspect-prerequisites", "", SOURCE_SHA, "b" * 64)


def test_prerequisite_inspection_refuses_elevated_effective_uid_before_private_path_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host.os, "getuid", lambda: 10001)
    monkeypatch.setattr(host.os, "geteuid", lambda: 0)
    monkeypatch.setattr(host.pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_name="boca-deploy"))
    monkeypatch.setattr(
        host, "_socket_state", lambda _path: pytest.fail("elevated process probed host socket")
    )
    monkeypatch.setattr(
        host, "_safe_dir", lambda _path: pytest.fail("elevated process probed runtime")
    )
    with pytest.raises(PreflightError, match="dedicated Boca identity"):
        host.phase("inspect-prerequisites", "", SOURCE_SHA, "b" * 64)


def test_rootless_boundary_refuses_elevated_effective_uid_before_docker_or_socket_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host.os, "getuid", lambda: 10001)
    monkeypatch.setattr(host.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        host, "_rootless_socket_secure", lambda: pytest.fail("elevated process probed socket")
    )
    monkeypatch.setattr(host, "_run", lambda *args: pytest.fail("elevated process ran Docker"))
    with pytest.raises(PreflightError, match="dedicated Boca identity"):
        host._validate_docker_boundary()


def test_rootless_boundary_refuses_changed_effective_group_before_socket_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _dedicated_test_identity(monkeypatch)
    monkeypatch.setattr(host.os, "getegid", lambda: 999)
    monkeypatch.setattr(
        host, "_rootless_socket_secure", lambda: pytest.fail("setgid process probed socket")
    )
    with pytest.raises(PreflightError, match="dedicated Boca identity"):
        host._validate_docker_boundary()


def test_socket_probe_distinguishes_present_absent_unsafe_and_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_dir = tmp_path / "private"
    private_dir.mkdir(mode=0o700)
    socket_path = private_dir / "bus"
    socket_path.touch()
    (private_dir / "link").symlink_to(socket_path)
    restricted = private_dir / "restricted"
    original_lstat = Path.lstat

    def fake_lstat(path: Path) -> os.stat_result | SimpleNamespace:
        if path == socket_path:
            return SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=os.getuid())
        if path == restricted:
            raise PermissionError("permission denied")
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    assert host._socket_state(socket_path, expected_uid=os.getuid()) == "owned"
    assert host._socket_state(private_dir / "missing", expected_uid=os.getuid()) == "absent"
    assert host._socket_state(private_dir / "link", expected_uid=os.getuid()) == "unsafe"
    assert host._socket_state(restricted, expected_uid=os.getuid()) == "unavailable"


def test_inspection_reports_unproven_rootless_without_docker_or_host_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _dedicated_test_identity(monkeypatch)
    monkeypatch.setattr(host, "_rootless_service_metadata", lambda _ready: "BOCA_ROOTLESS_SERVICE stub")
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setattr(host, "ROOTLESS_SOCKET", runtime / "docker.sock")
    monkeypatch.setattr(host, "PRIVATE_MANAGER_SOCKET", runtime / "systemd" / "private")
    monkeypatch.setattr(host, "USER_BUS_SOCKET", runtime / "bus")
    monkeypatch.setattr(host, "ROOTFUL_SOCKET", tmp_path / "rootful-absent")
    monkeypatch.setattr(host, "_safe_dir", lambda _path: True)
    controllers = tmp_path / "controllers"
    controllers.write_text("cpu memory pids\n")
    monkeypatch.setattr(host, "CGROUP_CONTROLLERS", controllers)
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: pytest.fail("Docker used"))
    with pytest.raises(PreflightError, match="metadata unproven"):
        host.phase("inspect-prerequisites", "", SOURCE_SHA, "b" * 64)
    report = capsys.readouterr().out
    assert "BOCA_HOST_INSPECT" in report
    assert "rootless=absent" in report
    assert "state=PREREQUISITES_UNPROVEN" in report


def test_inspection_under_boca_uid_reports_only_metadata_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _dedicated_test_identity(monkeypatch)
    monkeypatch.setattr(host, "_rootless_service_metadata", lambda _ready: "BOCA_ROOTLESS_SERVICE stub")
    runtime = tmp_path / "runtime"
    sockets = {runtime / "systemd" / "private", runtime / "bus", runtime / "docker.sock"}
    monkeypatch.setattr(host, "ROOTLESS_SOCKET", runtime / "docker.sock")
    monkeypatch.setattr(host, "PRIVATE_MANAGER_SOCKET", runtime / "systemd" / "private")
    monkeypatch.setattr(host, "USER_BUS_SOCKET", runtime / "bus")
    monkeypatch.setattr(host, "ROOTFUL_SOCKET", tmp_path / "rootful-absent")
    original_lstat = Path.lstat

    def boca_lstat(path: Path) -> os.stat_result | SimpleNamespace:
        if path == runtime:
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=10001)
        if path in sockets:
            return SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=10001)
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", boca_lstat)
    controllers = tmp_path / "controllers"
    controllers.write_text("cpu io memory pids\n")
    monkeypatch.setattr(host, "CGROUP_CONTROLLERS", controllers)
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: pytest.fail("Docker used"))
    monkeypatch.setenv("BOCA_DEPLOY_SSH_KEY", "secret-sentinel")
    host.phase("inspect-prerequisites", "", SOURCE_SHA, "b" * 64)
    report = capsys.readouterr().out
    assert "state=METADATA_CANDIDATE" in report
    assert "private=owned bus=owned rootless=owned" in report
    assert "rootful=absent controllers=cpu,memory,pids" in report
    assert "secret-sentinel" not in report
    assert str(runtime) not in report


def test_inspection_has_empty_image_contract_and_does_not_weaken_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host.os, "getuid", lambda: 10001)
    monkeypatch.setattr(host, "inspect_prerequisites", lambda: pytest.fail("probed host"))
    with pytest.raises(PreflightError, match="coordinates"):
        host.phase("inspect-prerequisites", IMAGE, SOURCE_SHA, "b" * 64)


def test_first_install_preflight_still_accepts_approved_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    digest = _staged(tmp_path, monkeypatch)
    host.COMPOSE.unlink()
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: pytest.fail("Docker mutation"))
    host.phase("preflight", IMAGE, SOURCE_SHA, digest)
    assert "BOCA_PREFLIGHT_PASS" in capsys.readouterr().out


def test_effectful_phase_still_requires_immutable_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    digest = _staged(tmp_path, monkeypatch)
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: pytest.fail("Docker mutation"))
    with pytest.raises(PreflightError, match="coordinates"):
        host.phase("apply", "", SOURCE_SHA, digest)


@pytest.mark.parametrize(("phase_name", "image"), [("observe", IMAGE), ("preflight", "")])
def test_host_preflight_modes_reject_swapped_image_contracts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase_name: str, image: str
) -> None:
    digest = _staged(tmp_path, monkeypatch)
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: pytest.fail("Docker mutation"))
    with pytest.raises(PreflightError, match="coordinates"):
        host.phase(phase_name, image, SOURCE_SHA, digest)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("arch", "aarch64"),
        ("uid", 0),
        ("available_memory_kib", 400_000),
        ("available_disk_bytes", 2 * 1024**3),
        ("available_inodes", 1_000),
        ("docker_disk_bytes", 2 * 1024**3),
        ("docker_inodes", 1_000),
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


@pytest.mark.parametrize("unsafe", ["outside", "symlink", "unowned", "writable", "missing"])
def test_docker_storage_path_must_be_boca_owned_under_private_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe: str
) -> None:
    home = tmp_path / "boca-home"
    home.mkdir(mode=0o700)
    storage = home / ".local" / "share" / "docker"
    storage.mkdir(parents=True)
    outside = tmp_path / "other-workload"
    outside.mkdir()
    if unsafe == "symlink":
        storage.rmdir()
        storage.symlink_to(outside, target_is_directory=True)
    if unsafe == "missing":
        storage.rmdir()
    if unsafe == "writable":
        storage.chmod(0o777)
    target = outside if unsafe == "outside" else storage
    monkeypatch.setattr(
        host.pwd,
        "getpwuid",
        lambda _uid: SimpleNamespace(pw_name="boca-deploy", pw_dir=str(home)),
    )
    monkeypatch.setattr(
        host,
        "_run",
        lambda *args: json.dumps(
            {
                **ROOTLESS_INFO,
                "DockerRootDir": str(target),
                "Driver": "overlay2",
                "DriverStatus": [],
            }
        ),
    )
    original_lstat = Path.lstat

    def boca_lstat(path: Path) -> os.stat_result | SimpleNamespace:
        result = original_lstat(path)
        if path == home or home in path.parents:
            uid = 0 if unsafe == "unowned" and path == storage else 10001
            return SimpleNamespace(st_mode=result.st_mode, st_uid=uid)
        return result

    monkeypatch.setattr(Path, "lstat", boca_lstat)
    with pytest.raises(PreflightError, match="rootless Docker storage"):
        host._checked_docker_storage_dir()


def test_owned_rootless_docker_storage_path_is_accepted_without_listing_other_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "boca-home"
    home.mkdir(mode=0o700)
    storage = home / ".local" / "share" / "docker"
    storage.mkdir(parents=True)
    monkeypatch.setattr(
        host.pwd,
        "getpwuid",
        lambda _uid: SimpleNamespace(pw_name="boca-deploy", pw_dir=str(home)),
    )
    monkeypatch.setattr(
        host,
        "_run",
        lambda *args: json.dumps(
            {
                **ROOTLESS_INFO,
                "DockerRootDir": str(storage),
                "Driver": "overlay2",
                "DriverStatus": [],
            }
        ),
    )
    original_lstat = Path.lstat
    inspected: list[Path] = []

    def boca_lstat(path: Path) -> os.stat_result | SimpleNamespace:
        inspected.append(path)
        result = original_lstat(path)
        if path == home or home in path.parents:
            return SimpleNamespace(st_mode=result.st_mode, st_uid=10001)
        return result

    monkeypatch.setattr(Path, "lstat", boca_lstat)
    assert host._checked_docker_storage_dir() == storage
    assert set(inspected) == {home, home / ".local", home / ".local" / "share", storage}


@pytest.mark.parametrize(
    "backend",
    [
        {"Driver": "overlayfs", "DriverStatus": [["driver-type", "io.containerd.snapshotter.v1"]]},
        {"Driver": "overlay2", "DriverStatus": [["driver-type", "io.containerd.snapshotter.v1"]]},
        {"Driver": "overlay2"},
    ],
)
def test_containerd_or_unknown_storage_backend_is_no_go_before_path_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: dict[str, object]
) -> None:
    monkeypatch.setattr(
        host,
        "_run",
        lambda *args: json.dumps({**ROOTLESS_INFO, "DockerRootDir": str(tmp_path), **backend}),
    )
    monkeypatch.setattr(host.pwd, "getpwuid", lambda _uid: pytest.fail("probed home"))
    with pytest.raises(PreflightError, match="storage backend"):
        host._checked_docker_storage_dir()


def test_changed_rootless_daemon_metadata_blocks_storage_before_path_probe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        host,
        "_run",
        lambda *args: json.dumps(
            {
                **ROOTLESS_INFO,
                "SecurityOptions": [],
                "DockerRootDir": str(tmp_path),
                "Driver": "overlay2",
                "DriverStatus": [],
            }
        ),
    )
    monkeypatch.setattr(host.pwd, "getpwuid", lambda _uid: pytest.fail("probed home"))
    with pytest.raises(PreflightError, match="boundary changed"):
        host._checked_docker_storage_identity()


def test_storage_snapshot_rechecks_daemon_before_private_staging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        host,
        "_validate_docker_boundary",
        lambda: (_ for _ in ()).throw(PreflightError("rootless daemon changed")),
    )
    monkeypatch.setattr(host, "_safe_dir", lambda _root: pytest.fail("private staging probed"))
    with pytest.raises(PreflightError, match="rootless daemon changed"):
        host._storage_snapshot()


def test_snapshot_measures_staging_and_rootless_docker_filesystems_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "boca-stage"
    root.mkdir()
    data_root = tmp_path / "boca-home" / ".local" / "share" / "docker"
    data_root.mkdir(parents=True)
    monkeypatch.setattr(host, "ROOT", root)
    monkeypatch.setattr(host, "_require_dedicated_identity", lambda: 10001)
    monkeypatch.setattr(host, "_root_ready", lambda: True)
    monkeypatch.setattr(host, "_checked_docker_storage_dir", lambda: data_root)
    monkeypatch.setattr(host.os, "sched_getaffinity", lambda _pid: {0})
    monkeypatch.setattr(host.os, "getloadavg", lambda: (0.0, 0.0, 0.0))

    def read_only_docker(*args: str) -> str:
        assert args[0] == "docker"
        if args[1:4] == ("compose", "up", "--help"):
            return "--no-build --no-deps --wait"
        if args[1:4] == ("compose", "config", "--help"):
            return "--format"
        return ""

    monkeypatch.setattr(host, "_run", read_only_docker)
    measured: list[Path] = []

    def capacity(path: str | Path) -> SimpleNamespace:
        measured.append(Path(path))
        gib = 8 if Path(path) == root else 2
        return SimpleNamespace(f_bavail=gib * 1024**3, f_frsize=1, f_favail=100_000)

    monkeypatch.setattr(host.os, "statvfs", capacity)
    snapshot = host.collect_snapshot()
    assert measured == [root, data_root]
    assert snapshot.available_disk_bytes == 8 * 1024**3
    assert snapshot.docker_disk_bytes == 2 * 1024**3
    with pytest.raises(PreflightError, match="storage"):
        validate_snapshot(snapshot)


def _staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    root = tmp_path / "boca-socios"
    root.mkdir(mode=0o700)
    compose = root / "compose.yaml"
    compose.write_text("name: boca-socios\n")
    monkeypatch.setattr(host, "ROOT", root)
    monkeypatch.setattr(host, "COMPOSE", compose)
    monkeypatch.setattr(host, "collect_snapshot", safe_snapshot)
    monkeypatch.setattr(host, "_storage_snapshot", safe_storage)
    monkeypatch.setattr(host, "_validate_docker_boundary", lambda: None)
    # The test may run with a different UID; all other staging checks remain real.
    monkeypatch.setattr(host, "_safe_dir", lambda _path: True)
    digest = hashlib.sha256(compose.read_bytes()).hexdigest()

    def verify_compose(expected: str) -> None:
        if hashlib.sha256(compose.read_bytes()).hexdigest() != expected:
            raise PreflightError("staged Compose SHA-256 differs from reviewed file")

    monkeypatch.setattr(host, "_verify_compose", verify_compose)
    return digest


def safe_storage() -> host.StorageSnapshot:
    return host.StorageSnapshot(
        docker_root=Path("/home/boca-deploy/.local/share/docker"),
        driver="overlay2",
        driver_status=(),
        stage_device=11,
        docker_device=12,
        stage_inode=111,
        docker_inode=222,
        socket_device=13,
        socket_inode=333,
        stage_free_bytes=8 * 1024**3,
        stage_inodes=100_000,
        docker_free_bytes=8 * 1024**3,
        docker_inodes=100_000,
    )


def _docker_root(tmp_path: Path) -> Path:
    root = tmp_path / "rootless-docker"
    (root / "volumes" / host.KEY_VOLUME / "_data").mkdir(parents=True)
    return root


@pytest.mark.parametrize(
    "phase_name",
    ["observe", "preflight", "stage", "config", "apply", "diagnostic-config", "diagnostic"],
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
        host.phase(phase_name, "" if phase_name == "observe" else IMAGE, SOURCE_SHA, digest)
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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stage_free_bytes", 3 * 1024**3),
        ("docker_free_bytes", 3 * 1024**3),
        ("stage_inodes", 49_999),
        ("docker_inodes", 49_999),
        ("docker_root", Path("/home/boca-deploy/other-store")),
        ("driver", "vfs"),
        ("driver_status", (("Backing Filesystem", "other"),)),
        ("stage_device", 99),
        ("docker_device", 99),
        ("stage_inode", 999),
        ("docker_inode", 999),
        ("socket_device", 99),
        ("socket_inode", 999),
    ],
)
def test_post_pull_capacity_or_store_drift_blocks_key_and_compose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    digest = _staged(tmp_path, monkeypatch)
    capacities = iter((safe_storage(), replace(safe_storage(), **{field: value})))
    monkeypatch.setattr(host, "_storage_snapshot", lambda: next(capacities))
    commands: list[tuple[str, ...]] = []

    def fake_run(*args: str, env: dict[str, str] | None = None) -> str:
        commands.append(args)
        if args[:3] == ("docker", "image", "inspect"):
            return json.dumps([IMAGE]) if "RepoDigests" in args[4] else SOURCE_SHA
        return ""

    monkeypatch.setattr(host, "_run", fake_run)
    monkeypatch.setattr(host, "_create_key", lambda _image: pytest.fail("key created"))
    with pytest.raises(PreflightError, match="storage|capacity"):
        host.phase("apply", IMAGE, SOURCE_SHA, digest)
    assert ("docker", "pull", IMAGE) in commands
    assert not any("up" in command for command in commands)
    assert not any("stop" in command for command in commands)


def test_post_pull_capacity_measurement_failure_blocks_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    digest = _staged(tmp_path, monkeypatch)
    attempts = 0

    def capacity() -> host.StorageSnapshot:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise PreflightError("Docker capacity unavailable")
        return safe_storage()

    monkeypatch.setattr(host, "_storage_snapshot", capacity)
    monkeypatch.setattr(
        host,
        "_run",
        lambda *args, **kwargs: (
            json.dumps([IMAGE])
            if args[:3] == ("docker", "image", "inspect") and "RepoDigests" in args[4]
            else SOURCE_SHA
            if args[:3] == ("docker", "image", "inspect")
            else ""
        ),
    )
    monkeypatch.setattr(host, "_create_key", lambda _image: pytest.fail("key created"))
    with pytest.raises(PreflightError, match="capacity unavailable"):
        host.phase("apply", IMAGE, SOURCE_SHA, digest)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("docker_inodes", 49_999),
        ("docker_device", 99),
        ("docker_inode", 999),
        ("socket_inode", 999),
        ("driver", "vfs"),
    ],
)
def test_final_capacity_or_topology_drift_stops_only_boca_after_postflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    field: str,
    value: object,
) -> None:
    digest = _staged(tmp_path, monkeypatch)
    capacities = iter((safe_storage(), safe_storage(), replace(safe_storage(), **{field: value})))
    monkeypatch.setattr(host, "_storage_snapshot", lambda: next(capacities))
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

    monkeypatch.setattr(host, "_run", fake_run)
    monkeypatch.setattr(host, "_create_key", lambda _image: commands.append(("key", "created")))
    monkeypatch.setattr(host, "_diagnostic_files", lambda _sha: None)
    monkeypatch.setattr(host, "collect_diagnostic", lambda _image, _sha: healthy_diagnostic())
    with pytest.raises(PreflightError, match="storage"):
        host.phase("apply", IMAGE, SOURCE_SHA, digest)
    assert ("key", "created") in commands
    assert [cmd[-2:] for cmd in commands if "stop" in cmd] == [("stop", "controller")]
    assert not any("down" in cmd or "prune" in cmd for cmd in commands)
    assert "BOCA_DEPLOY_PASS" not in capsys.readouterr().out


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
    init, verify = (command for command in commands if command[:2] == ("docker", "run"))
    assert init[-1] == "init" and verify[-1] == "verify"
    assert "--network" in init and init[init.index("--network") + 1] == "none"
    assert "CHOWN" in init and "CHOWN" not in verify
    assert "--user" in verify and verify[verify.index("--user") + 1] == "10001:10001"
    assert "readonly" in verify[verify.index("--mount") + 1]
    assert not any("bind" in value for command in commands for value in command)


def test_changed_key_volume_after_initialization_blocks_verify_and_preserves_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _docker_root(tmp_path)
    inspections = 0
    commands: list[tuple[str, ...]] = []

    def fake_run(*args: str) -> str:
        nonlocal inspections
        commands.append(args)
        if args[:3] == ("docker", "volume", "create"):
            return host.KEY_VOLUME
        if args[:3] == ("docker", "volume", "inspect"):
            inspections += 1
            return json.dumps(
                {
                    "Name": host.KEY_VOLUME,
                    "Driver": "local",
                    "Scope": "local",
                    "Labels": {
                        "com.docker.compose.project": "boca-socios",
                        "com.docker.compose.volume": "boca_key",
                    },
                    "Options": {} if inspections == 1 else {"type": "none", "o": "bind"},
                    "Mountpoint": str(root / "volumes" / host.KEY_VOLUME / "_data"),
                }
            )
        if args[:2] == ("docker", "info"):
            return str(root)
        if args[:2] == ("docker", "run") and args[-1] == "init":
            return "BOCA_KEY_READY"
        raise AssertionError("verify must not run after volume changed")

    monkeypatch.setattr(host, "_run", fake_run)
    with pytest.raises(PreflightError, match="volume identity"):
        host._create_key(IMAGE)
    assert inspections == 2
    assert not any(command[:3] == ("docker", "volume", "rm") for command in commands)


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


def test_failed_controller_stop_reports_uncertain_rollback_without_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
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
        if "stop" in args:
            raise PreflightError("simulated stop failure")
        return ""

    def fail_postflight(_image: str, _sha: str) -> DiagnosticSnapshot:
        raise PreflightError("engine on")

    monkeypatch.setattr(host, "_run", fake_run)
    monkeypatch.setattr(host, "_create_key", lambda _image: commands.append(("key", "created")))
    monkeypatch.setattr(host, "_diagnostic_files", lambda _sha: None)
    monkeypatch.setattr(host, "collect_diagnostic", fail_postflight)
    with pytest.raises(PreflightError, match="engine on"):
        host.phase("apply", IMAGE, SOURCE_SHA, digest)
    output = capsys.readouterr()
    assert "BOCA_DEPLOY_PASS" not in output.out
    assert "BOCA_ROLLBACK_UNVERIFIED" in output.err
    assert [command[-2:] for command in commands if "stop" in command] == [("stop", "controller")]
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
        ("{{json .HostConfig}}", json.dumps({**GOOD_HOST_CONFIG, "NetworkMode": "host"})),
        ("{{json .HostConfig}}", json.dumps({**GOOD_HOST_CONFIG, "CapDrop": []})),
        ("{{json .HostConfig}}", json.dumps({**GOOD_HOST_CONFIG, "SecurityOpt": []})),
        ("{{json .HostConfig}}", json.dumps({**GOOD_HOST_CONFIG, "Tmpfs": None})),
        ("{{json .HostConfig}}", json.dumps({**GOOD_HOST_CONFIG, "CgroupnsMode": "host"})),
        (
            "{{json .NetworkSettings}}",
            json.dumps({**GOOD_NETWORK_SETTINGS, "Networks": {"bridge": {}}}),
        ),
        (
            "{{json .NetworkSettings}}",
            json.dumps({**GOOD_NETWORK_SETTINGS, "Ports": {"80/tcp": []}}),
        ),
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
        if args[:3] == ("docker", "network", "inspect"):
            return json.dumps(GOOD_NETWORK_INSPECT)
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
            if args[3] == "{{json .NetworkSettings}}":
                return json.dumps(GOOD_NETWORK_SETTINGS)
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
        if args[:2] == ("docker", "exec"):
            return (
                "BOCA_KEY_READY"
                if any("key_custody" in arg for arg in args)
                else GOOD_CGROUP_RECEIPT
            )
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
        network_mode="boca-socios_boca_private",
        networks=frozenset({"boca-socios_boca_private"}),
        network_id="d" * 64,
        network_ports=False,
        cap_drop=("ALL",),
        cap_add=(),
        security_opt=("no-new-privileges:true",),
        tmpfs=(("/tmp", "rw,noexec,nosuid,size=16m"),),  # noqa: S108 - container tmpfs
        cgroupns_mode="private",
        cgroup=host.CgroupLimits(
            cpu_quota=50_000,
            cpu_period=100_000,
            memory_bytes=268_435_456,
            pids_limit=64,
        ),
    )


def test_diagnostic_accepts_only_dormant_healthy_boca_controller() -> None:
    validate_diagnostic(healthy_diagnostic(), IMAGE, SOURCE_SHA)


@pytest.mark.parametrize(
    "receipt",
    [
        "{}",
        '{"cpu_quota":"50000","cpu_period":100000,"memory_bytes":268435456,"pids_limit":64}',
        '{"cpu_quota":50000,"cpu_period":100000,"memory_bytes":268435456,"pids_limit":64,"extra":1}',
        "{" * 257,
    ],
)
def test_cgroup_receipt_refuses_malformed_or_unbounded_output(
    monkeypatch: pytest.MonkeyPatch, receipt: str
) -> None:
    monkeypatch.setattr(host, "_run", lambda *args: receipt)
    with pytest.raises(PreflightError, match="cgroup"):
        host._cgroup_limits("c" * 64)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Id", "e" * 64),
        ("Driver", "host"),
        ("Internal", True),
        ("Attachable", True),
        ("Labels", {}),
        ("Containers", {"c" * 64: {}, "e" * 64: {}}),
    ],
)
def test_foreign_or_reconfigured_boca_network_is_no_go(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    actual = {**GOOD_NETWORK_INSPECT, field: value}
    monkeypatch.setattr(host, "_run", lambda *args: json.dumps(actual))
    with pytest.raises(PreflightError, match="network"):
        host._validate_boca_network("c" * 64, "d" * 64)


def test_only_exact_boca_network_id_is_inspected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []

    def fake_run(*args: str) -> str:
        commands.append(args)
        return json.dumps(GOOD_NETWORK_INSPECT)

    monkeypatch.setattr(host, "_run", fake_run)
    host._validate_boca_network("c" * 64, "d" * 64)
    assert commands == [("docker", "network", "inspect", "--format", "{{json .}}", "d" * 64)]


def test_runner_smoke_probes_effective_runtime_in_disposable_container() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text()
    smoke = workflow.split("  pr-runtime-smoke:\n", 1)[1].split("  deploy:\n", 1)[0]
    assert "docker inspect --format '{{json .NetworkSettings}}' \"$container\"" in smoke
    assert "docker network inspect --format '{{json .}}' \"$network_id\"" in smoke
    assert 'n["Id"] == nid' in smoke
    assert (
        'docker exec --user 10001:10001 "$container" python -m boca_socios.runtime_probe' in smoke
    )
    assert smoke.index("docker compose -p boca-socios -f compose.yaml up") < smoke.index(
        "python -m boca_socios.runtime_probe"
    )


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
        ("network_mode", "host"),
        ("networks", frozenset({"bridge"})),
        ("network_id", "bad"),
        ("network_ports", True),
        ("cap_drop", ()),
        ("cap_add", ("SYS_ADMIN",)),
        ("security_opt", ()),
        ("tmpfs", (("/tmp", "rw,size=16m"),)),  # noqa: S108 - invalid container tmpfs
        ("cgroupns_mode", "host"),
        ("cgroupns_mode", []),
        ("cgroup", None),
        ("cgroup", host.CgroupLimits(0, 100_000, 268_435_456, 64)),
        ("cgroup", host.CgroupLimits(100_000, 100_000, 268_435_456, 64)),
        ("cgroup", host.CgroupLimits(50_000, 100_000, 0, 64)),
        ("cgroup", host.CgroupLimits(50_000, 100_000, 268_435_456, -1)),
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
            if args[3] == "{{json .NetworkSettings}}":
                return json.dumps(GOOD_NETWORK_SETTINGS)
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
        if args[:3] == ("docker", "network", "inspect"):
            return json.dumps(GOOD_NETWORK_INSPECT)
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
                    return json.dumps(GOOD_HOST_CONFIG)
                case "{{json .NetworkSettings}}":
                    return json.dumps(GOOD_NETWORK_SETTINGS)
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
            return (
                "BOCA_KEY_READY"
                if any("key_custody" in arg for arg in args)
                else GOOD_CGROUP_RECEIPT
            )
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
    _dedicated_test_identity(monkeypatch)
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
