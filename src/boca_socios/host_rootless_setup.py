"""First-time preparation of Boca's user daemon, never application installation.

Streamed only by the protected workflow. Existing configuration and data are
preserved. Failure after a write is partial state requiring a separate review.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

UID = 10001
RUNTIME = Path("/run/user/10001")
DATA = (".local", "share", "docker")
CONFIG = (".config", "docker", "daemon.json")
UNIT = (".config", "systemd", "user", "docker.service")
ENABLE = (".config", "systemd", "user", "default.target.wants", "docker.service")


class SetupError(ValueError):
    """Only fixed diagnostic reasons leave the host."""


def _identity() -> Path:
    if os.getuid() != UID or os.geteuid() != UID or os.getgid() != os.getegid():
        raise SetupError("dedicated_identity_required")
    account = pwd.getpwuid(UID)
    if account.pw_name != "boca-deploy" or not re.fullmatch(r"/[A-Za-z0-9_/-]+", account.pw_dir):
        raise SetupError("dedicated_account_required")
    home = Path(account.pw_dir)
    if home.anchor != "/" or home == Path("/") or ".." in home.parts:
        raise SetupError("home_unsafe")
    return home


def _directory(home: Path, relative: tuple[str, ...], *, create: bool) -> int | None:
    """Return a private directory FD, never following or replacing a component."""
    if (
        home.anchor != "/"
        or home == Path("/")
        or ".." in home.parts
        or len(home.parts) > 24
        or len(str(home)) > 4096
        or any(part in {"", ".", ".."} or "/" in part for part in relative)
    ):
        raise SetupError("directory_path_unsafe")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open("/", flags)
    transferred = False
    try:
        for index, part in enumerate((*home.parts[1:], *relative), 1):
            own = index >= len(home.parts) - 1
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if index < len(home.parts) or not create:
                    return None
                os.mkdir(part, mode=0o700, dir_fd=descriptor)
                child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            metadata = os.fstat(descriptor)
            if (
                metadata.st_uid != (UID if own else 0)
                or stat.S_IMODE(metadata.st_mode) & 0o022
                or (index == len(home.parts) - 1 and stat.S_IMODE(metadata.st_mode) != 0o700)
            ):
                raise SetupError("directory_owner_or_mode_unsafe")
        transferred = True
        return descriptor
    except OSError as exc:
        raise SetupError("directory_inaccessible_or_redirected") from exc
    finally:
        if not transferred:
            os.close(descriptor)


def _entry(home: Path, relative: tuple[str, ...]) -> os.stat_result | None:
    descriptor = _directory(home, relative[:-1], create=False)
    if descriptor is None:
        return None
    try:
        try:
            return os.stat(relative[-1], dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return None
    finally:
        os.close(descriptor)


def _absent(home: Path, relative: tuple[str, ...]) -> None:
    if _entry(home, relative) is not None:
        raise SetupError("existing_configuration_or_data_preserved")


def _empty_data_root(home: Path) -> None:
    descriptor = _directory(home, DATA, create=False)
    if descriptor is None:
        return
    try:
        with os.scandir(descriptor) as entries:
            if next(entries, None) is not None:
                raise SetupError("existing_docker_data_preserved")
    finally:
        os.close(descriptor)


def _write_new(home: Path, relative: tuple[str, ...], content: str) -> None:
    parent = _directory(home, relative[:-1], create=True)
    if parent is None:
        raise SetupError("private_parent_unavailable")
    try:
        descriptor = os.open(
            relative[-1],
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.fsync(parent)
    finally:
        os.close(parent)


def _enable_new(home: Path) -> None:
    parent = _directory(home, ENABLE[:-1], create=True)
    if parent is None:
        raise SetupError("private_enable_parent_unavailable")
    try:
        os.symlink("../docker.service", ENABLE[-1], dir_fd=parent)
        os.fsync(parent)
    finally:
        os.close(parent)


def _environment(home: Path) -> dict[str, str]:
    return {
        "HOME": str(home),
        "USER": "boca-deploy",
        "LOGNAME": "boca-deploy",
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "LC_ALL": "C",
        "XDG_RUNTIME_DIR": str(RUNTIME),
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={RUNTIME}/bus",
        "DOCKER_HOST": f"unix://{RUNTIME}/docker.sock",
        "DOCKER_CONFIG": str(home / ".config/boca-empty-docker-client"),
    }


def _command_reason(command: tuple[str, ...]) -> str:
    if command[0] == "/usr/bin/systemctl":
        return {
            "start": "user_service_start_failed",
            "stop": "user_service_stop_failed",
            "daemon-reload": "user_manager_reload_failed",
        }.get(command[2], "user_service_metadata_failed")
    if command[0] == "/usr/bin/docker" and len(command) > 2 and command[2] == "stop":
        return "boca_container_stop_failed"
    return {
        "/usr/bin/loginctl": "dedicated_linger_query_failed",
        "/usr/bin/rootlesskit": "rootless_namespace_failed",
        "/usr/bin/dockerd": "daemon_config_validation_failed",
        "/usr/bin/docker": "private_daemon_metadata_failed",
    }.get(command[0], "dedicated_command_failed")


def _command(home: Path, *command: str, timeout: int = 15) -> str:
    reason = _command_reason(command)
    try:
        result = subprocess.run(  # noqa: S603 - fixed reviewed commands, no shell
            command,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_environment(home),
            timeout=timeout,
        )
    except subprocess.CalledProcessError as exc:
        raise SetupError(f"{reason}_exit_{exc.returncode}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SetupError(f"{reason}_timeout") from exc
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise SetupError(f"{reason}_unavailable") from exc
    if len(result.stdout) > 65536:
        raise SetupError("dedicated_command_output_unbounded")
    return result.stdout.strip()


def _read_fixed(path: str, limit: int = 1_048_576) -> str:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(descriptor, "r", encoding="ascii") as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise SetupError("prerequisite_file_unsafe")
        if path.startswith("/etc/") and (
            metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise SetupError("subordinate_id_file_unsafe")
        text = source.read(limit + 1)
    if len(text) > limit:
        raise SetupError("prerequisite_metadata_unbounded")
    return text


def _subordinate_ids(text: str) -> tuple[int, int]:
    matches = [
        line.split(":")
        for line in text.splitlines()
        if line.split(":", 1)[0] in {"boca-deploy", "10001"}
    ]
    if len(matches) != 1 or len(matches[0]) != 3:
        raise SetupError("dedicated_subordinate_ids_required")
    try:
        start, count = map(int, matches[0][1:])
    except ValueError as exc:
        raise SetupError("dedicated_subordinate_ids_required") from exc
    if start <= UID or count < 65536 or start + count > 2**32:
        raise SetupError("dedicated_subordinate_ids_required")
    return start, count


def _binary(path: str) -> None:
    try:
        metadata = Path(path).lstat()
    except OSError as exc:
        raise SetupError(f"fixed_binary_{Path(path).name}_unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or not os.access(path, os.X_OK)
    ):
        raise SetupError("trusted_existing_binary_required")


def _socket(path: Path) -> None:
    metadata = path.lstat()
    if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != UID:
        raise SetupError("private_socket_required")


def _capacity(home: Path, phase: str) -> None:
    descriptor = None
    for depth in range(len(DATA), -1, -1):
        descriptor = _directory(home, DATA[:depth], create=False)
        if descriptor is not None:
            break
    if descriptor is None:
        raise SetupError("capacity_path_unavailable")
    try:
        capacity = os.fstatvfs(descriptor)
    finally:
        os.close(descriptor)
    print(
        f"BOCA_ROOTLESS_CAPACITY phase={phase}"
        f" free_bytes={capacity.f_bavail * capacity.f_frsize} free_inodes={capacity.f_favail}"
        " application_budget=not_checked"
    )


def _preflight() -> Path:
    home = _identity()
    for anchor in (home, RUNTIME):
        descriptor = _directory(anchor, (), create=False)
        if descriptor is None:
            raise SetupError("private_directory_required")
        os.close(descriptor)
    _socket(RUNTIME / "systemd/private")
    _socket(RUNTIME / "bus")
    if os.access("/var/run/docker.sock", os.W_OK):
        raise SetupError("rootful_access_forbidden")
    _absent(RUNTIME, ("docker.sock",))
    _absent(RUNTIME, ("dockerd-rootless",))
    _absent(RUNTIME, ("containerd-rootless",))
    for relative in (
        CONFIG,
        UNIT,
        ENABLE,
        (*UNIT[:-1], "docker.service.d"),
        (".config", "boca-empty-docker-client"),
    ):
        _absent(home, relative)
    _empty_data_root(home)
    for name in (
        "env",
        "true",
        "systemctl",
        "loginctl",
        "docker",
        "dockerd",
        "dockerd-rootless.sh",
        "rootlesskit",
    ):
        _binary(f"/usr/bin/{name}")
    for name in ("newuidmap", "newgidmap"):
        _binary(f"/usr/bin/{name}")
    _subordinate_ids(_read_fixed("/etc/subuid"))
    _subordinate_ids(_read_fixed("/etc/subgid"))
    if int(_read_fixed("/proc/sys/user/max_user_namespaces", 64).strip()) < 1:
        raise SetupError("user_namespaces_required")
    controllers = _read_fixed(
        "/sys/fs/cgroup/user.slice/user-10001.slice/user@10001.service/cgroup.controllers", 1024
    ).split()
    if not {"cpu", "memory", "pids"} <= set(controllers):
        raise SetupError("dedicated_cgroup_delegation_required")
    linger = _command(
        home, "/usr/bin/loginctl", "show-user", "10001", "--property=Linger", "--value"
    )
    if linger != "yes":
        raise SetupError("dedicated_linger_requires_privileged_operator")
    state = _command(
        home,
        "/usr/bin/systemctl",
        "--user",
        "show",
        "docker.service",
        "--property=LoadState",
        "--value",
    )
    if state != "not-found":
        raise SetupError("existing_user_service_preserved")
    _capacity(home, "before")
    return home


def _namespace_smoke(home: Path) -> None:
    # Namespace smoke is separate and cannot be bypassed by an install --force.
    _command(home, "/usr/bin/rootlesskit", "--net=none", "/usr/bin/true")


def _service_failure_receipt(home: Path) -> None:
    try:
        raw = _command(
            home,
            "/usr/bin/systemctl",
            "--user",
            "show",
            "docker.service",
            "--property=Result,ExecMainStatus",
        )
        pairs = [line.split("=", 1) for line in raw.splitlines()]
        if len(pairs) != 2 or any(len(pair) != 2 for pair in pairs):
            raise SetupError("service_failure_metadata_invalid")
        fields = dict(pairs)
        result = fields.get("Result")
        status = fields.get("ExecMainStatus", "")
        if (
            set(fields) != {"Result", "ExecMainStatus"}
            or result
            not in {
                "success",
                "resources",
                "timeout",
                "exit-code",
                "signal",
                "core-dump",
                "watchdog",
                "start-limit-hit",
                "oom-kill",
                "protocol",
                "exec-condition",
            }
            or not re.fullmatch(r"[0-9]{1,3}", status)
            or int(status) > 255
        ):
            raise SetupError("service_failure_metadata_invalid")
        print(f"BOCA_ROOTLESS_SERVICE_FAILURE result={result} exit_status={int(status)}")
    except (SetupError, OSError, ValueError, TypeError):
        print("BOCA_ROOTLESS_SERVICE_FAILURE metadata=UNVERIFIED")


def _unit() -> str:
    return """[Unit]
Description=Boca dedicated rootless Docker
After=dbus.socket
[Service]
Type=exec
ExecStart=/usr/bin/env -i HOME=%h USER=boca-deploy LOGNAME=boca-deploy PATH=/usr/bin:/bin:/usr/sbin:/sbin XDG_RUNTIME_DIR=/run/user/10001 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/10001/bus /usr/bin/dockerd-rootless.sh --config-file=%h/.config/docker/daemon.json
Restart=no
TimeoutStartSec=45
TimeoutStopSec=30
Delegate=yes
KillMode=mixed
TasksMax=infinity
[Install]
WantedBy=default.target
"""


def _config(home: Path) -> str:
    return (
        json.dumps(
            {
                "hosts": [f"unix://{RUNTIME}/docker.sock"],
                "data-root": str(home.joinpath(*DATA)),
                "exec-root": f"{RUNTIME}/docker",
                "pidfile": f"{RUNTIME}/docker.pid",
                "storage-driver": "overlay2",
                "features": {"containerd-snapshotter": False},
                "exec-opts": ["native.cgroupdriver=systemd"],
            },
            sort_keys=True,
        )
        + "\n"
    )


def _postflight(home: Path) -> None:
    for attempt in range(30):
        try:
            _socket(RUNTIME / "docker.sock")
            break
        except FileNotFoundError:
            if attempt == 29:
                raise SetupError("dedicated_socket_startup_timeout") from None
            time.sleep(0.5)
    _socket(RUNTIME / "docker.sock")
    if os.access("/var/run/docker.sock", os.W_OK):
        raise SetupError("rootful_access_forbidden")
    state = _command(
        home,
        "/usr/bin/systemctl",
        "--user",
        "show",
        "docker.service",
        "--property=ActiveState,SubState",
    )
    if set(state.splitlines()) != {"ActiveState=active", "SubState=running"}:
        raise SetupError("dedicated_service_not_running")
    raw = _command(
        home,
        "/usr/bin/docker",
        "--host=unix:///run/user/10001/docker.sock",
        "info",
        "--format",
        "{{json .}}",
    )
    info = json.loads(raw)
    options = info.get("SecurityOptions") if isinstance(info, dict) else None
    if (
        not isinstance(info, dict)
        or not isinstance(options, list)
        or not all(isinstance(value, str) for value in options)
        or "name=rootless" not in options
        or info.get("CgroupVersion") != "2"
        or info.get("CgroupDriver") != "systemd"
        or info.get("Driver") != "overlay2"
        or info.get("DockerRootDir") != str(home.joinpath(*DATA))
        or type(info.get("Containers")) is not int
        or info.get("Containers") != 0
    ):
        raise SetupError("rootless_daemon_boundary_unproven")
    descriptor = _directory(home, DATA, create=False)
    if descriptor is None:
        raise SetupError("dedicated_data_root_unproven")
    os.close(descriptor)
    for kind in ("volume", "network"):
        if _command(
            home,
            "/usr/bin/docker",
            "--host=unix:///run/user/10001/docker.sock",
            kind,
            "ls",
            "-q",
            "--filter",
            "name=^boca-socios_",
        ):
            raise SetupError("existing_boca_namespace_preserved")
    _capacity(home, "after")


def prepare(phase: str, source_sha: str) -> None:
    if phase not in {"check", "apply"} or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise SetupError("invalid_setup_coordinates")
    home = _preflight()
    if phase == "check":
        print(
            f"BOCA_ROOTLESS_SETUP state=PREPARED_FOR_REVIEW source_sha={source_sha}"
            " application_database=not_accessed"
        )
        return
    _namespace_smoke(home)
    _write_new(home, CONFIG, _config(home))
    _command(home, "/usr/bin/dockerd", "--validate", f"--config-file={home.joinpath(*CONFIG)}")
    _write_new(home, UNIT, _unit())
    _command(home, "/usr/bin/systemctl", "--user", "daemon-reload")
    effective = _command(
        home,
        "/usr/bin/systemctl",
        "--user",
        "show",
        "docker.service",
        "--property=FragmentPath,DropInPaths",
    )
    if set(effective.splitlines()) != {f"FragmentPath={home.joinpath(*UNIT)}", "DropInPaths="}:
        raise SetupError("effective_unit_override_preserved_no_start")
    _empty_data_root(home)
    try:
        _command(home, "/usr/bin/systemctl", "--user", "start", "docker.service", timeout=50)
        _postflight(home)
        _enable_new(home)
    except (SetupError, OSError, ValueError, TypeError, KeyError):
        _service_failure_receipt(home)
        try:
            _command(home, "/usr/bin/systemctl", "--user", "stop", "docker.service", timeout=35)
        except SetupError:
            print("BOCA_ROOTLESS_SETUP_STOP state=UNVERIFIED files=retained", file=sys.stderr)
        raise
    print(
        f"BOCA_ROOTLESS_SETUP state=SERVICE_READY source_sha={source_sha}"
        " application_database=not_accessed application=not_installed"
    )


def _read_private(home: Path, relative: tuple[str, ...], expected: str) -> None:
    """Verify the two files this helper created without following a redirect."""
    parent = _directory(home, relative[:-1], create=False)
    if parent is None:
        raise SetupError("reviewed_service_configuration_missing")
    try:
        fd = os.open(relative[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        with os.fdopen(fd, "r", encoding="utf-8") as source:
            metadata = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != UID
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_size > 4096
            ):
                raise SetupError("reviewed_service_configuration_unsafe")
            actual = source.read(4097)
        if actual != expected:
            raise SetupError("reviewed_service_configuration_mismatch")
    except OSError as exc:
        raise SetupError("reviewed_service_configuration_unavailable") from exc
    finally:
        os.close(parent)


def _stop_service_state(home: Path) -> str:
    raw = _command(
        home,
        "/usr/bin/systemctl",
        "--user",
        "show",
        "docker.service",
        "--property=FragmentPath,DropInPaths,ActiveState,SubState,MainPID",
    )
    pairs = [line.split("=", 1) for line in raw.splitlines()]
    if len(pairs) != 5 or any(len(pair) != 2 for pair in pairs):
        raise SetupError("dedicated_service_state_unverified")
    fields = dict(pairs)
    if (
        len(fields) != 5
        or fields.get("FragmentPath") != str(home.joinpath(*UNIT))
        or fields.get("DropInPaths") != ""
    ):
        raise SetupError("effective_unit_override_preserved_no_stop")
    if fields.get("ActiveState") == "inactive" and fields.get("SubState") == "dead":
        if fields.get("MainPID") != "0":
            raise SetupError("dedicated_service_state_unverified")
        return "inactive"
    if fields.get("ActiveState") == "active" and fields.get("SubState") == "running":
        if not re.fullmatch(r"[1-9][0-9]{0,9}", fields.get("MainPID", "")):
            raise SetupError("dedicated_service_state_unverified")
        return "active"
    raise SetupError("dedicated_service_state_unverified")


def _stop_test_containers(home: Path) -> int:
    endpoint = "--host=unix:///run/user/10001/docker.sock"
    raw = _command(home, "/usr/bin/docker", endpoint, "info", "--format", "{{json .}}")
    info = json.loads(raw)
    if (
        not isinstance(info, dict)
        or not isinstance(info.get("SecurityOptions"), list)
        or "name=rootless" not in info["SecurityOptions"]
        or info.get("DockerRootDir") != str(home.joinpath(*DATA))
        or info.get("CgroupVersion") != "2"
        or info.get("CgroupDriver") != "systemd"
        or info.get("Driver") != "overlay2"
        or type(info.get("Containers")) is not int
        or not 0 <= info["Containers"] <= 12
    ):
        raise SetupError("rootless_daemon_boundary_unproven")
    raw_ids = _command(home, "/usr/bin/docker", endpoint, "ps", "-aq", "--no-trunc")
    ids = raw_ids.splitlines() if raw_ids else []
    if (
        len(ids) != info["Containers"]
        or len(set(ids)) != len(ids)
        or any(not re.fullmatch(r"[0-9a-f]{64}", item) for item in ids)
    ):
        raise SetupError("dedicated_container_inventory_unverified")
    running: list[str] = []
    for container_id in ids:
        record = json.loads(
            _command(
                home, "/usr/bin/docker", endpoint, "inspect", "--format", "{{json .}}", container_id
            )
        )
        config = record.get("Config") if isinstance(record, dict) else None
        labels = config.get("Labels") if isinstance(config, dict) else None
        state = record.get("State") if isinstance(record, dict) else None
        service = labels.get("com.docker.compose.service") if isinstance(labels, dict) else None
        number = (
            labels.get("com.docker.compose.container-number") if isinstance(labels, dict) else None
        )
        if (
            not isinstance(record, dict)
            or record.get("Id") != container_id
            or not isinstance(labels, dict)
            or labels.get("com.docker.compose.project") != "boca-socios"
            or service not in {"controller", "browser", "proxy"}
            or not isinstance(number, str)
            or not re.fullmatch(r"[1-9][0-9]{0,2}", number)
            or record.get("Name") != f"/boca-socios-{service}-{number}"
            or not isinstance(state, dict)
            or type(state.get("Running")) is not bool
        ):
            raise SetupError("unknown_container_preserved_no_stop")
        if state["Running"]:
            running.append(container_id)
    # Complete the inventory before the first effect. Never stop an unknown container.
    for container_id in running:
        _command(
            home, "/usr/bin/docker", endpoint, "stop", "--time", "10", container_id, timeout=25
        )
    for container_id in ids:
        record = json.loads(
            _command(
                home, "/usr/bin/docker", endpoint, "inspect", "--format", "{{json .}}", container_id
            )
        )
        state = record.get("State") if isinstance(record, dict) else None
        if (
            not isinstance(record, dict)
            or record.get("Id") != container_id
            or not isinstance(state, dict)
            or state.get("Running") is not False
        ):
            raise SetupError("boca_container_stop_unverified")
    after = json.loads(
        _command(home, "/usr/bin/docker", endpoint, "info", "--format", "{{json .}}")
    )
    after_ids = _command(home, "/usr/bin/docker", endpoint, "ps", "-aq", "--no-trunc")
    if (
        not isinstance(after, dict)
        or type(after.get("Containers")) is not int
        or after.get("Containers") != len(ids)
        or len(after_ids.splitlines() if after_ids else []) != len(ids)
        or set(after_ids.splitlines() if after_ids else []) != set(ids)
    ):
        raise SetupError("dedicated_container_inventory_changed_no_daemon_stop")
    return len(running)


def stop_test(source_sha: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise SetupError("invalid_stop_coordinates")
    home = _identity()
    for anchor in (home, RUNTIME):
        descriptor = _directory(anchor, (), create=False)
        if descriptor is None:
            raise SetupError("private_directory_required")
        os.close(descriptor)
    _socket(RUNTIME / "systemd/private")
    _socket(RUNTIME / "bus")
    if os.access("/var/run/docker.sock", os.W_OK):
        raise SetupError("rootful_access_forbidden")
    _read_private(home, CONFIG, _config(home))
    _read_private(home, UNIT, _unit())
    state = _stop_service_state(home)
    if state == "inactive":
        if _entry(RUNTIME, ("docker.sock",)) is not None:
            raise SetupError("stale_dedicated_socket_unverified")
        print(
            f"BOCA_STOP_TEST state=ALREADY_STOPPED source_sha={source_sha} containers=not_queried data=preserved"
        )
        return
    _socket(RUNTIME / "docker.sock")
    stopped = _stop_test_containers(home)
    _command(home, "/usr/bin/systemctl", "--user", "stop", "docker.service", timeout=35)
    if _stop_service_state(home) != "inactive":
        raise SetupError("dedicated_service_stop_unverified")
    for attempt in range(10):
        if _entry(RUNTIME, ("docker.sock",)) is None:
            break
        if attempt == 9:
            raise SetupError("dedicated_socket_stop_unverified")
        time.sleep(0.2)
    print(
        f"BOCA_STOP_TEST state=STOPPED source_sha={source_sha} containers={stopped} data=preserved"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Boca dedicated rootless service preparation")
    parser.add_argument("phase", choices=("check", "apply", "stop-test"))
    parser.add_argument("source_sha")
    args = parser.parse_args()
    prefix = "BOCA_STOP_TEST" if args.phase == "stop-test" else "BOCA_ROOTLESS_SETUP"
    try:
        if args.phase == "stop-test":
            stop_test(args.source_sha)
        else:
            prepare(args.phase, args.source_sha)
    except SetupError as exc:
        print(
            f"{prefix} state=NO_GO reason={exc} files=preserved_or_partial"
            " enablement=UNVERIFIED application_database=not_accessed",
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError, TypeError, KeyError):
        print(
            f"{prefix} state=NO_GO reason=metadata_or_io_unavailable"
            " files=preserved_or_partial enablement=UNVERIFIED application_database=not_accessed",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
