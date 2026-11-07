"""R82 adversarial CODE_ONLY tests of a unique stopped #807 Boca probe cleanup."""

from __future__ import annotations

import copy
import dataclasses
import json
import subprocess
import sys
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

ATTEMPT_807 = "42341290485"
CID_807 = "06ac6e6b596c8286957cdfa21d6f4e3f6b7f19a7da4cff8b8c9ba47a1307a70d"
SOURCE_807 = "1199c46fee8053e637b220ad9365ce3af15eb8e5"
IMAGE_807 = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
    "c31b41f0fd6332d9d4946d4047c7eb1e58e53ba04ad2ffdedfbb7aa54bcaaa04"
)
ATTEMPT_795 = "42329475083"
CID_795 = "65d844edb438710f44ce83c397906932710ad7f04f3e7a52634f9eaaf1fcc504"
LEGACY_ID = "27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793"
LEGACY_SHA = "cabce9f1e452e63ded115f447559a358dc0f4d1b"
LEGACY_IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:"
    "cf6e4266cfcfea0c07fa31301d59c7aaa3b9c2fefb9f6843baddd208cacd3b59"
)
PROFILE = (ROOT / "docker" / "seccomp_profile.json").read_bytes()
COMPACT = json.dumps(json.loads(PROFILE), separators=(",", ":"), ensure_ascii=False)


def _snapshot(*, present: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "version": "boca-worker-readonly-inspect-v3",
        "attempt": ATTEMPT_807,
        "legacy_id": LEGACY_ID,
        "socket": "PRESENT_OWNED",
        "docker": "OBSERVED",
        "probe": "PRESENT_PIN_MATCH" if present else "ABSENT",
        "probe_id": CID_807 if present else None,
        "probe_candidate_id": CID_807 if present else None,
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
    observer.verify(observer.canonical(result) + b"\n", ATTEMPT_807, LEGACY_ID)
    return result


def _full_worker(*, status: str = "exited") -> dict[str, Any]:
    return {
        "Id": CID_807,
        "Name": f"/boca-socios-cutover-preflight-{ATTEMPT_807}",
        "Config": {
            "Image": IMAGE_807,
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
                "boca.socios.cutover-preflight-attempt": ATTEMPT_807,
                "org.opencontainers.image.revision": SOURCE_807,
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
                "/tmp": "rw,noexec,nosuid,size=32m",  # noqa: S108
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
            "SecurityOpt": ["no-new-privileges:true", "seccomp=" + COMPACT],
        },
        "Mounts": [],
        "NetworkSettings": {"Ports": None, "Networks": {"none": {}}},
    }


class Rig:
    """Keep actual validators/transaction while replacing only external host effects."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.events: list[str] = []
        self.pre_reads = 0
        self.full_reads = 0
        self.rm_attempts = 0
        self.removed = False
        self.before = _snapshot(present=True)
        self.after = _snapshot(present=False)
        self.full = _full_worker()
        self.second_snapshot: dict[str, Any] | None = None
        self.second_full: dict[str, Any] | None = None
        self.post_snapshot: dict[str, Any] | None = None
        self.rm_ack = CID_807
        self.rm_error: Exception | None = None
        self.cid_retained = False
        self.cid_error: Exception | None = None
        self.lease_busy = False

        @contextmanager
        def lease(attempt: str) -> Iterator[object]:
            assert attempt == ATTEMPT_807
            self.events.append("lease-open")
            if self.lease_busy:
                raise recovery.cleanup.CleanupError("LEASE_BUSY")
            try:
                yield object()
            finally:
                self.events.append("lease-close")

        def verify_lease(_lease: object, attempt: str) -> None:
            assert attempt == ATTEMPT_807
            self.events.append("lease-check")

        monkeypatch.setattr(recovery.cleanup, "protected_boca_job_lease", lease)
        monkeypatch.setattr(recovery.cleanup, "verify_protected_boca_job_lease", verify_lease)
        monkeypatch.setattr(recovery, "_observe", self.observe)
        monkeypatch.setattr(recovery, "_inspect_full_exact", self.inspect_full)
        monkeypatch.setattr(recovery, "_profile", lambda: PROFILE)
        monkeypatch.setattr(recovery, "_remove_exact", self.remove)
        monkeypatch.setattr(recovery, "_cid_present", self.cid_present)

    def observe(self, *_args: object, **_kwargs: object) -> dict[str, Any]:
        self.events.append("observe")
        if self.removed:
            return copy.deepcopy(self.post_snapshot or self.after)
        self.pre_reads += 1
        return copy.deepcopy(
            self.second_snapshot
            if self.pre_reads == 2 and self.second_snapshot is not None
            else self.before
        )

    def inspect_full(self, *args: object, **_kwargs: object) -> dict[str, Any]:
        assert CID_807 in args or CID_807 in _kwargs.values()
        self.events.append("full-inspect")
        self.full_reads += 1
        return copy.deepcopy(
            self.second_full if self.full_reads == 2 and self.second_full is not None else self.full
        )

    def remove(self, *args: object, **_kwargs: object) -> str:
        assert CID_807 in args or CID_807 in _kwargs.values()
        self.events.append("rm")
        self.rm_attempts += 1
        if self.rm_error is not None:
            raise self.rm_error
        self.removed = True
        return self.rm_ack

    def cid_present(self, *args: object, **_kwargs: object) -> bool:
        assert CID_807 in args or CID_807 in _kwargs.values()
        self.events.append("cid-check")
        if self.cid_error is not None:
            raise self.cid_error
        return self.cid_retained or not self.removed


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> Rig:
    return Rig(monkeypatch)


@pytest.mark.parametrize("status", ["created", "exited"])
def test_r82_exact_stopped_probe_removed_once_with_dual_full_checks(rig: Rig, status: str) -> None:
    rig.full["State"]["Status"] = status

    result = recovery.execute(target=recovery.TARGET_807)

    assert result == {
        "version": "boca-worker-recovery-v1",
        "attempt": ATTEMPT_807,
        "probe_id": CID_807,
        "legacy_id": LEGACY_ID,
        "cleanup": "VERIFIED",
        "phase": "COMPLETE",
        "docker_writes": 1,
        "foreign_resources_touched": False,
        "cutover_authorized": False,
        "retry_authorized": False,
        "original": "RUNNING_HEALTHY",
    }
    assert rig.pre_reads == 2
    assert rig.full_reads == 2
    assert rig.rm_attempts == 1
    assert rig.events.count("cid-check") == 1
    assert rig.events.index("rm") > rig.events.index("full-inspect")
    assert rig.events[-1] == "lease-close"
    assert (
        recovery.verify_runner(observer.canonical(result) + b"\n", target=recovery.TARGET_807)
        == result
    )


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        ("attempt", ATTEMPT_795),
        ("probe_id", CID_795),
        ("probe_candidate_id", CID_795),
        ("probe_running", True),
        ("probe", "PRESENT_UNVERIFIED"),
        ("probe_full_json_stage", "AT_OR_ABOVE_CLEANUP_LIMIT"),
        ("probe_full_json_stage", "TIMEOUT"),
        ("seccomp", "PRESENT_OWNED"),
        ("seccomp", "UNVERIFIED"),
        ("socket", "PRESENT_UNVERIFIED"),
        ("docker", "PARTIAL"),
        ("legacy_id", CID_795),
        ("original", "RUNNING_OTHER"),
        ("original", "STOPPED"),
        ("original_port", "OTHER"),
        ("original_inspect_stage", "COMMAND_FAILED"),
        ("observer_writes", 1),
        ("foreign_resources_touched", True),
        ("cutover_authorized", True),
    ],
)
def test_r82_any_uncertain_observer_field_blocks_rm_before_write(
    rig: Rig, field: str, wrong: object
) -> None:
    rig.before[field] = wrong

    result = recovery.execute(target=recovery.TARGET_807)

    assert result["cleanup"] == "NO_GO_PRECHECK", field
    assert result["phase"] == "PRECHECK", field
    assert result["docker_writes"] == 0, field
    assert rig.rm_attempts == 0, field


@pytest.mark.parametrize(
    ("path", "wrong"),
    [
        (("Id",), CID_795),
        (("Name",), f"/boca-socios-cutover-preflight-{ATTEMPT_795}"),
        (
            ("Config", "Image"),
            "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "f" * 64,
        ),
        (("Config", "User"), "0:0"),
        (("Config", "Cmd"), ["sh"]),
        (("Config", "Labels", "boca.socios.cutover-preflight-attempt"), ATTEMPT_795),
        (("Config", "Labels", "org.opencontainers.image.revision"), "f" * 40),
        (("Config", "Labels", "com.docker.compose.project"), "foreign"),
        (("State", "Running"), True),
        (("State", "Status"), "running"),
        (("State", "Restarting"), True),
        (("State", "Paused"), True),
        (("State", "Dead"), True),
        (("State", "OOMKilled"), True),
        (("HostConfig", "RestartPolicy", "Name"), "always"),
        (("HostConfig", "NetworkMode"), "bridge"),
        (("HostConfig", "IpcMode"), "host"),
        (("HostConfig", "CgroupnsMode"), "host"),
        (("HostConfig", "ReadonlyRootfs"), False),
        (("HostConfig", "Privileged"), True),
        (("HostConfig", "NanoCpus"), 0),
        (("HostConfig", "Memory"), 0),
        (("HostConfig", "PidsLimit"), 0),
        (("HostConfig", "CapAdd"), ["SYS_ADMIN"]),
        (("HostConfig", "PortBindings"), {"8443/tcp": [{"HostPort": "8443"}]}),
        (("HostConfig", "Binds"), ["/foreign:/foreign"]),
        (("HostConfig", "Mounts"), [{"Source": "/srv/foreign"}]),
        (("HostConfig", "VolumesFrom"), ["foreign"]),
        (("HostConfig", "SecurityOpt"), ["no-new-privileges:true"]),
        (("HostConfig", "SecurityOpt"), ["seccomp=unreviewed"]),
        (("Mounts",), [{"Type": "volume", "Name": "foreign"}]),
        (("NetworkSettings", "Networks"), {"bridge": {}}),
        (("NetworkSettings", "Ports"), {"8443/tcp": [{}]}),
    ],
)
def test_r82_full_json_isolation_mismatch_prevents_any_rm(
    rig: Rig, path: tuple[str, ...], wrong: object
) -> None:
    fragment: Any = rig.full
    for key in path[:-1]:
        fragment = fragment[key]
    fragment[path[-1]] = wrong

    result = recovery.execute(target=recovery.TARGET_807)

    assert result["cleanup"] == "NO_GO_PRECHECK", path
    assert result["docker_writes"] == 0, path
    assert rig.rm_attempts == 0, path


@pytest.mark.parametrize(
    "bad_env",
    [
        ["BOCA_ENVIRONMENT=staging", "BOCA_RUNTIME_MODE=simulation", "BOCA_ENGINE_MODE=off"],
        [
            "BOCA_ENVIRONMENT=staging",
            "BOCA_RUNTIME_MODE=simulation",
            "BOCA_ENGINE_MODE=off",
            "BOCA_OBSERVER_STOP=1",
            "BOCA_ENGINE_MODE=off",
        ],
        [
            "BOCA_ENVIRONMENT=staging",
            "BOCA_RUNTIME_MODE=simulation",
            "BOCA_ENGINE_MODE=on",
            "BOCA_OBSERVER_STOP=1",
        ],
        [
            "BOCA_ENVIRONMENT=staging",
            "BOCA_RUNTIME_MODE=simulation",
            "BOCA_ENGINE_MODE=off",
            "BOCA_OBSERVER_STOP=1",
            "BOCA_EXTRA_PRIVILEGE=1",
        ],
    ],
)
def test_r82_boca_env_quartet_must_be_unique_and_safe(rig: Rig, bad_env: list[str]) -> None:
    rig.full["Config"]["Env"] = bad_env

    result = recovery.execute(target=recovery.TARGET_807)

    assert result["cleanup"] == "NO_GO_PRECHECK"
    assert result["docker_writes"] == 0
    assert rig.rm_attempts == 0


def test_r82_missing_probe_is_not_a_verified_idempotent_delete(rig: Rig) -> None:
    rig.before = _snapshot(present=False)
    result = recovery.execute(target=recovery.TARGET_807)
    assert (result["cleanup"], result["phase"], result["docker_writes"]) == (
        "NO_GO_PRECHECK",
        "PRECHECK",
        0,
    )
    assert rig.rm_attempts == 0


def test_r82_lease_contention_never_enters_observer(rig: Rig) -> None:
    rig.lease_busy = True
    result = recovery.execute(target=recovery.TARGET_807)
    assert result["cleanup"] == "NO_GO_PRECHECK"
    assert result["docker_writes"] == 0
    assert "observe" not in rig.events
    assert rig.rm_attempts == 0


def test_r82_second_observer_race_rejects_before_rm(rig: Rig) -> None:
    late = _snapshot(present=True)
    late["probe_running"] = True
    rig.second_snapshot = late

    result = recovery.execute(target=recovery.TARGET_807)

    assert result["cleanup"] == "NO_GO_PRECHECK"
    assert result["docker_writes"] == 0
    assert rig.pre_reads == 2
    assert rig.rm_attempts == 0


def test_r82_second_full_json_race_rejects_before_rm(rig: Rig) -> None:
    late = _full_worker()
    late["HostConfig"]["NetworkMode"] = "bridge"
    rig.second_full = late

    result = recovery.execute(target=recovery.TARGET_807)

    assert result["cleanup"] == "NO_GO_PRECHECK"
    assert result["docker_writes"] == 0
    assert rig.full_reads == 2
    assert rig.rm_attempts == 0


def test_r82_changed_reviewed_seccomp_bytes_block_removal(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    valid_but_different = json.dumps({**json.loads(PROFILE), "r82_attack": True}).encode()
    monkeypatch.setattr(recovery, "_profile", lambda: valid_but_different)
    result = recovery.execute(target=recovery.TARGET_807)
    assert result["cleanup"] == "NO_GO_PRECHECK"
    assert result["docker_writes"] == 0
    assert rig.rm_attempts == 0


@pytest.mark.parametrize(
    "error",
    [
        subprocess.TimeoutExpired(["docker", "container", "rm"], 12),
        subprocess.CalledProcessError(1, ["docker", "container", "rm"], stderr="PRIVATE"),
        OSError("Docker failed after rm request"),
    ],
)
def test_r82_ambiguous_rm_never_claims_verified_or_retries(rig: Rig, error: Exception) -> None:
    rig.rm_error = error

    result = recovery.execute(target=recovery.TARGET_807)

    assert result["cleanup"] == "INDETERMINATE"
    assert result["phase"] == "REMOVE"
    assert result["docker_writes"] == 1
    assert result["retry_authorized"] is False
    assert result["cutover_authorized"] is False
    assert rig.rm_attempts == 1
    assert "PRIVATE" not in str(result)


def test_r82_malformed_rm_ack_is_indeterminate_without_retry(rig: Rig) -> None:
    rig.rm_ack = CID_795
    result = recovery.execute(target=recovery.TARGET_807)
    assert result["cleanup"] == "INDETERMINATE"
    assert result["phase"] == "REMOVE"
    assert result["docker_writes"] == 1
    assert rig.rm_attempts == 1


def test_r82_cid_retained_after_rm_is_indeterminate(rig: Rig) -> None:
    rig.cid_retained = True
    result = recovery.execute(target=recovery.TARGET_807)
    assert result["cleanup"] == "INDETERMINATE"
    assert result["phase"] == "POSTCHECK"
    assert result["docker_writes"] == 1
    assert rig.rm_attempts == 1


def test_r82_name_reappears_after_rm_no_second_delete(rig: Rig) -> None:
    rig.post_snapshot = _snapshot(present=True)
    result = recovery.execute(target=recovery.TARGET_807)
    assert result["cleanup"] == "INDETERMINATE"
    assert result["phase"] == "POSTCHECK"
    assert result["docker_writes"] == 1
    assert rig.rm_attempts == 1


@pytest.mark.parametrize(
    "field,bad", [("original", "STOPPED"), ("original_port", "OTHER"), ("seccomp", "PRESENT_OWNED")]
)
def test_r82_postflight_legacy_or_seccomp_degradation_is_indeterminate(
    rig: Rig, field: str, bad: str
) -> None:
    late = _snapshot(present=False)
    late[field] = bad
    rig.post_snapshot = late

    result = recovery.execute(target=recovery.TARGET_807)

    assert result["cleanup"] == "INDETERMINATE"
    assert result["phase"] == "POSTCHECK"
    assert result["docker_writes"] == 1
    assert rig.rm_attempts == 1


def test_r82_postflight_cid_query_timeout_is_indeterminate(rig: Rig) -> None:
    rig.cid_error = subprocess.TimeoutExpired(["docker", "ps"], 12)
    result = recovery.execute(target=recovery.TARGET_807)
    assert result["cleanup"] == "INDETERMINATE"
    assert result["phase"] == "POSTCHECK"
    assert result["docker_writes"] == 1
    assert rig.rm_attempts == 1


def _verified_receipt() -> dict[str, Any]:
    return {
        "version": "boca-worker-recovery-v1",
        "attempt": ATTEMPT_807,
        "probe_id": CID_807,
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
    ("field", "wrong"),
    [
        ("version", "boca-worker-recovery-v2"),
        ("attempt", ATTEMPT_795),
        ("probe_id", CID_795),
        ("legacy_id", "f" * 64),
        ("cleanup", "NO_GO_PRECHECK"),
        ("cleanup", "INDETERMINATE"),
        ("phase", "POSTCHECK"),
        ("docker_writes", 0),
        ("docker_writes", 2),
        ("docker_writes", True),
        ("foreign_resources_touched", True),
        ("cutover_authorized", True),
        ("retry_authorized", True),
        ("original", "UNVERIFIED"),
    ],
)
def test_r82_runner_must_reject_every_incomplete_or_cross_incident_receipt(
    field: str, wrong: object
) -> None:
    bad = _verified_receipt()
    bad[field] = wrong
    with pytest.raises((recovery.RecoveryError, ValueError)):
        recovery.verify_runner(observer.canonical(bad) + b"\n", target=recovery.TARGET_807)


@pytest.mark.parametrize(
    "bad_raw",
    [b"", b"\xff", b" " * 1025, b"{}\n", b"not-json\n", b"{}\n{}\n"],
)
def test_r82_runner_refuses_invalid_transport(bad_raw: bytes) -> None:
    with pytest.raises((recovery.RecoveryError, ValueError, UnicodeError)):
        recovery.verify_runner(bad_raw, target=recovery.TARGET_807)


def test_r82_runner_refuses_duplicate_or_noncanonical_json() -> None:
    valid = observer.canonical(_verified_receipt()) + b"\n"
    assert recovery.verify_runner(valid, target=recovery.TARGET_807) == _verified_receipt()
    for forged in (
        b" " + valid,
        valid.rstrip(b"\n"),
        valid.replace(b'"docker_writes":1', b'"docker_writes":0,"docker_writes":1'),
    ):
        with pytest.raises((recovery.RecoveryError, ValueError)):
            recovery.verify_runner(forged, target=recovery.TARGET_807)


def test_r82_runner_does_not_accept_historical_r79_receipt() -> None:
    historical = {**_verified_receipt(), "attempt": ATTEMPT_795, "probe_id": CID_795}
    with pytest.raises((recovery.RecoveryError, ValueError)):
        recovery.verify_runner(observer.canonical(historical) + b"\n", target=recovery.TARGET_807)
    # Historical R79 verifier remains unchanged and still accepts its exact receipt.
    assert recovery.verify_runner(observer.canonical(historical) + b"\n") == historical


def test_r82_target_is_fixed_immutable_and_historical_target_remains_distinct() -> None:
    target = recovery.TARGET_807
    assert isinstance(target, recovery.RecoveryTarget)
    assert dataclasses.is_dataclass(target)
    assert target.attempt == ATTEMPT_807
    assert target.cid == CID_807
    assert target.source == SOURCE_807
    assert target.browser_image == IMAGE_807
    assert target.legacy_id == LEGACY_ID
    assert target.legacy_source == LEGACY_SHA
    assert target.legacy_image == LEGACY_IMAGE
    assert recovery.TARGET_795.attempt == ATTEMPT_795
    assert recovery.TARGET_795.cid == CID_795
    with pytest.raises(dataclasses.FrozenInstanceError):
        target.cid = CID_795


def test_r82_unreviewed_target_rejected_before_lease_or_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = dataclasses.replace(recovery.TARGET_807, cid="f" * 64)
    monkeypatch.setattr(
        recovery.cleanup,
        "protected_boca_job_lease",
        lambda _attempt: pytest.fail("unreviewed target reached lease"),
    )
    monkeypatch.setattr(recovery, "_observe", lambda *_args, **_kwargs: pytest.fail("Docker read"))
    monkeypatch.setattr(
        recovery, "_remove_exact", lambda *_args, **_kwargs: pytest.fail("Docker write")
    )
    try:
        result = recovery.execute(target=fake)
    except recovery.RecoveryError:
        pass
    else:
        assert result["cleanup"] == "NO_GO_PRECHECK"
        assert result["docker_writes"] == 0
        assert result["retry_authorized"] is False


def test_r82_remove_exact_uses_only_one_nonforce_nonvolume_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[tuple[str, ...], int]] = []

    def docker(command: tuple[str, ...], *, stdout_limit: int = 2048) -> str:
        commands.append((command, stdout_limit))
        return CID_807

    monkeypatch.setattr(observer, "_run_bounded", docker)
    assert recovery._remove_exact(CID_807, target=recovery.TARGET_807) == CID_807
    assert commands == [(("docker", "container", "rm", CID_807), 128)]
    assert all(
        forbidden not in " ".join(argv)
        for argv, _limit in commands
        for forbidden in ("--force", "--volumes", " -v ", "prune", "stop", "image", "network")
    )
    with pytest.raises(recovery.RecoveryError):
        recovery._remove_exact(CID_795, target=recovery.TARGET_807)
    assert len(commands) == 1


def test_r82_full_inspect_reads_only_exact_cid_with_byte_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[str, ...], int]] = []

    def docker(command: tuple[str, ...], *, stdout_limit: int = 2048) -> str:
        calls.append((command, stdout_limit))
        return json.dumps(_full_worker())

    monkeypatch.setattr(observer, "_run_bounded", docker)
    full = recovery._inspect_full_exact(CID_807, target=recovery.TARGET_807)
    assert full["Id"] == CID_807
    assert calls == [(("docker", "inspect", "--format", "{{json .}}", CID_807), 65535)]
    with pytest.raises(recovery.RecoveryError):
        recovery._inspect_full_exact(CID_795, target=recovery.TARGET_807)
    assert len(calls) == 1


def test_r82_postcheck_queries_only_pinned_cid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def docker(command: tuple[str, ...], *, stdout_limit: int = 2048) -> str:
        calls.append(command)
        assert stdout_limit == 2048
        return ""

    monkeypatch.setattr(observer, "_run_bounded", docker)
    assert recovery._cid_present(CID_807, target=recovery.TARGET_807) is False
    assert calls == [("docker", "ps", "-a", "-q", "--no-trunc", "--filter", f"id={CID_807}")]
    with pytest.raises(recovery.RecoveryError):
        recovery._cid_present(CID_795, target=recovery.TARGET_807)
    assert len(calls) == 1


def test_r82_cli_verify_mode_accepts_only_new_incident_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    new_receipt = tmp_path / "r82-receipt.json"
    new_receipt.write_bytes(observer.canonical(_verified_receipt()) + b"\n")
    assert recovery.main(["verify-807", str(new_receipt)]) == 0
    assert capsys.readouterr().out == "BOCA_WORKER_RECOVERY_VERIFIED\n"

    old_receipt = tmp_path / "r80-receipt.json"
    old_receipt.write_bytes(
        observer.canonical({**_verified_receipt(), "attempt": ATTEMPT_795, "probe_id": CID_795})
        + b"\n"
    )
    assert recovery.main(["verify-807", str(old_receipt)]) == 3
    assert "state=NO_GO" in capsys.readouterr().err


def test_r82_cli_refuses_freeform_target_arguments_before_any_host_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(recovery, "execute", lambda *_a, **_k: pytest.fail("untrusted host call"))
    assert recovery.main(["host-807", CID_807]) == 3
    assert recovery.main(["host-807", ATTEMPT_807]) == 3
    assert recovery.main(["host", CID_807]) == 3
