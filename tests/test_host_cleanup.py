"""Failed first-install cleanup must never cross the Boca ownership boundary."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from boca_socios import host_cleanup as cleanup

IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64
SOURCE_SHA = "b" * 40


def test_uid_1000_is_rejected_before_docker_or_private_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cleanup.os, "getuid", lambda: 1000)
    monkeypatch.setattr(cleanup, "_run", lambda *args: pytest.fail("Docker called"))
    monkeypatch.setattr(cleanup, "_check_rootless_boundary", lambda: pytest.fail("private probe"))
    with pytest.raises(cleanup.CleanupError, match="dedicated Boca identity"):
        cleanup.clean_failed_install(IMAGE, SOURCE_SHA, "c" * 64)


@pytest.mark.parametrize("elevated", ["uid", "gid"])
def test_setid_process_is_rejected_before_private_paths_or_docker(
    monkeypatch: pytest.MonkeyPatch, elevated: str
) -> None:
    monkeypatch.setattr(cleanup.os, "getuid", lambda: 10001)
    monkeypatch.setattr(cleanup.os, "geteuid", lambda: 0 if elevated == "uid" else 10001)
    monkeypatch.setattr(cleanup.os, "getgid", lambda: 10001)
    monkeypatch.setattr(cleanup.os, "getegid", lambda: 0 if elevated == "gid" else 10001)
    monkeypatch.setattr(
        cleanup.pwd, "getpwuid", lambda _uid: SimpleNamespace(pw_name="boca-deploy")
    )
    monkeypatch.setattr(cleanup, "_check_rootless_boundary", lambda: pytest.fail("private probe"))
    monkeypatch.setattr(cleanup, "_run", lambda *args: pytest.fail("Docker called"))
    with pytest.raises(cleanup.CleanupError, match="dedicated Boca identity"):
        cleanup.clean_failed_install(IMAGE, SOURCE_SHA, "c" * 64)


@pytest.mark.parametrize("resource", ["container", "image_user", "volume_image_user"])
def test_existing_state_is_preserved_without_mutating_commands(
    monkeypatch: pytest.MonkeyPatch, resource: str
) -> None:
    monkeypatch.setattr(cleanup, "_check_identity", lambda: None)
    monkeypatch.setattr(cleanup, "_check_rootless_boundary", lambda: None)
    monkeypatch.setattr(cleanup, "_checked_stage", lambda _sha: False)
    monkeypatch.setattr(cleanup, "_capacity", lambda: (5 * 1024**3, 100_000))
    calls: list[tuple[str, ...]] = []

    def docker(*args: str) -> str:
        calls.append(args)
        if resource == "container" and args[:3] == ("ps", "-a", "-q"):
            return "abc123"
        if resource == "volume_image_user" and args[:3] == ("volume", "ls", "-q"):
            return "boca-socios_boca_key"
        if (
            resource in {"image_user", "volume_image_user"}
            and args[:3] == ("ps", "-a", "-q")
            and "ancestor=" in " ".join(args)
        ):
            return "abc123"
        if args[:2] == ("image", "inspect"):
            return json.dumps(
                {
                    "Size": 128 * 1024**2,
                    "RepoDigests": [IMAGE],
                    "RepoTags": [],
                    "Config": {"Labels": {"org.opencontainers.image.revision": SOURCE_SHA}},
                }
            )
        return ""

    monkeypatch.setattr(cleanup, "_run", docker)
    with pytest.raises(cleanup.CleanupError):
        cleanup.clean_failed_install(IMAGE, SOURCE_SHA, "c" * 64)
    assert not any(args[:2] == ("image", "rm") for args in calls)
    assert not any("prune" in " ".join(args) or "down" in args for args in calls)


@pytest.mark.parametrize("retained", ["volume", "network"])
def test_exact_unreferenced_image_can_be_removed_while_key_data_or_network_remain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    retained: str,
) -> None:
    root = tmp_path / "boca-socios"
    root.mkdir(mode=0o700)
    compose = root / "compose.yaml"
    compose.write_text("name: boca-socios\n")
    monkeypatch.setattr(cleanup, "ROOT", root)
    monkeypatch.setattr(cleanup, "COMPOSE", compose)
    monkeypatch.setattr(cleanup, "_check_identity", lambda: None)
    monkeypatch.setattr(cleanup, "_check_rootless_boundary", lambda: None)
    monkeypatch.setattr(cleanup, "_checked_stage", lambda _sha: compose.is_file())
    monkeypatch.setattr(cleanup, "_capacity", lambda: (5 * 1024**3, 100_000))
    calls: list[tuple[str, ...]] = []

    def docker(*args: str) -> str:
        calls.append(args)
        if retained == "volume" and args[:3] == ("volume", "ls", "-q"):
            return "boca-socios_boca_key\nboca-socios_boca_data"
        if retained == "network" and args[:3] == ("network", "ls", "-q"):
            return "network-id"
        if args[:2] == ("image", "inspect"):
            return json.dumps(
                {
                    "Size": 128 * 1024**2,
                    "RepoDigests": [IMAGE],
                    "RepoTags": [],
                    "Config": {"Labels": {"org.opencontainers.image.revision": SOURCE_SHA}},
                }
            )
        return ""

    monkeypatch.setattr(cleanup, "_run", docker)
    result = cleanup.clean_failed_install(IMAGE, SOURCE_SHA, "c" * 64)
    assert result.removed_image and result.retained_state
    assert not result.removed_stage and compose.exists()
    assert ("image", "rm", "--no-prune", IMAGE) in calls
    assert not any(args[:2] in {("volume", "rm"), ("network", "rm")} for args in calls)
    assert "state=PARTIAL" in capsys.readouterr().out


@pytest.mark.parametrize(
    "change",
    [
        {"RepoDigests": ["ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64]},
        {"RepoDigests": [IMAGE, "ghcr.io/other/repo@sha256:" + "a" * 64]},
        {"RepoTags": ["shared:latest"]},
        {"Config": {"Labels": {"org.opencontainers.image.revision": "e" * 40}}},
        {"Size": -1},
    ],
)
def test_image_identity_must_be_exact_and_unshared(change: dict[str, object]) -> None:
    image = {
        "Size": 128 * 1024**2,
        "RepoDigests": [IMAGE],
        "RepoTags": [],
        "Config": {"Labels": {"org.opencontainers.image.revision": SOURCE_SHA}},
    }
    image.update(change)
    with pytest.raises(cleanup.CleanupError):
        cleanup.validate_image(image, IMAGE, SOURCE_SHA)


def test_symlink_or_changed_compose_is_never_unlinked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "boca-socios"
    root.mkdir(mode=0o700)
    target = tmp_path / "outside"
    target.write_text("unrelated")
    compose = root / "compose.yaml"
    compose.symlink_to(target)
    monkeypatch.setattr(cleanup, "ROOT", root)
    monkeypatch.setattr(cleanup, "COMPOSE", compose)
    monkeypatch.setattr(cleanup, "_checked_root", lambda: None)
    with pytest.raises(cleanup.CleanupError, match="staged Compose"):
        cleanup._checked_stage(hashlib.sha256(target.read_bytes()).hexdigest())
    assert target.read_text() == "unrelated"
    assert compose.is_symlink()


def test_exact_failed_image_and_stage_are_removed_with_bounded_disk_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "boca-socios"
    root.mkdir(mode=0o700)
    compose = root / "compose.yaml"
    compose.write_text("name: boca-socios\n")
    digest = hashlib.sha256(compose.read_bytes()).hexdigest()
    monkeypatch.setattr(cleanup, "ROOT", root)
    monkeypatch.setattr(cleanup, "COMPOSE", compose)
    monkeypatch.setattr(cleanup, "_check_identity", lambda: None)
    monkeypatch.setattr(cleanup, "_check_rootless_boundary", lambda: None)
    monkeypatch.setattr(cleanup, "_checked_root", lambda: None)
    monkeypatch.setattr(
        cleanup, "_checked_stage", lambda _sha: compose.is_file() and not compose.is_symlink()
    )
    capacities = iter([(5 * 1024**3, 100_000), (5 * 1024**3 + 128 * 1024**2, 101_000)])
    monkeypatch.setattr(cleanup, "_capacity", lambda: next(capacities))
    calls: list[tuple[str, ...]] = []

    def docker(*args: str) -> str:
        calls.append(args)
        if args[:2] == ("image", "inspect"):
            return json.dumps(
                {
                    "Size": 128 * 1024**2,
                    "RepoDigests": [IMAGE],
                    "RepoTags": [],
                    "Config": {"Labels": {"org.opencontainers.image.revision": SOURCE_SHA}},
                }
            )
        return ""

    monkeypatch.setattr(cleanup, "_run", docker)
    result = cleanup.clean_failed_install(IMAGE, SOURCE_SHA, digest)
    assert result.removed_image and result.removed_stage
    assert not compose.exists()
    assert ("image", "rm", "--no-prune", IMAGE) in calls
    assert not any("prune" == part or "down" == part for args in calls for part in args)
    assert "hostdir_free_mib_before=5120 hostdir_free_mib_after=5248" in capsys.readouterr().out


def test_failed_image_removal_preserves_stage_for_diagnosis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "boca-socios"
    root.mkdir(mode=0o700)
    compose = root / "compose.yaml"
    compose.write_text("name: boca-socios\n")
    digest = hashlib.sha256(compose.read_bytes()).hexdigest()
    monkeypatch.setattr(cleanup, "ROOT", root)
    monkeypatch.setattr(cleanup, "COMPOSE", compose)
    monkeypatch.setattr(cleanup, "_check_identity", lambda: None)
    monkeypatch.setattr(cleanup, "_check_rootless_boundary", lambda: None)
    monkeypatch.setattr(cleanup, "_checked_root", lambda: None)
    monkeypatch.setattr(cleanup, "_checked_stage", lambda _sha: compose.is_file())
    monkeypatch.setattr(cleanup, "_capacity", lambda: (5 * 1024**3, 100_000))

    def docker(*args: str) -> str:
        if args[:2] == ("image", "inspect"):
            return json.dumps(
                {
                    "Size": 1024,
                    "RepoDigests": [IMAGE],
                    "RepoTags": [],
                    "Config": {"Labels": {"org.opencontainers.image.revision": SOURCE_SHA}},
                }
            )
        if args[:2] == ("image", "rm"):
            raise cleanup.CleanupError("image removal failed")
        return ""

    monkeypatch.setattr(cleanup, "_run", docker)
    with pytest.raises(cleanup.CleanupIndeterminate, match="outcome is unverified"):
        cleanup.clean_failed_install(IMAGE, SOURCE_SHA, digest)
    assert compose.exists()


@pytest.mark.parametrize("later_failure", ["stage_recheck", "capacity_after"])
def test_post_image_removal_failure_reports_indeterminate_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    later_failure: str,
) -> None:
    monkeypatch.setattr(cleanup, "_check_identity", lambda: None)
    monkeypatch.setattr(cleanup, "_check_rootless_boundary", lambda: None)
    checks = 0
    measurements = 0
    removals: list[tuple[str, ...]] = []

    def stage_check(_sha: str) -> bool:
        nonlocal checks
        checks += 1
        if later_failure == "stage_recheck" and checks == 2:
            raise cleanup.CleanupError("staged Compose changed during cleanup")
        return later_failure == "stage_recheck"

    def capacity() -> tuple[int, int]:
        nonlocal measurements
        measurements += 1
        if later_failure == "capacity_after" and measurements == 2:
            raise cleanup.CleanupError("aggregate free storage is unavailable")
        return 5 * 1024**3, 100_000

    def docker(*args: str) -> str:
        if args[:2] == ("image", "inspect"):
            return json.dumps(
                {
                    "Size": 128 * 1024**2,
                    "RepoDigests": [IMAGE],
                    "RepoTags": [],
                    "Config": {"Labels": {"org.opencontainers.image.revision": SOURCE_SHA}},
                }
            )
        if args[:2] == ("image", "rm"):
            removals.append(args)
        return ""

    monkeypatch.setattr(cleanup, "_checked_stage", stage_check)
    monkeypatch.setattr(cleanup, "_capacity", capacity)
    monkeypatch.setattr(cleanup, "_run", docker)
    assert cleanup.main([IMAGE, SOURCE_SHA, "c" * 64]) == 1
    out = capsys.readouterr()
    assert removals == [("image", "rm", "--no-prune", IMAGE)]
    assert "BOCA_CLEANUP state=CLEANED" not in out.out
    assert "BOCA_CLEANUP_INDETERMINADO" in out.err


def test_private_runtime_must_be_owned_and_rootless_before_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cleanup, "_safe_private_runtime", lambda: False)
    monkeypatch.setattr(cleanup, "_run", lambda *args: pytest.fail("Docker called"))
    with pytest.raises(cleanup.CleanupError, match="rootless"):
        cleanup._check_rootless_boundary()


def test_unowned_runtime_parent_is_rejected_before_socket_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    (runtime / "docker.sock").symlink_to(tmp_path / "outside")
    monkeypatch.setattr(cleanup, "ROOTLESS_SOCKET", runtime / "docker.sock")
    assert not cleanup._safe_private_runtime()


def test_symlinked_root_is_rejected_before_listing_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "boca-socios"
    root.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(cleanup, "ROOT", root)
    with pytest.raises(cleanup.CleanupError, match="uncertain state"):
        cleanup._checked_root()


def test_already_clean_is_idempotent_without_docker_mutation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cleanup, "_check_identity", lambda: None)
    monkeypatch.setattr(cleanup, "_check_rootless_boundary", lambda: None)
    monkeypatch.setattr(cleanup, "_checked_stage", lambda _sha: False)
    monkeypatch.setattr(cleanup, "_capacity", lambda: (5 * 1024**3, 100_000))

    def docker(*args: str) -> str:
        if args[:2] == ("image", "inspect"):
            raise cleanup.ImageAbsent("exact Boca image absent")
        if args[:2] == ("image", "rm"):
            pytest.fail("already clean image removed")
        return ""

    monkeypatch.setattr(cleanup, "_run", docker)
    result = cleanup.clean_failed_install(IMAGE, SOURCE_SHA, "c" * 64)
    assert not result.removed_image and not result.removed_stage
    assert "state=ALREADY_CLEAN" in capsys.readouterr().out


def test_regular_stage_with_correct_hash_can_be_identified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "boca-socios"
    root.mkdir(mode=0o700)
    compose = root / "compose.yaml"
    compose.write_text("name: boca-socios\n")
    digest = hashlib.sha256(compose.read_bytes()).hexdigest()
    monkeypatch.setattr(cleanup, "ROOT", root)
    monkeypatch.setattr(cleanup, "COMPOSE", compose)
    monkeypatch.setattr(cleanup, "_checked_root", lambda: None)
    original_lstat = Path.lstat

    def boca_lstat(path: Path) -> os.stat_result | SimpleNamespace:
        if path == compose:
            return SimpleNamespace(
                st_mode=stat.S_IFREG | 0o600, st_uid=10001, st_size=compose.stat().st_size
            )
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", boca_lstat)
    assert cleanup._checked_stage(digest)


def test_actions_cleanup_only_follows_a_failed_staging_attempt() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text()
    preflight = workflow.index("Read-only host capacity and Boca namespace before first install")
    marker = workflow.index("Mark Boca staging attempt after read-only preflight")
    stage = workflow.index("Stage only reviewed Boca Compose file")
    apply = workflow.index("Pull verified digest and start only Boca controller")
    cleanup_step = workflow.index("Clean only proven disposable Boca artifacts after failure")
    assert preflight < marker < stage < apply < cleanup_step
    cleanup_section = workflow[cleanup_step : workflow.index("- name:", cleanup_step + 10)]
    assert (
        "if: failure() && inputs.operation == 'first-install' && "
        "steps.boca_stage_attempt.outputs.started == 'true'"
    ) in cleanup_section
    assert 'test "$GITHUB_RUN_ATTEMPT" = 1' in workflow[:marker]
    assert "src/boca_socios/host_cleanup.py" in cleanup_section
    assert (
        '"$BOCA_IMAGE_REF" "$BOCA_SOURCE_SHA" "$(cat "$RUNNER_TEMP/boca-compose.sha")"'
        in cleanup_section
    )
    assert "Boca first-install failed; original failure remains NO_GO" in cleanup_section
    assert "2>/dev/null" in cleanup_section  # Never echo an SSH error/host address.
    marker_section = workflow[marker:stage]
    assert "id: boca_stage_attempt" in marker_section
    assert "started=true" in marker_section and '"$GITHUB_OUTPUT"' in marker_section


@pytest.mark.parametrize("successful", [False, True])
def test_cleanup_failure_hook_redacts_ssh_output_and_keeps_original_failure(
    tmp_path: Path, successful: bool
) -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/boca-first-deploy.yml").read_text()
    start = workflow.index(
        "      - name: Clean only proven disposable Boca artifacts after failure"
    )
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
    (tmp_path / "boca-compose.sha").write_text("c" * 64)
    summary = tmp_path / "summary.md"
    environment = dict(os.environ)
    environment.update(
        {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(summary),
            "BOCA_IMAGE_REF": IMAGE,
            "BOCA_SOURCE_SHA": SOURCE_SHA,
            "FAKE_SSH_RC": "0" if successful else "17",
            "FAKE_SSH_STDOUT": (
                "BOCA_CLEANUP state=PARTIAL image=removed stage=retained retained=yes "
                "image_logical_mib=128 hostdir_free_mib_before=5120 hostdir_free_mib_after=5140 "
                "inodes_before=100000 inodes_after=100001"
                if successful
                else "host=1.2.3.4 secret=NEVER"
            ),
            "FAKE_SSH_STDERR": "host=1.2.3.4 secret=NEVER",
        }
    )
    completed = subprocess.run(  # noqa: S603 - executable and script are fixed test fixtures
        ["/usr/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert completed.returncode == 0
    receipt = summary.read_text()
    assert "original failure remains NO_GO" in receipt
    assert ("state=PARTIAL" in receipt) is successful
    if not successful:
        assert "INDETERMINADO" in receipt
        assert "artifacts retained" not in receipt
    assert "secret=NEVER" not in receipt + completed.stdout + completed.stderr
    assert "host=1.2.3.4" not in receipt + completed.stdout + completed.stderr
