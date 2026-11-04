"""No-host Option A contract: legacy observation and exact-ID park compensation.

No Docker daemon, Bocajuniors site, or protected blackbox module is loaded.
The stop/rename primitives intentionally are not workflow-dispatchable.
"""

from __future__ import annotations

import copy
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
ATTEMPT = "41897569929"
CONFIG_HASH = "a" * 64
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
        ("docker", "stop", "--time", "8", ORIGINAL_ID),
        ("docker", "rename", ORIGINAL_ID, f"boca-socios-controller-legacy-{ATTEMPT}"),
    ]
    assert state["State"]["Running"] is False
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
    expected = ["stop", "start"] if stop_may_have_effect else ["stop"]
    assert [call[1] for call in calls] == expected
    assert state["Name"] == "/boca-socios-controller-1"
    assert state["State"]["Running"] is True


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
    assert [call[1] for call in calls] == ["stop", "rename", "start"]
    assert state["Name"] == "/boca-socios-controller-1"
    assert state["State"]["Running"] is True


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
    assert [call[1] for call in calls] == ["stop", "rename", "rename", "start"]
    assert state["Name"] == "/boca-socios-controller-1"
    assert state["State"]["Running"] is True


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
    assert [call[1] for call in calls] == ["stop", "rename", "start"]
    assert state["State"]["Running"] is False


def test_worker_create_argv_is_single_service_no_egress_and_no_restart() -> None:
    argv = host._cutover_worker_create_argv(WORKER_IMAGE, TARGET_SHA, ATTEMPT, CONFIG_HASH)
    assert argv[:5] == ("docker", "create", "--pull", "never", "--name")
    assert argv[5] == host.CUTOVER_WORKER_NAME
    assert argv[argv.index("--network") + 1] == "none"
    assert argv[argv.index("--restart") + 1] == "no"
    assert argv[argv.index("--user") + 1] == "10002:10002"
    assert argv[argv.index("--security-opt") + 1] == "no-new-privileges:true"
    assert f"seccomp={host.BROWSER_SECCOMP}" in argv
    assert "127.0.0.1:8443" not in " ".join(argv)
    assert all(
        volume not in " ".join(argv)
        for volume in (host.DATA_VOLUME, host.KEY_VOLUME, host.OWNER_VOLUME)
    )
    assert WORKER_IMAGE in argv and "--publish" not in argv
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


def test_workflow_exposes_only_readonly_cutover_and_separate_legacy_release_proof() -> None:
    text = (PROJECT_ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    match = re.search(r"options: \[([^\n]+)\]", text)
    assert match is not None
    options = [item.strip() for item in match.group(1).split(",")]
    assert "cutover-a-observe" in options
    assert all(
        "cutover-a-" not in operation or operation == "cutover-a-observe" for operation in options
    )
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
