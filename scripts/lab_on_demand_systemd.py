"""Exercise the actual Boca socket installer in a disposable Ubuntu Actions user manager.

Run python3 scripts/lab_on_demand_systemd.py on a GitHub-hosted ubuntu-24.04 runner.
The fixture has only artificial release pins. An invalid frame exercises socket
activation without reaching the Docker client, a quota, the browser or the ledger.
"""

from __future__ import annotations

import fcntl
import grp
import hashlib
import os
import platform
import pwd
import re
import shutil
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import termios
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

USER = "boca-deploy"
UID = 10001
HOME_DIR = Path("/home/boca-deploy")
RUNTIME = Path("/run/user/10001")
SOCKET = "boca-bot-control.socket"
SERVICE = "boca-bot-control@.service"
SHELL = "/usr/sbin/nologin"
SYSTEMCTL = "/usr/bin/systemctl"
PREFIX = "BOCA_SYSTEMD_LAB"


class LabFailure(Exception):
    pass


def require(ok: bool, phase: str) -> None:
    if not ok:
        raise LabFailure(phase)


@contextmanager
def phase(label: str, *, translate_timeout: bool = True) -> Iterator[None]:
    role = "fixture" if sys.argv[1:2] == ["--fixture"] else "runner"
    start = time.monotonic()
    print(PREFIX, f"role={role}", "event=BEGIN", f"phase={label}", flush=True)
    try:
        yield
    except (subprocess.TimeoutExpired, TimeoutError):
        print(PREFIX, f"role={role}", "event=FAIL", f"phase={label}", "reason=TIMEOUT", flush=True)
        if translate_timeout:
            raise LabFailure(label + "_TIMEOUT") from None
        raise
    except Exception as exc:
        reason = str(exc) if isinstance(exc, LabFailure) else type(exc).__name__
        print(
            PREFIX, f"role={role}", "event=FAIL", f"phase={label}", f"reason={reason}", flush=True
        )
        raise
    else:
        elapsed_ms = round(1000 * (time.monotonic() - start))
        print(PREFIX, f"role={role}", "event=END", f"phase={label}", f"ms={elapsed_ms}", flush=True)


def command(
    *args: str,
    label: str,
    output: Literal["discard", "read", "publish"] = "discard",
    timeout: float = 40,
    polling: bool = False,
) -> str:
    def run() -> str:
        try:
            result = subprocess.run(  # noqa: S603 - fixed lab argv, no shell or deployment secrets
                args,
                stdin=subprocess.DEVNULL,
                # A helper may fork and leave its stdout open in a descendant.
                # Only actual queries need a pipe; administrative calls wait on
                # the command itself and always require its successful exit.
                stdout={"discard": subprocess.DEVNULL, "read": subprocess.PIPE, "publish": None}[
                    output
                ],
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise LabFailure(label + "_TIMEOUT") from None
        require(result.returncode == 0, label + "_EXIT")
        return result.stdout.decode("utf-8") if output == "read" else ""

    if polling:
        # The enclosing phase reports the deadline and the exact poll that failed.
        return run()
    with phase(label):
        return run()


def owned(tag: str) -> bool:
    try:
        record = pwd.getpwnam(USER)
    except KeyError:
        return False
    return (
        (record.pw_uid, record.pw_gid) == (UID, UID)
        and record.pw_dir == str(HOME_DIR)
        and record.pw_shell == SHELL
        and record.pw_gecos == tag
    )


def unused(*lookups: Callable[[], object]) -> bool:
    for lookup in lookups:
        try:
            lookup()
        except KeyError:
            continue
        return False
    return True


def vacant() -> bool:
    return unused(
        lambda: pwd.getpwnam(USER),
        lambda: pwd.getpwuid(UID),
        lambda: grp.getgrnam(USER),
        lambda: grp.getgrgid(UID),
    ) and all(
        not os.path.lexists(p) for p in (HOME_DIR, RUNTIME, Path("/var/lib/systemd/linger") / USER)
    )


def prepare_unit_directories(home: Path) -> None:
    # pathlib mkdir(parents=True) applies mode only to the leaf. The runner's
    # user-private-group umask can otherwise leave writable ancestors. Match
    # the four observed 0700 directories inside this newly created CI account.
    directory = home
    for part, label in (
        (".config", "CONFIG"),
        ("systemd", "SYSTEMD"),
        ("user", "USER"),
        ("default.target.wants", "WANTS"),
    ):
        directory /= part
        try:
            directory.mkdir(mode=0o700, exist_ok=True)
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError:
            raise LabFailure("LAB_UNIT_" + label + "_OPEN") from None
        try:
            info = os.fstat(fd)
            require((info.st_uid, info.st_gid) == (UID, UID), "LAB_UNIT_" + label + "_OWNER")
            # A distro skeleton may have created this directory before the lab.
            # Tighten only the verified inode belonging to the disposable user.
            if stat.S_IMODE(info.st_mode) != 0o700:
                os.fchmod(fd, 0o700)
            require(stat.S_IMODE(os.fstat(fd).st_mode) == 0o700, "LAB_UNIT_" + label + "_MODE")
        finally:
            os.close(fd)


def manager(*args: str, label: str, polling: bool = False) -> str:
    return command(
        SYSTEMCTL,
        "--user",
        *args,
        label=label,
        output="read" if args[0] in ("show", "list-units", "is-enabled") else "discard",
        timeout=3 if polling else 12,
        polling=polling,
    )


def project_user_unit(home: Path, unit: str, raw: str) -> None:
    """Print classified properties from this fixture only, before production validates them."""
    name = SOCKET if unit == SOCKET else SERVICE
    keys = {"LoadState", "FragmentPath", "DropInPaths", "ActiveState", "SubState"}
    rows = [line.partition("=") for line in raw.splitlines()]
    data = {key: value for key, equals, value in rows if equals and key in keys}
    shape = "EXACT" if len(rows) == len(keys) and set(data) == keys else "OTHER"

    def enum(key: str, values: tuple[str, ...]) -> str:
        value = data.get(key)
        return "MISSING" if value is None else value if value in values else "OTHER"

    fragment = data.get("FragmentPath")
    expected = str(home / ".config/systemd/user" / name)
    frag = (
        "MISSING"
        if fragment is None
        else "EMPTY"
        if not fragment
        else "EXPECTED"
        if fragment == expected
        else "OTHER"
    )
    drop = data.get("DropInPaths")
    print(
        PREFIX,
        "role=fixture event=STATE",
        "unit=SOCKET" if unit == SOCKET else "unit=TEMPLATE",
        f"shape={shape}",
        "load="
        + enum("LoadState", ("loaded", "not-found", "masked", "error", "bad-setting", "stub")),
        "active="
        + enum(
            "ActiveState",
            ("active", "inactive", "activating", "deactivating", "failed", "reloading"),
        ),
        "sub="
        + enum(
            "SubState",
            (
                "dead",
                "listening",
                "running",
                "failed",
                "start-pre",
                "start-post",
                "stop-pre",
                "stop-post",
                "stop-sigterm",
                "stop-sigkill",
            ),
        ),
        f"fragment={frag}",
        "drop=" + ("MISSING" if drop is None else "EMPTY" if not drop else "PRESENT"),
        flush=True,
    )
    if unit != SOCKET or data.get("LoadState") != "loaded":
        return
    folder = home / ".boca-on-demand/socket"
    for label, path in (("DIR", folder), ("NODE", folder / "control.sock")):
        try:
            meta = path.lstat()
        except FileNotFoundError:
            print(PREFIX, "role=fixture event=FS", f"path={label}", "kind=ABSENT", flush=True)
            break
        except OSError:
            print(PREFIX, "role=fixture event=FS", f"path={label}", "kind=UNAVAILABLE", flush=True)
            break
        kind = (
            "DIR"
            if stat.S_ISDIR(meta.st_mode)
            else "SOCKET"
            if stat.S_ISSOCK(meta.st_mode)
            else "LINK"
            if stat.S_ISLNK(meta.st_mode)
            else "OTHER"
        )
        uid = str(meta.st_uid) if meta.st_uid in (0, UID) else "OTHER"
        gid = str(meta.st_gid) if meta.st_gid in (0, UID) else "OTHER"
        nlink = str(meta.st_nlink) if meta.st_nlink < 10 else "MANY"
        print(
            PREFIX,
            "role=fixture event=FS",
            f"path={label}",
            f"kind={kind}",
            f"mode={stat.S_IMODE(meta.st_mode):04o}",
            f"uid={uid}",
            f"gid={gid}",
            f"nlink={nlink}",
            flush=True,
        )
        if label == "DIR":
            if kind != "DIR" or meta.st_uid != UID:
                break
            try:
                with os.scandir(path) as entries:
                    extra = any(e.name != "control.sock" for e in entries)
            except OSError:
                contents = "UNAVAILABLE"
            else:
                contents = "EXTRA" if extra else "NO_EXTRA"
            print(
                PREFIX, "role=fixture event=FS", "path=DIR", f"other_entries={contents}", flush=True
            )


def trace_user_manager(real: Callable[..., str]) -> Callable[..., str]:
    # Observe only. Every result and exception still comes from the actual
    # production systemctl runner; never print its argv, stdout or stderr.
    def traced(home: Path, *args: str) -> str:
        label = {
            "show": "SHOW_SOCKET" if args[-1] == SOCKET else "SHOW_TEMPLATE",
            "daemon-reload": "RELOAD",
            "start": "START_SOCKET",
            "stop": "STOP_SOCKET",
        }[args[0]]
        with phase("USER_" + label, translate_timeout=False):
            raw = real(home, *args)
            if args[0] == "show":
                project_user_unit(home, args[-1], raw)
            return raw

    return traced


def verify_reader(connection: socket.socket) -> None:
    # Linux AF_UNIX holds queued bytes until the receiver consumes the skb.
    # An early exit(3) in the loader also rejects a frame; prove that the real
    # handler consumed a partial frame and kept its stream open awaiting EOF.
    connection.sendall(b"incomplete")
    until = time.monotonic() + 8
    while time.monotonic() < until:
        count = fcntl.ioctl(connection.fileno(), termios.TIOCOUTQ, struct.pack("i", 0))
        if struct.unpack("i", count)[0] == 0:
            connection.setblocking(False)
            try:
                connection.recv(1, socket.MSG_PEEK)
            except BlockingIOError:
                connection.settimeout(2)
                connection.sendall(b"\n")
                connection.shutdown(socket.SHUT_WR)
                return
            raise LabFailure("HANDLER_CLOSED_BEFORE_FRAME")
        time.sleep(0.01)
    raise LabFailure("HANDLER_DID_NOT_READ")


def rejected_instance() -> str:
    # Get only this exact fixture's template instances; use the exit code to
    # distinguish execution of the actual sealed handler from exec/parse failures.
    until = time.monotonic() + 8
    while time.monotonic() < until:
        listing = manager(
            "list-units",
            "--all",
            "--plain",
            "--no-legend",
            "boca-bot-control@*.service",
            label="DENIED_LIST",
            polling=True,
        )
        for line in listing.splitlines():
            fields = line.split()
            if not fields or not re.fullmatch(
                r"boca-bot-control@[A-Za-z0-9_:.\\-]+\.service", fields[0]
            ):
                continue
            name = fields[0]
            state = manager(
                "show",
                "--property=Result,ExecMainStatus,ActiveState",
                name,
                label="DENIED_STATE",
                polling=True,
            )
            if set(state.splitlines()) == {
                "Result=exit-code",
                "ExecMainStatus=3",
                "ActiveState=failed",
            }:
                return name
        time.sleep(0.15)
    raise LabFailure("DENIED_INSTANCE_RECEIPT")


def exercise(package: Path, digest: str, run: str, tag: str) -> None:
    require(
        os.getuid() == os.geteuid() == os.getgid() == os.getegid() == UID and owned(tag),
        "FIXTURE_UID",
    )
    require(
        re.fullmatch(r"boca-ci-[0-9a-f]{32}", tag) is not None
        and re.fullmatch(r"[1-9][0-9]{0,19}", run) is not None,
        "FIXTURE_COORDINATES",
    )
    with package.open("rb") as f:
        public = f.read(512_001)
    require(
        0 < len(public) <= 512_000 and hashlib.sha256(public).hexdigest() == digest, "PUBLIC_BUNDLE"
    )
    # Emulate the proven memfd transport with the runner-built, digest-verified public
    # bytes. Only the lab introduces synthetic coordinates; all installation code is real.
    with os.fdopen(
        os.memfd_create("boca-systemd-lab", os.MFD_ALLOW_SEALING), "wb", buffering=0
    ) as fd:
        require(fd.write(public) == len(public), "PUBLIC_WRITE")
        fcntl.fcntl(
            fd.fileno(),
            fcntl.F_ADD_SEALS,
            fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL,
        )
        location = f"/proc/self/fd/{fd.fileno()}"
        sys.argv[0] = location
        sys.path.insert(0, location)
        from boca_socios import host_on_demand_service as svc
        from boca_socios.host_boca_cleanup import protected_boca_job_lease
        from boca_socios.host_boca_cutover import CandidateAcceptanceFailure
        from boca_socios.host_lifecycle_rootless_adapter import ReviewedInstalledPair
        from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

        svc._systemctl = trace_user_manager(svc._systemctl)
        with phase("FIXTURE_UNIT_DIRS"):
            prepare_unit_directories(HOME_DIR)
        # Validate the *real* systemctl contract for absent units before any creation.
        for name in (SOCKET, SERVICE):
            expected = {
                "LoadState": "not-found",
                "FragmentPath": "",
                "DropInPaths": "",
                "ActiveState": "inactive",
                "SubState": "dead",
            }
            require(svc._state(HOME_DIR, name) == expected, "ABSENT_UNIT_SHAPE")
        prefix = "ghcr.io/mbalbo2023/boca-socios-assistant"
        item = OnDemandInstallation(
            run,
            "9" * 40,
            "a" * 64,
            prefix + "@sha256:" + "b" * 64,
            "c" * 64,
            prefix + "-browser@sha256:" + "d" * 64,
            HOME_DIR / ".local/share/docker/volumes/boca-socios_boca_data/_data/boca.sqlite3",
            ReviewedInstalledPair(run, "e" * 64, "f" * 64),
        )
        with protected_boca_job_lease(run) as lease:
            with phase("PREPARE_DIRECTORY"):
                directory = svc.prepare_control_directory(run, lease)
            try:
                with phase("INSTALL"):
                    try:
                        svc.install_control(item, lease, bundle_sha256=digest)
                    except CandidateAcceptanceFailure as exc:
                        raise LabFailure(exc.check + "_" + exc.result) from None
                with phase("VERIFY_BOUND_INSTALL"):
                    svc.verify_control(item, lease)
                require(
                    manager("is-enabled", SOCKET, label="IS_ENABLED").strip() == "enabled",
                    "ENABLE_RECEIPT",
                )
                require(
                    manager(
                        "show", "--property=NAccepted", "--value", SOCKET, label="READ_ACCEPTS"
                    ).strip()
                    == "0",
                    "INITIAL_ACCEPTS",
                )
                with (
                    phase("SOCKET_FRAME"),
                    socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection,
                ):
                    connection.settimeout(2)
                    connection.connect(str(directory / "control.sock"))
                    verify_reader(connection)
                with phase("WAIT_DENIED_INSTANCE"):
                    instance = rejected_instance()
                require(
                    manager(
                        "show", "--property=NAccepted", "--value", SOCKET, label="READ_ACCEPTS"
                    ).strip()
                    == "1",
                    "SINGLE_ACCEPT",
                )
                manager("reset-failed", instance, label="RESET_DENIED_INSTANCE")
                # Rejoining while it listens must preserve the same socket inode.
                inode = (directory / "control.sock").stat()
                with phase("REJOIN"):
                    svc.install_control(item, lease, bundle_sha256=digest)
                require(
                    os.path.samestat(inode, (directory / "control.sock").stat()), "LISTENING_INODE"
                )
            finally:
                with phase("REMOVE_CONTROL"):
                    svc.remove_control(run, lease)
            for name in (SOCKET, SERVICE):
                require(
                    svc._state(HOME_DIR, name)["LoadState"] == "not-found", "ABSENT_AFTER_CLEANUP"
                )
            require(not (HOME_DIR / ".boca-on-demand").exists(), "PACKAGE_CLEANUP")


def stop_disposable_manager(sudo: tuple[str, ...], tag: str) -> None:
    """Queue only the disposable user's stop jobs, then observe the actual teardown."""
    require(owned(tag), "END_MANAGER_IDENTITY")
    units = (f"user@{UID}.service", f"user-runtime-dir@{UID}.service")
    command(*sudo, SYSTEMCTL, "--no-block", "stop", *units, label="END_MANAGER_QUEUE", timeout=10)
    last: tuple[str, ...] | None = None
    with phase("END_MANAGER_CONFIRM"):
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            left = deadline - time.monotonic()
            raw = command(
                *sudo,
                SYSTEMCTL,
                "show",
                "--all",
                "--property=Id,ActiveState,SubState",
                *units,
                label="END_MANAGER_STATE",
                output="read",
                timeout=min(4, max(0.1, left)),
                polling=True,
            )
            states: dict[str, tuple[str, str]] = {}
            for block in raw.strip().split("\n\n"):
                fields = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
                require(
                    set(fields) == {"Id", "ActiveState", "SubState"} and fields["Id"] not in states,
                    "END_MANAGER_SHAPE",
                )
                states[fields["Id"]] = (fields["ActiveState"], fields["SubState"])
            require(set(states) == set(units), "END_MANAGER_UNITS")
            alive = os.path.lexists(RUNTIME)
            public = tuple(
                v
                if v in ("active", "activating", "deactivating", "inactive", "failed")
                else "other"
                for v in (states[units[0]][0], states[units[1]][0])
            )
            summary = (*public, "present" if alive else "absent")
            if last != summary:
                print(
                    PREFIX,
                    "role=runner event=STATE phase=END_MANAGER_CONFIRM",
                    f"manager={summary[0]}",
                    f"runtime_unit={summary[1]}",
                    f"runtime_path={summary[2]}",
                    flush=True,
                )
                last = summary
            require("failed" not in public, "END_MANAGER_UNIT_FAILED")
            if all(state == ("inactive", "dead") for state in states.values()) and not alive:
                return
            time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
        raise LabFailure("END_MANAGER_CONFIRM_TIMEOUT")


def ephemeral() -> None:
    release = platform.freedesktop_os_release()
    require(
        os.getuid() != 0
        and os.environ.get("GITHUB_ACTIONS") == "true"
        and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
        and os.environ.get("RUNNER_OS") == "Linux"
        and os.environ.get("GITHUB_REPOSITORY") == "mbalbo2023/boca-socios-assistant"
        and (release.get("ID"), release.get("VERSION_ID")) == ("ubuntu", "24.04"),
        "REQUIRES_EPHEMERAL_RUNNER",
    )
    require(Path("/proc/1/comm").read_text().strip() == "systemd", "SYSTEMD_PID1")
    run = os.environ.get("GITHUB_RUN_ID", "")
    require(re.fullmatch(r"[1-9][0-9]{0,19}", run) is not None and vacant(), "ACCOUNT_NOT_VACANT")
    root = Path(__file__).resolve().parents[1]
    tag = "boca-ci-" + uuid4().hex
    sudo = ("/usr/bin/sudo", "-n")
    with tempfile.TemporaryDirectory(prefix="boca-systemd-lab-") as scratch:
        stage = Path(scratch)
        bundle = stage / "public.pyz"
        helper = stage / "fixture.py"
        command(
            sys.executable,
            "-I",
            "-B",
            str(root / "scripts/build_protected_boca_bundle.py"),
            str(root),
            str(bundle),
            label="BUILD",
        )
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
        shutil.copyfile(__file__, helper)
        bundle.chmod(0o444)
        helper.chmod(0o444)
        stage.chmod(0o711)
        command(*sudo, "/usr/sbin/groupadd", "--gid", str(UID), USER, label="LAB_GROUP")
        home_id: tuple[int, int] | None = None
        manager_requested = False
        try:
            # Exactly one sysusers.d line. No useradd hooks, skeleton copy,
            # subordinate allocations or per-UID login-record initialization.
            command(
                *sudo,
                "/usr/bin/systemd-sysusers",
                "--inline",
                f"u {USER} {UID}:{USER} {tag} {HOME_DIR} {SHELL}",
                label="LAB_ACCOUNT",
            )
            require(owned(tag) and grp.getgrgid(UID).gr_name == USER, "LAB_ACCOUNT_IDENTITY")
            require(not os.path.lexists(HOME_DIR), "LAB_HOME_NOT_VACANT")
            command(*sudo, "/usr/bin/mkdir", "--mode=0700", str(HOME_DIR), label="LAB_HOME_CREATE")
            before = HOME_DIR.lstat()
            require(
                stat.S_ISDIR(before.st_mode)
                and before.st_uid == 0
                and stat.S_IMODE(before.st_mode) == 0o700,
                "LAB_HOME_NEW_INODE",
            )
            home_id = before.st_dev, before.st_ino
            command(
                *sudo,
                "/usr/bin/chown",
                "--no-dereference",
                "--from=0",
                f"{UID}:{UID}",
                str(HOME_DIR),
                label="LAB_HOME_OWNER",
            )
            after = HOME_DIR.lstat()
            require(
                os.path.samestat(before, after)
                and (after.st_uid, after.st_gid) == (UID, UID)
                and stat.S_IMODE(after.st_mode) == 0o700,
                "LAB_HOME_IDENTITY",
            )
            manager_requested = True
            command(*sudo, "/usr/bin/loginctl", "enable-linger", USER, label="LAB_LINGER")
            command(*sudo, SYSTEMCTL, "start", f"user@{UID}.service", label="LAB_MANAGER")
            command(
                *sudo,
                "-u",
                USER,
                "/usr/bin/env",
                "-i",
                f"HOME={HOME_DIR}",
                f"USER={USER}",
                f"LOGNAME={USER}",
                "PATH=/usr/bin:/bin",
                f"XDG_RUNTIME_DIR={RUNTIME}",
                f"DBUS_SESSION_BUS_ADDRESS=unix:path={RUNTIME}/bus",
                "/usr/bin/python3",
                "-I",
                "-B",
                str(helper),
                "--fixture",
                str(bundle),
                digest,
                run,
                tag,
                output="publish",
                # Outer safety envelope covers installation, rejection, rejoin
                # and teardown. The real user-manager calls each keep their 15s limit.
                timeout=120,
                label="FIXTURE",
            )
        finally:
            if owned(tag):
                if manager_requested:
                    command(*sudo, "/usr/bin/loginctl", "disable-linger", USER, label="END_LINGER")
                    stop_disposable_manager(sudo, tag)
                require(owned(tag), "END_IDENTITY")
                remove_home: tuple[str, ...] = ()
                if home_id is not None:
                    info = HOME_DIR.lstat()
                    require(
                        stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == home_id,
                        "END_HOME_INODE",
                    )
                    if info.st_uid == 0:
                        # chown did not finish. rmdir can only remove our still-empty inode.
                        command(*sudo, "/usr/bin/rmdir", str(HOME_DIR), label="END_EMPTY_HOME")
                    else:
                        require((info.st_uid, info.st_gid) == (UID, UID), "END_HOME_OWNER")
                        remove_home = ("--remove",)
                command(*sudo, "/usr/sbin/userdel", *remove_home, USER, label="END_ACCOUNT")
            try:
                group = grp.getgrnam(USER)
            except KeyError:
                pass  # userdel may have already deleted the paired private group.
            else:
                require(
                    group.gr_gid == UID
                    and not group.gr_mem
                    and unused(lambda: pwd.getpwnam(USER), lambda: pwd.getpwuid(UID)),
                    "END_GROUP_IDENTITY",
                )
                command(*sudo, "/usr/sbin/groupdel", USER, label="END_GROUP")
    require(vacant(), "FINAL_ACCOUNT_RESIDUE")


if __name__ == "__main__":
    error_output = sys.stdout if sys.argv[1:2] == ["--fixture"] else sys.stderr
    try:
        if len(sys.argv) == 6 and sys.argv[1] == "--fixture":
            with phase("EXERCISE"):
                exercise(Path(sys.argv[2]), *sys.argv[3:])
        elif len(sys.argv) == 1:
            ephemeral()
            print(
                PREFIX,
                "state=PASS absent=verified listener=verified rejected_frame=verified cleanup=verified",
            )
        else:
            raise LabFailure("ARGUMENTS")
    except LabFailure as error:
        print(PREFIX, "state=NO_GO", "check=" + str(error), file=error_output, flush=True)
        raise SystemExit(1) from None
    except Exception as error:
        print(
            PREFIX,
            "state=NO_GO",
            "check=UNAVAILABLE",
            "type=" + type(error).__name__,
            file=error_output,
            flush=True,
        )
        raise SystemExit(1) from None
