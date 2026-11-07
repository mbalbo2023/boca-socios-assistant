"""R79 one-shot stopped-worker recovery; no real Docker/SSH/host effects."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from scripts import host_cutover_worker_inspect as observer  # noqa: E402
from scripts import host_cutover_worker_recovery as recovery  # noqa: E402

ATTEMPT = "42329475083"
CID = "65d844edb438710f44ce83c397906932710ad7f04f3e7a52634f9eaaf1fcc504"
LEGACY_ID = "27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793"
SOURCE = "92624ed6b7e75c6010f59670c866df00a29766dd"
BROWSER_IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
    "3894cfff995858d7c0ffdb994180a0d28a8a92bb69a0526fb040db2297fd8bf9"
)
PROFILE = (ROOT / "docker" / "seccomp_profile.json").read_bytes()
COMPACT_PROFILE = json.dumps(json.loads(PROFILE), separators=(",", ":"), ensure_ascii=False)


def _observed(*, present: bool) -> dict[str, Any]:
    """Literal R78 v3 evidence, independently verified by the real receipt parser."""
    record: dict[str, Any] = {
        "version": "boca-worker-readonly-inspect-v3",
        "attempt": ATTEMPT,
        "legacy_id": LEGACY_ID,
        "socket": "PRESENT_OWNED",
        "docker": "OBSERVED",
        "probe": "PRESENT_PIN_MATCH" if present else "ABSENT",
        "probe_id": CID if present else None,
        "probe_candidate_id": CID if present else None,
        "probe_running": False if present else None,
        "probe_list_stage": "OK" if present else "ABSENT",
        "probe_list_rc": None,
        "probe_inspect_stage": "OK" if present else "SKIPPED",
        "probe_inspect_rc": None,
        "probe_full_json_stage": "BELOW_CLEANUP_LIMIT" if present else "SKIPPED",
        "probe_full_json_rc": None,
        "seccomp": "ABSENT",
        "original": "RUNNING_HEALTHY",
        "original_port": "LOOPBACK_8443",
        "original_inspect_stage": "OK",
        "original_inspect_rc": None,
        "observer_writes": 0,
        "foreign_resources_touched": False,
        "cutover_authorized": False,
    }
    observer.verify(observer.canonical(record) + b"\n", ATTEMPT, LEGACY_ID)
    return record


def _full_probe(*, status: str = "exited") -> dict[str, Any]:
    """Realistic stopped Docker metadata; secrets and host mounts are excluded."""
    return {
        "Id": CID,
        "Name": f"/boca-socios-cutover-preflight-{ATTEMPT}",
        "Config": {
            "Image": BROWSER_IMAGE,
            "User": "10002:10002",
            "Cmd": ["python", "-c", "import time; time.sleep(90)"],
            "Env": [
                "BOCA_ENVIRONMENT=staging",
                "BOCA_RUNTIME_MODE=simulation",
                "BOCA_ENGINE_MODE=off",
                "BOCA_OBSERVER_STOP=1",
            ],
            "Labels": {
                "com.docker.compose.project": "boca-socios",
                "boca.socios.cutover-preflight-attempt": ATTEMPT,
                "org.opencontainers.image.revision": SOURCE,
            },
        },
        "State": {
            "Running": False,
            "Restarting": False,
            "Paused": False,
            "Dead": False,
            "Status": status,
            "OOMKilled": False,
        },
        "HostConfig": {
            "AutoRemove": False,
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "PidMode": "",
            "PublishAllPorts": False,
            "Devices": [],
            "DeviceRequests": None,
            "ShmSize": 67_108_864,
            "Tmpfs": {
                "/tmp": "rw,noexec,nosuid,size=32m",  # noqa: S108 - fixture tmpfs
                "/home/boca-browser": "rw,noexec,nosuid,size=16m",
            },
            "NetworkMode": "none",
            "IpcMode": "private",
            "CgroupnsMode": "private",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "Init": True,
            "NanoCpus": 1_000_000_000,
            "Memory": 805_306_368,
            "PidsLimit": 128,
            "CapDrop": ["ALL"],
            "CapAdd": ["SYS_CHROOT"],
            "PortBindings": None,
            "Binds": None,
            "Mounts": None,
            "VolumesFrom": None,
            "SecurityOpt": ["no-new-privileges:true", "seccomp=" + COMPACT_PROFILE],
        },
        "Mounts": [],
        "NetworkSettings": {"Ports": None, "Networks": {"none": {}}},
    }


class LocalRecoveryRig:
    """Fake only external boundaries; exercise execute() and real validations."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.events: list[str] = []
        self.pre_observations = 0
        self.full_reads = 0
        self.removal_attempts = 0
        self.removed = False
        self.before = _observed(present=True)
        self.after = _observed(present=False)
        self.full = _full_probe()
        self.late_observation: dict[str, Any] | None = None
        self.late_full: dict[str, Any] | None = None
        self.lease_failure = False
        self.full_failure: Exception | None = None
        self.remove_failure: Exception | None = None
        self.remove_ack = CID
        self.retained_cid = False
        self.cid_failure: Exception | None = None

        @contextmanager
        def fake_lease(attempt: str) -> Iterator[object]:
            assert attempt == ATTEMPT
            self.events.append("lease-open")
            if self.lease_failure:
                raise recovery.cleanup.CleanupError("LEASE_BUSY")
            try:
                yield object()
            finally:
                self.events.append("lease-close")

        def verify_lease(_lease: object, attempt: str) -> None:
            assert attempt == ATTEMPT
            self.events.append("lease-verify")

        monkeypatch.setattr(recovery.cleanup, "protected_boca_job_lease", fake_lease)
        monkeypatch.setattr(recovery.cleanup, "verify_protected_boca_job_lease", verify_lease)
        monkeypatch.setattr(recovery, "_observe", self.observe)
        monkeypatch.setattr(recovery, "_inspect_full_exact", self.inspect_full)
        monkeypatch.setattr(recovery, "_profile", lambda: PROFILE)
        monkeypatch.setattr(recovery, "_remove_exact", self.remove)
        monkeypatch.setattr(recovery, "_cid_present", self.cid_present)

    def observe(self) -> dict[str, Any]:
        self.events.append("observe")
        if self.removed:
            return copy.deepcopy(self.after)
        self.pre_observations += 1
        if self.pre_observations >= 2 and self.late_observation is not None:
            return copy.deepcopy(self.late_observation)
        return copy.deepcopy(self.before)

    def inspect_full(self, cid: str) -> dict[str, Any]:
        assert cid == CID
        self.events.append("full-inspect")
        self.full_reads += 1
        if self.full_failure is not None:
            raise self.full_failure
        if self.full_reads >= 2 and self.late_full is not None:
            return copy.deepcopy(self.late_full)
        return copy.deepcopy(self.full)

    def remove(self, cid: str) -> str:
        assert cid == CID
        self.events.append("rm")
        self.removal_attempts += 1
        if self.remove_failure is not None:
            raise self.remove_failure
        self.removed = True
        return self.remove_ack

    def cid_present(self, cid: str) -> bool:
        assert cid == CID
        self.events.append("cid-check")
        if self.cid_failure is not None:
            raise self.cid_failure
        return self.retained_cid or not self.removed


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> LocalRecoveryRig:
    return LocalRecoveryRig(monkeypatch)


@pytest.mark.parametrize("status", ["created", "exited"])
def test_exact_stopped_probe_removed_once_and_legacy_survives(
    rig: LocalRecoveryRig, status: str
) -> None:
    rig.full["State"]["Status"] = status
    result = recovery.execute()
    assert result == {
        "version": "boca-worker-recovery-v1",
        "attempt": ATTEMPT,
        "probe_id": CID,
        "legacy_id": LEGACY_ID,
        "cleanup": "VERIFIED",
        "phase": "COMPLETE",
        "docker_writes": 1,
        "foreign_resources_touched": False,
        "cutover_authorized": False,
        "retry_authorized": False,
        "original": "RUNNING_HEALTHY",
    }
    assert rig.removal_attempts == 1
    assert rig.pre_observations == 2
    assert rig.full_reads == 2
    assert rig.events.count("cid-check") == 1
    assert rig.events.index("rm") > rig.events.index("full-inspect")
    assert rig.events[-1] == "lease-close"
    assert recovery.verify_runner(observer.canonical(result) + b"\n") == result


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("socket", "PRESENT_UNVERIFIED"),
        ("seccomp", "PRESENT_OWNED"),
        ("seccomp", "UNVERIFIED"),
        ("docker", "PARTIAL"),
        ("probe", "PRESENT_UNVERIFIED"),
        ("probe_id", "e" * 64),
        ("probe_candidate_id", "e" * 64),
        ("probe_running", True),
        ("probe_full_json_stage", "AT_OR_ABOVE_CLEANUP_LIMIT"),
        ("probe_full_json_stage", "TIMEOUT"),
        ("original", "RUNNING_OTHER"),
        ("original", "STOPPED"),
        ("original_port", "OTHER"),
        ("original_inspect_stage", "IDENTITY_MISMATCH"),
        ("observer_writes", 1),
        ("foreign_resources_touched", True),
        ("cutover_authorized", True),
    ],
)
def test_unverified_observer_field_refuses_recovery_without_writes(
    rig: LocalRecoveryRig, key: str, value: object
) -> None:
    rig.before[key] = value
    result = recovery.execute()
    assert result["cleanup"] == "NO_GO_PRECHECK"
    assert result["phase"] == "PRECHECK"
    assert result["docker_writes"] == 0
    assert rig.removal_attempts == 0


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("Id",), "e" * 64),
        (("Name",), "/boca-socios-other"),
        (("Config", "Image"), "ghcr.io/foreign/image@sha256:" + "f" * 64),
        (("Config", "User"), "0:0"),
        (("Config", "Cmd"), ["sh"]),
        (("Config", "Labels", "com.docker.compose.project"), "foreign"),
        (("Config", "Labels", "boca.socios.cutover-preflight-attempt"), "42"),
        (("Config", "Labels", "org.opencontainers.image.revision"), "d" * 40),
        (("State", "Running"), True),
        (("State", "Restarting"), True),
        (("State", "Paused"), True),
        (("State", "Dead"), True),
        (("State", "Status"), "running"),
        (("State", "Status"), "paused"),
        (("State", "OOMKilled"), True),
        (("HostConfig", "AutoRemove"), True),
        (("HostConfig", "PidMode"), "host"),
        (("HostConfig", "PublishAllPorts"), True),
        (("HostConfig", "Devices"), [{"PathOnHost": "/dev/null"}]),
        (("HostConfig", "DeviceRequests"), [{"Driver": "nvidia"}]),
        (("HostConfig", "ShmSize"), 0),
        (("HostConfig", "Tmpfs"), {"/tmp": "rw,exec,size=32m"}),  # noqa: S108
        (("HostConfig", "RestartPolicy", "Name"), "always"),
        (("HostConfig", "NetworkMode"), "bridge"),
        (("HostConfig", "IpcMode"), "host"),
        (("HostConfig", "CgroupnsMode"), "host"),
        (("HostConfig", "ReadonlyRootfs"), False),
        (("HostConfig", "Privileged"), True),
        (("HostConfig", "Init"), False),
        (("HostConfig", "NanoCpus"), 0),
        (("HostConfig", "Memory"), 0),
        (("HostConfig", "PidsLimit"), 0),
        (("HostConfig", "CapDrop"), []),
        (("HostConfig", "CapAdd"), ["SYS_ADMIN"]),
        (("HostConfig", "PortBindings"), {"8443/tcp": [{"HostPort": "8443"}]}),
        (("HostConfig", "Binds"), ["/data:/data"]),
        (("HostConfig", "Mounts"), [{"Source": "/srv/foreign"}]),
        (("HostConfig", "VolumesFrom"), ["foreign"]),
        (("HostConfig", "SecurityOpt"), ["no-new-privileges:true"]),
        (("HostConfig", "SecurityOpt"), ["seccomp=unreviewed"]),
        (("Mounts",), [{"Type": "volume", "Name": "owner-data"}]),
        (("NetworkSettings", "Networks"), {"bridge": {}}),
        (("NetworkSettings", "Ports"), {"8443/tcp": [{}]}),
    ],
)
def test_full_isolation_drift_never_deletes_container(
    rig: LocalRecoveryRig, path: tuple[str, ...], value: object
) -> None:
    part: Any = rig.full
    for key in path[:-1]:
        part = part[key]
    part[path[-1]] = value
    result = recovery.execute()
    assert result["cleanup"] == "NO_GO_PRECHECK", path
    assert result["docker_writes"] == 0, path
    assert rig.removal_attempts == 0, path


@pytest.mark.parametrize(
    "replacement",
    [
        "BOCA_RUNTIME_MODE=live",
        "BOCA_ENGINE_MODE=on",
        "BOCA_OBSERVER_STOP=0",
    ],
)
def test_probe_with_changed_boca_safety_environment_is_not_owned_for_cleanup(
    rig: LocalRecoveryRig, replacement: str
) -> None:
    key = replacement.split("=", 1)[0]
    rig.full["Config"]["Env"] = [
        entry for entry in rig.full["Config"]["Env"] if not entry.startswith(key + "=")
    ] + [replacement]
    result = recovery.execute()
    assert result["cleanup"] == "NO_GO_PRECHECK"
    assert result["docker_writes"] == 0
    assert rig.removal_attempts == 0


@pytest.mark.parametrize(
    "change",
    ["missing", "duplicate", "unexpected_boca"],
)
def test_missing_duplicate_or_extra_boca_environment_refuses_cleanup(
    rig: LocalRecoveryRig, change: str
) -> None:
    env: list[str] = rig.full["Config"]["Env"]
    if change == "missing":
        env.remove("BOCA_OBSERVER_STOP=1")
    elif change == "duplicate":
        env.append("BOCA_ENGINE_MODE=off")
    else:
        env.append("BOCA_EXTRA_PRIVILEGE=1")
    result = recovery.execute()
    assert result["cleanup"] == "NO_GO_PRECHECK"
    assert result["docker_writes"] == 0
    assert rig.removal_attempts == 0


def test_missing_worker_is_no_write_no_go_not_an_idempotent_delete(
    rig: LocalRecoveryRig,
) -> None:
    rig.before = _observed(present=False)
    result = recovery.execute()
    assert result["cleanup"] == "NO_GO_PRECHECK"
    assert result["docker_writes"] == 0
    assert rig.removal_attempts == 0


def test_lease_contention_blocks_all_read_and_write_effects(rig: LocalRecoveryRig) -> None:
    rig.lease_failure = True
    result = recovery.execute()
    assert result["cleanup"] == "NO_GO_PRECHECK"
    assert result["docker_writes"] == 0
    assert "observe" not in rig.events
    assert rig.removal_attempts == 0


def test_late_observer_change_blocks_cleanup_before_rm(rig: LocalRecoveryRig) -> None:
    rig.late_observation = _observed(present=True)
    rig.late_observation["probe_running"] = True
    result = recovery.execute()
    assert result["cleanup"] == "NO_GO_PRECHECK"
    assert rig.pre_observations == 2
    assert rig.removal_attempts == 0


def test_late_full_json_isolation_change_blocks_cleanup_before_rm(rig: LocalRecoveryRig) -> None:
    rig.late_full = _full_probe()
    rig.late_full["HostConfig"]["Privileged"] = True
    result = recovery.execute()
    assert result["cleanup"] == "NO_GO_PRECHECK"
    assert rig.full_reads == 2
    assert rig.removal_attempts == 0


def test_failed_full_metadata_read_blocks_cleanup(rig: LocalRecoveryRig) -> None:
    rig.full_failure = subprocess.CalledProcessError(1, ["docker", "inspect"])
    result = recovery.execute()
    assert result["cleanup"] == "NO_GO_PRECHECK"
    assert result["docker_writes"] == 0
    assert rig.removal_attempts == 0


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.TimeoutExpired(["docker", "container", "rm"], 12),
        subprocess.CalledProcessError(1, ["docker", "container", "rm"], stderr="PRIVATE"),
        OSError("Docker socket disappeared"),
    ],
)
def test_ambiguous_remove_failure_never_reports_success_or_retries(
    rig: LocalRecoveryRig, failure: Exception
) -> None:
    rig.remove_failure = failure
    result = recovery.execute()
    assert result["cleanup"] == "INDETERMINATE"
    assert result["phase"] == "REMOVE"
    assert result["docker_writes"] == 1
    assert result["cutover_authorized"] is False
    assert result["retry_authorized"] is False
    assert rig.removal_attempts == 1
    assert "PRIVATE" not in str(result)


def test_ambiguous_success_ack_is_indeterminate_without_retry(rig: LocalRecoveryRig) -> None:
    rig.remove_ack = "e" * 64
    result = recovery.execute()
    assert result["cleanup"] == "INDETERMINATE"
    assert result["phase"] == "REMOVE"
    assert result["docker_writes"] == 1
    assert rig.removal_attempts == 1


def test_retained_exact_cid_after_rm_never_reports_verified(rig: LocalRecoveryRig) -> None:
    rig.retained_cid = True
    result = recovery.execute()
    assert result["cleanup"] == "INDETERMINATE"
    assert result["phase"] == "POSTCHECK"
    assert result["docker_writes"] == 1
    assert rig.removal_attempts == 1


def test_postflight_name_reappears_and_is_not_deleted_again(rig: LocalRecoveryRig) -> None:
    rig.after = _observed(present=True)
    result = recovery.execute()
    assert result["cleanup"] == "INDETERMINATE"
    assert result["phase"] == "POSTCHECK"
    assert result["docker_writes"] == 1
    assert rig.removal_attempts == 1


@pytest.mark.parametrize(
    ("key", "value"),
    [("original", "STOPPED"), ("original", "RUNNING_OTHER"), ("original_port", "OTHER")],
)
def test_legacy_degradation_after_rm_makes_result_indeterminate(
    rig: LocalRecoveryRig, key: str, value: object
) -> None:
    rig.after[key] = value
    result = recovery.execute()
    assert result["cleanup"] == "INDETERMINATE"
    assert result["phase"] == "POSTCHECK"
    assert result["docker_writes"] == 1
    assert rig.removal_attempts == 1


def test_cid_postcheck_error_is_indeterminate_and_never_retries(rig: LocalRecoveryRig) -> None:
    rig.cid_failure = subprocess.TimeoutExpired(["docker", "ps"], 12)
    result = recovery.execute()
    assert result["cleanup"] == "INDETERMINATE"
    assert result["phase"] == "POSTCHECK"
    assert result["docker_writes"] == 1
    assert rig.removal_attempts == 1


def _successful_receipt() -> dict[str, Any]:
    return {
        "version": "boca-worker-recovery-v1",
        "attempt": ATTEMPT,
        "probe_id": CID,
        "legacy_id": LEGACY_ID,
        "cleanup": "VERIFIED",
        "phase": "COMPLETE",
        "docker_writes": 1,
        "foreign_resources_touched": False,
        "cutover_authorized": False,
        "retry_authorized": False,
        "original": "RUNNING_HEALTHY",
    }


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("version", "boca-worker-recovery-v2"),
        ("attempt", "42329475084"),
        ("probe_id", "e" * 64),
        ("legacy_id", "d" * 64),
        ("cleanup", "NO_GO_PRECHECK"),
        ("cleanup", "INDETERMINATE"),
        ("phase", "POSTCHECK"),
        ("docker_writes", 0),
        ("docker_writes", True),
        ("docker_writes", 2),
        ("foreign_resources_touched", True),
        ("cutover_authorized", True),
        ("retry_authorized", True),
        ("original", "UNVERIFIED"),
    ],
)
def test_runner_rejects_forged_or_incomplete_success_receipt(key: str, value: object) -> None:
    record = _successful_receipt()
    record[key] = value
    with pytest.raises((recovery.RecoveryError, ValueError)):
        recovery.verify_runner(observer.canonical(record) + b"\n")


@pytest.mark.parametrize(
    "bad_raw",
    [
        b"",
        b"\xff",
        b" " * 1025,
        b"{}\n",
        b"not-json\n",
        b"{}\n{}\n",
    ],
)
def test_runner_rejects_malformed_or_oversized_transport(bad_raw: bytes) -> None:
    with pytest.raises((recovery.RecoveryError, ValueError, UnicodeError)):
        recovery.verify_runner(bad_raw)


def test_runner_rejects_noncanonical_and_duplicate_key_json() -> None:
    raw = observer.canonical(_successful_receipt()) + b"\n"
    assert recovery.verify_runner(raw) == _successful_receipt()
    for bad in (
        b" " + raw,
        raw[:-1],
        raw.replace(b'"version":', b'"version":"duplicate","version":', 1),
    ):
        with pytest.raises((recovery.RecoveryError, ValueError)):
            recovery.verify_runner(bad)


def _substitute_docker_with_local_child(
    monkeypatch: pytest.MonkeyPatch, script: str
) -> tuple[list[tuple[str, ...]], list[subprocess.Popen[bytes]]]:
    """Real bounded pipes/child lifecycle; invoke Python instead of Docker."""
    real_popen = subprocess.Popen
    commands: list[tuple[str, ...]] = []
    children: list[subprocess.Popen[bytes]] = []

    def launch(argv: tuple[str, ...], **kwargs: Any) -> subprocess.Popen[bytes]:
        commands.append(argv)
        assert argv[0] == "/usr/bin/docker"
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["env"]["DOCKER_HOST"] == "unix:///run/user/10001/docker.sock"
        assert kwargs["env"]["PATH"] == "/usr/bin:/bin"
        assert set(kwargs["env"]) == {"DOCKER_HOST", "XDG_RUNTIME_DIR", "PATH", "LANG"}
        assert all(not key.startswith("DOCKER_") for key in kwargs["env"] if key != "DOCKER_HOST")
        child = real_popen((sys.executable, "-c", script), **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(observer.subprocess, "Popen", launch)
    return commands, children


def test_remove_uses_one_exact_nonforce_nonvolume_rootless_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands, children = _substitute_docker_with_local_child(monkeypatch, f"print('{CID}')")
    assert recovery._remove_exact(CID) == CID
    assert commands == [("/usr/bin/docker", "container", "rm", CID)]
    assert children[0].poll() == 0
    with pytest.raises(recovery.RecoveryError):
        recovery._remove_exact("e" * 64)
    assert len(commands) == 1


def test_full_json_inspection_bounded_in_bytes_during_emission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands, children = _substitute_docker_with_local_child(
        monkeypatch,
        "import sys,time; sys.stdout.buffer.write(b'x'*65536); sys.stdout.flush(); time.sleep(2)",
    )
    started = time.monotonic()
    with pytest.raises(observer.InspectError, match="DOCKER_BOUNDS"):
        recovery._inspect_full_exact(CID)
    assert time.monotonic() - started < 1.5
    assert children[0].poll() is not None
    assert commands == [("/usr/bin/docker", "inspect", "--format", "{{json .}}", CID)]


def test_remove_stderr_bounded_and_discarded_before_child_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands, children = _substitute_docker_with_local_child(
        monkeypatch,
        "import sys,time; sys.stderr.buffer.write(b'SECRET_MARKER'+b'x'*2049); "
        "sys.stderr.flush(); time.sleep(2)",
    )
    started = time.monotonic()
    with pytest.raises(observer.InspectError, match="DOCKER_BOUNDS") as error:
        recovery._remove_exact(CID)
    assert time.monotonic() - started < 1.5
    assert "SECRET_MARKER" not in str(error.value)
    assert children[0].poll() is not None
    assert commands == [("/usr/bin/docker", "container", "rm", CID)]


def test_remove_deadline_kills_and_reaps_hung_child(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(observer, "DOCKER_TIMEOUT_SECONDS", 0.1)
    commands, children = _substitute_docker_with_local_child(
        monkeypatch, "import time; time.sleep(3)"
    )
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        recovery._remove_exact(CID)
    assert time.monotonic() - started < 1.0
    assert children[0].poll() is not None
    assert commands == [("/usr/bin/docker", "container", "rm", CID)]


def test_remove_nonzero_exit_never_exposes_docker_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _commands, children = _substitute_docker_with_local_child(
        monkeypatch, "import sys; sys.stderr.write('SECRET_MARKER'); sys.exit(1)"
    )
    with pytest.raises(subprocess.CalledProcessError) as error:
        recovery._remove_exact(CID)
    assert "SECRET_MARKER" not in str(error.value)
    assert children[0].poll() == 1


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [("", False), (CID + "\n", True)],
)
def test_postflight_exact_cid_query_accepts_only_empty_or_pinned_id(
    monkeypatch: pytest.MonkeyPatch, stdout: str, expected: bool
) -> None:
    # A complete CID is mandatory even for postflight; never enumerate the host.
    script = "import sys; sys.stdout.write(" + repr(stdout) + ")"
    commands, children = _substitute_docker_with_local_child(monkeypatch, script)
    assert recovery._cid_present(CID) is expected
    assert commands == [
        ("/usr/bin/docker", "ps", "-a", "-q", "--no-trunc", "--filter", f"id={CID}")
    ]
    assert children[0].poll() == 0


@pytest.mark.parametrize("stdout", ["e" * 64, CID + "\n" + CID, "incomplete"])
def test_ambiguous_postflight_cid_output_fails_closed(
    monkeypatch: pytest.MonkeyPatch, stdout: str
) -> None:
    script = "import sys; sys.stdout.write(" + repr(stdout) + ")"
    commands, children = _substitute_docker_with_local_child(monkeypatch, script)
    with pytest.raises(recovery.RecoveryError):
        recovery._cid_present(CID)
    assert len(commands) == 1
    assert children[0].poll() == 0


def test_profile_compaction_preserves_exact_reviewed_effective_json() -> None:
    assert recovery._compact_json_profile(PROFILE) == "seccomp=" + COMPACT_PROFILE


def test_cli_rejects_freeform_commands_without_reaching_execute(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden_execute() -> dict[str, Any]:
        pytest.fail("unauthorized CLI input reached recovery.execute()")

    monkeypatch.setattr(recovery, "execute", forbidden_execute)
    for argv in ([], ["rm", CID], ["host", CID], ["host", "--force"], ["stop", CID]):
        assert recovery.main(argv) == 3
        assert "NO_GO" in capsys.readouterr().err
