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
import struct
import subprocess
import sys
import tempfile
import termios
import time
from collections.abc import Callable
from pathlib import Path
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


def command(*args: str, phase: str, publish: bool = False) -> str:
    result = subprocess.run(  # noqa: S603 - fixed lab argv, no shell or inherited deployment secrets
        args,
        stdin=subprocess.DEVNULL,
        stdout=None if publish else subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=40,
    )
    require(result.returncode == 0, phase)
    return "" if publish else result.stdout.decode("utf-8")


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


def manager(*args: str) -> str:
    return command(SYSTEMCTL, "--user", *args, phase="MANAGER_QUERY")


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
            "list-units", "--all", "--plain", "--no-legend", "boca-bot-control@*.service"
        )
        for line in listing.splitlines():
            fields = line.split()
            if not fields or not re.fullmatch(
                r"boca-bot-control@[A-Za-z0-9_:.\\-]+\.service", fields[0]
            ):
                continue
            name = fields[0]
            state = manager("show", "--property=Result,ExecMainStatus,ActiveState", name)
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

        unitdir = HOME_DIR / ".config/systemd/user"
        (unitdir / "default.target.wants").mkdir(mode=0o700, parents=True, exist_ok=True)
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
            directory = svc.prepare_control_directory(run, lease)
            try:
                try:
                    svc.install_control(item, lease, bundle_sha256=digest)
                except CandidateAcceptanceFailure as exc:
                    raise LabFailure(exc.check + "_" + exc.result) from None
                svc.verify_control(item, lease)
                require(manager("is-enabled", SOCKET).strip() == "enabled", "ENABLE_RECEIPT")
                require(
                    manager("show", "--property=NAccepted", "--value", SOCKET).strip() == "0",
                    "INITIAL_ACCEPTS",
                )
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    connection.settimeout(2)
                    connection.connect(str(directory / "control.sock"))
                    verify_reader(connection)
                instance = rejected_instance()
                require(
                    manager("show", "--property=NAccepted", "--value", SOCKET).strip() == "1",
                    "SINGLE_ACCEPT",
                )
                manager("reset-failed", instance)
                # Rejoining while it listens must preserve the same socket inode.
                inode = (directory / "control.sock").stat()
                svc.install_control(item, lease, bundle_sha256=digest)
                require(
                    os.path.samestat(inode, (directory / "control.sock").stat()), "LISTENING_INODE"
                )
            finally:
                svc.remove_control(run, lease)
            for name in (SOCKET, SERVICE):
                require(
                    svc._state(HOME_DIR, name)["LoadState"] == "not-found", "ABSENT_AFTER_CLEANUP"
                )
            require(not (HOME_DIR / ".boca-on-demand").exists(), "PACKAGE_CLEANUP")


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
            phase="BUILD",
        )
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
        shutil.copyfile(__file__, helper)
        bundle.chmod(0o444)
        helper.chmod(0o444)
        stage.chmod(0o711)
        command(*sudo, "/usr/sbin/groupadd", "--gid", str(UID), USER, phase="LAB_GROUP")
        try:
            command(
                *sudo,
                "/usr/sbin/useradd",
                "--no-user-group",
                "--no-log-init",
                "--uid",
                str(UID),
                "--gid",
                str(UID),
                "--create-home",
                "--home-dir",
                str(HOME_DIR),
                "--shell",
                SHELL,
                "--comment",
                tag,
                USER,
                phase="LAB_ACCOUNT",
            )
            require(
                owned(tag)
                and HOME_DIR.is_dir()
                and not HOME_DIR.is_symlink()
                and HOME_DIR.stat().st_uid == UID,
                "LAB_IDENTITY",
            )
            command(*sudo, "/usr/bin/chmod", "0700", str(HOME_DIR), phase="LAB_HOME")
            command(*sudo, "/usr/bin/loginctl", "enable-linger", USER, phase="LAB_LINGER")
            command(*sudo, SYSTEMCTL, "start", f"user@{UID}.service", phase="LAB_MANAGER")
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
                publish=True,
                phase="FIXTURE",
            )
        finally:
            if owned(tag):
                command(*sudo, "/usr/bin/loginctl", "disable-linger", USER, phase="END_LINGER")
                command(
                    *sudo,
                    SYSTEMCTL,
                    "stop",
                    f"user@{UID}.service",
                    f"user-runtime-dir@{UID}.service",
                    phase="END_MANAGER",
                )
                require(owned(tag), "END_IDENTITY")
                command(*sudo, "/usr/sbin/userdel", "--remove", USER, phase="END_ACCOUNT")
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
                command(*sudo, "/usr/sbin/groupdel", USER, phase="END_GROUP")
    require(vacant(), "FINAL_ACCOUNT_RESIDUE")


if __name__ == "__main__":
    error_output = sys.stdout if sys.argv[1:2] == ["--fixture"] else sys.stderr
    try:
        if len(sys.argv) == 6 and sys.argv[1] == "--fixture":
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
        print(PREFIX, "state=NO_GO", "check=" + str(error), file=error_output)
        raise SystemExit(1) from None
    except Exception as error:
        print(
            PREFIX,
            "state=NO_GO",
            "check=UNAVAILABLE",
            "type=" + type(error).__name__,
            file=error_output,
        )
        raise SystemExit(1) from None
