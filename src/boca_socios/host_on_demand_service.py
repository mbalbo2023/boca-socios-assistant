"""Boca user socket activation. Install/remove run only inside the protected Cutover lease.

A transient systemd instance receives one AF_UNIX stream on stdin. The stream
carries only an existing ledger UUID. Host coordinates come exclusively from
the digest-pinned, operator-owned installation, outside the controller mount.
"""

from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import pwd
import re
import select
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import zipfile
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_lifecycle as lifecycle
from boca_socios.host_boca_cleanup import BocaJobLease
from boca_socios.host_boca_cleanup import verify_protected_boca_job_lease as _verify_lease
from boca_socios.host_lifecycle_rootless_adapter import ReviewedInstalledPair
from boca_socios.panel.lifecycle_intents import canonical_operation_id

if TYPE_CHECKING:
    from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

_HOME = Path("/home/boca-deploy")
_ROOT = ".boca-on-demand"
_SOCKET = "boca-bot-control.socket"
_SERVICE = "boca-bot-control@.service"
_PROBE = "boca-bot-control@fragment.service"
_SOCKET_NAME = "control.sock"
_DB = Path(".local/share/docker/volumes/boca-socios_boca_data/_data/boca.sqlite3")
_MAX_ZIP = 512_000
_MAX_PLAN = 8_192
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_UID = 10001
_MARKER = "attempt"
_BINDING = "binding.json"
_ARCHIVE = "handler.pyz"
_REMOVING = "removing"
_PROPERTIES = ("LoadState", "FragmentPath", "DropInPaths", "ActiveState", "SubState")
_DATA = frozenset({_MARKER, _BINDING, _ARCHIVE, _SOCKET, _SERVICE, _REMOVING, "socket"})
# Only named source bytes from the already-verified Cutover ZIP may become durable.
# Never persist the transaction dispatcher, incident recovery scripts or deployment files.
_RUNTIME_FILES = (
    "boca_socios/__init__.py",
    "boca_socios/host_boca_cleanup.py",
    "boca_socios/host_boca_lifecycle.py",
    "boca_socios/host_lifecycle_rootless_adapter.py",
    "boca_socios/host_first_deploy.py",
    "boca_socios/host_cutover_ipc_probe.py",
    "boca_socios/worker_start_capture.py",
    "boca_socios/host_on_demand_lifecycle.py",
    "boca_socios/host_on_demand_service.py",
    "boca_socios/integration/__init__.py",
    "boca_socios/integration/engine_socket.py",
    "boca_socios/panel/__init__.py",
    "boca_socios/panel/lifecycle_intents.py",
    "boca_socios/storage/__init__.py",
    "boca_socios/storage/migrations/__init__.py",
    *("boca_socios/storage/migrations/" + name for name in lifecycle._MIGRATION_FILES),
)
_MAIN = (
    "import sys\n"
    "from boca_socios.host_on_demand_service import socket_main\n"
    "raise SystemExit(socket_main(sys.argv[2]) if len(sys.argv) == 3 "
    "and sys.argv[1] == 'on-demand-serve' else 3)\n"
).encode("ascii")
# The systemd unit pins BOTH archive and binding SHA. Verify before importing any
# application Python. Execute the same verified anonymous bytes, no writable path reopen.
_LOADER = (
    "import fcntl,hashlib,os,sys; "
    "p,h,b=sys.argv[1:]; "
    "f=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK); "
    "r=os.fdopen(f,'rb').read(512001); "
    "(0<len(r)<=512000 and hashlib.sha256(r).hexdigest()==h) or sys.exit(3); "
    "d=os.memfd_create('boca-control',os.MFD_ALLOW_SEALING); "
    "os.write(d,r)==len(r) or sys.exit(3); "
    "fcntl.fcntl(d,fcntl.F_ADD_SEALS,fcntl.F_SEAL_WRITE|fcntl.F_SEAL_GROW|"
    "fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_SEAL); "
    "os.set_inheritable(d,True); "
    "os.execve('/usr/bin/python3',['/usr/bin/python3','-I','-B','/proc/self/fd/'+str(d),"
    "'on-demand-serve',b],{'PATH':'/usr/bin:/bin','LANG':'C'})"
)


class ControlRefused(ValueError):
    """Closed failure, with no host output, secret, arbitrary path or exception detail."""


def _refuse() -> ControlRefused:
    return ControlRefused("Boca on-demand activation identity or state unavailable")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _home() -> Path:
    account = pwd.getpwuid(_UID)
    if (
        (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) != (_UID,) * 4
        or account.pw_name != "boca-deploy"
        or account.pw_dir != str(_HOME)
        or account.pw_gid != _UID
        or _HOME.resolve(strict=True) != _HOME
    ):
        raise _refuse()
    _directory(_HOME, mode=0o700)
    return _HOME


def control_directory() -> Path:
    """Canonical host source of the controller's single read-only activation bind."""
    return _HOME / _ROOT / "socket"


def _directory(path: Path, *, mode: int | None = None) -> None:
    s = path.lstat()
    if (
        not stat.S_ISDIR(s.st_mode)
        or (s.st_uid, s.st_gid) != (os.geteuid(), os.getegid())
        or s.st_mode & 0o022
        or mode is not None
        and stat.S_IMODE(s.st_mode) != mode
    ):
        raise _refuse()


def _present(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _read(path: Path, limit: int, *, links: tuple[int, ...] = (1,)) -> bytes:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    with os.fdopen(os.open(path, flags), "rb") as stream:
        s = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(s.st_mode)
            or s.st_nlink not in links
            or (s.st_uid, s.st_gid) != (os.geteuid(), os.getegid())
            or stat.S_IMODE(s.st_mode) != 0o600
            or not 0 < s.st_size <= limit
        ):
            raise _refuse()
        data = stream.read(limit + 1)
        if len(data) != s.st_size:
            raise _refuse()
        return data


def _sync(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _new(path: Path, content: bytes) -> None:
    # Prefer an unnamed inode so process termination cannot leave a half-written
    # file or extra hard link in the private payload directory. linkat publishes
    # exclusively, and reopens no source pathname controlled by a caller.
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            fd = os.open(".", os.O_TMPFILE | os.O_RDWR, 0o600, dir_fd=directory)
        except OSError as exc:
            if exc.errno not in (errno.EOPNOTSUPP, errno.EISDIR, errno.EINVAL):
                raise
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".publishing-") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
                os.link(f.name, path, follow_symlinks=False)
        else:
            with os.fdopen(fd, "wb") as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(fd)
                os.link(
                    f"/proc/self/fd/{fd}", path.name, dst_dir_fd=directory, follow_symlinks=True
                )
        os.fsync(directory)
    finally:
        os.close(directory)


def _check_attempt(attempt: str) -> bytes:
    if type(attempt) is not str or not cleanup.ATTEMPT_ID.fullmatch(attempt):
        raise _refuse()
    return (attempt + "\n").encode("ascii")


def _owned(home: Path, attempt: str) -> Path:
    root = home / _ROOT
    _directory(root, mode=0o700)
    if _read(root / _MARKER, 32) != _check_attempt(attempt) or not {
        p.name for p in root.iterdir()
    }.issubset(_DATA):
        raise _refuse()
    return root


def prepare_control_directory(attempt: str, lease: BocaJobLease) -> Path:
    """Create (or rejoin) only this attempt's host socket mount before docker create."""
    _verify_lease(lease, attempt)
    marker = _check_attempt(attempt)
    home = _home()
    root = home / _ROOT
    try:
        root.mkdir(mode=0o700)
    except FileExistsError:
        _owned(home, attempt)
    else:
        try:
            _new(root / _MARKER, marker)
            _sync(home)
        except Exception:
            if not any(root.iterdir()):
                root.rmdir()
            raise
    if _present(root / _REMOVING):
        raise _refuse()
    folder = root / "socket"
    if not _present(folder):
        folder.mkdir(mode=0o711)
        # User service/SSH umask is allowed to be 0077.  The mapped container UID
        # needs search permission on this directory after its dedicated bind.
        folder.chmod(0o711)
        _sync(root)
    _directory(folder, mode=0o711)
    if any(p.name != _SOCKET_NAME for p in folder.iterdir()):
        raise _refuse()
    return folder


def _runtime_archive(raw: bytes) -> bytes:
    target = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(target, "w") as runtime:
        if len(source.namelist()) != len(set(source.namelist())):
            raise _refuse()
        for name in (*_RUNTIME_FILES, "__main__.py"):
            entry = zipfile.ZipInfo(name)
            entry.compress_type = zipfile.ZIP_DEFLATED
            data = _MAIN if name == "__main__.py" else source.read(name)
            runtime.writestr(entry, data)
    result = target.getvalue()
    if len(result) > _MAX_ZIP:
        raise _refuse()
    return result


def _bundle(expected: str | None) -> bytes:
    # _bundle_digest enforces /proc/self/fd/N and the bounded authenticated transport.
    from boca_socios.host_boca_cutover_cli import _bundle_digest

    digest = _bundle_digest()
    if expected is not None and digest != expected:
        raise _refuse()
    with open(sys.argv[0], "rb") as stream:
        raw = stream.read(_MAX_ZIP + 1)
    if not 0 < len(raw) <= _MAX_ZIP or _sha(raw) != digest:
        raise _refuse()
    return _runtime_archive(raw)


def _plan(home: Path, installation: OnDemandInstallation, archive_hash: str) -> bytes:
    from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

    item = installation
    if (
        type(item) is not OnDemandInstallation
        or not _DIGEST.fullmatch(archive_hash)
        or item.database_path != home / _DB
    ):
        raise _refuse()
    item.coordinates("00000000-0000-4000-8000-000000000001")
    binding = {**asdict(item), "database_path": str(item.database_path)}
    return json.dumps(
        {"version": 1, "bundle_sha256": archive_hash, "installation": binding},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _decode(home: Path, raw: bytes) -> tuple[OnDemandInstallation, str]:
    from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

    try:
        obj = json.loads(raw)
        data = obj["installation"]
        data["database_path"] = Path(data["database_path"])
        data["pair"] = ReviewedInstalledPair(**data["pair"])
        item = OnDemandInstallation(**data)
        digest = obj["bundle_sha256"]
        if raw != _plan(home, item, digest):
            raise _refuse()
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise _refuse() from None
    return item, digest


def _units(archive_hash: str, plan_hash: str) -> dict[str, bytes]:
    sock = (
        "[Unit]\nDescription=Boca owner panel activation socket\n"
        "[Socket]\nListenStream=%h/.boca-on-demand/socket/control.sock\n"
        "Accept=yes\nSocketMode=0666\nRemoveOnStop=yes\nBacklog=8\nMaxConnections=8\n"
        "[Install]\nWantedBy=default.target\n"
    )
    service = (
        "[Unit]\nDescription=Apply one authenticated Boca ledger request\n"
        "[Service]\nType=oneshot\nStandardInput=socket\nStandardOutput=null\n"
        "StandardError=null\nNoNewPrivileges=yes\nRestrictAddressFamilies=AF_UNIX\n"
        "UMask=0077\nTimeoutStartSec=5min\n"
        f'ExecStart=/usr/bin/python3 -I -B -c "{_LOADER}" '
        f"%h/.boca-on-demand/{_ARCHIVE} {archive_hash} {plan_hash}\n"
    )
    return {_SOCKET: sock.encode("ascii"), _SERVICE: service.encode("ascii")}


def _unit_dir(home: Path) -> Path:
    folder = home
    for name in (".config", "systemd", "user"):
        folder /= name
        _directory(folder)
    # Existing persistent Docker user unit already requires this standard directory.
    _directory(folder / "default.target.wants")
    return folder


def _systemctl(home: Path, *args: str) -> str:
    env = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "XDG_RUNTIME_DIR": "/run/user/10001",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/10001/bus",
    }
    proc = subprocess.run(  # noqa: S603 - fixed Boca user manager and exact unit verbs
        ("/usr/bin/systemctl", "--user", *args),
        env=env,
        stdin=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        timeout=15,
        check=False,
    )
    if proc.returncode not in ((0, 4) if args[0] == "show" else (0,)):
        # Preserve the exit category for the protected installer without piping
        # the manager's diagnostics, process output or argument vector into a receipt.
        raise _refuse() from subprocess.CalledProcessError(proc.returncode, "Boca user manager")
    if len(proc.stdout) > 4096:
        raise _refuse()
    return proc.stdout.decode("ascii")


def _state(home: Path, name: str) -> dict[str, str]:
    unit = _PROBE if name == _SERVICE else _SOCKET
    raw = _systemctl(home, "show", "--all", "--property=" + ",".join(_PROPERTIES), unit)
    entries = [line.partition("=") for line in raw.splitlines()]
    values = {k: v for k, _, v in entries}
    if (
        len(entries) != len(_PROPERTIES)
        or set(values) != set(_PROPERTIES)
        or any(sep != "=" for _, sep, _ in entries)
        or values["DropInPaths"]
    ):
        raise _refuse()
    return values


def _known(home: Path, directory: Path, name: str, linked: bool) -> dict[str, str]:
    state = _state(home, name)
    absent = state["LoadState"] == "not-found" and not state["FragmentPath"]
    own = (
        linked and state["LoadState"] == "loaded" and state["FragmentPath"] == str(directory / name)
    )
    if not (own or absent and state["ActiveState"] == "inactive"):
        raise _refuse()
    return state


def _matches(source: Path, dest: Path) -> bool:
    if not _present(dest):
        return False
    if not _present(source) or not stat.S_ISREG(dest.lstat().st_mode) or not source.samefile(dest):
        raise _refuse()
    return True


def _enabled(directory: Path, socket_owned: bool) -> bool:
    link = directory / "default.target.wants" / _SOCKET
    if not _present(link):
        return False
    if not socket_owned or not link.is_symlink() or os.readlink(link) != "../" + _SOCKET:
        raise _refuse()
    return True


def _socket(root: Path) -> None:
    folder = root / "socket"
    _directory(folder, mode=0o711)
    if {p.name for p in folder.iterdir()} != {_SOCKET_NAME}:
        raise _refuse()
    s = (folder / _SOCKET_NAME).lstat()
    if (
        not stat.S_ISSOCK(s.st_mode)
        or s.st_nlink != 1
        or stat.S_IMODE(s.st_mode) != 0o666
        or (s.st_uid, s.st_gid) != (os.geteuid(), os.getegid())
    ):
        raise _refuse()


def _unit_link(root: Path, directory: Path, name: str, data: bytes) -> bool:
    canonical = root / name
    linked = _matches(canonical, directory / name)
    if _present(canonical) and _read(canonical, 4096, links=((2,) if linked else (1,))) != data:
        raise _refuse()
    return linked


def _inspect(home: Path, root: Path, contents: dict[str, bytes]) -> tuple[bool, bool]:
    directory = _unit_dir(home)
    folder = root / "socket"
    _directory(folder, mode=0o711)
    if any(path.name != _SOCKET_NAME for path in folder.iterdir()):
        raise _refuse()
    active = False
    loaded: dict[str, bool] = {}
    for name, data in contents.items():
        linked = _unit_link(root, directory, name, data)
        state = _known(home, directory, name, linked)
        loaded[name] = linked and state["LoadState"] == "loaded"
        if name == _SOCKET:
            active = state["ActiveState"] == "active" and state["SubState"] == "listening"
            if active:
                _socket(root)
            elif state["ActiveState"] not in ("inactive", "failed") or _present(
                root / "socket" / _SOCKET_NAME
            ):
                raise _refuse()
    enabled = _enabled(directory, _present(directory / _SOCKET))
    return active, enabled and all(loaded.values())


def install_control(
    installation: OnDemandInstallation, lease: BocaJobLease, *, bundle_sha256: str | None = None
) -> None:
    """Publish only a prepared attempt, pin both CIDs, then verify a listening unit."""
    # Only the protected installer reports Cutover stages. The installed
    # handler ZIP intentionally excludes the general deployment dispatcher.
    from boca_socios.host_boca_cutover import candidate_check

    with candidate_check("CONTROL_HOME_UNITS"):
        run = installation.installation_run_id
        _verify_lease(lease, run)
        home = _home()
        root = _owned(home, run)
        _directory(root / "socket", mode=0o711)
        if _present(root / _REMOVING):
            raise _refuse()
        directory = _unit_dir(home)
    with candidate_check("CONTROL_ARCHIVE_BINDING"):
        archive = _bundle(bundle_sha256)
        digest = _sha(archive)
        plan = _plan(home, installation, digest)
        units = _units(digest, _sha(plan))
    with candidate_check("CONTROL_UNIT_PREFLIGHT"):
        active, ready = _inspect(home, root, units)
    with candidate_check("CONTROL_PUBLISH"):
        for name, data in ((_BINDING, plan), (_ARCHIVE, archive), *units.items()):
            path = root / name
            if _present(path):
                if _read(path, len(data), links=(1, 2) if name in units else (1,)) != data:
                    raise _refuse()
            else:
                _new(path, data)
        for name in units:
            if not _matches(root / name, directory / name):
                os.link(root / name, directory / name, follow_symlinks=False)
        _sync(directory)
        if not _enabled(directory, True):
            enable = directory / "default.target.wants"
            os.symlink("../" + _SOCKET, enable / _SOCKET)
            _sync(enable)
    with candidate_check("CONTROL_MANAGER_RELOAD"):
        if not ready:
            _systemctl(home, "daemon-reload")
        if not active:
            # Verify owner fragments and drop-ins in the reloaded manager before starting.
            _, ready = _inspect(home, root, units)
            if not ready:
                raise _refuse()
    if not active:
        with candidate_check("CONTROL_LISTENER_START"):
            _systemctl(home, "start", _SOCKET)
    with candidate_check("CONTROL_LISTENER_VERIFY"):
        verify_control(installation, lease)


def verify_control(installation: OnDemandInstallation, lease: BocaJobLease) -> None:
    _verify_lease(lease, installation.installation_run_id)
    if _verified_installation(_home()) != installation:
        raise _refuse()


def read_installed_binding(lease: BocaJobLease) -> OnDemandInstallation:
    """Read the pinned installation under an independent protected status lease."""
    _verify_lease(lease, lease.attempt_id)
    return _verified_installation(_home())


def _verified_installation(home: Path) -> OnDemandInstallation:
    root = home / _ROOT
    _directory(root, mode=0o700)
    if _present(root / _REMOVING):
        # The handler rejects every new connection after this durable boundary,
        # even if interruption left the manager reporting an active listener.
        raise _refuse()
    raw = _read(root / _BINDING, _MAX_PLAN)
    item, digest = _decode(home, raw)
    _owned(home, item.installation_run_id)
    if _sha(_read(root / _ARCHIVE, _MAX_ZIP)) != digest or _inspect(
        home, root, _units(digest, _sha(raw))
    ) != (True, True):
        raise _refuse()
    return item


def remove_control(attempt: str, lease: BocaJobLease) -> None:
    """Compensate only this prepared/bound installation; fail closed on any drift."""
    _verify_lease(lease, attempt)
    home = _home()
    if not _present(home / _ROOT):
        return
    root = _owned(home, attempt)
    folder = root / "socket"
    if _present(folder):
        _directory(folder, mode=0o711)
    if _present(root / _BINDING):
        raw = _read(root / _BINDING, _MAX_PLAN)
        item, digest = _decode(home, raw)
        if item.installation_run_id != attempt or (
            _present(root / _ARCHIVE) and _sha(_read(root / _ARCHIVE, _MAX_ZIP)) != digest
        ):
            raise _refuse()
        units = _units(digest, _sha(raw))
        directory = _unit_dir(home)
        removing = root / _REMOVING
        proof = _sha(raw).encode("ascii")
        if _present(removing):
            if _read(removing, 64) != proof:
                raise _refuse()
            # A previous process may have unlinked an exact hardlink before its
            # manager reload. Recheck the remaining on-disk inodes/enable link
            # before asking the dedicated user manager to refresh that stale cache.
            for name, data in units.items():
                _unit_link(root, directory, name, data)
            _enabled(directory, _present(directory / _SOCKET))
            _systemctl(home, "daemon-reload")
        active, _ = _inspect(home, root, units)
        if not _present(removing):
            _new(removing, proof)
        if active:
            _systemctl(home, "stop", _SOCKET)
            if _inspect(home, root, units)[0]:
                raise _refuse()
        changed = False
        if _enabled(directory, _present(directory / _SOCKET)):
            (directory / "default.target.wants" / _SOCKET).unlink()
            _sync(directory / "default.target.wants")
            changed = True
        for name in units:
            if _matches(root / name, directory / name):
                (directory / name).unlink()
                changed = True
        _sync(directory)
        if changed:
            _systemctl(home, "daemon-reload")
        for name in units:
            state = _known(home, directory, name, False)
            if state["LoadState"] != "not-found":
                raise _refuse()
        for name in (*units, _ARCHIVE, _REMOVING, _BINDING):
            (root / name).unlink(missing_ok=True)
    # Only an absent or empty known socket directory may be removed here.
    if _present(folder):
        folder.rmdir()
    (root / _MARKER).unlink()
    root.rmdir()
    _sync(home)


def _controller_pid(cid: str) -> int:
    if not _DIGEST.fullmatch(cid):
        raise _refuse()
    info = cleanup._docker(
        "inspect",
        "--type",
        "container",
        "--format",
        "{{.Id}} {{.State.Running}} {{.State.Pid}}",
        cid,
    )
    parts = info.strip().split(" ")
    if (
        len(parts) != 3
        or parts[:2] != [cid, "true"]
        or not re.fullmatch(r"[1-9][0-9]{0,9}", parts[2])
    ):
        raise _refuse()
    return int(parts[2])


def _proc_field(pid: int, name: str) -> str:
    with (Path("/proc") / str(pid) / name).open("rb") as f:
        data = f.read(4_097)
    if not 0 < len(data) <= 4_096:
        raise _refuse()
    return data.decode("ascii")


def _mapping(pid: int, field: str) -> int:
    maps: list[int] = []
    for line in _proc_field(pid, field).splitlines():
        columns = line.split()
        if len(columns) != 3 or not all(re.fullmatch(r"[0-9]{1,10}", col) for col in columns):
            raise _refuse()
        inside, outside, length = map(int, columns)
        if inside <= _UID < inside + length:
            maps.append(outside + _UID - inside)
    if len(maps) != 1:
        raise _refuse()
    return maps[0]


def verify_controller_peer(connection: socket.socket, installation: OnDemandInstallation) -> bool:
    """Match the kernel peer credentials AND its running container's pinned cgroup."""
    try:
        if (
            connection.family != socket.AF_UNIX
            or connection.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM
        ):
            return False
        pid, uid, gid = struct.unpack(
            "iII",
            connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("iII")),
        )
        if pid <= 0:
            return False
        cid = installation.controller_id
        init = _controller_pid(cid)
        with ExitStack() as stack:
            live = select.poll()
            # Recent Linux exposes a pidfd of the original connecting task directly.
            # On older kernels pin the SO_PEERCRED PID and independently recheck
            # both Docker init identity and the credential-bound controller cgroup.
            try:
                peerfd = connection.getsockopt(
                    socket.SOL_SOCKET, getattr(socket, "SO_PEERPIDFD", 77)
                )
            except OSError as exc:
                if exc.errno != errno.ENOPROTOOPT:
                    raise
                peerfd = os.pidfd_open(pid)
            stack.callback(os.close, peerfd)
            live.register(peerfd, select.POLLIN)
            initfd = os.pidfd_open(init)
            stack.callback(os.close, initfd)
            live.register(initfd, select.POLLIN)
            if (_mapping(init, "uid_map"), _mapping(init, "gid_map")) != (uid, gid):
                return False
            init_path = _proc_field(init, "cgroup").splitlines()
            if len(init_path) != 1 or not init_path[0].startswith("0::/"):
                return False
            path = Path(init_path[0].removeprefix("0::"))
            if path.name not in {cid, f"docker-{cid}.scope"} or ".." in path.parts:
                return False
            return (
                _proc_field(pid, "cgroup").splitlines() == init_path
                and _controller_pid(cid) == init
                and not live.poll(0)
            )
    except (OSError, OverflowError, ValueError, struct.error):
        return False


def handle_connection(
    connection: socket.socket,
    installation: OnDemandInstallation,
    *,
    peer_check: Callable[[socket.socket, OnDemandInstallation], bool] = verify_controller_peer,
    apply: Callable[[str, OnDemandInstallation], object] | None = None,
) -> bool:
    deadline = time.monotonic() + 2.0
    frame = bytearray()
    try:
        while len(frame) <= 37:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            connection.settimeout(remaining)
            part = connection.recv(38 - len(frame))
            if not part:
                break
            frame.extend(part)
        if len(frame) != 37 or frame[-1:] != b"\n":
            return False
        op = canonical_operation_id(frame[:-1].decode("ascii"))
        if not peer_check(connection, installation):
            return False
        if apply is None:
            from boca_socios.host_on_demand_lifecycle import apply_panel_request

            apply = apply_panel_request
        apply(op, installation)
        return True
    except (OSError, ValueError):
        return False


def socket_main(binding_sha256: str) -> int:
    try:
        if not _DIGEST.fullmatch(binding_sha256):
            return 3
        home = _home()
        root = home / _ROOT
        _directory(root, mode=0o700)
        raw = _read(root / _BINDING, _MAX_PLAN)
        if _sha(raw) != binding_sha256:
            return 3
        installation, digest = _decode(home, raw)
        # The physical service is only reachable through the verified sealed bundle.
        if not re.fullmatch(r"/proc/self/fd/[1-9][0-9]*", sys.argv[0]):
            return 3
        with open(sys.argv[0], "rb") as archive:
            if _sha(archive.read(_MAX_ZIP + 1)) != digest:
                return 3
        _owned(home, installation.installation_run_id)
        if _present(root / _REMOVING):
            return 3
        with socket.socket(fileno=0) as accepted:
            return 0 if handle_connection(accepted, installation) else 3
    except Exception:
        # A private failure never emits proc, Docker, systemd or database bytes.
        return 3
