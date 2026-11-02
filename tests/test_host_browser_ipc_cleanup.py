"""Fail-closed, new-only browser IPC cleanup never touches foreign/owner state."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from boca_socios import host_cleanup as cleanup

IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64
BROWSER = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "b" * 64
SOURCE = "c" * 40
CONTROLLER = "d" * 64
WORKER = "e" * 64
PROBE = "1" * 64
ATTEMPT = "41360122998"
NETWORK = "boca-socios_boca_private"
IPC_VOLUME = "boca-socios_boca_browser_ipc"
PERSISTENT = {"boca-socios_boca_owner", "boca-socios_boca_key", "boca-socios_boca_data"}


class FakeDocker:
    """No real Docker commands; writes record only exact attempted mutations."""

    def __init__(self, storage: Path) -> None:
        self.containers: dict[str, bool] = {"controller": True, "worker": True}
        self.probe_phase: str | None = None
        self.probe_running = True
        self.probe_bad_mount = False
        self.probe_bad_label = False
        self.probe_bad_ports = False
        self.probe_bad_caps = False
        self.probe_bad_command = False
        self.probe_bad_image = False
        self.probe_bad_user = False
        self.probe_bad_security = False
        self.probe_bad_env = False
        self.probe_pid_mode = "private"
        self.probe_ipc_mode = "private"
        self.probe_cgroupns_mode = "private"
        self.probe_userns_mode = ""
        self.probe_uts_mode = ""
        self.probe_init: bool | None = None
        self.probe_auto_remove = True
        self.duplicate_probe = False
        self.probe_auto_remove_on_stop = False
        self.probe_auto_remove_before_rm = False
        self.probe_disappears_after_inventory = False
        self.probe_inventory_snapshots = 0
        self.images = {IMAGE, BROWSER}
        self.volumes = set(PERSISTENT) | {IPC_VOLUME}
        self.network = True
        self.network_id = "a" * 64
        self.network_inspects = 0
        self.replace_before_recheck = False
        self.replace_before_remove = False
        self.foreign = False
        self.other_peer = False
        self.port = "8443"
        self.worker_network = "none"
        self.worker_mount = IPC_VOLUME
        self.seccomp_profile = '{"defaultAction":"SCMP_ACT_ERRNO","syscalls":[]}'
        self.seccomp_override: str | None = None
        self.mutate_then_fail = False
        self.commands: list[tuple[str, ...]] = []
        self.storage = storage

    def _container(self, service: str) -> dict[str, object]:
        controller = service == "controller"
        identity = CONTROLLER if controller else WORKER
        mounts = (
            [
                {
                    "Type": "volume",
                    "Name": "boca-socios_boca_data",
                    "Destination": "/data",
                    "RW": True,
                },
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
                {
                    "Type": "volume",
                    "Name": IPC_VOLUME,
                    "Destination": "/run/boca-browser-ipc",
                    "RW": False,
                },
            ]
            if controller
            else [
                {
                    "Type": "volume",
                    "Name": self.worker_mount,
                    "Destination": "/run/boca-browser-ipc",
                    "RW": True,
                }
            ]
        )
        port = {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": self.port}]}
        network = NETWORK if controller else self.worker_network
        host: dict[str, object] = {
            "NetworkMode": network,
            "PortBindings": port if controller else {},
            "ReadonlyRootfs": True,
            "Privileged": False,
            "RestartPolicy": {"Name": "no"},
            "CapDrop": ["ALL"],
            "CapAdd": [] if controller else ["SYS_CHROOT"],
            "Memory": 256 * 1024**2 if controller else 768 * 1024**2,
            "NanoCpus": 500_000_000 if controller else 1_000_000_000,
            "PidsLimit": 64 if controller else 128,
            "SecurityOpt": ["no-new-privileges:true"]
            if controller
            else [
                "no-new-privileges:true",
                self.seccomp_override or ("seccomp=" + self.seccomp_profile),
            ],
        }
        if not controller:
            host.update(
                {
                    "IpcMode": "private",
                    "CgroupnsMode": "private",
                    "Init": True,
                    "PidMode": "",
                    "Devices": [],
                }
            )
        return {
            "Id": identity,
            "Name": "/boca-socios-controller-1" if controller else "/boca-socios-browser-worker-1",
            "Config": {
                "Image": IMAGE if controller else BROWSER,
                "User": "10001:10001" if controller else "10002:10002",
                "Cmd": ["python", "-m", "boca_socios.runtime", "serve-beta"]
                if controller
                else ["python", "-m", "boca_socios.browser.ipc_worker"],
                "Labels": {
                    "com.docker.compose.project": "boca-socios",
                    "com.docker.compose.service": service if controller else "browser-worker",
                    "org.opencontainers.image.revision": SOURCE,
                    "boca.socios.browser-ipc-attempt": ATTEMPT,
                },
            },
            "HostConfig": host,
            "Mounts": mounts,
            "State": {"Running": self.containers[service], "Restarting": False},
            "NetworkSettings": {
                "Ports": port if controller else {},
                "Networks": {network: {}},
            },
        }

    def _probe(self) -> dict[str, object]:
        phase = self.probe_phase
        assert phase is not None
        spec = cleanup._browser_ipc_probe_spec(phase)
        assert spec is not None
        mounts = [
            {
                "Type": "volume",
                "Driver": "local",
                "Name": name,
                "Destination": destination,
                "RW": rw,
            }
            for name, destination, rw in sorted(spec.mounts)
        ]
        if self.probe_bad_mount:
            mounts[0]["Name"] = "boca-socios_boca_owner"
        labels = {
            "com.docker.compose.project": "boca-socios",
            "org.opencontainers.image.revision": SOURCE,
            "boca.socios.browser-ipc-attempt": ATTEMPT,
            "boca.socios.browser-ipc-phase": phase,
        }
        if self.probe_bad_label:
            labels["boca.socios.browser-ipc-phase"] = "different"
        return {
            "Id": PROBE,
            "Name": f"/boca-socios-browser-ipc-probe-{phase}-{ATTEMPT}",
            "Config": {
                "Image": IMAGE
                if self.probe_bad_image
                else (BROWSER if spec.image_is_browser else IMAGE),
                "User": "30000:30000" if self.probe_bad_user else spec.user,
                "Cmd": ["sh", "-c", "unreviewed"] if self.probe_bad_command else list(spec.command),
                "Entrypoint": None,
                "Labels": labels,
                "Env": [
                    "BOCA_ENVIRONMENT=staging",
                    "BOCA_RUNTIME_MODE=simulation",
                    "BOCA_ENGINE_MODE=off",
                ]
                + (["BOCA_ENGINE_MODE=live"] if self.probe_bad_env else []),
            },
            "HostConfig": {
                "NetworkMode": "none",
                "PidMode": self.probe_pid_mode,
                "IpcMode": self.probe_ipc_mode,
                "CgroupnsMode": self.probe_cgroupns_mode,
                "UsernsMode": self.probe_userns_mode,
                "UTSMode": self.probe_uts_mode,
                "Init": self.probe_init,
                "AutoRemove": self.probe_auto_remove,
                "PortBindings": {"8444/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8444"}]}
                if self.probe_bad_ports
                else {},
                "ReadonlyRootfs": True,
                "Privileged": False,
                "RestartPolicy": {"Name": "no"},
                "CapDrop": ["ALL"],
                "CapAdd": ["SYS_ADMIN"] if self.probe_bad_caps else list(spec.capabilities),
                "Memory": spec.memory,
                "NanoCpus": spec.nano_cpus,
                "PidsLimit": spec.pids,
                "SecurityOpt": ["seccomp=unconfined"]
                if self.probe_bad_security
                else ["no-new-privileges"],
                "PublishAllPorts": False,
                "Devices": [],
            },
            "Mounts": mounts,
            "State": {"Running": self.probe_running, "Restarting": False},
            "NetworkSettings": {"Ports": {}, "Networks": {"none": {}}},
        }

    def __call__(self, *args: str) -> str:
        self.commands.append(args)
        if args[:3] == ("ps", "-a", "-q"):
            if args == ("ps", "-a", "-q", "--no-trunc"):
                self.probe_inventory_snapshots += 1
                if self.probe_disappears_after_inventory and self.probe_inventory_snapshots > 1:
                    self.probe_phase = None
            if "--filter" in args:
                expression = args[args.index("--filter") + 1]
                if expression.startswith("ancestor="):
                    return ""  # No container uses a disposable image after service rm.
                if expression.startswith("volume="):
                    return ""  # No container uses the IPC volume after service rm.
            identities = ([CONTROLLER] if "controller" in self.containers else []) + (
                [WORKER] if "worker" in self.containers else []
            )
            if self.probe_phase is not None:
                identities.append(PROBE)
            if self.duplicate_probe:
                identities.append("2" * 64)
            if self.foreign and ("--filter" not in args):
                identities.append("f" * 64)
            return "\n".join(identities)
        if args[:2] == ("container", "inspect"):
            if args[-1] == "2" * 64:
                second = self._probe()
                second["Id"] = "2" * 64
                return json.dumps(second)
            if args[-1] == PROBE:
                return json.dumps(self._probe())
            return json.dumps(self._container("controller" if args[-1] == CONTROLLER else "worker"))
        if args[:2] == ("container", "stop"):
            if args[-1] == PROBE:
                assert args[2:4] == ("--time", "8")
                self.probe_running = False
                if self.probe_auto_remove_on_stop:
                    self.probe_phase = None
                return PROBE
            service = "controller" if args[-1] == CONTROLLER else "worker"
            assert args[2] == "--time" and args[3] == ("30" if service == "controller" else "8")
            self.containers[service] = False
            return args[-1]
        if args[:2] == ("container", "rm"):
            if args[-1] == PROBE:
                assert not self.probe_running
                self.probe_phase = None
                if self.probe_auto_remove_before_rm:
                    raise cleanup.CleanupError("--rm helper completed before explicit rm")
                return PROBE
            service = "controller" if args[-1] == CONTROLLER else "worker"
            assert not self.containers[service]
            self.containers.pop(service)
            if self.mutate_then_fail:
                raise cleanup.CleanupError("synthetic Docker error after mutation")
            return args[-1]
        if args[:2] == ("volume", "ls"):
            return "\n".join(sorted(self.volumes))
        if args[:2] == ("volume", "inspect"):
            return json.dumps(
                {
                    "Name": IPC_VOLUME,
                    "Driver": "local",
                    "Scope": "local",
                    "Options": {},
                    "Mountpoint": str(self.storage / "volumes" / IPC_VOLUME / "_data"),
                    "Labels": {
                        "com.docker.compose.project": "boca-socios",
                        "com.docker.compose.volume": "boca_browser_ipc",
                        "boca.socios.browser-ipc-attempt": ATTEMPT,
                    },
                }
            )
        if args[:2] == ("volume", "rm"):
            assert args[2:] == (IPC_VOLUME,)
            self.volumes.remove(IPC_VOLUME)
            return IPC_VOLUME
        if args[:2] == ("network", "ls"):
            return NETWORK if self.network else ""
        if args[:2] == ("network", "inspect"):
            self.network_inspects += 1
            if self.replace_before_recheck and self.network_inspects >= 2:
                self.network_id = "f" * 64
            peers = {CONTROLLER: {}} if "controller" in self.containers else {}
            if self.other_peer:
                peers["foreign"] = {}
            return json.dumps(
                {
                    "Name": NETWORK,
                    "Id": self.network_id,
                    "Driver": "bridge",
                    "Internal": False,
                    "Labels": {
                        "com.docker.compose.project": "boca-socios",
                        "com.docker.compose.network": "boca_private",
                    },
                    "Containers": peers,
                }
            )
        if args[:2] == ("network", "rm"):
            if self.replace_before_remove:
                self.network_id = "f" * 64
                # Docker refuses the disappeared exact ID; the new bridge
                # with the same name remains untouched.
                if args[2:] != (self.network_id,):
                    raise cleanup.CleanupError("old bridge ID no longer exists")
            assert args[2:] == (self.network_id,)
            self.network = False
            return NETWORK
        if args[:2] == ("image", "inspect"):
            if args[-1] not in self.images:
                raise cleanup.ImageAbsent("exact Boca image absent")
            return json.dumps(
                {
                    "Size": 128 * 1024**2,
                    "RepoDigests": [args[-1]],
                    "RepoTags": [],
                    "Config": {"Labels": {"org.opencontainers.image.revision": SOURCE}},
                }
            )
        if args[:2] == ("image", "rm"):
            assert args[2] == "--no-prune"
            self.images.remove(args[3])
            return args[3]
        pytest.fail(f"Unexpected Docker command: {args}")


@pytest.fixture
def case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[FakeDocker, dict[str, object], dict[str, Path]]:
    root = tmp_path / "boca-socios"
    root.mkdir(mode=0o700)
    storage = tmp_path / "docker"
    (storage / "volumes" / IPC_VOLUME / "_data").mkdir(parents=True)
    finals = {
        "base": root / "compose.beta.yaml",
        "overlay": root / "compose.beta.browser.yaml",
        "seccomp": root / "seccomp_profile.json",
    }
    for name, path in finals.items():
        if name == "seccomp":
            path.write_text('{\n  "defaultAction": "SCMP_ACT_ERRNO",\n  "syscalls": []\n}\n')
        else:
            path.write_text(f"reviewed-{name}\n")
        path.chmod(0o600)
    marker: dict[str, object] = {
        "version": "browser-ipc-new-only-v2",
        "attempt_id": ATTEMPT,
        "source_sha": SOURCE,
        "controller_digest": IMAGE,
        "browser_digest": BROWSER,
        "beta_compose_sha": hashlib.sha256(finals["base"].read_bytes()).hexdigest(),
        "overlay_compose_sha": hashlib.sha256(finals["overlay"].read_bytes()).hexdigest(),
        "seccomp_sha": hashlib.sha256(finals["seccomp"].read_bytes()).hexdigest(),
        "controller_image_absent": True,
        "browser_image_absent": True,
        "bridge_absent": True,
        "ipc_volume_absent": True,
    }
    marker_path = root / "browser-ipc-attempt.json"
    marker_path.write_bytes(
        json.dumps(marker, sort_keys=True, separators=(",", ":")).encode("ascii")
    )
    marker_path.chmod(0o600)
    files = {**finals, "marker": marker_path}
    for name in ("base", "overlay", "seccomp"):
        partial = root / f".browser-ipc-{name}-{ATTEMPT}.part"
        partial.write_bytes(b"interrupted")
        partial.chmod(0o600)
        files[f"partial-{name}"] = partial

    original_lstat = Path.lstat
    original_fstat = os.fstat

    def owned_lstat(path: Path) -> os.stat_result | SimpleNamespace:
        metadata = original_lstat(path)
        if path in {root, *files.values()}:
            return SimpleNamespace(
                st_mode=metadata.st_mode,
                st_uid=10001,
                st_gid=10001,
                st_size=metadata.st_size,
                st_nlink=metadata.st_nlink,
                st_ino=metadata.st_ino,
                st_dev=metadata.st_dev,
            )
        return metadata

    def owned_fstat(descriptor: int) -> os.stat_result | SimpleNamespace:
        metadata = original_fstat(descriptor)
        try:
            pointed = Path(os.readlink(f"/proc/self/fd/{descriptor}"))
        except OSError:
            return metadata
        if pointed in files.values():
            return SimpleNamespace(
                st_mode=metadata.st_mode,
                st_uid=10001,
                st_gid=10001,
                st_size=metadata.st_size,
                st_nlink=metadata.st_nlink,
                st_ino=metadata.st_ino,
                st_dev=metadata.st_dev,
            )
        return metadata

    monkeypatch.setattr(Path, "lstat", owned_lstat)
    monkeypatch.setattr(os, "fstat", owned_fstat)
    monkeypatch.setattr(cleanup, "ROOT", root)
    monkeypatch.setattr(cleanup, "BETA_COMPOSE", finals["base"])
    monkeypatch.setattr(cleanup, "BROWSER_IPC_OVERLAY", finals["overlay"])
    monkeypatch.setattr(cleanup, "BROWSER_IPC_SECCOMP", finals["seccomp"])
    monkeypatch.setattr(cleanup, "BROWSER_IPC_MARKER", marker_path)
    monkeypatch.setattr(cleanup, "_check_identity", lambda: None)
    monkeypatch.setattr(cleanup, "_check_rootless_boundary", lambda: None)
    monkeypatch.setattr(cleanup, "_checked_docker_storage_dir", lambda: storage)
    monkeypatch.setattr(
        cleanup,
        "_capacity",
        lambda: cleanup.CapacitySnapshot(
            docker_root=storage,
            stage_device=1,
            docker_device=2,
            stage_free_bytes=4096 * 1024**2,
            docker_free_bytes=4096 * 1024**2,
            stage_inodes=100000,
            docker_inodes=90000,
        ),
    )
    docker = FakeDocker(storage)
    monkeypatch.setattr(cleanup, "_run", docker)
    return docker, marker, files


def run_cleanup(marker: dict[str, object]) -> cleanup.BrowserIPCCleanupResult:
    return cleanup.clean_failed_browser_ipc_install(
        IMAGE,
        SOURCE,
        str(marker["beta_compose_sha"]),
        BROWSER,
        str(marker["overlay_compose_sha"]),
        str(marker["seccomp_sha"]),
        ATTEMPT,
    )


@pytest.mark.parametrize("services", [set(), {"controller"}, {"worker"}, {"controller", "worker"}])
def test_only_zero_one_or_two_exact_containers_removed(
    case: tuple[FakeDocker, dict[str, object], dict[str, Path]],
    services: set[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    docker, marker, files = case
    docker.containers = {service: True for service in services}
    result = run_cleanup(marker)
    assert result.removed_controller == ("controller" in services)
    assert result.removed_worker == ("worker" in services)
    assert result.removed_ipc_volume and result.removed_network
    assert result.removed_image and result.removed_browser_image
    assert result.removed_beta_stage and result.removed_overlay_stage
    assert result.removed_seccomp_stage and result.removed_partials == 3
    assert not any(path.exists() for path in files.values())
    assert docker.volumes == PERSISTENT
    assert docker.containers == {} and not docker.images and not docker.network
    assert not any(
        args[:2] in {("volume", "prune"), ("system", "prune")} for args in docker.commands
    )
    assert not any("--force" in args or "--volumes" in args for args in docker.commands)
    if "controller" in services and "worker" in services:
        assert docker.commands.index(
            ("container", "stop", "--time", "8", WORKER)
        ) < docker.commands.index(("container", "stop", "--time", "30", CONTROLLER))
    assert "BOCA_BROWSER_IPC_CLEANUP state=CLEANED" in capsys.readouterr().out


@pytest.mark.parametrize(
    "phase",
    [
        "ipc-dir-init",
        "synthetic-ipc",
        "key-init",
        "key-verify",
        "owner-check",
        "config-check",
        "data-init",
    ],
)
@pytest.mark.parametrize("services", [set(), {"worker"}, {"worker", "controller"}])
def test_orphaned_named_phase_probe_is_selectively_stopped_before_services(
    case: tuple[FakeDocker, dict[str, object], dict[str, Path]],
    phase: str,
    services: set[str],
) -> None:
    docker, marker, _ = case
    docker.containers = {service: True for service in services}
    docker.probe_phase = phase
    docker.probe_running = True
    result = run_cleanup(marker)
    assert result.removed_probe
    assert result.removed_controller == ("controller" in services)
    assert result.removed_worker == ("worker" in services)
    assert docker.probe_phase is None and docker.containers == {}
    assert docker.volumes == PERSISTENT
    assert docker.commands.index(
        ("container", "stop", "--time", "8", PROBE)
    ) < docker.commands.index(("container", "rm", PROBE))
    for service_id in (WORKER, CONTROLLER):
        if any(
            command[:2] == ("container", "stop") and command[-1] == service_id
            for command in docker.commands
        ):
            assert docker.commands.index(("container", "rm", PROBE)) < next(
                i
                for i, command in enumerate(docker.commands)
                if command[:2] == ("container", "stop") and command[-1] == service_id
            )
    assert not any("--force" in command or "--volumes" in command for command in docker.commands)


@pytest.mark.parametrize("when", ["before-stop", "on-stop", "before-rm"])
def test_docker_run_auto_remove_race_is_idempotent_for_exact_probe_only(
    case: tuple[FakeDocker, dict[str, object], dict[str, Path]],
    when: str,
) -> None:
    docker, marker, files = case
    docker.containers = {}
    docker.probe_phase = "key-verify"
    docker.probe_disappears_after_inventory = when == "before-stop"
    docker.probe_auto_remove_on_stop = when == "on-stop"
    docker.probe_auto_remove_before_rm = when == "before-rm"
    result = run_cleanup(marker)
    assert result.removed_probe
    assert docker.probe_phase is None and not files["marker"].exists()
    assert docker.volumes == PERSISTENT
    assert not any("--force" in command or "--volumes" in command for command in docker.commands)
    if when in {"before-stop", "on-stop"}:
        assert ("container", "rm", PROBE) not in docker.commands
    assert sum(command == ("container", "rm", PROBE) for command in docker.commands) <= 1


@pytest.mark.parametrize(
    "change",
    [
        "mount",
        "phase-label",
        "port",
        "capability",
        "duplicate-probe",
        "command",
        "image",
        "user",
        "security",
        "duplicate-env",
        "pid-host",
        "ipc-host",
        "cgroupns-host",
        "userns-host",
        "uts-host",
        "init-true",
        "autoremove-false",
    ],
)
def test_unreviewed_or_duplicated_helper_blocks_cleanup_without_deleting(
    case: tuple[FakeDocker, dict[str, object], dict[str, Path]],
    change: str,
) -> None:
    docker, marker, files = case
    docker.containers = {}
    docker.probe_phase = "ipc-dir-init"
    if change == "mount":
        docker.probe_bad_mount = True
    elif change == "phase-label":
        docker.probe_bad_label = True
    elif change == "port":
        docker.probe_bad_ports = True
    elif change == "capability":
        docker.probe_bad_caps = True
    elif change == "command":
        docker.probe_bad_command = True
    elif change == "image":
        docker.probe_bad_image = True
    elif change == "user":
        docker.probe_bad_user = True
    elif change == "security":
        docker.probe_bad_security = True
    elif change == "duplicate-env":
        docker.probe_phase = "owner-check"
        docker.probe_bad_env = True
    elif change == "pid-host":
        docker.probe_pid_mode = "host"
    elif change == "ipc-host":
        docker.probe_ipc_mode = "host"
    elif change == "cgroupns-host":
        docker.probe_cgroupns_mode = "host"
    elif change == "userns-host":
        docker.probe_userns_mode = "host"
    elif change == "uts-host":
        docker.probe_uts_mode = "host"
    elif change == "init-true":
        docker.probe_init = True
    elif change == "autoremove-false":
        docker.probe_auto_remove = False
    else:
        docker.duplicate_probe = True
    with pytest.raises(cleanup.CleanupError):
        run_cleanup(marker)
    assert docker.probe_phase is not None and files["marker"].exists()
    assert docker.images == {IMAGE, BROWSER} and docker.volumes == PERSISTENT | {IPC_VOLUME}
    assert not any(
        command[:2]
        in {("container", "stop"), ("container", "rm"), ("network", "rm"), ("image", "rm")}
        for command in docker.commands
    )


def test_images_preexisting_are_retained_and_cleanup_idempotent(
    case: tuple[FakeDocker, dict[str, object], dict[str, Path]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    docker, marker, _ = case
    marker["controller_image_absent"] = False
    marker["browser_image_absent"] = False
    marker_path = cleanup.BROWSER_IPC_MARKER
    marker_path.write_bytes(
        json.dumps(marker, sort_keys=True, separators=(",", ":")).encode("ascii")
    )
    result = run_cleanup(marker)
    assert result.retained_image and result.retained_browser_image
    assert docker.images == {IMAGE, BROWSER} and docker.volumes == PERSISTENT
    assert not any(command[:2] == ("image", "rm") for command in docker.commands)
    assert "image=retained browser_image=retained" in capsys.readouterr().out
    again = run_cleanup(marker)
    assert not again.removed_marker
    assert "state=ALREADY_CLEAN" in capsys.readouterr().out


def test_other_slot_partial_from_same_attempt_is_disposed_but_other_attempt_is_refused(
    case: tuple[FakeDocker, dict[str, object], dict[str, Path]],
) -> None:
    docker, marker, files = case
    files["partial-base"].unlink()
    files["partial-seccomp"].unlink()
    result = run_cleanup(marker)
    assert result.removed_partials == 1
    assert not files["partial-overlay"].exists()
    assert docker.volumes == PERSISTENT


def test_other_attempt_partial_blocks_all_deletion(
    case: tuple[FakeDocker, dict[str, object], dict[str, Path]],
) -> None:
    docker, marker, files = case
    wrong = files["marker"].parent / ".browser-ipc-overlay-412.part"
    wrong.write_bytes(b"not-this-attempt")
    wrong.chmod(0o600)
    with pytest.raises(cleanup.CleanupError):
        run_cleanup(marker)
    assert wrong.exists() and files["marker"].exists()
    assert not any(
        command[:2] in {("container", "stop"), ("image", "rm")} for command in docker.commands
    )


@pytest.mark.parametrize(
    "change",
    [
        "foreign",
        "peer",
        "port",
        "worker-egress",
        "worker-owner-mount",
        "foreign-volume",
        "marker-sha",
        "marker-extra",
        "marker-preexisting-bridge",
        "stage-change",
        "wrong-partial",
        "wrong-marker-mode",
        "different-attempt",
        "numeric-sha",
    ],
)
def test_uncertain_inventory_refuses_before_any_mutation(
    case: tuple[FakeDocker, dict[str, object], dict[str, Path]],
    change: str,
) -> None:
    docker, marker, files = case
    if change == "foreign":
        docker.foreign = True
    elif change == "peer":
        docker.other_peer = True
    elif change == "port":
        docker.port = "8444"
    elif change == "worker-egress":
        docker.worker_network = NETWORK
    elif change == "worker-owner-mount":
        docker.worker_mount = "boca-socios_boca_owner"
    elif change == "foreign-volume":
        docker.volumes.add("boca-socios_someone_else")
    elif change == "marker-sha":
        marker["seccomp_sha"] = "0" * 64
    elif change == "marker-extra":
        marker["extra"] = True
    elif change == "marker-preexisting-bridge":
        marker["bridge_absent"] = False
    elif change == "stage-change":
        files["overlay"].write_text("unreviewed change")
    elif change == "wrong-partial":
        files["partial-base"].chmod(0o644)
    elif change == "wrong-marker-mode":
        files["marker"].chmod(0o644)
    elif change == "numeric-sha":
        marker["seccomp_sha"] = int("9" * 64)
    else:
        marker["attempt_id"] = "400"
    if change.startswith("marker-") or change in {"different-attempt", "numeric-sha"}:
        files["marker"].write_bytes(
            json.dumps(marker, sort_keys=True, separators=(",", ":")).encode("ascii")
        )
    with pytest.raises(cleanup.CleanupError):
        run_cleanup(
            {
                **marker,
                "beta_compose_sha": hashlib.sha256(files["base"].read_bytes()).hexdigest(),
                "overlay_compose_sha": hashlib.sha256(files["overlay"].read_bytes()).hexdigest(),
                "seccomp_sha": hashlib.sha256(files["seccomp"].read_bytes()).hexdigest(),
            }
        )
    assert docker.containers == {"controller": True, "worker": True}
    assert docker.images == {IMAGE, BROWSER} and docker.network
    assert docker.volumes.issuperset(PERSISTENT)
    assert not any(
        command[:2]
        in {
            ("container", "stop"),
            ("container", "rm"),
            ("volume", "rm"),
            ("network", "rm"),
            ("image", "rm"),
        }
        for command in docker.commands
    )


@pytest.mark.parametrize(
    "security_opt",
    [
        "seccomp=/srv/boca-socios/seccomp_profile.json",
        "seccomp=unconfined",
        'seccomp={"defaultAction":"SCMP_ACT_ALLOW","syscalls":[]}',
    ],
)
def test_worker_security_opt_must_embed_exact_reviewed_json(
    case: tuple[FakeDocker, dict[str, object], dict[str, Path]],
    security_opt: str,
) -> None:
    docker, marker, files = case
    docker.seccomp_override = security_opt
    with pytest.raises(cleanup.CleanupError):
        run_cleanup(marker)
    assert files["marker"].exists()
    assert docker.images == {IMAGE, BROWSER} and docker.volumes == PERSISTENT | {IPC_VOLUME}
    assert not any(
        command[:2] in {("container", "stop"), ("container", "rm")} for command in docker.commands
    )


def test_seccomp_duplicate_json_key_rejected_even_with_matching_stage_digest(
    case: tuple[FakeDocker, dict[str, object], dict[str, Path]],
) -> None:
    docker, marker, files = case
    files["seccomp"].write_text(
        '{"defaultAction":"SCMP_ACT_ERRNO","defaultAction":"SCMP_ACT_ALLOW"}'
    )
    marker["seccomp_sha"] = hashlib.sha256(files["seccomp"].read_bytes()).hexdigest()
    files["marker"].write_bytes(
        json.dumps(marker, sort_keys=True, separators=(",", ":")).encode("ascii")
    )
    with pytest.raises(cleanup.CleanupError):
        run_cleanup(marker)
    assert files["seccomp"].exists() and files["marker"].exists()
    assert docker.images == {IMAGE, BROWSER}
    assert not any(command[:2] == ("container", "stop") for command in docker.commands)


def test_seccomp_same_size_swap_between_sha_check_and_effective_read_never_deletes(
    case: tuple[FakeDocker, dict[str, object], dict[str, Path]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docker, marker, files = case
    changed = files["seccomp"].read_text().replace("SCMP_ACT_ERRNO", "SCMP_ACT_ALLOW")
    assert len(changed.encode()) == files["seccomp"].stat().st_size
    docker.seccomp_profile = '{"defaultAction":"SCMP_ACT_ALLOW","syscalls":[]}'
    original_read = cleanup._browser_ipc_read_private
    seccomp_reads = 0

    def swap_after_two_good_reads(path: Path, metadata: os.stat_result, limit: int) -> bytes:
        nonlocal seccomp_reads
        if path == files["seccomp"]:
            seccomp_reads += 1
            # Initial _browser_ipc_stages + nested _browser_ipc_stage both pass
            # the reviewed SHA. Replace in place immediately before the
            # effective JSON read, preserving owner, inode and byte count.
            if seccomp_reads == 3:
                path.write_text(changed)
        return original_read(path, metadata, limit)

    monkeypatch.setattr(cleanup, "_browser_ipc_read_private", swap_after_two_good_reads)
    with pytest.raises(cleanup.CleanupError):
        run_cleanup(marker)
    assert seccomp_reads == 3
    assert files["marker"].exists() and files["seccomp"].exists()
    assert docker.images == {IMAGE, BROWSER} and docker.volumes == PERSISTENT | {IPC_VOLUME}
    assert not any(
        command[:2] in {("container", "stop"), ("container", "rm")} for command in docker.commands
    )


def test_large_exact_worker_inspect_remains_bounded_without_general_relaxation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout="x" * 20_000, stderr="")

    monkeypatch.setattr(cleanup.subprocess, "run", fake_run)
    assert len(cleanup._run("container", "inspect", "--format", "{{json .}}", WORKER)) == 20_000
    with pytest.raises(cleanup.CleanupError, match="bounded output"):
        cleanup._run("volume", "inspect", "--format", "{{json .}}", IPC_VOLUME)
    with pytest.raises(cleanup.CleanupError, match="bounded output"):
        cleanup._run("container", "inspect", "--format", "{{json .}}", "bad-id")


def test_mid_cleanup_error_is_indeterminate_and_does_not_retry(
    case: tuple[FakeDocker, dict[str, object], dict[str, Path]],
) -> None:
    docker, marker, files = case
    docker.mutate_then_fail = True
    with pytest.raises(cleanup.CleanupIndeterminate):
        run_cleanup(marker)
    assert files["marker"].exists()
    assert docker.volumes == PERSISTENT | {IPC_VOLUME}
    assert docker.images == {IMAGE, BROWSER}
    assert docker.network
    assert sum(cmd[:2] == ("container", "rm") for cmd in docker.commands) == 1


@pytest.mark.parametrize("when", ["before-recheck", "before-remove"])
def test_reused_bridge_name_cannot_remove_replacement_network(
    case: tuple[FakeDocker, dict[str, object], dict[str, Path]],
    when: str,
) -> None:
    docker, marker, files = case
    docker.containers = {}  # No mutations may precede the bridge gate.
    docker.replace_before_recheck = when == "before-recheck"
    docker.replace_before_remove = when == "before-remove"
    expected = cleanup.CleanupError if when == "before-recheck" else cleanup.CleanupIndeterminate
    with pytest.raises(expected):
        run_cleanup(marker)
    assert docker.network and docker.network_id == "f" * 64
    assert files["marker"].exists()
    assert docker.images == {IMAGE, BROWSER} and docker.volumes == PERSISTENT | {IPC_VOLUME}
    assert not any(
        command[:2] in {("image", "rm"), ("volume", "rm")} for command in docker.commands
    )
    if when == "before-remove":
        assert ("network", "rm", "a" * 64) in docker.commands
        assert ("network", "rm", NETWORK) not in docker.commands
    else:
        assert not any(command[:2] == ("network", "rm") for command in docker.commands)


@pytest.mark.parametrize("replacement", ["fifo", "symlink"])
def test_marker_swapped_between_lstat_and_open_refuses_without_blocking(
    case: tuple[FakeDocker, dict[str, object], dict[str, Path]],
    monkeypatch: pytest.MonkeyPatch,
    replacement: str,
) -> None:
    docker, marker, files = case
    marker_path = files["marker"]
    original_open = os.open
    did_swap = False

    def swap_during_open(path: str | os.PathLike[str], flags: int, *args: object) -> int:
        nonlocal did_swap
        if Path(path) == marker_path and not did_swap:
            did_swap = True
            assert flags & os.O_NONBLOCK and flags & os.O_NOFOLLOW
            marker_path.unlink()
            if replacement == "fifo":
                os.mkfifo(marker_path, mode=0o600)
            else:
                marker_path.symlink_to(files["base"])
        return original_open(path, flags, *args)

    monkeypatch.setattr(os, "open", swap_during_open)
    with pytest.raises(cleanup.CleanupError):
        run_cleanup(marker)
    assert did_swap
    assert not docker.commands
    assert docker.images == {IMAGE, BROWSER} and docker.network


def test_fifo_marker_is_rejected_before_opening(
    case: tuple[FakeDocker, dict[str, object], dict[str, Path]],
) -> None:
    docker, marker, files = case
    files["marker"].unlink()
    os.mkfifo(files["marker"], mode=0o600)
    with pytest.raises(cleanup.CleanupError):
        run_cleanup(marker)
    assert not docker.commands


def test_ambiguous_marker_duplicate_key_never_deletes(
    case: tuple[FakeDocker, dict[str, object], dict[str, Path]],
) -> None:
    docker, marker, files = case
    raw = files["marker"].read_text()
    files["marker"].write_text(raw.replace('"version":', '"version":"not-reviewed","version":'))
    with pytest.raises(cleanup.CleanupError):
        run_cleanup(marker)
    assert not docker.commands


def test_cli_rejects_invalid_arity_before_any_docker_operation(
    case: tuple[FakeDocker, dict[str, object], dict[str, Path]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    docker, marker, _ = case
    assert cleanup.main(["--browser-ipc-v2", IMAGE, SOURCE, str(marker["beta_compose_sha"])]) == 1
    assert not docker.commands
    assert "BOCA_CLEANUP_NO_GO" in capsys.readouterr().err
    assert cleanup.main([IMAGE, SOURCE, str(marker["beta_compose_sha"]), BROWSER]) == 1
    assert not docker.commands


def test_cli_indeterminate_requires_manual_review_without_browser_retry(
    case: tuple[FakeDocker, dict[str, object], dict[str, Path]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, marker, _ = case

    def uncertain(*_args: object) -> None:
        raise cleanup.CleanupIndeterminate("simulated mid-operation failure")

    monkeypatch.setattr(cleanup, "clean_failed_browser_ipc_install", uncertain)
    assert (
        cleanup.main(
            [
                "--browser-ipc-v2",
                IMAGE,
                SOURCE,
                str(marker["beta_compose_sha"]),
                BROWSER,
                str(marker["overlay_compose_sha"]),
                str(marker["seccomp_sha"]),
                ATTEMPT,
            ]
        )
        == 1
    )
    output = capsys.readouterr().err
    assert "BOCA_BROWSER_IPC_CLEANUP_INDETERMINATE" in output
    assert "do not retry automatically" in output
