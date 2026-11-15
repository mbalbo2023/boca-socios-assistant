"""Exact initializer recovery across real profile, state machine and bounded pipes."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import test_r304_telegram_incident_readonly as incident_fixture

RUN = "43730000000"
WORKFLOW = "a" * 40
HELPER = "ba6699b977623135224e0ab6de8a26a882cecda8bfa819458deace75cb282367"
CONTROLLER = "b0dd0fed57c55dbdeb9a6e833d913cb86c0868ae1587394a934450342114bfa1"
WORKER = "c9c882ff12666fb6cac130879925879cfc0c5c23173a843434adee96b4339dce"
VOLUME = "boca-socios_boca_telegram"
ROOT = "/home/boca-deploy/.local/share/docker/volumes/"
CONTROL = "/home/boca-deploy/.boca-on-demand/socket"
ZERO = "0001-01-01T00:00:00Z"
STARTED = "2026-11-15T15:00:00.123456789Z"
FINISHED = "2026-11-15T15:00:00.223456789Z"
PREFIX = b"BOCA_TELEGRAM_INITIALIZER_RECOVERY_V1 "


def module():
    name = "boca_socios.host_telegram_initializer_recovery"
    assert importlib.util.find_spec(name) is not None, "reviewed initializer recovery is missing"
    return importlib.import_module(name)


def frame(value):
    return PREFIX + json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def accepted():
    return {
        "version": 1,
        "operation": "initialize-and-retire",
        "recovery_run_id": RUN,
        "workflow_sha": WORKFLOW,
        "observation_run_id": "43725809501",
        "incident_run_id": "43705714873",
        "source_sha": "845f31abfb1762dff27e6fc3274fcc40507f3f18",
        "installation_run_id": "43704768556",
        "helper_cid": HELPER,
        "state": "ACCEPTED",
        "phase": "COMPLETE",
        "initialization": "ACCEPTED",
        "retirement": "RETIRED",
        "pair_state": "UNCHANGED_HEALTHY_WORKER_STOPPED",
        "engine": "UNVERIFIED",
        "sender_state": "OFF",
        "disk_before": {"bytes_free": 999, "inodes_free": 111, "device": 22, "inode": 33},
        "disk_after": {"bytes_free": 999, "inodes_free": 111, "device": 22, "inode": 33},
    }


def fixture(monkeypatch, tmp_path, fault="", *, post_health=None):
    recovery = module()
    observer, _ = incident_fixture.scenario(monkeypatch)
    from boca_socios import host_boca_cleanup as cleanup

    original_docker = cleanup._docker
    commands, clients = [], []
    state = {"started": False, "exists": True, "post_reads": 0, "pre_reads": 0}
    volume = {
        "Name": VOLUME,
        "Driver": "local",
        "Scope": "local",
        "Options": None,
        "Mountpoint": ROOT + VOLUME + "/_data",
        "project": "boca-socios",
        "volume": "boca_telegram",
    }
    if fault == "volume-options":
        volume["Options"] = {"device": "/unrelated"}
    mounts = {}
    for cid, entries in (
        (
            CONTROLLER,
            [
                ("boca_data", "/data", True),
                ("boca_key", "/run/secrets", False),
                ("boca_owner", "/run/owner", False),
                ("boca_browser_ipc", "/run/boca-browser-ipc", False),
                ("boca_site_config", "/run/boca-site-config", True),
            ],
        ),
        (
            WORKER,
            [
                ("boca_browser_ipc", "/run/boca-browser-ipc", True),
                ("boca_site_config", "/run/boca-site-config", False),
            ],
        ),
    ):
        mounts[cid] = [
            {
                "Type": "volume",
                "Name": "boca-socios_" + name,
                "Driver": "local",
                "Source": ROOT + "boca-socios_" + name + "/_data",
                "Destination": target,
                "RW": rw,
            }
            for name, target, rw in entries
        ]
    mounts[CONTROLLER].append(
        {
            "Type": "bind",
            "Source": CONTROL,
            "Destination": "/run/boca-bot-control",
            "RW": False,
            "Propagation": "rprivate",
        }
    )
    if fault == "pair-mount":
        mounts[WORKER][0]["Source"] = ROOT
    if fault == "telegram-on-controller":
        mounts[CONTROLLER][0] = {
            "Type": "volume",
            "Name": VOLUME,
            "Driver": "local",
            "Source": ROOT + VOLUME + "/_data",
            "Destination": "/data",
            "RW": True,
        }
    if fault == "control-source":
        mounts[CONTROLLER][-1]["Source"] = "/unrelated/control"

    def docker(*args):
        commands.append(args)
        if args == ("rm", HELPER):
            assert state["started"]
            if fault != "rm-present":
                state["exists"] = False
            if fault == "rm-lost":
                raise OSError("PRIVATE rm acknowledgement lost")
            return "PRIVATE unexpected ack" if fault == "rm-ack" else HELPER + "\n"
        if args[:2] == ("ps", "-a"):
            state["post_reads" if state["started"] else "pre_reads"] += 1
            raw = original_docker(*args).replace(incident_fixture.HELPER, HELPER)
            if not state["exists"] or fault == "absent":
                raw = (
                    "\n".join(line for line in raw.splitlines() if not line.startswith(HELPER))
                    + "\n"
                )
            if fault == "foreign":
                raw += "f" * 64 + " private-unrelated\n"
            return raw
        if args[:3] == ("volume", "inspect", "--format"):
            assert args[-1] == VOLUME
            key = args[3]
            mapping = {
                "{{json .Name}}": "Name",
                "{{json .Driver}}": "Driver",
                "{{json .Scope}}": "Scope",
                "{{json .Options}}": "Options",
                "{{json .Mountpoint}}": "Mountpoint",
                '{{json (index .Labels "com.docker.compose.project")}}': "project",
                '{{json (index .Labels "com.docker.compose.volume")}}': "volume",
            }
            return json.dumps(volume[mapping[key]])
        if args[:2] == ("inspect", "--format"):
            cid, template = args[-1], args[2]
            assert cid in {CONTROLLER, WORKER, HELPER}
            if cid in mounts and template == "{{json .Mounts}}":
                return json.dumps(mounts[cid])
            extra = {
                "{{json .Config.Entrypoint}}": ["sh"] if fault == "entrypoint" else None,
                "{{json .Config.WorkingDir}}": "/app",
                "{{json .Config.OpenStdin}}": fault != "stdin",
                "{{json .Config.Tty}}": fault == "tty",
                "{{json .State.StartedAt}}": STARTED
                if state["started"] or fault == "started"
                else ZERO,
                "{{json .State.FinishedAt}}": FINISHED
                if state["started"] and fault != "post-finish"
                else ZERO,
            }
            if template in extra:
                assert cid == HELPER
                return json.dumps(extra[template])
            old_cid = incident_fixture.HELPER if cid == HELPER else cid
            raw = original_docker(*args[:-1], old_cid)
            key = {value: key for key, value in observer._TEMPLATES.items()}[template]
            value = json.loads(raw)
            if cid == HELPER and key == "Id":
                value = HELPER
            if key == "State.Status":
                value = (
                    "running"
                    if cid == CONTROLLER
                    else "exited"
                    if cid == HELPER and state["started"]
                    else "created"
                )
            if key == "State.Running":
                value = cid == CONTROLLER
            if key == "State.Pid":
                value = 1234 if cid == CONTROLLER else 0
            if key == "State.Health.Status" and cid == CONTROLLER:
                value = "unhealthy" if fault == "post-pair" and not state["exists"] else "healthy"
            if key == "State.Health.Status" and cid == HELPER:
                value = (
                    post_health
                    if state["started"]
                    else "starting"
                    if fault == "created-health"
                    else None
                )
            if key == "HostConfig.CapAdd":
                value = ["CAP_CHOWN"] if fault != "extra-cap" else ["CAP_CHOWN", "NET_ADMIN"]
            if cid == HELPER and key == "Image" and fault == "image":
                value = "sha256:" + "f" * 64
            if (
                cid == HELPER
                and key == "Config.User"
                and (
                    fault == "before-rm"
                    and state["post_reads"] >= 2
                    or fault == "post-profile"
                    and state["started"]
                )
            ):
                value = "123:123"
            if cid == HELPER and key == "NetworkSettings.Networks":
                value = {"none": {"EndpointID": "changed-after-start" if state["started"] else ""}}
                if fault == "raw-drift" and state["pre_reads"] >= 2:
                    value = {"none": {"EndpointID": "private-drift"}}
            return json.dumps(value)
        return original_docker(*args)

    monkeypatch.setattr(cleanup, "_docker", docker)
    real_resolve, real_lstat = Path.resolve, Path.lstat

    def resolve(path, *args, **kwargs):
        if str(path).startswith("/home/boca-deploy/"):
            if fault == "symlink" and str(path) == ROOT + VOLUME + "/_data":
                return Path("/unrelated")
            return path
        return real_resolve(path, *args, **kwargs)

    identities = {
        ROOT + "boca-socios_boca_telegram/_data": 55,
        ROOT + "boca-socios_boca_data/_data": 56,
        ROOT + "boca-socios_boca_key/_data": 57,
        ROOT + "boca-socios_boca_owner/_data": 58,
        ROOT + "boca-socios_boca_browser_ipc/_data": 59,
        ROOT + "boca-socios_boca_site_config/_data": 60,
        CONTROL: 61,
    }
    if fault == "alias-data":
        identities[ROOT + "boca-socios_boca_data/_data"] = 55
    if fault == "alias-control":
        identities[CONTROL] = 55

    def lstat(path, *args, **kwargs):
        if str(path).startswith("/home/boca-deploy/"):
            return os.stat_result(
                (stat.S_IFDIR | 0o700, identities[str(path)], 22, 1, 10001, 10001, 0, 0, 0, 0)
            )
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(Path, "lstat", lstat)
    # Real flock acquisition and verification, with only OS ownership metadata translated.
    lease_dir = tmp_path / "lease"
    lease_dir.mkdir(mode=0o700)
    monkeypatch.setattr(cleanup, "LEASE_DIR", str(lease_dir))
    real_open, real_fstat, real_close = os.open, os.fstat, os.close
    lease_fds = set()

    def opened(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        if str(path) == str(lease_dir) or path == cleanup.LEASE_FILE:
            lease_fds.add(fd)
        return fd

    def fstat(fd):
        value = real_fstat(fd)
        if fd in lease_fds:
            copied = list(value)
            copied[4:6] = [10001, 10001]
            return os.stat_result(copied)
        return value

    def close(fd):
        lease_fds.discard(fd)
        return real_close(fd)

    monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, "fstat", fstat)
    monkeypatch.setattr(os, "close", close)
    real_popen = subprocess.Popen

    def popen(argv, **kwargs):
        assert argv == [
            "/usr/bin/docker",
            "--host",
            cleanup.DOCKER_SOCKET,
            "start",
            "--attach",
            "--interactive",
            HELPER,
        ]
        assert kwargs["stdin"] == subprocess.PIPE
        assert kwargs["stdout"] == subprocess.PIPE and kwargs["stderr"] == subprocess.PIPE
        assert kwargs["env"] == {
            "DOCKER_HOST": cleanup.DOCKER_SOCKET,
            "XDG_RUNTIME_DIR": "/run/user/10001",
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
        }
        commands.append(("start", HELPER))
        state["started"] = True
        payload = b'{"initialized":true}'
        if fault == "response":
            payload = b'{"initialized": true}'
        if fault == "overflow":
            payload = b"PRIVATE" * 1000
        stderr = (
            b"PRIVATE"
            if fault == "stderr"
            else b"PRIVATE" * 1000
            if fault == "stderr-overflow"
            else b""
        )
        code = (
            "import sys,time; data=sys.stdin.buffer.read(); "
            'assert data==b\'{"new_empty_volume":"boca-socios_boca_telegram"}\'; '
            f"sys.stdout.buffer.write({payload!r}); sys.stdout.buffer.flush(); "
            f"sys.stderr.buffer.write({stderr!r}); sys.stderr.buffer.flush(); "
            + ("time.sleep(10); " if fault == "timeout" else "")
            + ("raise SystemExit(1)" if fault == "exit" else "")
        )
        client = real_popen([sys.executable, "-c", code], **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(subprocess, "Popen", popen)
    if fault == "timeout":
        ticks = iter([0.0, 31.0])
        monkeypatch.setattr(recovery, "monotonic", lambda: next(ticks, 31.0))
    return recovery, commands, state, clients


def decoded(recovery, raw):
    assert recovery.verify(raw, RUN, WORKFLOW) == raw
    assert b"PRIVATE" not in raw
    return json.loads(raw[len(PREFIX) :])


def test_r305_recovery_resumes_only_exact_helper_and_retires_after_proof(monkeypatch, tmp_path):
    recovery, commands, state, clients = fixture(monkeypatch, tmp_path)
    value = decoded(recovery, recovery.recover(RUN, WORKFLOW))
    assert value == accepted()
    assert [command for command in commands if command[0] in {"start", "rm", "stop", "create"}] == [
        ("start", HELPER),
        ("rm", HELPER),
    ]
    assert not state["exists"] and len(clients) == 1 and clients[0].poll() == 0


@pytest.mark.parametrize(
    "fault",
    [
        "absent",
        "foreign",
        "volume-options",
        "pair-mount",
        "telegram-on-controller",
        "control-source",
        "entrypoint",
        "stdin",
        "tty",
        "started",
        "extra-cap",
        "image",
        "raw-drift",
        "symlink",
    ],
)
def test_r305_preflight_refuses_uncertain_identity_without_effect(monkeypatch, tmp_path, fault):
    recovery, commands, _, clients = fixture(monkeypatch, tmp_path, fault)
    value = decoded(recovery, recovery.recover(RUN, WORKFLOW))
    assert (value["state"], value["phase"], value["initialization"], value["retirement"]) == (
        "NO_GO",
        "PREFLIGHT",
        "NOT_ATTEMPTED",
        "NOT_ATTEMPTED",
    )
    assert value["sender_state"] == value["pair_state"] == "UNVERIFIED"
    assert not clients and not any(cmd[0] in {"start", "stop", "rm", "create"} for cmd in commands)


@pytest.mark.parametrize(
    "fault",
    [
        "response",
        "exit",
        "stderr",
        "overflow",
        "stderr-overflow",
        "timeout",
        "post-profile",
        "post-finish",
    ],
)
def test_r305_uncertain_initialization_preserves_helper_and_bounds_private_pipes(
    monkeypatch,
    tmp_path,
    fault,
):
    recovery, commands, state, clients = fixture(monkeypatch, tmp_path, fault)
    value = decoded(recovery, recovery.recover(RUN, WORKFLOW))
    assert value["state"] == "NO_GO" and value["initialization"] == "INDETERMINATE"
    assert value["retirement"] == "NOT_ATTEMPTED" and state["exists"]
    assert len(clients) == 1 and clients[0].poll() is not None
    assert [cmd[0] for cmd in commands if cmd[0] in {"start", "stop", "rm", "create"}] == ["start"]


@pytest.mark.parametrize(
    "fault,retirement",
    [
        ("before-rm", "NOT_ATTEMPTED"),
        ("rm-ack", "INDETERMINATE"),
        ("rm-lost", "INDETERMINATE"),
        ("rm-present", "INDETERMINATE"),
        ("post-pair", "RETIRED"),
    ],
)
def test_r305_partial_receipt_preserves_accepted_initialization_without_retry(
    monkeypatch,
    tmp_path,
    fault,
    retirement,
):
    recovery, commands, _, clients = fixture(monkeypatch, tmp_path, fault)
    value = decoded(recovery, recovery.recover(RUN, WORKFLOW))
    assert value["state"] == "NO_GO" and value["initialization"] == "ACCEPTED"
    assert value["retirement"] == retirement and value["sender_state"] == "UNVERIFIED"
    assert len(clients) == 1 and sum(cmd[0] == "rm" for cmd in commands) <= 1


@pytest.mark.parametrize(
    "change",
    [
        {"phase": "RETIRE"},
        {"retirement": "INDETERMINATE"},
        {"initialization": "INDETERMINATE"},
        {"sender_state": "UNVERIFIED"},
        {"engine": "OFF"},
        {"version": True},
        {"workflow_sha": "b" * 40},
        {"helper_cid": "d" * 64},
        {"disk_after": None},
        {"disk_before": {"bytes_free": True, "inodes_free": 1, "device": 22, "inode": 33}},
        {"disk_after": {"bytes_free": 999, "inodes_free": 111, "device": 22, "inode": 34}},
    ],
)
def test_r305_receipt_rejects_false_success_and_fabricated_coordinates(change):
    recovery = module()
    value = {**accepted(), **change}
    with pytest.raises(ValueError):
        recovery.verify(frame(value), RUN, WORKFLOW)


@pytest.mark.parametrize(
    "phase,initialization,retirement",
    [
        ("INPUT", "NOT_ATTEMPTED", "NOT_ATTEMPTED"),
        ("PREFLIGHT", "NOT_ATTEMPTED", "NOT_ATTEMPTED"),
        ("START", "INDETERMINATE", "NOT_ATTEMPTED"),
        ("VERIFY_INITIALIZATION", "INDETERMINATE", "NOT_ATTEMPTED"),
        ("RETIRE", "ACCEPTED", "NOT_ATTEMPTED"),
        ("RETIRE", "ACCEPTED", "INDETERMINATE"),
        ("POSTFLIGHT", "ACCEPTED", "INDETERMINATE"),
        ("POSTFLIGHT", "ACCEPTED", "RETIRED"),
    ],
)
def test_r305_receipt_accepts_only_closed_partial_state_families(phase, initialization, retirement):
    recovery = module()
    value = {
        **accepted(),
        "state": "NO_GO",
        "phase": phase,
        "initialization": initialization,
        "retirement": retirement,
        "pair_state": "UNVERIFIED",
        "sender_state": "UNVERIFIED",
        "disk_after": None,
    }
    if phase in {"INPUT", "PREFLIGHT"}:
        value["disk_before"] = None
    assert recovery.verify(frame(value), RUN, WORKFLOW) == frame(value)
    for key, bad in (
        ("sender_state", "OFF"),
        ("pair_state", "UNCHANGED_HEALTHY_WORKER_STOPPED"),
        ("state", "ACCEPTED"),
        ("retirement", "NOT_ATTEMPTED" if phase == "POSTFLIGHT" else "RETIRED"),
    ):
        if key == "retirement" and phase == "POSTFLIGHT" and retirement == "RETIRED":
            bad = "NOT_ATTEMPTED"
        with pytest.raises(ValueError):
            recovery.verify(frame({**value, key: bad}), RUN, WORKFLOW)


def test_r305_receipt_rejects_duplicate_and_noncanonical_frames():
    recovery = module()
    raw = frame(accepted())
    for bad in (
        raw + b"\n",
        raw.replace(b'"version":1', b'"version":1,"version":1'),
        raw.replace(b'"version":1', b'"version": 1'),
        raw[:-1],
        b"PRIVATE",
        raw * 8,
    ):
        with pytest.raises(ValueError):
            recovery.verify(bad, RUN, WORKFLOW)


@pytest.mark.parametrize(
    "contents,uid,expected,effective_uid",
    [
        ([], 0, True, 0),
        (["private"], 0, False, 0),
        ([], 10001, False, 0),
        ([], 0, "identity", 10001),
    ],
)
def test_r305_installed_initializer_checks_empty_owner_before_any_write(
    monkeypatch, contents, uid, expected, effective_uid
):
    from types import SimpleNamespace

    from boca_socios import telegram_maintenance as installed

    effects = []
    real_open, real_close, real_fstat = os.open, os.close, os.fstat
    real_listdir, real_fchmod, real_fchown, real_fsync = os.listdir, os.fchmod, os.fchown, os.fsync
    descriptor = 777777
    for identity in ("getuid", "geteuid", "getgid", "getegid"):
        monkeypatch.setattr(os, identity, lambda: 0)
    monkeypatch.setattr(os, "geteuid", lambda: effective_uid)
    monkeypatch.setattr(
        os,
        "open",
        lambda path, flags, *a, **kw: (
            descriptor if path == installed.CUSTODY else real_open(path, flags, *a, **kw)
        ),
    )
    monkeypatch.setattr(
        os, "close", lambda fd: effects.append("close") if fd == descriptor else real_close(fd)
    )
    monkeypatch.setattr(
        os, "fstat", lambda fd: SimpleNamespace(st_uid=uid) if fd == descriptor else real_fstat(fd)
    )
    monkeypatch.setattr(
        os, "listdir", lambda path: contents if path == descriptor else real_listdir(path)
    )
    monkeypatch.setattr(
        os,
        "fchmod",
        lambda fd, mode: (
            effects.append(("chmod", mode)) if fd == descriptor else real_fchmod(fd, mode)
        ),
    )
    monkeypatch.setattr(
        os,
        "fchown",
        lambda fd, user, group: (
            effects.append(("chown", user, group))
            if fd == descriptor
            else real_fchown(fd, user, group)
        ),
    )
    monkeypatch.setattr(
        os, "fsync", lambda fd: effects.append("fsync") if fd == descriptor else real_fsync(fd)
    )
    request = {"new_empty_volume": VOLUME}
    if expected == "identity":
        with pytest.raises(installed.bootstrap.BootstrapError, match="dedicated_identity_required"):
            installed.execute("initialize-volume", request)
        assert effects == []
    elif expected:
        assert installed.execute("initialize-volume", request) == {"initialized": True}
        assert effects == [("chmod", 0o700), ("chown", 10001, 10001), "fsync", "close"]
    else:
        with pytest.raises(ValueError, match="empty_new_volume_required"):
            installed.execute("initialize-volume", request)
        assert effects == ["close"]


@pytest.mark.parametrize("fault,pipe", [("overflow", "stdout"), ("stderr-overflow", "stderr")])
def test_r305_private_pipe_limit_applies_during_acquisition(monkeypatch, tmp_path, fault, pipe):
    recovery, _, _, clients = fixture(monkeypatch, tmp_path, fault)
    real_read = os.read
    acquired = {"stdout": 0, "stderr": 0}

    def read(fd, maximum):
        chunk = real_read(fd, maximum)
        if clients:
            for name in acquired:
                stream = getattr(clients[0], name)
                if not stream.closed and stream.fileno() == fd:
                    acquired[name] += len(chunk)
        return chunk

    monkeypatch.setattr(os, "read", read)
    value = decoded(recovery, recovery.recover(RUN, WORKFLOW))
    assert value["initialization"] == "INDETERMINATE"
    # The peer emitted 7000 bytes: rejection happens at 1025, before a full capture.
    assert acquired[pipe] == 1025 and max(acquired.values()) == 1025


def test_r305_contended_canonical_lease_refuses_before_docker_effect(monkeypatch, tmp_path):
    recovery, commands, _, clients = fixture(monkeypatch, tmp_path)
    from boca_socios import host_boca_cleanup as cleanup

    with cleanup.protected_boca_job_lease("999"):
        value = decoded(recovery, recovery.recover(RUN, WORKFLOW))
    assert value["phase"] == "PREFLIGHT" and value["initialization"] == "NOT_ATTEMPTED"
    assert commands == [] and clients == []


@pytest.mark.parametrize("identity", ["getuid", "geteuid", "getgid", "getegid"])
def test_r305_real_effective_rootless_identity_required_before_lease(
    monkeypatch, tmp_path, identity
):
    recovery, commands, _, clients = fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(os, identity, lambda: 1000)
    value = decoded(recovery, recovery.recover(RUN, WORKFLOW))
    assert value["phase"] == "INPUT" and value["disk_before"] is None
    assert commands == [] and clients == []


def test_r305_postflight_release_error_keeps_init_and_retirement_facts(monkeypatch, tmp_path):
    from contextlib import contextmanager

    from boca_socios import host_boca_cleanup as cleanup

    recovery, _, _, _ = fixture(monkeypatch, tmp_path)
    real_lease = cleanup.protected_boca_job_lease

    @contextmanager
    def release_error(run_id):
        with real_lease(run_id) as lease:
            yield lease
        raise OSError("PRIVATE lease release failure")

    monkeypatch.setattr(cleanup, "protected_boca_job_lease", release_error)
    value = decoded(recovery, recovery.recover(RUN, WORKFLOW))
    assert (value["state"], value["phase"], value["initialization"], value["retirement"]) == (
        "NO_GO",
        "POSTFLIGHT",
        "ACCEPTED",
        "RETIRED",
    )
    assert value["sender_state"] == value["pair_state"] == "UNVERIFIED"


@pytest.mark.parametrize("post_health", [None, "starting", "unhealthy", "healthy"])
def test_r305_exited_helper_health_does_not_override_initialized_proof(
    monkeypatch,
    tmp_path,
    post_health,
):
    recovery, commands, state, _ = fixture(monkeypatch, tmp_path, post_health=post_health)
    value = decoded(recovery, recovery.recover(RUN, WORKFLOW))
    assert value["state"] == "ACCEPTED" and value["initialization"] == "ACCEPTED"
    assert not state["exists"]
    assert [cmd[0] for cmd in commands if cmd[0] in {"start", "rm", "stop"}] == ["start", "rm"]


def test_r305_created_helper_health_still_requires_none(monkeypatch, tmp_path):
    recovery, commands, _, clients = fixture(monkeypatch, tmp_path, "created-health")
    value = decoded(recovery, recovery.recover(RUN, WORKFLOW))
    assert value["phase"] == "PREFLIGHT" and value["initialization"] == "NOT_ATTEMPTED"
    assert not clients and not any(cmd[0] in {"start", "rm", "stop"} for cmd in commands)


@pytest.mark.parametrize("alias", ["alias-data", "alias-control"])
def test_r305_telegram_physical_alias_refuses_before_start(monkeypatch, tmp_path, alias):
    recovery, commands, _, clients = fixture(monkeypatch, tmp_path, alias)
    value = decoded(recovery, recovery.recover(RUN, WORKFLOW))
    assert value["state"] == "NO_GO" and value["phase"] == "PREFLIGHT"
    assert value["initialization"] == "NOT_ATTEMPTED"
    assert not clients and not any(cmd[0] in {"start", "rm", "stop"} for cmd in commands)
