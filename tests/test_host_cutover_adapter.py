"""No-host Option A contract: legacy observation and exact-ID park compensation.

No Docker daemon, Bocajuniors site, or protected blackbox module is loaded.
The stop/rename primitives intentionally are not workflow-dispatchable.
"""

from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host

LEGACY_SHA = "a" * 40
TARGET_SHA = "b" * 40
LEGACY_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "c" * 64
TARGET_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64
WORKER_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "e" * 64
LEGACY_COMPOSE_SHA = "f" * 64
ORIGINAL_ID = "1" * 64
CANDIDATE_ID = "2" * 64
WORKER_ID = "3" * 64
ATTEMPT = "41897569929"
CONFIG_HASH = "a" * 64
SECCOMP = b"reviewed-private-seccomp-profile"
SECCOMP_SHA = hashlib.sha256(SECCOMP).hexdigest()
ORIGIN = "http://localhost:8443"
OWNER = "test-owner"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _legacy_record() -> dict[str, object]:
    return {
        "Id": ORIGINAL_ID,
        "Name": "/boca-socios-controller-1",
        "Config": {
            "Image": LEGACY_IMAGE,
            "User": "10001:10001",
            "Cmd": ["python", "-m", "boca_socios.runtime", "serve-beta"],
            "Labels": {
                "com.docker.compose.project": "boca-socios",
                "com.docker.compose.service": "controller",
                "com.docker.compose.container-number": "1",
                "org.opencontainers.image.revision": LEGACY_SHA,
            },
        },
        "HostConfig": {
            "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
            "NetworkMode": "boca-socios_boca_private",
            "PortBindings": {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]},
            "ReadonlyRootfs": True,
            "Privileged": False,
            "PublishAllPorts": False,
            "Init": True,
            "CapDrop": ["ALL"],
            "CapAdd": None,
            "NanoCpus": 500_000_000,
            "Memory": 268_435_456,
            "PidsLimit": 64,
        },
        "State": {"Running": True, "Restarting": False},
        "NetworkSettings": {"Networks": {"boca-socios_boca_private": {}}},
        "Mounts": [
            {
                "Type": "volume",
                "Driver": "local",
                "Name": host.DATA_VOLUME,
                "Destination": "/data",
                "RW": True,
            },
            {
                "Type": "volume",
                "Driver": "local",
                "Name": host.KEY_VOLUME,
                "Destination": "/run/secrets",
                "RW": False,
            },
            {
                "Type": "volume",
                "Driver": "local",
                "Name": host.OWNER_VOLUME,
                "Destination": "/run/owner",
                "RW": False,
            },
        ],
    }


def _cutover_calls(monkeypatch: pytest.MonkeyPatch) -> tuple[list[tuple[str, ...]], dict]:
    state = _legacy_record()
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(host, "_browser_inspect_record", lambda _id: copy.deepcopy(state))
    monkeypatch.setattr(host, "_browser_port_free", lambda: None)
    monkeypatch.setattr(host, "_browser_wait_healthy", lambda _id: None)

    def run(*args: str, **_kwargs: object) -> str:
        calls.append(args)
        if args[:2] == ("docker", "update"):
            assert args[3] == ORIGINAL_ID
            assert args[2] in ("--restart=no", "--restart=unless-stopped")
            state["HostConfig"]["RestartPolicy"]["Name"] = args[2].split("=", 1)[1]
            return ORIGINAL_ID
        if args[:2] == ("docker", "stop"):
            assert args == ("docker", "stop", "--time", "8", ORIGINAL_ID)
            state["State"]["Running"] = False
            return ORIGINAL_ID
        if args[:2] == ("docker", "rename"):
            assert args[2] == ORIGINAL_ID
            state["Name"] = "/" + args[3]
            return ""
        if args[:2] == ("docker", "start"):
            assert args == ("docker", "start", ORIGINAL_ID)
            state["State"]["Running"] = True
            return ORIGINAL_ID
        pytest.fail(f"unexpected Docker operation: {args!r}")

    monkeypatch.setattr(host, "_run", run)
    return calls, state


def test_readonly_gate_authenticates_historical_and_target_identities(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(host, "_validate_docker_boundary", lambda: seen.append("boundary"))
    monkeypatch.setattr(host, "_browser_engine_version", lambda: "28.0.0")
    monkeypatch.setattr(
        host,
        "_beta_acceptance_status",
        lambda *_args: (
            host.DiagnosticSnapshot(
                uid=10001,
                key_secure=True,
                mounts_secure=True,
                container_id=ORIGINAL_ID,
                health="healthy",
                image_ref=LEGACY_IMAGE,
                revision=LEGACY_SHA,
                project=host.PROJECT,
                service="controller",
                user="10001:10001",
                runtime_mode="simulation",
                engine_mode="off",
                cpu_nano=500_000_000,
                memory_bytes=268_435_456,
                pids_limit=64,
                read_only=True,
                privileged=False,
                has_ports=False,
                network_mode=host.BROWSER_BRIDGE,
                networks=frozenset({host.BROWSER_BRIDGE}),
                network_id="9" * 64,
                network_ports=False,
                cap_drop=("ALL",),
                cap_add=(),
                security_opt=("no-new-privileges:true",),
                tmpfs=(("/tmp", "rw,noexec,nosuid,size=16m"),),  # noqa: S108
                cgroupns_mode="private",
                cgroup=host.CgroupLimits(50_000, 100_000, 268_435_456, 64),
            ),
            object(),
        ),
    )
    monkeypatch.setattr(host, "_browser_inventory", lambda **_kwargs: seen.append("inventory"))
    monkeypatch.setattr(
        host,
        "_names",
        lambda _kind, _name: {host.DATA_VOLUME, host.KEY_VOLUME, host.OWNER_VOLUME},
    )
    monkeypatch.setattr(host, "_browser_root_entries", lambda _expected: seen.append("root"))
    monkeypatch.setattr(host, "_validate_owner_context", lambda *_args: None)
    host.phase(
        "cutover-a-observe",
        LEGACY_IMAGE,
        LEGACY_SHA,
        LEGACY_COMPOSE_SHA,
        ORIGIN,
        OWNER,
        browser_image=WORKER_IMAGE,
        target_image=TARGET_IMAGE,
        target_sha=TARGET_SHA,
        legacy_container_id=ORIGINAL_ID,
    )
    assert seen == ["boundary", "inventory", "root"]
    receipt = capsys.readouterr().out
    assert "state=READY" in receipt
    assert f"legacy_id={ORIGINAL_ID}" in receipt
    assert "effects=none" in receipt


@pytest.mark.parametrize(
    "changed",
    [
        {"target_sha": LEGACY_SHA},
        {"target_image": LEGACY_IMAGE},
        {"browser_image": TARGET_IMAGE},
        {"expected_legacy_id": "1" * 63},
    ],
)
def test_observe_rejects_coordinate_drift(changed: dict[str, str]) -> None:
    values = {
        "legacy_image": LEGACY_IMAGE,
        "legacy_sha": LEGACY_SHA,
        "legacy_compose_sha": LEGACY_COMPOSE_SHA,
        "target_image": TARGET_IMAGE,
        "target_sha": TARGET_SHA,
        "browser_image": WORKER_IMAGE,
        "expected_legacy_id": ORIGINAL_ID,
    }
    values.update(changed)
    with pytest.raises(host.PreflightError):
        host._cutover_validate_coordinates(**values)


@pytest.mark.parametrize(
    ("branch", "key", "altered"),
    [
        ("Config", "Image", TARGET_IMAGE),
        ("HostConfig", "RestartPolicy", {"Name": "no", "MaximumRetryCount": 0}),
        ("HostConfig", "NetworkMode", "host"),
        ("HostConfig", "CapDrop", []),
        ("HostConfig", "PidsLimit", 128),
        ("HostConfig", "PortBindings", {"8443/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8443"}]}),  # noqa: S104 - rejected fixture
    ],
)
def test_park_never_stops_when_original_drifted(
    monkeypatch: pytest.MonkeyPatch, branch: str, key: str, altered: object
) -> None:
    calls, state = _cutover_calls(monkeypatch)
    state[branch][key] = altered
    with pytest.raises(host.PreflightError):
        host._cutover_park_original(ORIGINAL_ID, LEGACY_IMAGE, LEGACY_SHA, ATTEMPT)
    assert calls == []


def test_park_stops_then_renames_exact_original_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, state = _cutover_calls(monkeypatch)
    host._cutover_park_original(ORIGINAL_ID, LEGACY_IMAGE, LEGACY_SHA, ATTEMPT)
    assert calls == [
        ("docker", "update", "--restart=no", ORIGINAL_ID),
        ("docker", "stop", "--time", "8", ORIGINAL_ID),
        ("docker", "rename", ORIGINAL_ID, f"boca-socios-controller-legacy-{ATTEMPT}"),
    ]
    assert state["State"]["Running"] is False
    assert state["HostConfig"]["RestartPolicy"]["Name"] == "no"
    assert state["Name"] == f"/boca-socios-controller-legacy-{ATTEMPT}"


@pytest.mark.parametrize("stop_may_have_effect", [False, True])
def test_stop_transport_failure_distinguishes_live_from_stopped_original(
    monkeypatch: pytest.MonkeyPatch, stop_may_have_effect: bool
) -> None:
    calls, state = _cutover_calls(monkeypatch)
    original_run = host._run

    def interrupted_stop(*args: str, **kwargs: object) -> str:
        if args[:2] == ("docker", "stop"):
            calls.append(args)
            if stop_may_have_effect:
                state["State"]["Running"] = False
            raise host.PreflightError("synthetic transport timeout")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(host, "_run", interrupted_stop)
    with pytest.raises(host.PreflightError, match="RUNNING again"):
        host._cutover_park_original(ORIGINAL_ID, LEGACY_IMAGE, LEGACY_SHA, ATTEMPT)
    expected = (
        ["update", "stop", "start", "update"]
        if stop_may_have_effect
        else ["update", "stop", "update"]
    )
    assert [call[1] for call in calls] == expected
    assert state["Name"] == "/boca-socios-controller-1"
    assert state["State"]["Running"] is True
    assert state["HostConfig"]["RestartPolicy"]["Name"] == "unless-stopped"


@pytest.mark.parametrize("update_may_have_effect", [False, True])
def test_restart_policy_update_timeout_recovers_running_original_without_stop(
    monkeypatch: pytest.MonkeyPatch, update_may_have_effect: bool
) -> None:
    calls, state = _cutover_calls(monkeypatch)
    original_run = host._run

    def interrupted_update(*args: str, **kwargs: object) -> str:
        if args[:3] == ("docker", "update", "--restart=no"):
            calls.append(args)
            if update_may_have_effect:
                state["HostConfig"]["RestartPolicy"]["Name"] = "no"
            raise host.PreflightError("synthetic Docker update transport timeout")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(host, "_run", interrupted_update)
    with pytest.raises(host.PreflightError, match="RUNNING again"):
        host._cutover_park_original(ORIGINAL_ID, LEGACY_IMAGE, LEGACY_SHA, ATTEMPT)
    assert [call[1] for call in calls] == (
        ["update", "update"] if update_may_have_effect else ["update"]
    )
    assert state["State"]["Running"] is True
    assert state["HostConfig"]["RestartPolicy"]["Name"] == "unless-stopped"


def test_failed_rename_compensates_by_starting_original_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, state = _cutover_calls(monkeypatch)
    original_run = host._run

    def fail_rename(*args: str, **kwargs: object) -> str:
        if args[:2] == ("docker", "rename"):
            calls.append(args)
            raise host.PreflightError("synthetic rename failed")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(host, "_run", fail_rename)
    with pytest.raises(host.PreflightError, match="RUNNING again"):
        host._cutover_park_original(ORIGINAL_ID, LEGACY_IMAGE, LEGACY_SHA, ATTEMPT)
    assert [call[1] for call in calls] == ["update", "stop", "rename", "start", "update"]
    assert state["Name"] == "/boca-socios-controller-1"
    assert state["State"]["Running"] is True
    assert state["HostConfig"]["RestartPolicy"]["Name"] == "unless-stopped"


def test_failed_post_rename_check_compensates_rename_back_then_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, state = _cutover_calls(monkeypatch)
    port_checks = 0

    def fail_first_port_check() -> None:
        nonlocal port_checks
        port_checks += 1
        if port_checks == 1:
            raise host.PreflightError("synthetic occupied port")

    monkeypatch.setattr(host, "_browser_port_free", fail_first_port_check)
    with pytest.raises(host.PreflightError, match="RUNNING again"):
        host._cutover_park_original(ORIGINAL_ID, LEGACY_IMAGE, LEGACY_SHA, ATTEMPT)
    assert [call[1] for call in calls] == ["update", "stop", "rename", "rename", "start", "update"]
    assert state["Name"] == "/boca-socios-controller-1"
    assert state["State"]["Running"] is True
    assert state["HostConfig"]["RestartPolicy"]["Name"] == "unless-stopped"


def test_compensation_failure_is_explicitly_indeterminate(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, state = _cutover_calls(monkeypatch)
    original_run = host._run

    def fail_rename_and_start(*args: str, **kwargs: object) -> str:
        if args[:2] in (("docker", "rename"), ("docker", "start")):
            calls.append(args)
            raise host.PreflightError("synthetic daemon interruption")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(host, "_run", fail_rename_and_start)
    with pytest.raises(host.PreflightError, match="INDETERMINATE"):
        host._cutover_park_original(ORIGINAL_ID, LEGACY_IMAGE, LEGACY_SHA, ATTEMPT)
    assert [call[1] for call in calls] == ["update", "stop", "rename", "start"]
    assert state["State"]["Running"] is False


def test_compensation_restart_policy_restore_failure_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, state = _cutover_calls(monkeypatch)
    original_run = host._run

    def fail_rename_then_update(*args: str, **kwargs: object) -> str:
        if args[:2] == ("docker", "rename") or args[:3] == (
            "docker",
            "update",
            "--restart=unless-stopped",
        ):
            calls.append(args)
            raise host.PreflightError("synthetic intermittent daemon failure")
        return original_run(*args, **kwargs)

    monkeypatch.setattr(host, "_run", fail_rename_then_update)
    with pytest.raises(host.PreflightError, match="INDETERMINATE"):
        host._cutover_park_original(ORIGINAL_ID, LEGACY_IMAGE, LEGACY_SHA, ATTEMPT)
    assert [call[1] for call in calls] == ["update", "stop", "rename", "start", "update"]
    assert state["State"]["Running"] is True
    assert state["HostConfig"]["RestartPolicy"]["Name"] == "no"


def test_worker_create_argv_is_single_service_no_egress_and_no_restart() -> None:
    argv = host._cutover_worker_create_argv(WORKER_IMAGE, TARGET_SHA, ATTEMPT, CONFIG_HASH)
    assert argv[:5] == ("docker", "create", "--pull", "never", "--name")
    assert argv[5] == host.CUTOVER_WORKER_NAME
    assert argv[argv.index("--network") + 1] == "none"
    assert argv[argv.index("--restart") + 1] == "no"
    assert argv[argv.index("--user") + 1] == "10002:10002"
    assert argv[argv.index("--security-opt") + 1] == "no-new-privileges:true"
    assert f"seccomp={host.ROOT / f'cutover-a-{ATTEMPT}' / host.BROWSER_SECCOMP.name}" in argv
    assert "127.0.0.1:8443" not in " ".join(argv)
    assert all(
        volume not in " ".join(argv)
        for volume in (host.DATA_VOLUME, host.KEY_VOLUME, host.OWNER_VOLUME)
    )
    assert WORKER_IMAGE in argv and "--publish" not in argv
    assert "BOCA_OBSERVER_STOP=1" in argv
    assert f"com.docker.compose.config-hash={CONFIG_HASH}" in argv
    assert "--rm" not in argv and "--privileged" not in argv
    assert "docker compose" not in " ".join(argv)


def test_candidate_argv_reuses_exact_volume_names_no_invisible_restart() -> None:
    argv = host._cutover_candidate_create_argv(
        TARGET_IMAGE, TARGET_SHA, ATTEMPT, ORIGIN, OWNER, CONFIG_HASH
    )
    assert argv[:2] == ("docker", "create")
    assert argv[argv.index("--name") + 1] == "boca-socios-controller-1"
    assert argv[argv.index("--restart") + 1] == "no"
    assert argv[argv.index("--publish") + 1] == "127.0.0.1:8443:8443/tcp"
    assert argv[argv.index("--network") + 1] == host.BROWSER_BRIDGE
    for volume in (host.DATA_VOLUME, host.KEY_VOLUME, host.OWNER_VOLUME, host.BROWSER_IPC_VOLUME):
        assert f"source={volume}" in " ".join(argv)
    assert "BOCA_ENGINE_MODE=off" in argv
    assert "BOCA_RUNTIME_MODE=simulation" in argv
    assert "BOCA_BROWSER_BACKEND=ipc" in argv
    assert f"com.docker.compose.config-hash={CONFIG_HASH}" in argv
    assert "BOCA_TELEGRAM_TOKEN" not in " ".join(argv)
    assert "--privileged" not in argv and "--cap-add" not in argv
    assert "docker compose" not in " ".join(argv)


def _worker_preparation_fake(
    monkeypatch: pytest.MonkeyPatch, *, fail_at: str | None = None
) -> tuple[list[tuple[str, ...]], dict[str, object], dict[str, object]]:
    calls, legacy = _cutover_calls(monkeypatch)
    worker: dict[str, object] = {"exists": False, "running": False, "volume": False}
    original_run = host._run

    def inspect(identifier: str) -> dict[str, object]:
        if identifier == ORIGINAL_ID:
            return copy.deepcopy(legacy)
        assert identifier == WORKER_ID
        return {"Id": WORKER_ID, "State": {"Running": worker["running"]}}

    def runner(*args: str, **kwargs: object) -> str:
        if args[:2] == ("docker", "ps"):
            calls.append(args)
            assert args[-1] == "name=^/boca-socios-browser-worker-1$"
            return WORKER_ID if worker["exists"] else ""
        if args[:2] == ("docker", "create"):
            calls.append(args)
            worker["exists"] = True
            if fail_at == "create":
                raise host.PreflightError("synthetic create timed out after success")
            return WORKER_ID
        if args[:2] == ("docker", "start") and args[-1] == WORKER_ID:
            calls.append(args)
            worker["running"] = True
            if fail_at == "start":
                raise host.PreflightError("synthetic worker start timed out")
            return WORKER_ID
        if args[:2] == ("docker", "stop") and args[-1] == WORKER_ID:
            calls.append(args)
            worker["running"] = False
            return WORKER_ID
        if args[:2] == ("docker", "rm") and args[-1] == WORKER_ID:
            calls.append(args)
            worker["exists"] = False
            return WORKER_ID
        if args[:3] == ("docker", "volume", "rm"):
            calls.append(args)
            assert args[-1] == host.BROWSER_IPC_VOLUME
            worker["volume"] = False
            return host.BROWSER_IPC_VOLUME
        return original_run(*args, **kwargs)

    def create_volume(*_args: object) -> None:
        worker["volume"] = True
        if fail_at == "volume":
            raise host.PreflightError("synthetic volume init timeout")

    def worker_postflight(
        _id: str, _image: str, _sha: str, _attempt: str, _seccomp: str, **kwargs: object
    ) -> None:
        assert _id == WORKER_ID
        assert kwargs["running"] is worker["running"] if "running" in kwargs else True
        if kwargs.get("verify_runtime", True) and fail_at == "health":
            raise host.PreflightError("synthetic worker health failed")

    monkeypatch.setattr(host, "_run", runner)
    monkeypatch.setattr(host, "_browser_inspect_record", inspect)
    monkeypatch.setattr(host, "_browser_create_ipc_volume", create_volume)
    monkeypatch.setattr(host, "_browser_validate_ipc_volume", lambda _id: None)
    monkeypatch.setattr(host, "_browser_worker_postflight", worker_postflight)
    monkeypatch.setattr(
        host,
        "_names",
        lambda _kind, _pattern: {host.BROWSER_IPC_VOLUME} if worker["volume"] else set(),
    )
    return calls, legacy, worker


def _prepare_worker() -> str:
    return host._cutover_prepare_worker(
        ORIGINAL_ID,
        LEGACY_IMAGE,
        LEGACY_SHA,
        WORKER_IMAGE,
        TARGET_SHA,
        ATTEMPT,
        CONFIG_HASH,
        SECCOMP_SHA,
        SECCOMP,
    )


def test_worker_prepare_is_one_identity_stays_no_egress_and_preserves_live_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, legacy, worker = _worker_preparation_fake(monkeypatch)
    assert _prepare_worker() == WORKER_ID
    assert worker == {"exists": True, "running": True, "volume": True}
    assert legacy["State"]["Running"] is True
    assert all(command[:2] not in (("docker", "stop"), ("docker", "compose")) for command in calls)
    create = next(command for command in calls if command[:2] == ("docker", "create"))
    assert create[create.index("--network") + 1] == "none"
    assert "--publish" not in create
    assert "BOCA_OBSERVER_STOP=1" in create


@pytest.mark.parametrize("failure", ["volume", "create", "start", "health"])
def test_worker_failure_compensates_only_worker_and_attempt_volume(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    calls, legacy, worker = _worker_preparation_fake(monkeypatch, fail_at=failure)
    with pytest.raises(host.PreflightError, match="original controller RUNNING"):
        _prepare_worker()
    assert worker == {"exists": False, "running": False, "volume": False}
    assert legacy["State"]["Running"] is True
    assert all(command[:2] != ("docker", "stop") or command[-1] == WORKER_ID for command in calls)
    assert all(command[:2] != ("docker", "rm") or command[-1] == WORKER_ID for command in calls)
    assert any(command[:3] == ("docker", "volume", "rm") for command in calls)


@pytest.mark.parametrize(
    ("failure", "primary"),
    [
        ("volume", "IPC"),
        ("create", "CREATE"),
        ("start", "START"),
        ("health", "HEALTH_POSTFLIGHT"),
    ],
)
def test_worker_failed_operation_is_typed_and_compensation_is_independent(
    monkeypatch: pytest.MonkeyPatch, failure: str, primary: str
) -> None:
    _worker_preparation_fake(monkeypatch, fail_at=failure)
    with pytest.raises(host.CutoverWorkerPhaseError) as captured:
        _prepare_worker()
    assert captured.value.primary == primary
    assert captured.value.compensation == "VERIFIED"
    assert "synthetic" not in str(captured.value)


@pytest.mark.parametrize(
    ("running", "status", "expected"),
    [
        (False, "starting", "HEALTH_EXITED"),
        (True, "unhealthy", "HEALTH_UNHEALTHY"),
        (True, None, "HEALTH_WAIT"),
        (True, "unknown", "HEALTH_WAIT"),
    ],
)
def test_worker_health_wait_failure_exposes_only_allowlisted_status(
    monkeypatch: pytest.MonkeyPatch,
    running: bool,
    status: str | None,
    expected: str,
) -> None:
    health = {"Status": status} if status is not None else None
    monkeypatch.setattr(
        host,
        "_browser_inspect_record",
        lambda _id: {"State": {"Running": running, "Health": health}},
    )
    with pytest.raises(host.PreflightError) as captured:
        host._browser_wait_healthy(WORKER_ID)
    assert getattr(captured.value, "phase", None) == expected


def test_worker_health_wait_does_not_claim_exit_when_docker_state_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host, "_browser_inspect_record", lambda _id: {"State": None})
    with pytest.raises(host.PreflightError) as captured:
        host._browser_wait_healthy(WORKER_ID)
    assert getattr(captured.value, "phase", None) == "HEALTH_WAIT"


@pytest.mark.parametrize(
    ("exit_code", "oom", "expected_exit", "expected_oom"),
    [
        (0, False, 0, False),
        (1, True, 1, True),
        (137, False, 137, False),
        (137, True, 137, True),
        (True, False, "UNKNOWN", False),
        (-1, "true", "UNKNOWN", "UNKNOWN"),
        (256, None, "UNKNOWN", "UNKNOWN"),
        ("137", 1, "UNKNOWN", "UNKNOWN"),
    ],
)
def test_worker_exited_captures_only_exact_docker_state_before_compensation(
    monkeypatch: pytest.MonkeyPatch,
    exit_code: object,
    oom: object,
    expected_exit: object,
    expected_oom: object,
) -> None:
    inspections: list[str] = []

    def inspect(container: str) -> dict[str, object]:
        inspections.append(container)
        return {
            "State": {
                "Running": False,
                "ExitCode": exit_code,
                "OOMKilled": oom,
                "Error": "SECRET=never-publish",
                "Health": {"Log": ["SECRET=never-publish"]},
            },
            "Config": {"Env": ["SECRET=never-publish"]},
            "Mounts": ["PRIVATE"],
        }

    monkeypatch.setattr(host, "_browser_inspect_record", inspect)
    with pytest.raises(host.WorkerHealthPhaseError) as captured:
        host._browser_wait_healthy(WORKER_ID)
    assert inspections == [WORKER_ID]
    assert captured.value.phase == "HEALTH_EXITED"
    assert captured.value.exit_code == expected_exit
    assert captured.value.oom_killed == expected_oom
    assert "SECRET" not in str(captured.value)
    assert "PRIVATE" not in str(captured.value)


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_worker_exited_evidence_survives_both_compensation_outcomes(
    monkeypatch: pytest.MonkeyPatch, cleanup_fails: bool
) -> None:
    calls, legacy, worker = _worker_preparation_fake(monkeypatch)

    def exited(_container: str) -> None:
        raise host.WorkerHealthPhaseError("HEALTH_EXITED", exit_code=137, oom_killed=True)

    monkeypatch.setattr(host, "_browser_wait_healthy", exited)
    if cleanup_fails:

        def fail_cleanup(*_args: object) -> None:
            raise host.PreflightError("PRIVATE compensation failure")

        monkeypatch.setattr(host, "_cutover_compensate_worker", fail_cleanup)
    with pytest.raises(host.CutoverWorkerPhaseError) as captured:
        _prepare_worker()
    assert captured.value.primary == "HEALTH_EXITED"
    assert captured.value.exit_code == 137
    assert captured.value.oom_killed is True
    assert captured.value.compensation == ("INDETERMINATE" if cleanup_fails else "VERIFIED")
    assert legacy["State"]["Running"] is True
    assert "PRIVATE" not in str(captured.value)
    if not cleanup_fails:
        assert not worker["exists"]
        assert any(command[:2] == ("docker", "rm") for command in calls)


def test_worker_health_wait_timeout_has_no_private_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter((0.0, 1.0, 91.0))
    monkeypatch.setattr(host, "monotonic", lambda: next(clock))
    monkeypatch.setattr(host, "sleep", lambda _duration: None)
    monkeypatch.setattr(
        host,
        "_browser_inspect_record",
        lambda _id: {"State": {"Running": True, "Health": {"Status": "starting"}}},
    )
    with pytest.raises(host.PreflightError) as captured:
        host._browser_wait_healthy(WORKER_ID)
    assert getattr(captured.value, "phase", None) == "HEALTH_TIMEOUT"
    assert "docker" not in str(captured.value).lower()


def test_worker_health_wait_and_postflight_are_separate_failure_categories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _worker_preparation_fake(monkeypatch)

    def failed_inspection(_container: str) -> None:
        raise host.PreflightError("private inspect response")

    monkeypatch.setattr(host, "_browser_wait_healthy", failed_inspection)
    with pytest.raises(host.CutoverWorkerPhaseError) as captured:
        _prepare_worker()
    assert captured.value.primary == "HEALTH_WAIT"
    assert captured.value.compensation == "VERIFIED"
    assert "private inspect response" not in str(captured.value)


def test_worker_typed_health_failure_survives_selective_compensation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_wait = host._browser_wait_healthy
    _worker_preparation_fake(monkeypatch)
    original_inspect = host._browser_inspect_record

    def unhealthy_worker(container: str) -> dict[str, object]:
        record = original_inspect(container)
        if container == WORKER_ID:
            state = record["State"]
            assert isinstance(state, dict)
            state["Health"] = {"Status": "unhealthy"}
        return record

    monkeypatch.setattr(host, "_browser_inspect_record", unhealthy_worker)
    monkeypatch.setattr(host, "_browser_wait_healthy", original_wait)
    with pytest.raises(host.CutoverWorkerPhaseError) as captured:
        _prepare_worker()
    assert captured.value.primary == "HEALTH_UNHEALTHY"
    assert captured.value.compensation == "VERIFIED"


def test_worker_cleanup_failure_keeps_original_failed_create_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _worker_preparation_fake(monkeypatch, fail_at="create")

    def uncertain_cleanup(*_args: object) -> None:
        raise host.PreflightError("private cleanup error")

    monkeypatch.setattr(host, "_cutover_compensate_worker", uncertain_cleanup)
    with pytest.raises(host.CutoverWorkerPhaseError) as captured:
        _prepare_worker()
    assert captured.value.primary == "CREATE"
    assert captured.value.compensation == "INDETERMINATE"
    assert "private cleanup error" not in str(captured.value)


def test_dual_image_pull_exposes_storage_and_pull_operation_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    phases: list[str] = []
    monkeypatch.setattr(host, "_storage_snapshot", lambda: object())
    monkeypatch.setattr(host, "_validate_storage_capacity", lambda *_a, **_kw: None)
    monkeypatch.setattr(host, "_validate_storage_continuity", lambda *_a, **_kw: None)
    monkeypatch.setattr(host, "_browser_validate_image", lambda *_a: None)
    monkeypatch.setattr(host, "_run", lambda *_a, **_kw: "")
    host._browser_pull_both(TARGET_IMAGE, WORKER_IMAGE, TARGET_SHA, phase_hook=phases.append)
    assert phases == ["STORAGE", "PULL", "STORAGE", "PULL", "STORAGE"]


def _candidate_handoff_fake(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_at: str | None = None,
    after_effect: bool = False,
    create_after_effect: bool = True,
    invalid_label: bool = False,
    worker_cleanup_failure: bool = False,
) -> tuple[list[tuple[str, ...]], dict[str, object], dict[str, object]]:
    calls, legacy = _cutover_calls(monkeypatch)
    host._cutover_park_original(ORIGINAL_ID, LEGACY_IMAGE, LEGACY_SHA, ATTEMPT)
    candidate: dict[str, object] = {"exists": False, "running": False}
    original_run = host._run

    def inspected(identifier: str) -> dict[str, object]:
        if identifier == ORIGINAL_ID:
            return copy.deepcopy(legacy)
        if identifier == CANDIDATE_ID:
            return {
                "Id": CANDIDATE_ID,
                "Name": "/boca-socios-controller-1",
                "Config": {
                    "Labels": {
                        "com.docker.compose.config-hash": (
                            "f" * 64 if invalid_label else CONFIG_HASH
                        )
                    }
                },
                "State": {"Running": candidate["running"]},
            }
        pytest.fail(f"unexpected Docker inspect target {identifier}")

    def runner(*args: str, **kwargs: object) -> str:
        if args[:2] == ("docker", "compose"):
            calls.append(args)
            assert args[-2] == "-q"
            assert args[-1] in ("controller", "browser-worker")
            if fail_at == "compose":
                return "4" * 64
            return CANDIDATE_ID if args[-1] == "controller" else WORKER_ID
        if args[:2] == ("docker", "ps"):
            calls.append(args)
            assert args[-1] == "name=^/boca-socios-controller-1$"
            return CANDIDATE_ID if candidate["exists"] else ""
        if args[:2] == ("docker", "create"):
            calls.append(args)
            if fail_at != "create" or create_after_effect:
                candidate["exists"] = True
            if fail_at == "create":
                raise host.PreflightError("synthetic created then SSH timeout")
            return CANDIDATE_ID
        if args[:2] == ("docker", "start") and args[2] == CANDIDATE_ID:
            calls.append(args)
            if after_effect:
                candidate["running"] = True
            if fail_at == "start":
                raise host.PreflightError("synthetic start timeout")
            candidate["running"] = True
            return CANDIDATE_ID
        if args[:2] == ("docker", "stop") and args[-1] == CANDIDATE_ID:
            calls.append(args)
            candidate["running"] = False
            return CANDIDATE_ID
        if args[:2] == ("docker", "rm"):
            calls.append(args)
            if args == ("docker", "rm", ORIGINAL_ID):
                legacy["retired"] = True
                return ORIGINAL_ID
            assert args == ("docker", "rm", CANDIDATE_ID)
            candidate["exists"] = False
            return CANDIDATE_ID
        return original_run(*args, **kwargs)

    monkeypatch.setattr(host, "_browser_inspect_record", inspected)
    monkeypatch.setattr(host, "_run", runner)
    monkeypatch.setattr(host, "_browser_controller_postflight", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(host, "_browser_worker_postflight", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(host, "_cutover_worker_name_id", lambda: WORKER_ID)

    def cleanup_worker(
        image: str, source_sha: str, attempt: str, seccomp_sha: str, seccomp: bytes
    ) -> None:
        assert (image, source_sha, attempt, seccomp_sha, seccomp) == (
            WORKER_IMAGE,
            TARGET_SHA,
            ATTEMPT,
            LEGACY_COMPOSE_SHA,
            b"isolated-reviewed-seccomp",
        )
        calls.append(("compensate-worker", WORKER_ID))
        if worker_cleanup_failure:
            raise host.PreflightError("synthetic worker selective removal receipt lost")

    monkeypatch.setattr(host, "_cutover_compensate_worker", cleanup_worker)

    def loopback(*_args: object) -> None:
        if fail_at == "health":
            raise host.PreflightError("synthetic candidate unhealthy")

    monkeypatch.setattr(host, "_beta_loopback_health", loopback)
    monkeypatch.setattr(
        host,
        "_browser_docker_ids",
        lambda: (
            {CANDIDATE_ID, WORKER_ID}
            if legacy.get("retired")
            else {ORIGINAL_ID, CANDIDATE_ID, WORKER_ID}
        ),
    )
    return calls, legacy, candidate


def _activate() -> str:
    return host._cutover_activate_candidate(
        ORIGINAL_ID,
        LEGACY_IMAGE,
        LEGACY_SHA,
        TARGET_IMAGE,
        TARGET_SHA,
        WORKER_IMAGE,
        WORKER_ID,
        ATTEMPT,
        ORIGIN,
        OWNER,
        CONFIG_HASH,
        LEGACY_COMPOSE_SHA,
        b"isolated-reviewed-seccomp",
    )


def test_candidate_starts_only_after_original_parked_and_retains_old_id_for_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, legacy, candidate = _candidate_handoff_fake(monkeypatch)
    assert _activate() == CANDIDATE_ID
    assert candidate == {"exists": True, "running": True}
    assert legacy["State"]["Running"] is False
    assert legacy["HostConfig"]["RestartPolicy"]["Name"] == "no"
    assert all(command[:2] != ("docker", "rm") for command in calls)
    assert all(command[:2] != ("docker", "compose") for command in calls)


@pytest.mark.parametrize(
    ("failure", "after_effect"),
    [("create", False), ("start", False), ("start", True), ("health", False)],
)
def test_candidate_create_start_or_health_failure_compensates_exact_id(
    monkeypatch: pytest.MonkeyPatch, failure: str, after_effect: bool
) -> None:
    calls, legacy, candidate = _candidate_handoff_fake(
        monkeypatch, fail_at=failure, after_effect=after_effect
    )
    with pytest.raises(host.PreflightError, match="restored RUNNING"):
        _activate()
    assert candidate == {"exists": False, "running": False}
    assert legacy["Name"] == "/boca-socios-controller-1"
    assert legacy["State"]["Running"] is True
    assert legacy["HostConfig"]["RestartPolicy"]["Name"] == "unless-stopped"
    assert ("docker", "rm", CANDIDATE_ID) in calls
    assert ("docker", "start", ORIGINAL_ID) in calls
    assert ("docker", "rm", ORIGINAL_ID) not in calls
    assert ("compensate-worker", WORKER_ID) in calls


def test_create_timeout_without_side_effect_restores_old_without_candidate_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, legacy, candidate = _candidate_handoff_fake(
        monkeypatch, fail_at="create", create_after_effect=False
    )
    with pytest.raises(host.PreflightError, match="restored RUNNING"):
        _activate()
    assert candidate["exists"] is False
    assert legacy["State"]["Running"] is True
    assert ("docker", "rm", CANDIDATE_ID) not in calls
    assert ("compensate-worker", WORKER_ID) in calls


def test_untrusted_candidate_identity_never_removed_and_restore_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, legacy, candidate = _candidate_handoff_fake(monkeypatch, invalid_label=True)
    with pytest.raises(host.PreflightError, match="INDETERMINATE"):
        _activate()
    assert candidate["exists"] is True
    assert legacy["State"]["Running"] is False
    assert ("docker", "rm", CANDIDATE_ID) not in calls
    assert ("docker", "start", ORIGINAL_ID) not in calls
    assert ("compensate-worker", WORKER_ID) not in calls


def test_worker_cleanup_uncertain_after_exact_id_restore_marks_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, legacy, candidate = _candidate_handoff_fake(
        monkeypatch, fail_at="health", worker_cleanup_failure=True
    )
    with pytest.raises(host.PreflightError, match="INDETERMINATE"):
        _activate()
    assert candidate == {"exists": False, "running": False}
    assert legacy["Name"] == "/boca-socios-controller-1"
    assert legacy["State"]["Running"] is True
    assert ("compensate-worker", WORKER_ID) in calls
    assert ("docker", "rm", ORIGINAL_ID) not in calls


def _retire() -> None:
    host._cutover_retire_accepted_original(
        ORIGINAL_ID,
        LEGACY_IMAGE,
        LEGACY_SHA,
        CANDIDATE_ID,
        TARGET_IMAGE,
        TARGET_SHA,
        WORKER_ID,
        WORKER_IMAGE,
        ATTEMPT,
        ORIGIN,
        OWNER,
        CONFIG_HASH,
        LEGACY_COMPOSE_SHA,
        b"isolated-reviewed-seccomp",
        host.ROOT / f"cutover-a-{ATTEMPT}",
    )


def test_retirement_only_after_candidate_healthy_and_compose_discovers_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, legacy, candidate = _candidate_handoff_fake(monkeypatch)
    assert _activate() == CANDIDATE_ID
    _retire()
    assert legacy["retired"] is True
    assert candidate["running"] is True
    assert [call[2] for call in calls if call[:2] == ("docker", "rm")] == [ORIGINAL_ID]
    compose_calls = [call for call in calls if call[:2] == ("docker", "compose")]
    assert [call[-1] for call in compose_calls] == ["controller", "browser-worker"]
    assert all(f"cutover-a-{ATTEMPT}" in " ".join(call) for call in compose_calls)


def test_retirement_refuses_unhealthy_candidate_without_deleting_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, legacy, candidate = _candidate_handoff_fake(monkeypatch)
    assert _activate() == CANDIDATE_ID
    candidate["running"] = False
    with pytest.raises(host.PreflightError, match="health"):
        _retire()
    assert legacy.get("retired") is not True
    assert ("docker", "rm", ORIGINAL_ID) not in calls


def test_retirement_compose_mismatch_is_indeterminate_after_irreversible_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, legacy, candidate = _candidate_handoff_fake(monkeypatch, fail_at="compose")
    assert _activate() == CANDIDATE_ID
    with pytest.raises(host.PreflightError, match="INDETERMINATE; do not retry"):
        _retire()
    assert legacy["retired"] is True
    assert candidate["running"] is True
    assert ("docker", "start", ORIGINAL_ID) not in calls


def test_command_builders_reject_unsourced_coordinates() -> None:
    with pytest.raises(host.PreflightError):
        host._cutover_worker_create_argv(LEGACY_IMAGE, TARGET_SHA, ATTEMPT, CONFIG_HASH)
    with pytest.raises(host.PreflightError):
        host._cutover_worker_create_argv(
            WORKER_IMAGE, TARGET_SHA, "not-an-actions-run", CONFIG_HASH
        )
    with pytest.raises(host.PreflightError):
        host._cutover_candidate_create_argv(
            TARGET_IMAGE, TARGET_SHA, ATTEMPT, "http://evil", OWNER, CONFIG_HASH
        )
    with pytest.raises(host.PreflightError):
        host._cutover_worker_create_argv(WORKER_IMAGE, TARGET_SHA, ATTEMPT, "not-a-hash")


def test_workflow_cutover_v3_requires_dispatch_and_legacy_release_proof() -> None:
    text = (PROJECT_ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    match = re.search(r"options: \[([^\n]+)\]", text)
    assert match is not None
    options = [item.strip() for item in match.group(1).split(",")]
    assert "cutover-a-observe" in options
    assert [operation for operation in options if operation.startswith("cutover-a-")] == [
        "cutover-a-reconcile",
        # R47 one-time, exact-incident remedial operations are independently
        # host/ACK gated; neither promotes nor replays the original APPLY.
        "cutover-a-stage-recover",
        # R96 #844 exact one-shot recovery is a distinct signed incident.
        "cutover-a-stage-recover-844",
        "cutover-a-image-retire",
        "cutover-a-observe",
        # R76 one exact failed preflight metadata-only inspection, no GO.
        "cutover-a-worker-inspect",
        # R112 exact failed-cutover Docker events forensic; READ_ONLY, no retry GO.
        "cutover-a-worker-events-r112",
        # R79 one exact stopped-only recovery; no automatic worker preflight or Cutover.
        "cutover-a-worker-recover",
        # R82 distinct #807 stopped-only recovery, same guarded executor, no Cutover GO.
        "cutover-a-worker-recover-807",
        # R87 exact #819 stopped-only recovery, separate owner gate and zero Cutover GO.
        "cutover-a-worker-recover-819",
        # R91 exact #827 stopped-only recovery, independent one-shot gate.
        "cutover-a-worker-recover-827",
        # R94 exact #834 stopped-only recovery; never repeats the failed preflight.
        "cutover-a-worker-recover-834",
        # P0 rootless/GHCR image probe is a distinct, non-GO transaction.
        "cutover-a-worker-preflight",
        "cutover-a-apply",
    ]
    # The new incident reconciliation reads host state but never consumes GO_B.
    assert "if: inputs.operation == 'cutover-a-reconcile'" in text
    assert "host_cutover_postapply_reconcile.py verify" in text
    assert (
        "BOCA_CUTOVER_A_GO_BINDING_SHA256: ${{ vars.BOCA_CUTOVER_A_GO_BINDING_SHA256 }}" not in text
    )
    assert (
        'check_boca_deploy_dispatch.py "$RUNNER_TEMP/boca-dispatch-v3" --write-invocation' in text
    )
    assert "python scripts/check_cutover_a_go.py --from-actions" not in text
    assert "check_legacy_go_dispatch.py apply" in text
    assert "boca-protected-legacy-go-prepare" in text
    assert "BOCA_CUTOVER_A_DISPATCH_BINDING_SHA256" in text
    assert '"$BOCA_LEGACY_SOURCE_SHA"' in text
    assert '"$BOCA_LEGACY_RELEASE_RUN_ID"' in text
    assert "boca-cutover-legacy-compose.sha" in text
    assert "original=RUNNING worker=absent effects=none" in text
    assert "config --hash controller" in text
    assert "config --hash browser-worker" in text
    assert "com.docker.compose.config-hash=$candidate_hash" in text
    assert "com.docker.compose.config-hash=$worker_hash" in text
    assert (
        "docker compose up"
        not in text[
            text.index("Observe original RUNNING") : text.index("Recheck current main before Site")
        ]
    )
