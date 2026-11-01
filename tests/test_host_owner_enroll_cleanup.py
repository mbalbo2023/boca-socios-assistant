"""Boca-only immediate cleanup after one-use Chrome owner enrollment."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from boca_socios import host_cleanup as cleanup

IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64
SHA = "b" * 40
COMPOSE_SHA = "c" * 64
CAPABILITY_SHA = hashlib.sha256(b"synthetic-opaque-test-capability").hexdigest()
CONTAINER_ID = "d" * 64


class FakeEnrollDocker:
    def __init__(self, volume_dir: Path) -> None:
        self.container = True
        self.running = True
        self.network = True
        self.image = True
        self.volumes = {cleanup.OWNER_VOLUME, cleanup.ENROLL_VOLUME}
        self.volume_dir = volume_dir
        self.foreign_container = False
        self.foreign_peer = False
        self.wrong_mount = False
        self.wrong_volume_label = False
        self.stopped_ports_cleared = False
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> str:
        self.commands.append(args)
        if args[:3] == ("ps", "-a", "-q"):
            if self.foreign_container and len(args) == 4:
                return "e" * 64
            if (
                any("label=com.docker.compose.project" in x for x in args)
                and self.foreign_container
            ):
                return CONTAINER_ID if self.container else ""
            if any("name=^/boca-socios-owner-enroll-1" in x for x in args):
                return CONTAINER_ID if self.container else ""
            return CONTAINER_ID if self.container else ""
        if args[:2] == ("container", "inspect"):
            return json.dumps(
                {
                    "Id": CONTAINER_ID,
                    "Name": "/" + cleanup.ENROLL_CONTAINER,
                    "Config": {
                        "Image": IMAGE,
                        "User": "10001:10001",
                        "Labels": {
                            "com.docker.compose.project": "boca-socios",
                            "com.docker.compose.service": "owner-enroll",
                            "org.opencontainers.image.revision": SHA,
                        },
                        "Cmd": [
                            "python",
                            "-m",
                            "boca_socios.owner_enrollment",
                            "synthetic-owner",
                            CAPABILITY_SHA,
                            "A" * 43,
                            "b" * 64,
                        ],
                    },
                    "HostConfig": {
                        "NetworkMode": cleanup.ENROLL_NETWORK,
                        "PortBindings": {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]},
                        "ReadonlyRootfs": True,
                        "Privileged": False,
                        "CapDrop": ["ALL"],
                        "CapAdd": None,
                        "Memory": 128 * 1024**2,
                        "NanoCpus": 500_000_000,
                        "PidsLimit": 32,
                        "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
                    },
                    "Mounts": [
                        {
                            "Type": "volume",
                            "Name": cleanup.ENROLL_VOLUME
                            if not self.wrong_mount
                            else "foreign_project_volume",
                            "Destination": "/run/enrollment",
                            "RW": True,
                        }
                    ],
                    "NetworkSettings": {
                        "Ports": {}
                        if self.stopped_ports_cleared and not self.running
                        else {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]},
                        "Networks": {cleanup.ENROLL_NETWORK: {"NetworkID": "f" * 64}},
                    },
                    "State": {"Running": self.running, "Restarting": False},
                }
            )
        if args[:2] == ("container", "stop"):
            assert args == ("container", "stop", "--time", "15", CONTAINER_ID)
            self.running = False
            return CONTAINER_ID
        if args[:2] == ("container", "rm"):
            assert args == ("container", "rm", CONTAINER_ID) and not self.running
            self.container = False
            return CONTAINER_ID
        if args[:2] == ("network", "ls"):
            return cleanup.ENROLL_NETWORK if self.network else ""
        if args[:2] == ("network", "inspect"):
            return json.dumps(
                {
                    "Id": "f" * 64,
                    "Name": cleanup.ENROLL_NETWORK,
                    "Driver": "bridge",
                    "Internal": True,
                    "Labels": {
                        "com.docker.compose.project": "boca-socios",
                        "com.docker.compose.network": "owner_enroll_private",
                    },
                    "Containers": {"foreign": {}}
                    if self.foreign_peer
                    else ({CONTAINER_ID: {}} if self.container and self.running else {}),
                }
            )
        if args[:2] == ("network", "rm"):
            assert args == ("network", "rm", cleanup.ENROLL_NETWORK)
            self.network = False
            return cleanup.ENROLL_NETWORK
        if args[:2] == ("volume", "ls"):
            return "\n".join(sorted(self.volumes))
        if args[:2] == ("volume", "inspect"):
            return json.dumps(
                {
                    "Name": cleanup.ENROLL_VOLUME,
                    "Driver": "local",
                    "Scope": "local",
                    "Options": None,
                    "Mountpoint": str(self.volume_dir),
                    "Labels": {
                        "com.docker.compose.project": "boca-socios",
                        "com.docker.compose.volume": "foreign"
                        if self.wrong_volume_label
                        else "owner_enroll_staging",
                    },
                }
            )
        if args[:2] == ("volume", "rm"):
            assert args == ("volume", "rm", cleanup.ENROLL_VOLUME)
            assert not self.container
            self.volumes.remove(cleanup.ENROLL_VOLUME)
            return cleanup.ENROLL_VOLUME
        if args[:2] == ("image", "inspect"):
            if not self.image:
                raise cleanup.ImageAbsent("not present")
            return json.dumps(
                {
                    "Size": 105 * 1024**2,
                    "RepoDigests": [IMAGE],
                    "RepoTags": [],
                    "Config": {"Labels": {"org.opencontainers.image.revision": SHA}},
                }
            )
        if args[:2] == ("image", "rm"):
            assert args == ("image", "rm", "--no-prune", IMAGE)
            self.image = False
            return IMAGE
        pytest.fail(f"unexpected Docker query {args}")


@pytest.fixture
def enroll_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[FakeEnrollDocker, Path, Path]:
    root = tmp_path / "boca-socios"
    root.mkdir(mode=0o700)
    volume_root = tmp_path / "docker"
    stage = volume_root / "volumes" / cleanup.ENROLL_VOLUME / "_data"
    stage.mkdir(parents=True, mode=0o700)
    marker = root / "owner-enroll-attempt.json"
    marker.write_text(
        json.dumps(
            {
                "image": IMAGE,
                "source_sha": SHA,
                "compose_sha": COMPOSE_SHA,
                "capability_sha256": CAPABILITY_SHA,
                "image_preexisting": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="ascii",
    )
    marker.chmod(0o400)
    monkeypatch.setattr(cleanup, "ROOT", root)
    monkeypatch.setattr(cleanup, "ENROLL_MARKER", marker)
    original_lstat = Path.lstat

    def owned_lstat(path: Path) -> os.stat_result | SimpleNamespace:
        metadata = original_lstat(path)
        if path in {root, marker}:
            return SimpleNamespace(
                st_mode=metadata.st_mode,
                st_uid=10001,
                st_gid=10001,
                st_nlink=1,
                st_size=metadata.st_size,
                st_dev=metadata.st_dev,
            )
        return metadata

    monkeypatch.setattr(Path, "lstat", owned_lstat)
    monkeypatch.setattr(cleanup, "_check_identity", lambda: None)
    monkeypatch.setattr(cleanup, "_check_rootless_boundary", lambda: None)
    monkeypatch.setattr(cleanup, "_checked_docker_storage_dir", lambda: volume_root)
    monkeypatch.setattr(
        cleanup,
        "_capacity",
        lambda: cleanup.CapacitySnapshot(
            docker_root=volume_root,
            stage_device=1,
            docker_device=2,
            stage_free_bytes=5 * 1024**3,
            docker_free_bytes=5 * 1024**3,
            stage_inodes=100000,
            docker_inodes=110000,
        ),
    )
    fake = FakeEnrollDocker(stage)
    monkeypatch.setattr(cleanup, "_run", fake)
    return fake, stage, marker


def test_enrollment_cleanup_removes_only_proven_disposable_artifacts(
    enroll_case: tuple[FakeEnrollDocker, Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    docker, _stage, marker = enroll_case
    result = cleanup.clean_owner_enroll_artifacts(IMAGE, SHA, COMPOSE_SHA)
    assert result.removed_container and result.removed_network
    assert result.removed_image and result.removed_stage
    assert not marker.exists()
    assert docker.volumes == {cleanup.OWNER_VOLUME}
    assert all("prune" not in cmd and "down" not in cmd for cmd in docker.commands)
    assert all(
        cmd == ("volume", "rm", cleanup.ENROLL_VOLUME)
        for cmd in docker.commands
        if cmd[:2] == ("volume", "rm")
    )
    assert docker.commands.index(("container", "stop", "--time", "15", CONTAINER_ID)) < (
        docker.commands.index(("container", "rm", CONTAINER_ID))
    )
    assert ("volume", "rm", cleanup.ENROLL_VOLUME) in docker.commands
    assert "BOCA_OWNER_ENROLL_CLEANUP state=CLEANED" in capsys.readouterr().out


@pytest.mark.parametrize(
    "unsafe", ["foreign-container", "foreign-peer", "mount", "volume", "stage-label", "marker"]
)
def test_enrollment_cleanup_rejects_uncertain_provenance_without_deletion(
    enroll_case: tuple[FakeEnrollDocker, Path, Path], unsafe: str
) -> None:
    docker, stage, marker = enroll_case
    if unsafe == "foreign-container":
        docker.foreign_container = True
    elif unsafe == "foreign-peer":
        docker.foreign_peer = True
    elif unsafe == "mount":
        docker.wrong_mount = True
    elif unsafe == "volume":
        docker.volumes.add("foreign_boca_volume")
    elif unsafe == "stage-label":
        docker.wrong_volume_label = True
    else:
        marker.chmod(0o644)
    with pytest.raises(cleanup.CleanupError):
        cleanup.clean_owner_enroll_artifacts(IMAGE, SHA, COMPOSE_SHA)
    assert docker.container and docker.network and docker.image
    assert cleanup.ENROLL_VOLUME in docker.volumes and marker.exists()
    assert not any(
        cmd[:2] in {("container", "stop"), ("container", "rm"), ("network", "rm"), ("image", "rm")}
        for cmd in docker.commands
    )


def test_enrollment_cleanup_keeps_preexisting_digest_image(
    enroll_case: tuple[FakeEnrollDocker, Path, Path],
) -> None:
    docker, _stage, marker = enroll_case
    record = json.loads(marker.read_text())
    record["image_preexisting"] = True
    marker.chmod(0o600)
    marker.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")))
    marker.chmod(0o400)
    result = cleanup.clean_owner_enroll_artifacts(IMAGE, SHA, COMPOSE_SHA)
    assert not result.removed_image and docker.image
    assert not any(cmd[:2] == ("image", "rm") for cmd in docker.commands)


def test_enrollment_cleanup_accepts_stopped_publish_map_and_private_marker(
    enroll_case: tuple[FakeEnrollDocker, Path, Path],
) -> None:
    docker, _stage, marker = enroll_case
    docker.running = False
    docker.stopped_ports_cleared = True
    marker.chmod(0o600)  # A marker awaiting fchmod remains private and canonical.
    result = cleanup.clean_owner_enroll_artifacts(IMAGE, SHA, COMPOSE_SHA)
    assert result.removed_container and result.removed_stage
    assert cleanup.ENROLL_VOLUME not in docker.volumes and not marker.exists()


def test_enrollment_cleanup_is_idempotent_after_success(
    enroll_case: tuple[FakeEnrollDocker, Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    docker, _stage, _marker = enroll_case
    cleanup.clean_owner_enroll_artifacts(IMAGE, SHA, COMPOSE_SHA)
    result = cleanup.clean_owner_enroll_artifacts(IMAGE, SHA, COMPOSE_SHA)
    assert not any((result.removed_container, result.removed_network, result.removed_stage))
    assert "state=ALREADY_CLEAN" in capsys.readouterr().out


def test_enrollment_cleanup_partial_network_failure_is_indeterminate(
    enroll_case: tuple[FakeEnrollDocker, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    docker, stage, marker = enroll_case
    original = docker.__call__

    def broken(*args: str) -> str:
        if args[:2] == ("network", "rm"):
            raise cleanup.CleanupError("simulated Docker outage")
        return original(*args)

    monkeypatch.setattr(cleanup, "_run", broken)
    with pytest.raises(cleanup.CleanupIndeterminate):
        cleanup.clean_owner_enroll_artifacts(IMAGE, SHA, COMPOSE_SHA)
    assert not docker.container and docker.network and marker.exists()
    assert docker.volumes == {cleanup.OWNER_VOLUME, cleanup.ENROLL_VOLUME}


def test_enrollment_cleanup_rejects_redirected_named_staging_mountpoint(
    enroll_case: tuple[FakeEnrollDocker, Path, Path], tmp_path: Path
) -> None:
    docker, stage, marker = enroll_case
    foreign = tmp_path / "foreign"
    stage.rename(foreign)
    stage.symlink_to(foreign, target_is_directory=True)
    with pytest.raises(cleanup.CleanupError):
        cleanup.clean_owner_enroll_artifacts(IMAGE, SHA, COMPOSE_SHA)
    assert foreign.is_dir() and marker.exists() and docker.container


def test_enrollment_cleanup_cli_does_not_change_beta_path(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cleanup, "clean_owner_enroll_artifacts", lambda *_: calls.append("enroll"))
    monkeypatch.setattr(cleanup, "clean_failed_beta_install", lambda *_: calls.append("beta"))
    monkeypatch.setattr(cleanup, "clean_failed_install", lambda *_: calls.append("first"))
    assert cleanup.main(["--enroll", IMAGE, SHA, COMPOSE_SHA]) == 0
    assert cleanup.main(["--beta", IMAGE, SHA, COMPOSE_SHA]) == 0
    assert cleanup.main([IMAGE, SHA, COMPOSE_SHA]) == 0
    assert calls == ["enroll", "beta", "first"]
