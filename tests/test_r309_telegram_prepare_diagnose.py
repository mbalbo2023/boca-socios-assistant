"""D1–D10: execute literal image programs and real validators; fake external I/O only."""

from __future__ import annotations

import builtins
import errno
import hashlib
import io
import json
import os
import pwd
import sqlite3
import stat
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_on_demand_service as service
from boca_socios import host_telegram_backend as backend
from boca_socios import host_telegram_maintenance as maintenance
from boca_socios import host_telegram_status as status
from boca_socios.host_lifecycle_rootless_adapter import ReviewedInstalledPair
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "845f31abfb1762dff27e6fc3274fcc40507f3f18"
APPLY = "43704768556"
INCIDENT = "43738415332"
WORKFLOW = "b" * 40
RUN = "43740000123"
CONTROLLER = "b0dd0fed57c55dbdeb9a6e833d913cb86c0868ae1587394a934450342114bfa1"
WORKER = "c9c882ff12666fb6cac130879925879cfc0c5c23173a843434adee96b4339dce"
IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:9fc622a3a7165ce03d1113b5f7f334d402a0dad0c6cbfe2da28075843d11bea0"
BROWSER = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:1a59e0b0cb5eb3621820aed635364076542b691fa6e9c73c0e344f09dacc3abe"
KEY = "telegram_recipient_x25519.key"
PUBLIC = "telegram_recipient_public_v2.json"
ADMIN = "boca_telegram_admin_status_v1.json"
PUBLIC_KEY = "e06Qm75__kTEZaIgA31gjuNYl9Me-XLwf3SJLLD3PxM"
FINGERPRINT = "d19bf3f082782c87b783fe7134698aeff6e66d9f86afaf7cf9e9b8bf40bab3ff"
VOLUME = "boca-socios_boca_telegram"
VOLUME_ROOT = "/home/boca-deploy/.local/share/docker/volumes/"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def public_document(**changes):
    return {
        "version": 2,
        "purpose": "boca-telegram-prepared-recipient-v2",
        "source_sha": SOURCE,
        "installation_fingerprint": "f" * 64,
        "recipient": {
            "state": "PREPARED",
            "public_key": PUBLIC_KEY,
            "fingerprint": FINGERPRINT,
        },
        **changes,
    }


def admin_document(**changes):
    return {
        "version": 1,
        "source_sha": SOURCE,
        "observation_run_id": "43705000000",
        "installation_run_id": APPLY,
        "controller_id": CONTROLLER,
        "worker_id": WORKER,
        "sender_id": None,
        "observed_at": "2020-11-15T00:00:00+00:00",
        "configured": "UNVERIFIED",
        "paired": "UNVERIFIED",
        "sender": "ABSENT",
        "human_receipt": "UNVERIFIED",
        **changes,
    }


class ProgramFS:
    """Real files/descriptors, with only the container path/UID I/O translated."""

    def __init__(self, tmp_path):
        self.root = tmp_path / "image-root"
        self.data = self.root / "data"
        self.custody = self.root / "run/telegram"
        self.data.mkdir(parents=True, mode=0o700)
        self.custody.mkdir(parents=True, mode=0o700)
        self.opens = []
        self.secret_reads = []
        self.scan_counts = []
        self.open_fault = None
        self.stat_fault = None
        self.after_private_open = None
        self.host = False
        self.lease_descriptors = []

    def write(self, name, data, *, mode=None):
        path = (self.custody if name == KEY or name.startswith("extra") else self.data) / name
        path.write_bytes(data)
        path.chmod(mode if mode is not None else 0o600 if name == ADMIN else 0o400)
        return path

    def install(self, monkeypatch):
        real_open, real_stat, real_fstat, real_scandir = os.open, os.stat, os.fstat, os.scandir
        real_lstat, real_listdir, real_readlink = os.lstat, os.listdir, os.readlink

        def mapped(path):
            if not isinstance(path, (str, bytes, os.PathLike)):
                return path
            value = os.fsdecode(path)
            if (
                value == "/"
                or value == "/data"
                or value.startswith("/data/")
                or value == "/run"
                or value == "/run/telegram"
            ):
                return self.root / value.removeprefix("/")
            if self.host and (
                value.startswith("/home/boca-deploy") or value.startswith("/run/user/10001")
            ):
                return self.root / value.removeprefix("/")
            return path

        def metadata(value):
            values = list(value)
            values[4:6] = [10001, 10001]
            return os.stat_result(
                values,
                {
                    "st_atime_ns": value.st_atime_ns,
                    "st_mtime_ns": value.st_mtime_ns,
                    "st_ctime_ns": value.st_ctime_ns,
                },
            )

        def opened(path, flags, *args, **kwargs):
            name = os.fsdecode(path)
            self.opens.append(name)
            if self.open_fault is not None:
                self.open_fault(name, flags)
            descriptor = real_open(mapped(path), flags, *args, **kwargs)
            if name == cleanup.LEASE_FILE and flags & os.O_CREAT:
                self.lease_descriptors.append((kwargs["dir_fd"], descriptor))
            if name == KEY:
                self.secret_reads.append(descriptor)
                if self.after_private_open is not None:
                    self.after_private_open(len(self.secret_reads))
            return descriptor

        def observed(path, *args, **kwargs):
            if self.stat_fault is not None:
                self.stat_fault(os.fsdecode(path))
            return metadata(real_stat(mapped(path), *args, **kwargs))

        def scanned(path):
            original = real_scandir(mapped(path))
            count = [0]
            self.scan_counts.append(count)

            class BoundedScan:
                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    original.close()

                def __iter__(self):
                    return self

                def __next__(self):
                    count[0] += 1
                    assert count[0] <= 2, "a snapshot must inspect at most two entries"
                    return next(original)

            return BoundedScan()

        monkeypatch.setattr(os, "open", opened)
        monkeypatch.setattr(os, "stat", observed)
        monkeypatch.setattr(os, "fstat", lambda fd: metadata(real_fstat(fd)))
        monkeypatch.setattr(os, "scandir", scanned)
        if self.host:
            monkeypatch.setattr(os, "scandir", lambda path: real_scandir(mapped(path)))
            monkeypatch.setattr(
                os, "lstat", lambda path, *a, **kw: metadata(real_lstat(mapped(path), *a, **kw))
            )
            monkeypatch.setattr(os, "listdir", lambda path: real_listdir(mapped(path)))
            monkeypatch.setattr(
                os, "readlink", lambda path, *a, **kw: real_readlink(mapped(path), *a, **kw)
            )
        for name in ("getuid", "geteuid", "getgid", "getegid"):
            monkeypatch.setattr(os, name, lambda: 10001)
        monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: pytest.fail("SQL is forbidden"))


def execute_program(module, name, fs, monkeypatch, *, payload=b"{}", missing=""):
    program = getattr(module, name, None)
    assert isinstance(program, str), f"D3/D5 literal program {name} is missing"
    captured = io.BytesIO()
    with monkeypatch.context() as scoped:
        fs.install(scoped)
        scoped.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(payload)))
        scoped.setattr(sys, "stdout", SimpleNamespace(buffer=captured))
        if missing:
            original = builtins.__import__

            def import_module(name, *args, **kwargs):
                if name == missing:
                    raise ImportError("synthetic image dependency absent")
                return original(name, *args, **kwargs)

            scoped.setattr(builtins, "__import__", import_module)
        exec(compile(program, "<fixed-installed-R-program>", "exec"), {"__name__": "__main__"})  # noqa: S102 - exact owned literal, external filesystem I/O isolated
    raw = captured.getvalue()
    assert 0 < len(raw) <= 4096
    value = json.loads(raw)
    assert canonical(value) == raw
    return value, raw


def test_d3_public_program_uses_installed_r_parsers_and_retains_old_history(tmp_path, monkeypatch):
    fs = ProgramFS(tmp_path)
    fs.write(PUBLIC, canonical(public_document()))
    fs.write(ADMIN, canonical(admin_document()) + b"\n")
    value, raw = execute_program(status, "PUBLIC_OBSERVE_PROGRAM", fs, monkeypatch)
    assert value["recipient"]["state"] == value["admin"]["state"] == "VALID"
    assert value["recipient"]["fingerprint"] == FINGERPRINT
    assert value["admin"]["observation_run_id"] == "43705000000"
    assert value["admin"]["observed_at"] == "2020-11-15T00:00:00+00:00"
    assert set(fs.opens) <= {"/", "data", PUBLIC, ADMIN, "/data/" + ADMIN}
    assert not fs.secret_reads and b"bot_token" not in raw
    # These exact unchanged files were compared to the installed R commit before coding.
    for relative, digest in (
        (
            "telegram_bootstrap.py",
            "61e884e05fb05b4b43aa0842a5a36f5b1a1a584ff2f87f64240090b73f444941",
        ),
        (
            "panel/telegram_recipient.py",
            "d9b11bbd043f2452575e2ae4b97be06d224b6fd8a8683e232dae67f07663edd2",
        ),
        (
            "notify/projection.py",
            "adc46d2b453dae6a9b61361415783195a17276e792c920b8c034619102446a19",
        ),
    ):
        assert (
            hashlib.sha256((ROOT / "src/boca_socios" / relative).read_bytes()).hexdigest() == digest
        )


@pytest.mark.parametrize(
    "fault,want",
    [
        ("absent", "ABSENT"),
        ("denied", "NOT_READ"),
        ("io", "NOT_READ"),
        ("link", "INVALID"),
        ("mode", "INVALID"),
        ("invalid", "INVALID"),
        ("source", "INVALID"),
        ("extra", "INVALID"),
        ("dependency", "NOT_READ"),
    ],
)
def test_d3_public_absence_is_only_enoent_under_valid_parent(tmp_path, monkeypatch, fault, want):
    fs = ProgramFS(tmp_path)
    if fault != "absent":
        document = public_document()
        if fault == "source":
            document["source_sha"] = "not-a-source"
        if fault == "extra":
            document["secret"] = "must-not-escape"
        target = fs.write(
            PUBLIC, b"invalid-secret-bytes" if fault == "invalid" else canonical(document)
        )
        if fault == "mode":
            target.chmod(0o600)
        if fault == "link":
            target.unlink()
            target.symlink_to("unread-private-target")
    if fault in {"denied", "io"}:

        def fail(name):
            if name == PUBLIC:
                raise OSError(errno.EACCES if fault == "denied" else errno.EIO, "must-not-escape")

        fs.stat_fault = fail
    value, raw = execute_program(
        status,
        "PUBLIC_OBSERVE_PROGRAM",
        fs,
        monkeypatch,
        missing="boca_socios.panel.telegram_recipient" if fault == "dependency" else "",
    )
    assert value["recipient"]["state"] == want
    assert b"must-not-escape" not in raw and b"invalid-secret" not in raw
    assert not fs.secret_reads


@pytest.mark.parametrize(
    "fault,want,entries",
    [
        ("empty", "ABSENT", "EMPTY"),
        ("key", "VALID", "KEY_ONLY"),
        ("extra", "NOT_READ", "EXTRA_ENTRIES_PRESENT"),
        ("link", "INVALID", "KEY_ONLY"),
        ("mode", "INVALID", "KEY_ONLY"),
        ("size", "INVALID", "KEY_ONLY"),
        ("nlink", "INVALID", "KEY_ONLY"),
        ("denied", "NOT_READ", "KEY_ONLY"),
        ("io", "NOT_READ", "KEY_ONLY"),
        ("dependency", "NOT_READ", "KEY_ONLY"),
    ],
)
def test_d5_two_key_snapshots_never_read_secret_for_extra_or_invalid_metadata(
    tmp_path, monkeypatch, fault, want, entries
):
    fs = ProgramFS(tmp_path)
    if fault != "empty":
        key = fs.write(KEY, b"\x11" * (31 if fault == "size" else 32))
        if fault == "extra":
            fs.write("extra-private-one", b"never-read-me")
            fs.write("extra-private-two", b"never-read-me")
        if fault == "link":
            key.unlink()
            key.symlink_to("never-read-me")
        if fault == "mode":
            key.chmod(0o600)
        if fault == "nlink":
            os.link(key, fs.root / "other-key-link")
    if fault in {"denied", "io"}:

        def fail(name, flags):
            if name == KEY:
                raise OSError(errno.EACCES if fault == "denied" else errno.EIO, "never-read-me")

        fs.open_fault = fail
    value, raw = execute_program(
        maintenance,
        "RECIPIENT_OBSERVE_PROGRAM",
        fs,
        monkeypatch,
        missing="cryptography.hazmat.primitives.asymmetric.x25519" if fault == "dependency" else "",
    )
    assert (value["state"], value["entries"], value["samples"]) == (want, entries, 2)
    assert value["fingerprint"] == (FINGERPRINT if fault == "key" else None)
    assert len(fs.secret_reads) == (2 if fault in {"key", "dependency"} else 0)
    assert len(fs.scan_counts) == 2 and all(count[0] <= 2 for count in fs.scan_counts)
    assert b"never-read-me" not in raw and b"extra-private" not in raw


def test_d5_inode_drift_between_new_descriptors_is_changed(tmp_path, monkeypatch):
    fs = ProgramFS(tmp_path)
    key = fs.write(KEY, b"\x11" * 32)

    def replace_on_second_open(count):
        if count == 2:
            key.unlink()
            fs.write(KEY, b"\x11" * 32)

    fs.after_private_open = replace_on_second_open
    value, _ = execute_program(maintenance, "RECIPIENT_OBSERVE_PROGRAM", fs, monkeypatch)
    assert value["state"] == "CHANGED" and value["fingerprint"] is None


def test_d7_diagnosis_entrypoint_is_distinct_from_prepare():
    assert callable(getattr(backend, "diagnose_installed_telegram", None)), "D1 coordinator missing"
    assert callable(getattr(backend, "verify_prepare_diagnosis", None)), "D7 codec missing"


def test_d3_d5_invalid_parent_metadata_changes_are_not_stable(tmp_path, monkeypatch):
    fs = ProgramFS(tmp_path)
    fs.data.chmod(0o755)
    first, _ = execute_program(status, "PUBLIC_OBSERVE_PROGRAM", fs, monkeypatch)
    fs.data.chmod(0o750)
    second, _ = execute_program(status, "PUBLIC_OBSERVE_PROGRAM", fs, monkeypatch)
    assert first["recipient"]["state"] == second["recipient"]["state"] == "INVALID"
    assert first["recipient"]["witness"] != second["recipient"]["witness"]
    fs.custody.chmod(0o755)
    opens = 0

    def changed_parent(name, flags):
        nonlocal opens
        if name == "telegram":
            opens += 1
            if opens == 2:
                fs.custody.chmod(0o750)

    fs.open_fault = changed_parent
    result, _ = execute_program(maintenance, "RECIPIENT_OBSERVE_PROGRAM", fs, monkeypatch)
    assert result["state"] == result["entries"] == "CHANGED"
    assert fs.secret_reads == []


class Runtime:
    """Existing real lease, binding and profile validators over external OS/Docker fixtures."""

    def __init__(self, tmp_path, monkeypatch, *, volume=True, fault=""):
        import test_host_lifecycle_rootless_adapter as fixtures

        self.fs = ProgramFS(tmp_path)
        self.fs.host = True
        self.fault = fault
        self.events = []
        self.helper = None
        self.public_reads = 0
        self.helper_inspects = 0
        self.created_commands = []
        self.pipe_override = None
        self.monkeypatch = monkeypatch
        self.home = Path("/home/boca-deploy")
        local_home = self.fs.root / "home/boca-deploy"
        control = local_home / service._ROOT
        unit_dir = local_home / ".config/systemd/user"
        wants = unit_dir / "default.target.wants"
        for path in (local_home, control, unit_dir, wants, self.fs.root / "run/user/10001"):
            path.mkdir(parents=True, mode=0o700, exist_ok=True)
        for path in (local_home / ".config", local_home / ".config/systemd"):
            path.chmod(0o700)
        socket_dir = control / "socket"
        socket_dir.mkdir(mode=0o711)
        os.mknod(socket_dir / service._SOCKET_NAME, stat.S_IFSOCK | 0o666)
        (socket_dir / service._SOCKET_NAME).chmod(0o666)
        self.item = OnDemandInstallation(
            installation_run_id=APPLY,
            source_sha=SOURCE,
            controller_id=CONTROLLER,
            controller_image=IMAGE,
            worker_id=WORKER,
            worker_image=BROWSER,
            database_path=self.home / service._DB,
            pair=ReviewedInstalledPair(
                APPLY,
                "e" * 64,
                "f" * 64,
                sender_id=fixtures.SENDER if fault == "registered-sender" else "",
                sender_config_hash=fixtures.CONFIG_SENDER if fault == "registered-sender" else "",
                sender_attempt_id=fixtures.SENDER_ATTEMPT if fault == "registered-sender" else "",
            ),
        )
        archive = b"offline pinned existing binding archive"
        plan = service._plan(self.home, self.item, hashlib.sha256(archive).hexdigest())
        units = service._units(
            hashlib.sha256(archive).hexdigest(), hashlib.sha256(plan).hexdigest()
        )
        for name, raw in (
            (service._MARKER, (APPLY + "\n").encode()),
            (service._BINDING, plan),
            (service._ARCHIVE, archive),
            *units.items(),
        ):
            path = control / name
            path.write_bytes(raw)
            path.chmod(0o600)
        for name in units:
            os.link(control / name, unit_dir / name)
        (wants / service._SOCKET).symlink_to("../" + service._SOCKET)
        for name, value in {
            "SOURCE": SOURCE,
            "CONTROLLER": CONTROLLER,
            "WORKER": WORKER,
            "CONTROLLER_REF": IMAGE,
            "WORKER_REF": BROWSER,
            "INSTALLED": APPLY,
            "CONFIG_CONTROLLER": "e" * 64,
            "CONFIG_WORKER": "f" * 64,
        }.items():
            monkeypatch.setattr(fixtures, name, value)
        self.reader = fixtures.FakeIO(
            self.item.database_path.parent,
            worker_running=False,
            sender_running=False if fault == "registered-sender" else None,
        )
        self.reader.fields[("container", CONTROLLER, "HostConfig.RestartPolicy")] = {
            "Name": "unless-stopped",
            "MaximumRetryCount": 0,
        }
        self.reader.fields[("container", WORKER, "HostConfig.PortBindings")] = {}
        for ident in (CONTROLLER, WORKER):
            for mount in self.reader.fields[("container", ident, "Mounts")]:
                mount["Source"] = VOLUME_ROOT + mount["Name"] + "/_data"
        self.reader.fields[("container", CONTROLLER, "Mounts")].append(
            {
                "Type": "bind",
                "Source": str(self.home / service._ROOT / "socket"),
                "Destination": "/run/boca-bot-control",
                "RW": False,
                "Propagation": "rprivate",
            }
        )
        if volume and not any(
            entry.name == VOLUME for entry in self.reader.inventory_value.volumes
        ):
            self.reader.inventory_value = replace(
                self.reader.inventory_value,
                volumes=(
                    *self.reader.inventory_value.volumes,
                    cleanup.Volume(
                        VOLUME,
                        (
                            ("com.docker.compose.project", "boca-socios"),
                            ("com.docker.compose.volume", "boca_telegram"),
                        ),
                    ),
                ),
            )
        for entry in self.reader.inventory_value.volumes:
            path = VOLUME_ROOT + entry.name + "/_data"
            (self.fs.root / path.removeprefix("/")).mkdir(parents=True, mode=0o700)
            self.reader.fields[("volume", entry.name, "Mountpoint")] = path
            self.reader.fields[("volume", entry.name, "Name")] = entry.name
        original_inventory = self.reader.inventory

        def inventory():
            current = original_inventory()
            if self.helper is not None:
                current = replace(
                    current,
                    containers=(
                        *current.containers,
                        cleanup.Container(
                            "d" * 64,
                            self.helper["Name"],
                            "sha256:" + "a" * 64,
                            self.helper["State"]["Running"],
                            (("com.docker.compose.project", "boca-socios"),),
                            (VOLUME,),
                            (),
                        ),
                    ),
                )
            return current

        self.reader.inventory = inventory
        self.real_popen = subprocess.Popen

    def literal(self, program, payload=b"{}"):
        captured = io.BytesIO()
        with self.monkeypatch.context() as scoped:
            scoped.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(payload)))
            scoped.setattr(sys, "stdout", SimpleNamespace(buffer=captured))
            exec(compile(program, "<installed-image-literal>", "exec"), {"__name__": "__main__"})  # noqa: S102 - exact owned literal, external filesystem I/O isolated
        return captured.getvalue()

    def command(self, argv, **kwargs):
        args = tuple(argv)
        if args[0] == "/usr/bin/systemctl":
            assert args[1:3] == ("--user", "show")
            name = service._SOCKET if args[-1] == service._SOCKET else service._SERVICE
            text = (
                "LoadState=loaded\nFragmentPath="
                + str(self.home / ".config/systemd/user" / name)
                + "\nDropInPaths=\nActiveState="
                + ("active" if name == service._SOCKET else "inactive")
                + "\nSubState="
                + ("listening" if name == service._SOCKET else "dead")
                + "\n"
            )
            return subprocess.CompletedProcess(argv, 0, text.encode(), b"")
        command = (
            args[3:]
            if args[:3] == ("/usr/bin/docker", "--host", cleanup.DOCKER_SOCKET)
            else args[1:]
        )
        assert args[0] in {"docker", "/usr/bin/docker"}, args
        if command[:2] == ("volume", "inspect"):
            result = json.dumps(
                {
                    "Name": VOLUME,
                    "Driver": "local",
                    "Scope": "local",
                    "Options": {},
                    "Mountpoint": VOLUME_ROOT + VOLUME + "/_data",
                    "Labels": {
                        "com.docker.compose.project": "boca-socios",
                        "com.docker.compose.volume": "boca_telegram",
                    },
                }
            )
        elif command == ("info", "--format", "{{.DockerRootDir}}"):
            result = "/home/boca-deploy/.local/share/docker"
        elif command[0] == "create":
            assert self.helper is None, "a second helper is forbidden"
            self.events.append("CREATE")
            assert command[command.index("--network") + 1] == "none"
            assert command[command.index("--user") + 1] == "10001:10001"
            assert command[command.index("--log-driver") + 1] == "none"
            assert command[command.index("--cpus") + 1] == "0.25"
            assert command[command.index("--memory") + 1] == "64m"
            assert command[command.index("--pids-limit") + 1] == "16"
            assert command.count("--mount") == 1
            assert (
                command[command.index("--mount") + 1]
                == f"type=volume,source={VOLUME},target=/run/telegram,volume-nocopy,readonly"
            )
            assert "--rm" not in command and "--cap-add" not in command
            image_index = command.index(IMAGE)
            self.created_commands.append(command[image_index + 1 :])
            self.helper = {
                "Id": "d" * 64,
                "Name": "/" + command[command.index("--name") + 1],
                "Config": {
                    "Image": IMAGE,
                    "User": "10001:10001",
                    "Cmd": list(command[image_index + 1 :]),
                    "Labels": {"com.docker.compose.project": "boca-socios"},
                },
                "HostConfig": {
                    "NetworkMode": "none",
                    "ReadonlyRootfs": True,
                    "Privileged": False,
                    "LogConfig": {"Type": "none"},
                    "CapDrop": ["ALL"],
                    "CapAdd": None,
                    "PidsLimit": 16,
                    "Memory": 67108864,
                    "NanoCpus": 250000000,
                    "PublishAllPorts": False,
                    "PortBindings": {},
                    "RestartPolicy": {"Name": "no"},
                    "SecurityOpt": ["no-new-privileges"],
                },
                "Mounts": [
                    {
                        "Type": "volume",
                        "Name": VOLUME,
                        "Source": VOLUME_ROOT + VOLUME + "/_data",
                        "Destination": "/run/telegram",
                        "RW": False,
                        "Driver": "local",
                    }
                ],
                "NetworkSettings": {"Networks": {"none": {}}},
                "State": {"Running": False, "Restarting": False, "ExitCode": 0, "Pid": 0},
            }
            if self.fault == "cmd-before":
                self.helper["Config"]["Cmd"][-1] += "\npass"
            if self.fault == "relative-interpreter":
                self.helper["Config"]["Cmd"][0] = "python"
            result = "uncertain" if self.fault == "create-ack" else "d" * 64
        elif command[:3] == ("inspect", "--format", "{{json .}}"):
            assert command[-1] == "d" * 64 and self.helper is not None
            self.helper_inspects += 1
            result = json.dumps(self.helper)
        elif command == ("stop", "-t", "5", "d" * 64):
            self.events.append("STOP_HELPER")
            assert self.helper is not None
            self.helper["State"]["Running"] = False
            result = "uncertain" if self.fault == "stop-ack" else "d" * 64
        elif command == ("rm", "d" * 64):
            self.events.append("REMOVE_HELPER")
            assert self.helper is not None and not self.helper["State"]["Running"]
            if self.fault != "remove-ack":
                self.helper = None
            result = "uncertain" if self.fault == "remove-ack" else "d" * 64
        else:
            pytest.fail("forbidden host operation " + repr(command[:3]))
        return subprocess.CompletedProcess(
            argv,
            0,
            result if kwargs.get("text") else result.encode(),
            "" if kwargs.get("text") else b"",
        )

    def process(self, argv, **kwargs):
        args = tuple(argv)
        assert args[:3] == ("/usr/bin/docker", "--host", cleanup.DOCKER_SOCKET)
        command = args[3:]
        if command[:3] == ("exec", "--user", "10001:10001"):
            assert command[3:8] == (CONTROLLER, "/app/.venv/bin/python", "-I", "-B", "-c")
            assert command[8:] == (status.PUBLIC_OBSERVE_PROGRAM,)
            self.public_reads += 1
            self.events.append("PUBLIC_A" if self.public_reads == 1 else "PUBLIC_B")
            if self.fault == "public-drift" and self.public_reads == 2:
                self.fs.write(
                    PUBLIC,
                    canonical(public_document(installation_fingerprint=self.item.fingerprint())),
                )
            raw = self.literal(command[-1])
            if self.public_reads == 2 and self.fault == "guard-after":
                self.reader.engine_running = True
        else:
            assert command == ("start", "--attach", "--interactive", "d" * 64)
            assert self.helper is not None
            self.events.append("START_HELPER")
            assert self.helper["Config"]["Cmd"] == [
                "/app/.venv/bin/python",
                "-I",
                "-B",
                "-c",
                maintenance.RECIPIENT_OBSERVE_PROGRAM,
            ]
            raw = self.literal(self.helper["Config"]["Cmd"][-1])
            if self.fault == "cmd-after":
                self.helper["Config"]["Cmd"][-1] += "\npass"
            if self.fault in {"pipe", "stop-ack"}:
                self.helper["State"]["Running"] = True
        script = "import os,sys; sys.stdin.buffer.read(); os.write(1,bytes.fromhex(sys.argv[1]))"
        if self.fault in {"pipe", "stop-ack"} and command[0] == "start":
            raw = b"x" * 4097
        if self.pipe_override is not None and command[0] == self.pipe_override[0]:
            raw = self.pipe_override[1]
        return self.real_popen([sys.executable, "-I", "-B", "-c", script, raw.hex()], **kwargs)

    @contextmanager
    def boundary(self):
        with self.monkeypatch.context() as scoped:
            self.fs.install(scoped)
            scoped.setattr(
                pwd,
                "getpwuid",
                lambda uid: SimpleNamespace(
                    pw_name="boca-deploy", pw_dir=str(self.home), pw_gid=10001
                ),
            )
            scoped.setattr(subprocess, "run", self.command)
            scoped.setattr(subprocess, "Popen", self.process)
            for name in (
                "DOCKER_HOST",
                "DOCKER_CONTEXT",
                "DOCKER_TLS_VERIFY",
                "DOCKER_CERT_PATH",
                "DOCKER_TLS",
                "DOCKER_CONFIG",
            ):
                scoped.delenv(name, raising=False)
            yield scoped

    @contextmanager
    def installed(self):
        with self.boundary(), cleanup.protected_boca_job_lease(RUN) as lease:
            yield lease

    def diagnose(self):
        target = getattr(backend, "diagnose_installed_telegram", None)
        assert callable(target), "D1 coordinator missing"
        with self.installed() as lease:
            raw = target(
                RUN,
                lease=lease,
                reader=self.reader,
                expected_source_sha=SOURCE,
                workflow_sha=WORKFLOW,
            )
        assert len(raw) <= 4096
        return json.loads(raw.split(b" ", 1)[1]), raw


@pytest.mark.parametrize(
    "public,key,volume,want",
    [
        (False, True, True, "PREPARE_FINAL_REUSE_KEY"),
        (True, True, True, "PUBLIC_REBIND_REQUIRED"),
        (False, False, True, "PREPARE_FINAL_CREATE_KEY"),
        (False, False, False, "PREPARE_FINAL_CREATE_KEY"),
        (True, False, True, "INCONSISTENT_PRESERVE"),
    ],
)
def test_d1_d8_full_diagnosis_uses_real_binding_lease_and_profiles(
    tmp_path, monkeypatch, public, key, volume, want
):
    fixture = Runtime(tmp_path, monkeypatch, volume=volume)
    if public:
        fixture.fs.write(
            PUBLIC, canonical(public_document(installation_fingerprint=fixture.item.fingerprint()))
        )
    fixture.fs.write(ADMIN, canonical(admin_document()) + b"\n")
    if key:
        fixture.fs.write(KEY, b"\x11" * 32)
    value, raw = fixture.diagnose()
    assert (value["state"], value["phase"], value["reason"]) == (
        "OBSERVED_NO_GO",
        "COMPLETE",
        "NONE",
    )
    assert value["recommendation"] == want
    assert (
        value["source_sha"] == SOURCE
        and value["installation_run_id"] == APPLY
        and value["incident_run_id"] == INCIDENT
    )
    assert value["workflow_source_sha"] == WORKFLOW and value["attempt_id"] == RUN
    assert value["engine"] == "STOPPED" and value["sender"] == "ABSENT"
    assert value["stage"] == "NOT_INSPECTED" and value["historical_cause"] == "UNDETERMINED"
    assert value["prepare_authorized"] is value["adopt_authorized"] is False
    assert value["data_writes"] == value["custody_writes"] == value["status_writes"] == 0
    assert fixture.events == (
        ["PUBLIC_A", "CREATE", "START_HELPER", "REMOVE_HELPER", "PUBLIC_B"]
        if volume
        else ["PUBLIC_A", "PUBLIC_B"]
    )
    assert value["helper"]["retirement"] == ("RETIRED" if volume else "NOT_ATTEMPTED")
    assert fixture.reader.effects == [] and fixture.helper is None
    assert not any(
        name.encode() in raw
        for name in (KEY, "bot_token", "chat_id", "boca.sqlite3", "/run/telegram")
    )


@pytest.mark.parametrize(
    "fault",
    [
        "sender",
        "extra-helper",
        "writer",
        "writer-alias",
        "worker",
        "engine",
        "source",
        "binding",
        "volume-alias",
    ],
)
def test_d2_guard_refuses_before_public_or_helper_effects(tmp_path, monkeypatch, fault):
    fixture = Runtime(tmp_path, monkeypatch)
    if fault in {"sender", "extra-helper"}:
        extra = cleanup.Container(
            "a" * 64,
            "/boca-socios-telegram-1" if fault == "sender" else "/boca-socios-telegram-maint-old",
            "sha256:" + "a" * 64,
            False,
            (("com.docker.compose.project", "boca-socios"),),
            (VOLUME,),
            (),
        )
        fixture.reader.inventory_value = replace(
            fixture.reader.inventory_value,
            containers=(*fixture.reader.inventory_value.containers, extra),
        )
    elif fault == "writer":
        fixture.reader.fields[("container", CONTROLLER, "Mounts")][0]["Source"] = (
            VOLUME_ROOT + VOLUME + "/_data"
        )
    elif fault == "writer-alias":
        fixture.reader.fields[("container", CONTROLLER, "Mounts")][0]["Source"] = (
            VOLUME_ROOT + "boca-socios_boca_data/../" + VOLUME + "/_data"
        )
    elif fault == "worker":
        fixture.reader.set_state(WORKER, True)
    elif fault == "engine":
        fixture.reader.engine_running = True
    elif fault == "volume-alias":
        fixture.reader.fields[("volume", VOLUME, "Mountpoint")] += "/../_data"
    else:
        local = fixture.fs.root / "home/boca-deploy" / service._ROOT / service._BINDING
        data = json.loads(local.read_bytes())
        data["installation"]["source_sha" if fault == "source" else "installation_run_id"] = (
            "a" * 40 if fault == "source" else "43704768557"
        )
        local.write_bytes(canonical(data))
    value, _ = fixture.diagnose()
    assert value["state"] == "INCOMPLETE_NO_GO" and value["recommendation"] == "PRESERVE_REVIEW"
    assert value["helper"]["create_attempted"] is False and fixture.events == []


@pytest.mark.parametrize(
    "fault,retirement,removed",
    [
        ("cmd-before", "INDETERMINATE", False),
        ("cmd-after", "INDETERMINATE", False),
        ("create-ack", "INDETERMINATE", False),
        ("remove-ack", "INDETERMINATE", True),
        ("pipe", "RETIRED", True),
        ("stop-ack", "INDETERMINATE", False),
        ("public-drift", "RETIRED", True),
    ],
)
def test_d4_d6_uncertainty_preserves_exact_helper_and_never_retries(
    tmp_path, monkeypatch, fault, retirement, removed
):
    fixture = Runtime(tmp_path, monkeypatch, fault=fault)
    fixture.fs.write(KEY, b"\x11" * 32)
    value, _ = fixture.diagnose()
    assert value["state"] == "INCOMPLETE_NO_GO" and value["recommendation"] == "PRESERVE_REVIEW"
    assert value["helper"]["retirement"] == retirement
    assert value["helper"]["id"] == (None if fault == "create-ack" else "d" * 64)
    assert fixture.events.count("CREATE") == 1 and fixture.events.count("START_HELPER") <= 1
    assert ("REMOVE_HELPER" in fixture.events) is removed
    if fault in {"pipe", "stop-ack"}:
        assert fixture.events.count("STOP_HELPER") == 1
    assert fixture.reader.effects == []


@pytest.mark.parametrize(
    "case,want",
    [
        ("public-source", "PRESERVE_REVIEW"),
        ("public-binding", "PRESERVE_REVIEW"),
        ("admin-source", "PRESERVE_REVIEW"),
        ("admin-invalid", "PRESERVE_REVIEW"),
        ("key-mismatch", "PRESERVE_REVIEW"),
        ("extra", "CUSTODY_PRESENT_REVIEW"),
        ("key-invalid", "PRESERVE_REVIEW"),
    ],
)
def test_d8_non_actionable_observations_preserve_custody(tmp_path, monkeypatch, case, want):
    fixture = Runtime(tmp_path, monkeypatch)
    public = public_document(installation_fingerprint=fixture.item.fingerprint())
    admin = admin_document()
    if case == "public-source":
        public["source_sha"] = "a" * 40
    if case == "public-binding":
        public["installation_fingerprint"] = "a" * 64
    if case == "admin-source":
        admin["source_sha"] = "a" * 40
    fixture.fs.write(PUBLIC, canonical(public))
    fixture.fs.write(ADMIN, b"invalid" if case == "admin-invalid" else canonical(admin) + b"\n")
    fixture.fs.write(
        KEY,
        b"\x12" * 32 if case == "key-mismatch" else b"\x11" * 32,
        mode=0o600 if case == "key-invalid" else 0o400,
    )
    if case == "extra":
        fixture.fs.write("extra-secret", b"NEVER_EXPORTED")
    value, raw = fixture.diagnose()
    assert value["state"] == "OBSERVED_NO_GO" and value["recommendation"] == want
    if case in {"extra", "key-invalid"}:
        assert fixture.fs.secret_reads == []
    assert b"NEVER_EXPORTED" not in raw and b"unexpected-secret" not in raw


def test_d7_codec_rejects_closed_schema_and_cross_protocol_forgery(tmp_path, monkeypatch):
    fixture = Runtime(tmp_path, monkeypatch, volume=False)
    value, raw = fixture.diagnose()
    verify = getattr(backend, "verify_prepare_diagnosis", None)
    assert callable(verify), "D7 codec missing"
    kwargs = {"attempt_id": RUN, "source_sha": SOURCE, "workflow_sha": WORKFLOW}
    assert verify(raw, **kwargs) == value
    prefix = raw.split(b" ", 1)[0] + b" "
    mutations = [
        ("extra", "NEVER_EXPORTED"),
        ("version", True),
        ("operation", "prepare"),
        ("source_sha", "b" * 40),
        ("workflow_source_sha", SOURCE),
        ("attempt_id", "43705000001"),
        ("installation_run_id", "43704768557"),
        ("incident_run_id", RUN),
        ("phase", "PREFLIGHT"),
        ("reason", "GUARD_UNVERIFIED"),
        ("state", "PREPARED"),
        ("recommendation", "PREPARE_FINAL_REUSE_KEY"),
        ("data_writes", True),
        ("custody_writes", 1),
        ("status_writes", -1),
        ("prepare_authorized", True),
        ("adopt_authorized", True),
        ("engine", "RUNNING"),
        ("sender", "RUNNING"),
        ("stage", "ABSENT"),
        ("historical_cause", "RECOVERED"),
        ("helper", {**value["helper"], "id": "SECRET"}),
        ("helper", {**value["helper"], "start_attempted": True}),
        ("custody", {**value["custody"], "fingerprint": "SECRET"}),
        ("recipient", {**value["recipient"], "source_sha": "bad"}),
        ("admin", {**value["admin"], "observed_at": "SECRET"}),
    ]
    for field, replacement in mutations:
        changed = {**value, field: replacement}
        with pytest.raises(ValueError):
            verify(prefix + canonical(changed) + b"\n", **kwargs)
    for broken in (
        raw + b"\n",
        raw[:-1],
        raw.replace(b"{", b"{ ", 1),
        b"x" * 4097,
        raw.replace(b'"version":1', b'"version":1,"version":1'),
        backend.TelegramBackendReceipt(
            "prepare", RUN, SOURCE, "PREPARED", "NOT_NEEDED"
        ).redacted_json(),
    ):
        with pytest.raises(ValueError):
            verify(broken, **kwargs)
    with pytest.raises(ValueError):
        backend.verify_backend_receipt(
            raw, operation="prepare", attempt_id=RUN, expected_source_sha=SOURCE
        )


@pytest.mark.parametrize("paired,sender", [("NOT_PAIRED", "ABSENT"), ("UNVERIFIED", "UNVERIFIED")])
def test_d3_historical_parser_valid_states_are_not_host_rejected(
    tmp_path, monkeypatch, paired, sender
):
    fixture = Runtime(tmp_path, monkeypatch, volume=False)
    fixture.fs.write(
        ADMIN, canonical(admin_document(configured="ABSENT", paired=paired, sender=sender)) + b"\n"
    )
    value, _ = fixture.diagnose()
    assert value["state"] == "OBSERVED_NO_GO"
    assert value["admin"]["state"] == "MATCH_R"
    assert value["admin"]["observed_at"] == "2020-11-15T00:00:00+00:00"


def test_d7_codec_rejects_mislabeled_public_coordinates(tmp_path, monkeypatch):
    fixture = Runtime(tmp_path, monkeypatch)
    fixture.fs.write(
        PUBLIC, canonical(public_document(installation_fingerprint=fixture.item.fingerprint()))
    )
    fixture.fs.write(ADMIN, canonical(admin_document()) + b"\n")
    fixture.fs.write(KEY, b"\x11" * 32)
    value, raw = fixture.diagnose()
    assert value["state"] == "OBSERVED_NO_GO"
    prefix = raw.split(b" ", 1)[0] + b" "
    for kind, field, change in [
        ("recipient", "source_sha", "a" * 40),
        ("admin", "source_sha", "a" * 40),
        ("admin", "installation_run_id", "43704768557"),
        ("admin", "paired", "ABSENT"),
        ("admin", "observed_at", "9999-11-15T00:00:00+00:00"),
    ]:
        changed = {**value, kind: {**value[kind], field: change}}
        with pytest.raises(ValueError):
            backend.verify_prepare_diagnosis(
                prefix + canonical(changed) + b"\n",
                attempt_id=RUN,
                source_sha=SOURCE,
                workflow_sha=WORKFLOW,
            )


def test_d2_registered_stopped_sender_passes_healthy_but_diagnosis_explicitly_refuses(
    tmp_path, monkeypatch
):
    from boca_socios.host_telegram_installed_context import resolve_installed_context

    fixture = Runtime(tmp_path, monkeypatch, fault="registered-sender")
    with fixture.installed() as lease:
        context = resolve_installed_context(
            RUN,
            lease=lease,
            reader=fixture.reader,
            expected_source_sha=SOURCE,
            workflow_sha=WORKFLOW,
        )
        context.healthy()
        assert context.installation.pair.sender_id and not context.installation.pair.sender_running
        raw = backend.diagnose_installed_telegram(
            RUN,
            lease=lease,
            reader=fixture.reader,
            expected_source_sha=SOURCE,
            workflow_sha=WORKFLOW,
        )
    value = backend.verify_prepare_diagnosis(
        raw, attempt_id=RUN, source_sha=SOURCE, workflow_sha=WORKFLOW, allow_failure=True
    )
    assert value["state"] == "INCOMPLETE_NO_GO" and value["phase"] == "PREFLIGHT"
    assert fixture.events == [] and value["helper"]["create_attempted"] is False


def test_d2_changed_postflight_does_not_present_preflight_as_current(tmp_path, monkeypatch):
    fixture = Runtime(tmp_path, monkeypatch, fault="guard-after")
    value, _ = fixture.diagnose()
    assert value["state"] == "INCOMPLETE_NO_GO" and value["phase"] == "POSTFLIGHT"
    assert value["guards"] == "BEFORE" and value["engine"] == value["sender"] == "NOT_READ"
    assert value["helper"]["retirement"] == "RETIRED" and fixture.reader.effects == []


@pytest.mark.parametrize(
    "channel,raw",
    [
        ("exec", b'{"arbitrary":"SECRET"}'),
        ("start", b'{"arbitrary":"SECRET"}'),
        ("start", b'{"state":"VALID","state":"VALID"}'),
        ("exec", b"x" * 4097),
    ],
)
def test_d6_external_pipe_corruption_never_exports_bytes_or_loses_helper_id(
    tmp_path, monkeypatch, channel, raw
):
    fixture = Runtime(tmp_path, monkeypatch)
    fixture.pipe_override = (channel, raw)
    value, receipt = fixture.diagnose()
    assert value["state"] == "INCOMPLETE_NO_GO"
    assert b"SECRET" not in receipt and b"arbitrary" not in receipt
    assert value["helper"]["id"] == ("d" * 64 if channel == "start" else None)
    assert value["helper"]["retirement"] == ("RETIRED" if channel == "start" else "NOT_ATTEMPTED")
    assert fixture.events.count("CREATE") <= 1 and fixture.reader.effects == []


def test_d4_one_helper_empty_request_and_no_second_observation(tmp_path, monkeypatch):
    from boca_socios.host_telegram_installed_context import resolve_installed_context

    fixture = Runtime(tmp_path, monkeypatch)
    with fixture.installed() as lease:
        context = resolve_installed_context(
            RUN,
            lease=lease,
            reader=fixture.reader,
            expected_source_sha=SOURCE,
            workflow_sha=WORKFLOW,
        )
        storage = maintenance.InstalledMaintenance(context)
        for request in ({"extra": True}, [], None):
            with pytest.raises(maintenance.MaintenanceError):
                storage.call("recipient-observe", request)
        assert fixture.events == []
        assert storage.call("recipient-observe", {})["state"] == "ABSENT"
        with pytest.raises(maintenance.MaintenanceError):
            storage.call("recipient-observe", {})
    assert fixture.events == ["CREATE", "START_HELPER", "REMOVE_HELPER"]


def test_d7_absence_needs_metadata_witness_and_d8_invalid_public_blocks_extras(
    tmp_path, monkeypatch
):
    fixture = Runtime(tmp_path, monkeypatch)
    value, raw = fixture.diagnose()
    assert value["state"] == "OBSERVED_NO_GO"
    prefix = raw.split(b" ", 1)[0] + b" "
    for kind in ("recipient", "admin", "custody"):
        changed = {**value, kind: {**value[kind], "witness": None}}
        with pytest.raises(ValueError):
            backend.verify_prepare_diagnosis(
                prefix + canonical(changed) + b"\n",
                attempt_id=RUN,
                source_sha=SOURCE,
                workflow_sha=WORKFLOW,
            )
    fixture.fs.write(PUBLIC, b"invalid")
    fixture.fs.write("extra-private", b"SECRET")
    value, raw = fixture.diagnose()
    assert value["recipient"]["state"] == "INVALID"
    assert value["custody"]["entries"] == "EXTRA_ENTRIES_PRESENT"
    assert value["recommendation"] == "PRESERVE_REVIEW"
    assert b"SECRET" not in raw and fixture.fs.secret_reads == []


@pytest.mark.parametrize("relative_tamper", [False, True])
def test_review_d4_recipient_command_uses_absolute_interpreter_and_rejects_relative(
    tmp_path, monkeypatch, relative_tamper
):
    fixture = Runtime(
        tmp_path, monkeypatch, fault="relative-interpreter" if relative_tamper else ""
    )
    value, _ = fixture.diagnose()
    assert fixture.created_commands == [
        ("/app/.venv/bin/python", "-I", "-B", "-c", maintenance.RECIPIENT_OBSERVE_PROGRAM)
    ]
    if relative_tamper:
        assert value["state"] == "INCOMPLETE_NO_GO"
        assert value["helper"]["id"] == "d" * 64
        assert value["helper"]["start_attempted"] is False
        assert value["helper"]["retirement"] == "INDETERMINATE"
        assert fixture.events == ["PUBLIC_A", "CREATE"]
    else:
        assert value["state"] == "OBSERVED_NO_GO"
        assert value["helper"]["retirement"] == "RETIRED"


@pytest.mark.parametrize("fault", ["", "recipient-denied", "admin-io", "parent-denied"])
def test_review_d3_public_bytes_use_real_installed_readers(tmp_path, monkeypatch, fault):
    import ast

    from boca_socios import telegram_bootstrap
    from boca_socios.notify import projection

    fs = ProgramFS(tmp_path)
    fs.write(PUBLIC, canonical(public_document()))
    fs.write(ADMIN, canonical(admin_document()) + b"\n")
    calls = []
    readers = {
        telegram_bootstrap._directory.__code__: "_directory",
        telegram_bootstrap._read.__code__: "_read",
        projection._read_admin_receipt.__code__: "_read_admin_receipt",
    }

    def track(frame, event, arg):
        if event == "call" and frame.f_code in readers:
            calls.append((readers[frame.f_code], dict(frame.f_locals)))

    def fail(name, flags):
        if (
            (fault == "recipient-denied" and name == PUBLIC)
            or (fault == "admin-io" and name == "/data/" + ADMIN)
            or (fault == "parent-denied" and name == "data")
        ):
            raise OSError(errno.EIO if fault == "admin-io" else errno.EACCES, "private I/O details")

    fs.open_fault = fail
    old_profile = sys.getprofile()
    try:
        sys.setprofile(track)
        value, raw = execute_program(status, "PUBLIC_OBSERVE_PROGRAM", fs, monkeypatch)
    finally:
        sys.setprofile(old_profile)
    names = [name for name, _ in calls]
    assert names.count("_directory") == 2
    assert all(
        locals_["path"] == Path("/data") and locals_["uid"] == 10001
        for name, locals_ in calls
        if name == "_directory"
    )
    if fault == "parent-denied":
        assert names == ["_directory", "_directory"]
        assert value["recipient"]["state"] == value["admin"]["state"] == "NOT_READ"
    else:
        assert names == ["_directory", "_read", "_directory", "_read_admin_receipt"]
        recipient = next(locals_ for name, locals_ in calls if name == "_read")
        assert (recipient["name"], recipient["uid"], recipient["maximum"]) == (PUBLIC, 10001, 1024)
        admin = next(locals_ for name, locals_ in calls if name == "_read_admin_receipt")
        assert admin["path"] == Path("/data") / ADMIN
        assert value["recipient"]["state"] == (
            "NOT_READ" if fault == "recipient-denied" else "VALID"
        )
        assert value["admin"]["state"] == ("NOT_READ" if fault == "admin-io" else "VALID")
    assert b"private I/O details" not in raw and not fs.secret_reads
    # Observe the real function calls; never substitute their validators or their bytes.
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "os"
        and node.func.attr in {"read", "fdopen"}
        for node in ast.walk(ast.parse(status.PUBLIC_OBSERVE_PROGRAM))
    )
