"""Host preflight and failure boundary are testable without Docker or SSH."""

import base64
import hashlib
import json
import stat
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host
from boca_socios.host_first_deploy import (
    DiagnosticSnapshot,
    HostSnapshot,
    PreflightError,
    validate_diagnostic,
    validate_snapshot,
)

SOURCE_SHA = "a" * 40
IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64


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
    monkeypatch.setattr(host, "SECRET_DIR", root / "secrets")
    monkeypatch.setattr(host, "KEY", root / "secrets/master.key")
    monkeypatch.setattr(host, "collect_snapshot", safe_snapshot)
    # The test may run with a different UID; all other staging checks remain real.
    monkeypatch.setattr(host, "_safe_dir", lambda _path: True)
    digest = hashlib.sha256(compose.read_bytes()).hexdigest()

    def verify_compose(expected: str) -> None:
        if hashlib.sha256(compose.read_bytes()).hexdigest() != expected:
            raise PreflightError("staged Compose SHA-256 differs from reviewed file")

    monkeypatch.setattr(host, "_verify_compose", verify_compose)
    return digest


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
    assert not host.KEY.exists()
    assert not any("up" in command for command in commands)


def test_failed_start_stops_only_controller_and_preserves_owner_only_key(
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
    with pytest.raises(PreflightError, match="unhealthy"):
        host.phase("apply", IMAGE, SOURCE_SHA, digest)
    assert [command[-2:] for command in commands if "stop" in command] == [("stop", "controller")]
    assert len(base64.b64decode(host.KEY.read_bytes().strip(), validate=True)) == 32
    assert stat.S_IMODE(host.KEY.stat().st_mode) == 0o400
    assert not host._root_ready()  # A failed first install cannot retry over its retained key.
    assert not any("down" in command or "prune" in command for command in commands)


def healthy_diagnostic() -> DiagnosticSnapshot:
    return DiagnosticSnapshot(
        uid=10001,
        key_secure=True,
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
                        }
                    )
                case "{{.State.Health.Status}}":
                    return "healthy"
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


@pytest.mark.parametrize("symlink", [False, True])
def test_diagnostic_rejects_missing_or_symlinked_key_without_reading_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, symlink: bool
) -> None:
    digest = _staged(tmp_path, monkeypatch)
    host.SECRET_DIR.mkdir(mode=0o700)
    if symlink:
        host.KEY.symlink_to(tmp_path / "outside")
    monkeypatch.setattr(host.os, "getuid", lambda: 10001)
    monkeypatch.setattr(
        host.pwd, "getpwuid", lambda _uid: type("Account", (), {"pw_name": "boca-deploy"})()
    )
    with pytest.raises(PreflightError):
        host._diagnostic_files(digest)
