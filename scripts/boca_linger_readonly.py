"""Boca UID10001-only rootless prerequisites; streamed by existing manual Action.

No Docker socket connection, service activation, filesystem write, or arbitrary
path input. All output is a small fixed-vocabulary receipt without raw paths.
"""

from __future__ import annotations

import errno
import os
import pwd
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

UID = 10001
ACCOUNT = "boca-deploy"
HOME = Path("/home/boca-deploy")
RUNTIME = Path("/run/user/10001")
LINGER_MARKER = Path("/var/lib/systemd/linger/boca-deploy")
MAX_SUBID_BYTES = 1_048_576


class IdentityError(ValueError):
    """The dedicated Unix identity did not match the Boca-only contract."""


@dataclass(frozen=True)
class Metadata:
    state: str
    uid: int | None = None
    gid: int | None = None
    mode: int | None = None


def _dedicated_home() -> Path:
    # Never even inspect system files before checking the effective identity.
    if (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (UID,) * 4:
        raise IdentityError("dedicated identity required")
    try:
        account = pwd.getpwuid(UID)
    except (OSError, KeyError) as exc:
        raise IdentityError("dedicated account unavailable") from exc
    raw = account.pw_dir
    if (
        account.pw_name != ACCOUNT
        or account.pw_gid != UID
        or not isinstance(raw, str)
        or re.fullmatch(r"/[A-Za-z0-9_/-]{1,256}", raw) is None
        or ".." in Path(raw).parts
        or raw.startswith("//")
        or len(Path(raw).parts) > 24
        or Path(raw) != HOME
    ):
        raise IdentityError("dedicated account metadata unverified")
    return Path(raw)


def _fixed_metadata(path: Path) -> Metadata:
    """Stat one fixed path through directory descriptors, never follow links."""
    if (
        not path.is_absolute()
        or path == Path("/")
        or ".." in path.parts
        or len(path.parts) > 32
        or len(str(path)) > 4096
    ):
        return Metadata("UNSAFE")
    descriptor: int | None = None
    try:
        flags = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptor = os.open("/", flags)
        for part in path.parts[1:-1]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        info = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
        kind = (
            "DIRECTORY"
            if stat.S_ISDIR(info.st_mode)
            else "SOCKET"
            if stat.S_ISSOCK(info.st_mode)
            else "REGULAR"
            if stat.S_ISREG(info.st_mode)
            else "UNSAFE"
        )
        return Metadata(kind, info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))
    except FileNotFoundError:
        return Metadata("ABSENT")
    except PermissionError:
        return Metadata("UNAVAILABLE")
    except OSError as exc:
        return Metadata("UNSAFE" if exc.errno in {errno.ELOOP, errno.ENOTDIR} else "UNAVAILABLE")
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _linger() -> str:
    try:
        result = subprocess.run(  # noqa: S603 - single fixed read-only logind query
            (
                "/usr/bin/loginctl",
                "--no-ask-password",
                "show-user",
                "10001",
                "--property=Linger",
                "--value",
            ),
            check=False,
            text=True,
            encoding="ascii",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            timeout=5,
        )
        if result.returncode == 0:
            return {"yes\n": "YES", "no\n": "NO"}.get(result.stdout, "UNKNOWN")
    except (OSError, subprocess.SubprocessError, UnicodeError):
        pass
    return "UNKNOWN"


def _parse_subids(raw: str) -> str:
    # Do not expose or evaluate other accounts' ranges.
    entries = [
        line.split(":") for line in raw.splitlines() if line.split(":", 1)[0] in {ACCOUNT, str(UID)}
    ]
    if len(entries) != 1 or len(entries[0]) != 3:
        return "INVALID"
    start, count = entries[0][1:]
    if re.fullmatch(r"[0-9]{1,10}", start) is None or re.fullmatch(r"[0-9]{1,10}", count) is None:
        return "INVALID"
    first, quantity = int(start), int(count)
    return "VALID" if first > UID and quantity >= 65536 and first + quantity <= 2**32 else "INVALID"


def _subids(kind: str) -> str:
    if kind not in {"subuid", "subgid"}:
        return "UNKNOWN"
    descriptor: int | None = None
    try:
        descriptor = os.open(f"/etc/{kind}", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) & 0o022
            or not 0 <= info.st_size <= MAX_SUBID_BYTES
        ):
            return "UNKNOWN"
        data = os.read(descriptor, MAX_SUBID_BYTES + 1)
        if len(data) > MAX_SUBID_BYTES:
            return "UNKNOWN"
        return _parse_subids(data.decode("ascii"))
    except (OSError, UnicodeError, ValueError):
        return "UNKNOWN"
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _binary(name: str) -> str:
    if name not in {"newuidmap", "newgidmap"}:
        return "UNKNOWN"
    path = f"/usr/bin/{name}"
    info = _fixed_metadata(Path(path))
    if (
        info.state == "REGULAR"
        and info.uid == 0
        and info.mode is not None
        and not info.mode & 0o022
        and os.access(path, os.X_OK)
    ):
        return "AVAILABLE"
    return "UNAVAILABLE" if info.state == "ABSENT" else "UNKNOWN"


def _userns() -> str:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            "/proc/sys/user/max_user_namespaces", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        raw = os.read(descriptor, 32).decode("ascii")
        if re.fullmatch(r"[0-9]{1,12}\n?", raw):
            return "AVAILABLE" if int(raw) > 0 else "DISABLED"
    except (OSError, UnicodeError, ValueError):
        pass
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return "UNKNOWN"


def _dir(meta: Metadata) -> str:
    if meta.state == "DIRECTORY":
        return "PRIVATE" if (meta.uid, meta.gid, meta.mode) == (UID, UID, 0o700) else "UNSAFE"
    return meta.state


def _socket(meta: Metadata, *, systemd_default: bool = False) -> str:
    if meta.state == "SOCKET":
        if meta.uid != UID or meta.mode is None:
            return "UNSAFE"
        if not meta.mode & 0o200:
            return "NO_OWNER_WRITE"
        # systemd.socket defaults to 0666; user bus / manager sockets under
        # a verified 0700 runtime are not unsafe merely for this mode.
        if systemd_default and meta.mode == 0o666:
            return "SYSTEMD_DEFAULT"
        # Docker's socket must be separately non-world-writable. Its
        # supplementary GID (e.g. 166523) is reported, not rejected.
        return "OPEN_MODE" if meta.mode & 0o002 else "OWNED"
    return meta.state


def _fields(prefix: str, meta: Metadata) -> str:
    return (
        f"{prefix}_uid={meta.uid if meta.uid is not None else 'UNKNOWN'}"
        f" {prefix}_gid={meta.gid if meta.gid is not None else 'UNKNOWN'}"
        f" {prefix}_mode={meta.mode:04o}"
        if meta.mode is not None
        else f"{prefix}_uid=UNKNOWN {prefix}_gid=UNKNOWN {prefix}_mode=UNKNOWN"
    )


def collect() -> tuple[list[str], str]:
    home = _dedicated_home()
    home_stat, runtime = _fixed_metadata(home), _fixed_metadata(RUNTIME)
    manager = _fixed_metadata(RUNTIME / "systemd/private")
    bus = _fixed_metadata(RUNTIME / "bus")
    docker = _fixed_metadata(RUNTIME / "docker.sock")
    marker = _fixed_metadata(LINGER_MARKER)
    data_root = _fixed_metadata(home / ".local/share/docker")
    user_unit = _fixed_metadata(home / ".config/systemd/user/docker.service")
    linger = _linger()
    subuid, subgid = _subids("subuid"), _subids("subgid")
    newuidmap, newgidmap = _binary("newuidmap"), _binary("newgidmap")
    userns = _userns()
    manager_state = _socket(manager, systemd_default=True)
    bus_state = _socket(bus, systemd_default=True)
    docker_state = _socket(docker)
    state = (
        "METADATA_CANDIDATE"
        if linger == "YES"
        and _dir(home_stat) == _dir(runtime) == "PRIVATE"
        and manager_state in {"OWNED", "SYSTEMD_DEFAULT"}
        and bus_state in {"OWNED", "SYSTEMD_DEFAULT"}
        and docker_state == "OWNED"
        and subuid == subgid == "VALID"
        and newuidmap == newgidmap == "AVAILABLE"
        and userns == "AVAILABLE"
        else "PREREQUISITES_UNPROVEN"
    )
    lines = [
        f"BOCA_LINGER_ROOTLESS state={state} identity=OK linger={linger} marker={marker.state}",
        f"BOCA_LINGER_DIR home={_dir(home_stat)} {_fields('home', home_stat)}"
        f" runtime={_dir(runtime)} {_fields('runtime', runtime)}",
        f"BOCA_LINGER_SOCKET manager={manager_state} {_fields('manager', manager)}"
        f" bus={bus_state} {_fields('bus', bus)}"
        f" docker_socket={docker_state} {_fields('docker', docker)}",
        f"BOCA_LINGER_LAYOUT data_root={_dir(data_root)} {_fields('data', data_root)}"
        f" unit={user_unit.state} {_fields('unit', user_unit)}"
        f" marker={marker.state} {_fields('marker', marker)}",
        f"BOCA_LINGER_IDS subuid={subuid} subgid={subgid}"
        f" newuidmap={newuidmap} newgidmap={newgidmap} userns={userns}",
        "BOCA_LINGER_SCOPE docker_queries=0 changes=NONE blackbox=UNTOUCHED"
        " exitcode1_cause=UNKNOWN deploy=NO_GO",
    ]
    return lines, state


def main() -> int:
    try:
        lines, state = collect()
    except IdentityError:
        print("BOCA_LINGER_ROOTLESS state=NO_GO_IDENTITY identity=UNVERIFIED linger=UNKNOWN")
        return 1
    for line in lines:
        print(line)
    return 0 if state == "METADATA_CANDIDATE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
