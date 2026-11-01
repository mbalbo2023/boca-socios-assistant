"""A failed BETA deployment discards only verified, unused Boca artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from boca_socios import host_cleanup as cleanup

IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64
SHA = "b" * 40
CONTROLLER = "c" * 64
NETWORK = "boca-socios_boca_private"
VOLUMES = {"boca-socios_boca_owner", "boca-socios_boca_key", "boca-socios_boca_data"}


class FakeBetaDocker:
    def __init__(self) -> None:
        self.container = True
        self.running = False
        self.network = True
        self.image = True
        self.volumes = set(VOLUMES)
        self.mounts = [
            {"Type": "volume", "Name": "boca-socios_boca_data", "Destination": "/data", "RW": True},
            {
                "Type": "volume",
                "Name": "boca-socios_boca_key",
                "Destination": "/run/secrets",
                "RW": False,
            },
            {
                "Type": "volume",
                "Name": "boca-socios_boca_owner",
                "Destination": "/run/owner",
                "RW": False,
            },
        ]
        self.foreign_container = False
        self.network_peer = False
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> str:
        self.commands.append(args)
        if args[:3] == ("ps", "-a", "-q"):
            if self.foreign_container and len(args) == 4:
                return "f" * 64
            return CONTROLLER if self.container else ""
        if args[:2] == ("container", "inspect"):
            return json.dumps(
                {
                    "Id": CONTROLLER,
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
                    "HostConfig": {"NetworkMode": NETWORK},
                    "Mounts": self.mounts,
                    "State": {"Running": self.running, "Restarting": False},
                }
            )
        if args[:2] == ("container", "stop"):
            assert args[2:] == ("--time", "30", CONTROLLER)
            self.running = False
            return CONTROLLER
        if args[:2] == ("container", "rm"):
            assert args[2:] == (CONTROLLER,)
            assert not self.running
            self.container = False
            return CONTROLLER
        if args[:2] == ("volume", "ls"):
            return "\n".join(sorted(self.volumes))
        if args[:2] == ("network", "ls"):
            return NETWORK if self.network else ""
        if args[:2] == ("network", "inspect"):
            return json.dumps(
                {
                    "Name": NETWORK,
                    "Driver": "bridge",
                    "Labels": {
                        "com.docker.compose.project": "boca-socios",
                        "com.docker.compose.network": "boca_private",
                    },
                    "Containers": {"foreign": {}} if self.network_peer else {},
                }
            )
        if args[:2] == ("network", "rm"):
            assert args[2:] == (NETWORK,)
            self.network = False
            return NETWORK
        if args[:2] == ("image", "inspect"):
            if not self.image:
                raise cleanup.ImageAbsent("exact Boca image absent")
            return json.dumps(
                {
                    "Size": 128 * 1024**2,
                    "RepoDigests": [IMAGE],
                    "RepoTags": [],
                    "Config": {"Labels": {"org.opencontainers.image.revision": SHA}},
                }
            )
        if args[:2] == ("image", "rm"):
            assert args[2:] == ("--no-prune", IMAGE)
            self.image = False
            return IMAGE
        pytest.fail(f"unexpected Docker command {args}")


@pytest.fixture
def beta_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[FakeBetaDocker, Path, str]:
    root = tmp_path / "boca-socios"
    root.mkdir(mode=0o700)
    stage = root / "compose.beta.yaml"
    stage.write_text("name: boca-socios\n")
    compose_sha = hashlib.sha256(stage.read_bytes()).hexdigest()
    monkeypatch.setattr(cleanup, "ROOT", root)
    monkeypatch.setattr(cleanup, "BETA_COMPOSE", stage, raising=False)
    original_lstat = Path.lstat

    def owned_lstat(path: Path) -> os.stat_result | SimpleNamespace:
        metadata = original_lstat(path)
        if path in {root, stage}:
            return SimpleNamespace(st_mode=metadata.st_mode, st_uid=10001, st_size=metadata.st_size)
        return metadata

    monkeypatch.setattr(Path, "lstat", owned_lstat)
    monkeypatch.setattr(cleanup, "_check_identity", lambda: None)
    monkeypatch.setattr(cleanup, "_check_rootless_boundary", lambda: None)
    monkeypatch.setattr(
        cleanup,
        "_capacity",
        lambda: cleanup.CapacitySnapshot(
            docker_root=tmp_path / "docker",
            stage_device=1,
            docker_device=2,
            stage_free_bytes=4096 * 1024**2,
            docker_free_bytes=4096 * 1024**2,
            stage_inodes=100000,
            docker_inodes=90000,
        ),
    )
    fake = FakeBetaDocker()
    monkeypatch.setattr(cleanup, "_run", fake)
    return fake, stage, compose_sha


@pytest.mark.parametrize("initially_running", [False, True])
def test_failed_beta_discards_only_exact_staging_and_unused_docker_objects(
    beta_case: tuple[FakeBetaDocker, Path, str],
    capsys: pytest.CaptureFixture[str],
    initially_running: bool,
) -> None:
    docker, stage, compose_sha = beta_case
    docker.running = initially_running
    result = cleanup.clean_failed_beta_install(IMAGE, SHA, compose_sha)
    assert result.removed_container and result.removed_network
    assert result.removed_image and result.removed_stage
    assert not stage.exists()
    assert docker.volumes == VOLUMES
    assert all("prune" not in command and "down" not in command for command in docker.commands)
    assert not any(command[:2] == ("volume", "rm") for command in docker.commands)
    if initially_running:
        assert ("container", "stop", "--time", "30", CONTROLLER) in docker.commands
    receipt = capsys.readouterr().out
    assert "BOCA_BETA_CLEANUP state=CLEANED" in receipt
    assert "volumes=preserved" in receipt


@pytest.mark.parametrize("change", ["foreign", "mount", "network-peer", "volume"])
def test_uncertain_beta_identity_does_not_delete_anything(
    beta_case: tuple[FakeBetaDocker, Path, str], change: str
) -> None:
    docker, stage, compose_sha = beta_case
    if change == "foreign":
        docker.foreign_container = True
    elif change == "mount":
        docker.mounts[0]["Name"] = "another_project_data"
    elif change == "network-peer":
        docker.network_peer = True
    else:
        docker.volumes.add("boca-socios_unknown")
    with pytest.raises(cleanup.CleanupError):
        cleanup.clean_failed_beta_install(IMAGE, SHA, compose_sha)
    assert docker.container and docker.image and docker.network and stage.exists()
    assert not any(
        command[:2] in {("container", "rm"), ("network", "rm"), ("image", "rm")}
        for command in docker.commands
    )


def test_failed_beta_cleanup_is_idempotent_after_preserving_volumes(
    beta_case: tuple[FakeBetaDocker, Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    docker, stage, compose_sha = beta_case
    stage.unlink()
    docker.container = docker.network = docker.image = False
    result = cleanup.clean_failed_beta_install(IMAGE, SHA, compose_sha)
    assert not any(
        (
            result.removed_container,
            result.removed_network,
            result.removed_image,
            result.removed_stage,
        )
    )
    assert "state=ALREADY_CLEAN" in capsys.readouterr().out
    assert docker.volumes == VOLUMES


def test_failed_beta_cleanup_becomes_indeterminate_after_partial_removal(
    beta_case: tuple[FakeBetaDocker, Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    docker, stage, compose_sha = beta_case
    original = docker.__call__

    def broken(*args: str) -> str:
        if args[:2] == ("network", "rm"):
            raise cleanup.CleanupError("network removal failed")
        return original(*args)

    monkeypatch.setattr(cleanup, "_run", broken)
    with pytest.raises(cleanup.CleanupIndeterminate):
        cleanup.clean_failed_beta_install(IMAGE, SHA, compose_sha)
    assert not docker.container and docker.image and stage.exists()
    assert docker.volumes == VOLUMES


def test_failed_beta_cleanup_rejects_untrusted_compose_without_mutation(
    beta_case: tuple[FakeBetaDocker, Path, str],
) -> None:
    docker, stage, compose_sha = beta_case
    stage.write_text("changed\n")
    with pytest.raises(cleanup.CleanupError):
        cleanup.clean_failed_beta_install(IMAGE, SHA, compose_sha)
    assert not any(
        command[:2] in {("container", "rm"), ("network", "rm"), ("image", "rm")}
        for command in docker.commands
    )


def test_beta_cleanup_rejects_symlink_stage_even_when_target_hash_matches(
    beta_case: tuple[FakeBetaDocker, Path, str], tmp_path: Path
) -> None:
    docker, stage, compose_sha = beta_case
    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_text("name: boca-socios\n")
    stage.unlink()
    stage.symlink_to(elsewhere)
    with pytest.raises(cleanup.CleanupError, match="BETA staged Compose identity"):
        cleanup.clean_failed_beta_install(IMAGE, SHA, compose_sha)
    assert elsewhere.read_text() == "name: boca-socios\n"
    assert docker.container and docker.image and docker.network


def test_beta_cleanup_rejects_extra_file_in_private_staging_directory(
    beta_case: tuple[FakeBetaDocker, Path, str]
) -> None:
    docker, stage, compose_sha = beta_case
    (stage.parent / "unrecognized.txt").write_text("unreviewed artifact")
    with pytest.raises(cleanup.CleanupError, match="uncertain state"):
        cleanup.clean_failed_beta_install(IMAGE, SHA, compose_sha)
    assert docker.container and docker.image and docker.network


def test_beta_cleanup_rejects_wrong_controller_revision_before_mutation(
    beta_case: tuple[FakeBetaDocker, Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    docker, stage, compose_sha = beta_case
    original = docker.__call__

    def wrong_revision(*args: str) -> str:
        response = original(*args)
        if args[:2] == ("container", "inspect"):
            record = json.loads(response)
            record["Config"]["Labels"]["org.opencontainers.image.revision"] = "f" * 40
            return json.dumps(record)
        return response

    monkeypatch.setattr(cleanup, "_run", wrong_revision)
    with pytest.raises(cleanup.CleanupError, match="controller identity"):
        cleanup.clean_failed_beta_install(IMAGE, SHA, compose_sha)
    assert docker.container and docker.image and docker.network and stage.exists()
    assert not any(command[:2] == ("container", "rm") for command in docker.commands)


def test_beta_cleanup_failed_stop_is_indeterminate_and_keeps_volumes(
    beta_case: tuple[FakeBetaDocker, Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    docker, stage, compose_sha = beta_case
    docker.running = True
    original = docker.__call__

    def failed_stop(*args: str) -> str:
        if args[:2] == ("container", "stop"):
            raise cleanup.CleanupError("controller stop failed")
        return original(*args)

    monkeypatch.setattr(cleanup, "_run", failed_stop)
    with pytest.raises(cleanup.CleanupIndeterminate):
        cleanup.clean_failed_beta_install(IMAGE, SHA, compose_sha)
    assert docker.container and docker.image and docker.network and stage.exists()
    assert docker.volumes == VOLUMES


def test_beta_cleanup_detects_volume_inventory_drift_after_mutation(
    beta_case: tuple[FakeBetaDocker, Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    docker, stage, compose_sha = beta_case
    original = docker.__call__
    volume_queries = 0

    def drifting_volumes(*args: str) -> str:
        nonlocal volume_queries
        if args[:2] == ("volume", "ls"):
            volume_queries += 1
            if volume_queries > 1:
                return "boca-socios_boca_owner"
        return original(*args)

    monkeypatch.setattr(cleanup, "_run", drifting_volumes)
    with pytest.raises(cleanup.CleanupIndeterminate):
        cleanup.clean_failed_beta_install(IMAGE, SHA, compose_sha)
    assert docker.volumes == VOLUMES


def test_beta_cli_dispatch_preserves_existing_first_install_route(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(cleanup, "clean_failed_beta_install", lambda *_: seen.append("beta"))
    monkeypatch.setattr(cleanup, "clean_failed_install", lambda *_: seen.append("first"))
    assert cleanup.main(["--beta", IMAGE, SHA, "c" * 64]) == 0
    assert cleanup.main([IMAGE, SHA, "c" * 64]) == 0
    assert seen == ["beta", "first"]


def test_actions_beta_cleanup_is_immediate_after_bounded_stop() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text()
    rollback = workflow.index("Stop only positively identified Boca BETA controller on failure")
    cleanup_step = workflow.index("Clean unused Boca BETA artifacts after failed install")
    next_step = workflow.index("Recheck current main before BETA acceptance")
    assert rollback < cleanup_step < next_step
    section = workflow[cleanup_step:next_step]
    assert "failure() && inputs.operation == 'beta-install'" in section
    assert "steps.boca_beta_stage_attempt.outputs.started == 'true'" in section
    assert "src/boca_socios/host_cleanup.py" in section
    assert "--beta" in section
    assert "2>/dev/null" in section
    assert "NO_GO INDETERMINADO" in section


@pytest.mark.parametrize("successful", [False, True])
def test_actions_beta_cleanup_redacts_remote_output_and_preserves_failure(
    tmp_path: Path, successful: bool
) -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text()
    start = workflow.index("      - name: Clean unused Boca BETA artifacts after failed install")
    section = workflow[start : workflow.index("      - name:", start + 10)]
    script = textwrap.dedent(section.split("        run: |\n", 1)[1])
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_ssh = bin_dir / "ssh"
    fake_ssh.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$FAKE_SSH_STDOUT"\n'
        'printf "%s\\n" "$FAKE_SSH_STDERR" >&2\nexit "$FAKE_SSH_RC"\n'
    )
    fake_ssh.chmod(0o700)
    (tmp_path / "boca-beta-compose.sha").write_text("c" * 64)
    summary = tmp_path / "summary.md"
    env = dict(os.environ)
    env.update(
        {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(summary),
            "BOCA_IMAGE_REF": IMAGE,
            "BOCA_SOURCE_SHA": SHA,
            "FAKE_SSH_RC": "0" if successful else "23",
            "FAKE_SSH_STDOUT": (
                "BOCA_BETA_CLEANUP state=CLEANED container=removed network=removed "
                "image=removed stage=removed volumes=preserved image_logical_mib=128 "
                "same_fs=no stage_free_mib_before=4096 stage_free_mib_after=4097 "
                "docker_free_mib_before=4096 docker_free_mib_after=4230 "
                "stage_inodes_before=100000 stage_inodes_after=100001 "
                "docker_inodes_before=90000 docker_inodes_after=90002"
                if successful
                else "host=1.2.3.4 token=NEVER"
            ),
            "FAKE_SSH_STDERR": "host=1.2.3.4 token=NEVER",
        }
    )
    completed = subprocess.run(  # noqa: S603 - fixed test fixture shell
        ["/usr/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert completed.returncode == 0
    receipt = summary.read_text()
    assert "original failure remains NO_GO" in receipt
    assert ("state=CLEANED" in receipt) is successful
    if not successful:
        assert "INDETERMINADO" in receipt
    assert "token=NEVER" not in receipt + completed.stdout + completed.stderr
    assert "host=1.2.3.4" not in receipt + completed.stdout + completed.stderr
