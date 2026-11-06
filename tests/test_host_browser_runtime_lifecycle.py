"""Existing dual-service BETA lifecycle never reinitializes retained storage."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from boca_socios import host_first_deploy as host
from test_host_beta_acceptance import PASS
from test_host_browser_ipc_install import (
    ATTEMPT,
    BETA_SHA,
    BROWSER_IMAGE,
    CONTROLLER_ID,
    IMAGE,
    ORIGIN,
    OVERLAY_SHA,
    OWNER,
    SECCOMP_SHA,
    SOURCE,
    WORKER_ID,
    controller_record,
    marker,
    worker_record,
)

COORDS = (IMAGE, SOURCE, BETA_SHA, ORIGIN, OWNER, BROWSER_IMAGE, OVERLAY_SHA, SECCOMP_SHA, ATTEMPT)


def lifecycle(monkeypatch: pytest.MonkeyPatch) -> tuple[list[tuple[str, ...]], list[bool]]:
    commands: list[tuple[str, ...]] = []
    states: list[bool] = []
    identity = host.BrowserInstalled(CONTROLLER_ID, WORKER_ID, marker(), False)
    monkeypatch.setattr(
        host,
        "_browser_installed",
        lambda *args, running, **kwargs: states.append(running) or identity,
    )
    monkeypatch.setattr(host, "_storage_snapshot", lambda: object())
    monkeypatch.setattr(host, "_validate_storage_continuity", lambda *args, **kwargs: None)
    monkeypatch.setattr(host, "_browser_capacity", lambda **kwargs: None)
    monkeypatch.setattr(host, "_browser_port_free", lambda: None)
    monkeypatch.setattr(host, "_browser_wait_healthy", lambda container: None)
    monkeypatch.setattr(host, "_beta_loopback_health", lambda *args: None)

    def run(*args: str, **kwargs: object) -> str:
        commands.append(args)
        if args[:2] in (("docker", "start"), ("docker", "stop")):
            return args[-1]
        if args[-1] == "boca_socios.acceptance.host_probe":
            return PASS
        if args[:2] == ("docker", "exec") and "UnixSyntheticBrowser" in args[-1]:
            return "BOCA_BROWSER_IPC_SYNTHETIC_PASS"
        pytest.fail(f"unreviewed lifecycle effect {args}")

    monkeypatch.setattr(host, "_run", run)
    return commands, states


@pytest.mark.parametrize("operation", ["browser-start", "browser-restart"])
def test_existing_dual_start_never_initializes_or_recreates_storage(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    commands, states = lifecycle(monkeypatch)
    host._browser_lifecycle(operation, *COORDS)
    expected = [("docker", "start", WORKER_ID), ("docker", "start", CONTROLLER_ID)]
    if operation == "browser-restart":
        expected = [
            ("docker", "stop", "--time", "35", CONTROLLER_ID),
            ("docker", "stop", "--time", "35", WORKER_ID),
        ] + expected
    assert commands == expected
    assert states == (
        [True, False, True, True] if operation == "browser-restart" else [False, True, True]
    )


def test_no_start_effect_without_exact_stopped_topology(monkeypatch: pytest.MonkeyPatch) -> None:
    commands, _ = lifecycle(monkeypatch)
    monkeypatch.setattr(
        host,
        "_browser_installed",
        lambda *args, **kwargs: (_ for _ in ()).throw(host.PreflightError("foreign object")),
    )
    with pytest.raises(host.PreflightError):
        host._browser_lifecycle("browser-start", *COORDS)
    assert commands == []


def test_stale_ipc_worker_failure_never_starts_controller_or_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands, _ = lifecycle(monkeypatch)
    monkeypatch.setattr(
        host,
        "_browser_wait_healthy",
        lambda container: (_ for _ in ()).throw(
            host.PreflightError("worker refused retained socket")
        ),
    )
    with pytest.raises(host.PreflightError):
        host._browser_lifecycle("browser-start", *COORDS)
    assert commands == [("docker", "start", WORKER_ID)]


def test_dual_acceptance_exercises_real_ipc_and_existing_http_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands, states = lifecycle(monkeypatch)
    host._browser_lifecycle("browser-acceptance", *COORDS)
    assert len(commands) == 2 and all(command[:2] == ("docker", "exec") for command in commands)
    assert all(command[4] == CONTROLLER_ID for command in commands)
    assert "UnixSyntheticBrowser" in commands[0][-1]
    assert commands[1][-1] == "boca_socios.acceptance.host_probe"
    assert states == [True, True]


def test_acceptance_has_no_pass_receipt_after_identity_drift(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lifecycle(monkeypatch)
    identity = host.BrowserInstalled(CONTROLLER_ID, WORKER_ID, marker(), False)
    answers = iter((identity, replace(identity, worker="d" * 64)))
    monkeypatch.setattr(host, "_browser_installed", lambda *args, **kwargs: next(answers))
    with pytest.raises(host.PreflightError):
        host._browser_lifecycle("browser-acceptance", *COORDS)
    assert "PASS" not in capsys.readouterr().out


@pytest.mark.parametrize("service", ["controller", "worker"])
def test_stopped_service_checks_keep_isolation_without_claiming_kernel_health(
    monkeypatch: pytest.MonkeyPatch,
    service: str,
) -> None:
    record = controller_record() if service == "controller" else worker_record()
    record["State"] = {"Running": False, "Restarting": False}
    if service == "controller":
        record["NetworkSettings"]["Ports"] = {}  # type: ignore[index]
    monkeypatch.setattr(host, "_browser_inspect_record", lambda _: record)
    monkeypatch.setattr(host, "_browser_effective_seccomp_options", lambda *args: None)
    monkeypatch.setattr(host, "_browser_worker_probe", lambda _: pytest.fail("stopped worker exec"))
    monkeypatch.setattr(host, "_cgroup_limits", lambda _: pytest.fail("stopped controller exec"))
    if service == "controller":
        host._browser_controller_postflight(
            CONTROLLER_ID, IMAGE, SOURCE, ATTEMPT, ORIGIN, OWNER, running=False
        )
    else:
        host._browser_worker_postflight(
            WORKER_ID, BROWSER_IMAGE, SOURCE, ATTEMPT, SECCOMP_SHA, running=False
        )
    record["HostConfig"]["Privileged"] = True  # type: ignore[index]
    with pytest.raises(host.PreflightError):
        if service == "controller":
            host._browser_controller_postflight(
                CONTROLLER_ID, IMAGE, SOURCE, ATTEMPT, ORIGIN, OWNER, running=False
            )
        else:
            host._browser_worker_postflight(
                WORKER_ID, BROWSER_IMAGE, SOURCE, ATTEMPT, SECCOMP_SHA, running=False
            )


def test_telegram_dual_topology_reuses_installed_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[tuple[str, ...], bool]] = []

    def installed(*args: str, running: bool) -> host.BrowserInstalled:
        calls.append((args, running))
        return host.BrowserInstalled(CONTROLLER_ID, WORKER_ID, marker(), True)

    monkeypatch.setattr(host, "_browser_installed", installed)
    assert host._telegram_installed(
        IMAGE, SOURCE, BETA_SHA, ORIGIN, OWNER, BROWSER_IMAGE, OVERLAY_SHA, SECCOMP_SHA, ATTEMPT
    )
    assert calls == [(COORDS, False)]


def test_existing_attempt_comes_from_canonical_bound_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host, "_require_dedicated_identity", lambda: 10001)
    value = marker()
    monkeypatch.setattr(
        host,
        "_browser_root_file",
        lambda *args, **kwargs: json.dumps(value, sort_keys=True, separators=(",", ":")).encode(),
    )
    assert (
        host._browser_existing_attempt(
            IMAGE, SOURCE, BETA_SHA, BROWSER_IMAGE, OVERLAY_SHA, SECCOMP_SHA
        )
        == ATTEMPT
    )
    value["source_sha"] = "0" * 40
    with pytest.raises(host.PreflightError):
        host._browser_existing_attempt(
            IMAGE, SOURCE, BETA_SHA, BROWSER_IMAGE, OVERLAY_SHA, SECCOMP_SHA
        )


def test_readonly_capacity_never_claims_daemon_or_storage_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host.shutil, "which", lambda _: "/usr/bin/dockerd")
    monkeypatch.setattr(
        host.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="Docker version 29.1.2, build abc123\n"
        ),
    )
    monkeypatch.setattr(
        host, "_run", lambda *args, **kwargs: pytest.fail("Docker daemon consulted")
    )
    receipt = host._readonly_capacity_metadata()
    assert "dockerd_binary_version=29.1.2" in receipt
    assert "daemon_version=unverified storage=unverified capacity_gate=not_evaluated" in receipt


BOT_ID = "12345"
CHAT_HMAC = "b" * 64
RUNTIME_ATTEMPT = "789012"
SENDER_ID = "1" * 64
IMAGE_ID = "sha256:" + "2" * 64


def sender_record(*, running: bool = True) -> dict:
    return {
        "Id": SENDER_ID,
        "Image": IMAGE_ID,
        "Name": "/boca-socios-telegram-1",
        "RestartCount": 0,
        "State": {"Running": running, "Restarting": False, "StartedAt": "2026-11-02T10:00:00Z"},
        "Config": {
            "Image": IMAGE,
            "User": "10001:10001",
            "WorkingDir": "/app",
            "Entrypoint": None,
            "Cmd": [
                "python",
                "-m",
                "boca_socios.notify.telegram_worker",
                "serve",
                SOURCE,
                BOT_ID,
                CHAT_HMAC,
            ],
            "Healthcheck": {"Test": ["NONE"]},
            "Env": [
                "PATH=/usr/local/bin:/usr/bin",
                "BOCA_ENVIRONMENT=staging",
                "BOCA_RUNTIME_MODE=simulation",
                "BOCA_ENGINE_MODE=off",
                "BOCA_TELEGRAM_DISPATCH_MODE=explicit",
                "BOCA_DB_PATH=/data/boca.sqlite3",
            ],
            "Labels": {
                "com.docker.compose.project": "boca-socios",
                "com.docker.compose.service": "telegram",
                "com.docker.compose.container-number": "1",
                "org.opencontainers.image.revision": SOURCE,
                host.BROWSER_ATTEMPT_LABEL: ATTEMPT,
                host.TELEGRAM_ATTEMPT_LABEL: RUNTIME_ATTEMPT,
            },
        },
        "HostConfig": {
            "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "NanoCpus": 250_000_000,
            "Memory": 134_217_728,
            "PidsLimit": 32,
            "ReadonlyRootfs": True,
            "Privileged": False,
            "PublishAllPorts": False,
            "Init": True,
            "IpcMode": "private",
            "CgroupnsMode": "private",
            "NetworkMode": host.TELEGRAM_NETWORK,
            "PortBindings": {},
            "CapDrop": ["ALL"],
            "CapAdd": None,
            "SecurityOpt": ["no-new-privileges:true"],
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=8m"},  # noqa: S108 - private capped tmpfs
        },
        "Mounts": [
            {
                "Type": "volume",
                "Name": host.DATA_VOLUME,
                "Destination": "/data",
                "RW": True,
                "Driver": "local",
            },
            {
                "Type": "volume",
                "Name": host.TELEGRAM_VOLUME,
                "Destination": "/run/telegram",
                "RW": False,
                "Driver": "local",
            },
        ],
        "NetworkSettings": {
            "Ports": {},
            "Networks": {host.TELEGRAM_NETWORK: {"NetworkID": "3" * 64}},
        },
    }


def sender_image() -> str:
    return json.dumps(
        {
            "Id": IMAGE_ID,
            "RepoDigests": [IMAGE],
            "Config": {
                "Env": ["PATH=/usr/local/bin:/usr/bin"],
                "Labels": {"org.opencontainers.image.revision": SOURCE},
            },
        }
    )


@pytest.mark.parametrize("running", [True, False])
def test_durable_sender_exact_identity_passes_without_contacting_telegram(
    monkeypatch: pytest.MonkeyPatch,
    running: bool,
) -> None:
    monkeypatch.setattr(host, "_browser_inspect_record", lambda _: sender_record(running=running))
    commands = []
    monkeypatch.setattr(
        host, "_run", lambda *args, **kwargs: commands.append(args) or sender_image()
    )
    assert (
        host._telegram_worker_inspect(
            SENDER_ID,
            IMAGE,
            SOURCE,
            BOT_ID,
            CHAT_HMAC,
            ATTEMPT,
            running=running,
            runtime_attempt=RUNTIME_ATTEMPT,
        )
        == RUNTIME_ATTEMPT
    )
    assert all(command[:3] == ("docker", "image", "inspect") for command in commands)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("Config", "Cmd", ["python", "-m", "boca_socios.notify.telegram_worker", "serve"]),
        ("Config", "User", "0:0"),
        ("Config", "Env", ["BOCA_DB_PATH=/data/boca.sqlite3", "BOCA_DB_PATH=/data/boca.sqlite3"]),
        ("HostConfig", "Privileged", True),
        ("HostConfig", "Memory", 0),
        ("HostConfig", "PidsLimit", -1),
        ("HostConfig", "IpcMode", "host"),
        ("HostConfig", "NetworkMode", "host"),
        ("HostConfig", "RestartPolicy", {"Name": "always", "MaximumRetryCount": 0}),
        ("HostConfig", "PortBindings", {"8444/tcp": [{"HostPort": "8444"}]}),
        ("State", "Restarting", True),
        ("NetworkSettings", "Networks", {"other_network": {}}),
    ],
)
def test_sender_identity_drift_is_never_accepted(
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    key: str,
    value: object,
) -> None:
    record = sender_record()
    record[section][key] = value
    monkeypatch.setattr(host, "_browser_inspect_record", lambda _: record)
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: sender_image())
    with pytest.raises(host.PreflightError):
        host._telegram_worker_inspect(
            SENDER_ID, IMAGE, SOURCE, BOT_ID, CHAT_HMAC, ATTEMPT, running=True
        )


@pytest.mark.parametrize("attempt", ["", "001", "0", "old-run", "9" * 21])
def test_sender_runtime_attempt_must_be_positive_run_identity(
    monkeypatch: pytest.MonkeyPatch,
    attempt: str,
) -> None:
    record = sender_record()
    record["Config"]["Labels"][host.TELEGRAM_ATTEMPT_LABEL] = attempt
    monkeypatch.setattr(host, "_browser_inspect_record", lambda _: record)
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: sender_image())
    with pytest.raises(host.PreflightError):
        host._telegram_worker_inspect(
            SENDER_ID, IMAGE, SOURCE, BOT_ID, CHAT_HMAC, ATTEMPT, running=True
        )


def test_sender_run_command_has_no_new_privileges_or_unpinned_identity() -> None:
    command = host._telegram_worker_container(
        IMAGE, SOURCE, BOT_ID, CHAT_HMAC, ATTEMPT, RUNTIME_ATTEMPT
    )
    assert command[-7:] == (
        "python",
        "-m",
        "boca_socios.notify.telegram_worker",
        "serve",
        SOURCE,
        BOT_ID,
        CHAT_HMAC,
    )
    assert command[command.index("--name") + 1] == "boca-socios-telegram-1"
    assert command[command.index("--security-opt") + 1] == "no-new-privileges:true"
    assert command[command.index("--restart") + 1] == "no"
    assert "--ipc=private" in command and "--cgroupns=private" in command
    assert f"{host.TELEGRAM_ATTEMPT_LABEL}={RUNTIME_ATTEMPT}" in command
    assert all(flag not in command for flag in ("--rm", "--publish", "--privileged"))
    assert command.count("--mount") == 2


def sender_phase_fixture(
    monkeypatch: pytest.MonkeyPatch, *, sender: bool = False, network: bool = False
):
    from test_host_first_deploy import safe_storage

    commands: list[tuple[str, ...]] = []
    state = {"sender": sender, "network": network, "running": sender, "attempt": RUNTIME_ATTEMPT}
    baseline = host.BrowserInstalled(CONTROLLER_ID, WORKER_ID, marker(), True)
    capacity = []
    monkeypatch.setattr(
        host,
        "_browser_installed",
        lambda *args, **kwargs: replace(baseline, sender=SENDER_ID if state["sender"] else ""),
    )
    monkeypatch.setattr(host, "_storage_snapshot", safe_storage)
    monkeypatch.setattr(host, "_browser_capacity", lambda **kwargs: capacity.append(kwargs))
    monkeypatch.setattr(host, "_telegram_egress", lambda *args: None)
    monkeypatch.setattr(
        host,
        "_names",
        lambda *args: (
            {host.BROWSER_BRIDGE} | ({host.TELEGRAM_NETWORK} if state["network"] else set())
        ),
    )
    monkeypatch.setattr(host, "_telegram_worker_ready", lambda *args: None)

    def inspect(_):
        record = sender_record(running=bool(state["running"]))
        record["Config"]["Labels"][host.TELEGRAM_ATTEMPT_LABEL] = state["attempt"]
        return record

    monkeypatch.setattr(host, "_browser_inspect_record", inspect)

    def run(*args, **kwargs):
        commands.append(args)
        if args[:3] == ("docker", "image", "inspect"):
            return sender_image()
        if args[:3] == ("docker", "network", "create"):
            state["network"] = True
            return "3" * 64
        if args[:3] == ("docker", "network", "inspect"):
            return json.dumps(
                {
                    "Labels": {
                        host.BROWSER_ATTEMPT_LABEL: ATTEMPT,
                        host.TELEGRAM_ATTEMPT_LABEL: state["attempt"],
                    }
                }
            )
        if args[:2] == ("docker", "run"):
            state["sender"] = state["running"] = True
            return SENDER_ID
        if args[:2] == ("docker", "stop"):
            state["running"] = False
            return SENDER_ID
        if args[:2] == ("docker", "rm"):
            state["sender"] = False
            return SENDER_ID
        if args[:3] == ("docker", "network", "rm"):
            state["network"] = False
            return host.TELEGRAM_NETWORK
        pytest.fail(f"unreviewed sender operation {args}")

    monkeypatch.setattr(host, "_run", run)
    return commands, state, capacity


def test_sender_preflight_is_readonly_and_observes_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands, _, capacity = sender_phase_fixture(monkeypatch)
    host._browser_telegram_phase(
        "browser-telegram-preflight", *COORDS, BOT_ID, CHAT_HMAC, RUNTIME_ATTEMPT
    )
    assert commands == []
    assert capacity == [{"min_free_bytes": host.POSTINSTALL_STORAGE_MIN_BYTES}]


def test_sender_start_creates_only_current_attempt_network_and_fixed_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands, _, _ = sender_phase_fixture(monkeypatch)
    host._browser_telegram_phase(
        "browser-telegram-start", *COORDS, BOT_ID, CHAT_HMAC, RUNTIME_ATTEMPT
    )
    effects = [
        command
        for command in commands
        if command[:3] == ("docker", "network", "create") or command[:2] == ("docker", "run")
    ]
    assert len(effects) == 2
    assert all(f"{host.TELEGRAM_ATTEMPT_LABEL}={RUNTIME_ATTEMPT}" in command for command in effects)
    assert all(
        not any(word in command for word in ("volume", "pull", "prune", "init-key"))
        for command in effects
    )


@pytest.mark.parametrize(("sender", "network"), [(True, True), (False, True)])
def test_sender_start_rejects_existing_resources_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    sender: bool,
    network: bool,
) -> None:
    commands, _, _ = sender_phase_fixture(monkeypatch, sender=sender, network=network)
    with pytest.raises(host.PreflightError, match="no blind retry"):
        host._browser_telegram_phase(
            "browser-telegram-start", *COORDS, BOT_ID, CHAT_HMAC, RUNTIME_ATTEMPT
        )
    assert commands == []


def test_sender_failure_cleanup_removes_only_new_sender_and_network_and_reports_capacity(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    commands, _, _ = sender_phase_fixture(monkeypatch)
    monkeypatch.setattr(
        host,
        "_telegram_worker_ready",
        lambda *args: (_ for _ in ()).throw(host.PreflightError("durable proof absent")),
    )
    with pytest.raises(host.PreflightError, match="durable proof"):
        host._browser_telegram_phase(
            "browser-telegram-start", *COORDS, BOT_ID, CHAT_HMAC, RUNTIME_ATTEMPT
        )
    assert "PASS" not in capsys.readouterr().out
    host._browser_telegram_phase(
        "browser-telegram-cleanup", *COORDS, BOT_ID, CHAT_HMAC, RUNTIME_ATTEMPT
    )
    effects = [
        command
        for command in commands
        if command[:2] in (("docker", "stop"), ("docker", "rm"))
        or command[:3] == ("docker", "network", "rm")
    ]
    assert effects == [
        ("docker", "stop", "--time", "10", SENDER_ID),
        ("docker", "rm", SENDER_ID),
        ("docker", "network", "rm", host.TELEGRAM_NETWORK),
    ]
    output = capsys.readouterr().out
    assert "BOCA_BROWSER_TELEGRAM_CLEANUP_STORAGE" in output
    assert "before_docker_inodes=" in output and "after_docker_free_bytes=" in output
    assert "sender=absent network=absent data=preserved key=preserved owner=preserved" in output


@pytest.mark.parametrize("foreign", ["network", "sender"])
def test_sender_cleanup_refuses_other_run_before_first_destructive_action(
    monkeypatch: pytest.MonkeyPatch,
    foreign: str,
) -> None:
    commands, state, _ = sender_phase_fixture(monkeypatch, sender=True, network=True)
    if foreign == "network":
        state["attempt"] = "999"
    else:
        record = sender_record()
        record["Config"]["Labels"][host.TELEGRAM_ATTEMPT_LABEL] = "999"
        monkeypatch.setattr(host, "_browser_inspect_record", lambda _: record)
    with pytest.raises(host.PreflightError):
        host._browser_telegram_phase(
            "browser-telegram-cleanup", *COORDS, BOT_ID, CHAT_HMAC, RUNTIME_ATTEMPT
        )
    assert all(
        command[:2] not in (("docker", "stop"), ("docker", "rm"))
        and command[:3] != ("docker", "network", "rm")
        for command in commands
    )


def test_sender_cleanup_is_possible_below_install_capacity_without_weakening_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from test_host_first_deploy import safe_storage

    sender_phase_fixture(monkeypatch, sender=True, network=True)
    low = replace(
        safe_storage(),
        stage_free_bytes=1000,
        docker_free_bytes=1000,
        stage_inodes=100,
        docker_inodes=100,
    )
    monkeypatch.setattr(host, "_storage_snapshot", lambda: low)
    host._browser_telegram_phase(
        "browser-telegram-cleanup", *COORDS, BOT_ID, CHAT_HMAC, RUNTIME_ATTEMPT
    )
    changed = replace(low, docker_inode=999)
    with pytest.raises(host.PreflightError, match="storage topology"):
        host._validate_storage_continuity(low, changed, require_capacity=False)
    with pytest.raises(host.PreflightError, match="insufficient"):
        host._validate_storage_continuity(low, low)


def test_sender_readiness_uses_current_start_logs_and_rejects_unverified_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = sender_record()
    monkeypatch.setattr(host, "_browser_inspect_record", lambda _: record)
    commands = []
    expected = (
        f"BOCA_TELEGRAM_READY state=VERIFIED source_sha={SOURCE} api_accepted=1 identity=pinned"
    )
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: commands.append(args) or expected)
    host._telegram_worker_ready(SENDER_ID, SOURCE)
    assert commands == [
        ("docker", "logs", "--since", "2026-11-02T10:00:00Z", "--tail", "2", SENDER_ID)
    ]
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: expected + "\nunreviewed")
    with pytest.raises(host.PreflightError, match="unverified"):
        host._telegram_worker_ready(SENDER_ID, SOURCE)


def test_full3_restart_preserves_sender_identity_stops_sender_first_and_starts_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands, _ = lifecycle(monkeypatch)
    identity = host.BrowserInstalled(CONTROLLER_ID, WORKER_ID, marker(), True, SENDER_ID)
    monkeypatch.setattr(host, "_browser_installed", lambda *args, **kwargs: identity)
    capacities = []
    monkeypatch.setattr(host, "_browser_capacity", lambda **kwargs: capacities.append(kwargs))
    ready = []
    monkeypatch.setattr(host, "_telegram_worker_ready", lambda *args: ready.append(args))
    host._browser_lifecycle("browser-restart", *COORDS, BOT_ID, CHAT_HMAC)
    assert [command[-1] for command in commands] == [
        SENDER_ID,
        CONTROLLER_ID,
        WORKER_ID,
        WORKER_ID,
        CONTROLLER_ID,
        SENDER_ID,
    ]
    assert ready == [(SENDER_ID, SOURCE)]
    assert capacities == [{"min_free_bytes": host.POSTINSTALL_STORAGE_MIN_BYTES}]


@pytest.mark.parametrize(
    ("phase", "attempt"),
    [
        ("browser-telegram-start", ""),
        ("browser-telegram-start", RUNTIME_ATTEMPT),
        ("browser-telegram-cleanup", "001"),
        ("browser-status", RUNTIME_ATTEMPT),
        ("inspect-prerequisites", RUNTIME_ATTEMPT),
    ],
)
def test_sender_attempt_is_mandatory_and_cannot_leak_into_unrelated_phase(
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    attempt: str,
) -> None:
    monkeypatch.setattr(host, "_validate_docker_boundary", lambda: pytest.fail("host accessed"))
    with pytest.raises(host.PreflightError):
        host.phase(phase, IMAGE, SOURCE, BETA_SHA, ORIGIN, OWNER, telegram_attempt_id=attempt)


@pytest.mark.parametrize(
    ("controller_running", "worker_running"),
    [(True, True), (False, False), (True, False), (False, True)],
)
def test_cleanup_identifies_unhealthy_or_stopped_pair_without_requiring_health_or_mutating_it(
    monkeypatch: pytest.MonkeyPatch,
    controller_running: bool,
    worker_running: bool,
) -> None:
    from test_host_first_deploy import safe_storage

    controller, worker = controller_record(), worker_record()
    controller["Image"], worker["Image"] = IMAGE_ID, "sha256:" + "4" * 64
    controller["State"] = {
        "Running": controller_running,
        "Restarting": False,
        "Health": {"Status": "unhealthy"},
    }
    worker["State"] = {
        "Running": worker_running,
        "Restarting": False,
        "Health": {"Status": "unhealthy"},
    }
    if not controller_running:
        controller["NetworkSettings"]["Ports"] = None
    records = {CONTROLLER_ID: controller, WORKER_ID: worker}
    monkeypatch.setattr(host, "_browser_engine_version", lambda: None)
    monkeypatch.setattr(host, "_browser_read_marker", lambda *args: marker())
    monkeypatch.setattr(host, "_browser_verify_staged", lambda *args: None)
    monkeypatch.setattr(host, "_browser_compose_model", lambda *args: None)
    monkeypatch.setattr(host, "_browser_validate_image", lambda *args: None)
    monkeypatch.setattr(host, "_browser_inspect_record", lambda cid: records[cid])
    monkeypatch.setattr(host, "_browser_effective_seccomp_options", lambda *args: None)
    monkeypatch.setattr(
        host, "_browser_worker_probe", lambda _: pytest.fail("cleanup executed worker probe")
    )
    monkeypatch.setattr(
        host, "_cgroup_limits", lambda _: pytest.fail("cleanup executed controller probe")
    )
    network_checks = []
    monkeypatch.setattr(host, "_validate_boca_network", lambda *args: network_checks.append(args))
    for name in (
        "_browser_validate_ipc_volume",
        "_validate_owner_volume",
        "_validate_key_volume",
        "_validate_data_volume",
    ):
        monkeypatch.setattr(host, name, lambda *args: None)
    monkeypatch.setattr(host, "_storage_snapshot", safe_storage)
    volumes = {host.OWNER_VOLUME, host.KEY_VOLUME, host.DATA_VOLUME, host.BROWSER_IPC_VOLUME}
    monkeypatch.setattr(
        host, "_names", lambda kind, *_: volumes if kind == "volume" else {host.BROWSER_BRIDGE}
    )
    monkeypatch.setattr(host, "_browser_docker_ids", lambda: set(records))
    commands = []

    def run(*args, **kwargs):
        commands.append(args)
        if args[:3] == ("docker", "image", "inspect"):
            return IMAGE_ID if args[-1] == IMAGE else "sha256:" + "4" * 64
        if args[:3] == ("docker", "volume", "ls"):
            return "\n".join(volumes)
        if args[:3] == ("docker", "network", "ls"):
            return "\n".join({"bridge", "host", "none", host.BROWSER_BRIDGE})
        if args[:3] == ("docker", "ps", "-a"):
            if args[-1] == "name=^/boca-socios-controller-1$":
                return CONTROLLER_ID
            if args[-1] == "name=^/boca-socios-browser-worker-1$":
                return WORKER_ID
            return "\n".join(records)
        pytest.fail(f"cleanup attempted noninspection operation {args}")

    monkeypatch.setattr(host, "_run", run)
    proof = host._browser_installed(
        *COORDS, running=True, allow_service_failed=True, require_capacity=False
    )
    assert (proof.controller, proof.worker) == (CONTROLLER_ID, WORKER_ID)
    assert network_checks == [(CONTROLLER_ID if controller_running else "", "1" * 64)]
    assert all(command[1] not in {"start", "stop", "rm", "run"} for command in commands)
    if controller_running and worker_running:
        with pytest.raises(host.PreflightError, match="health"):
            host._browser_installed(*COORDS, running=True)
    controller["HostConfig"]["Privileged"] = True
    with pytest.raises(host.PreflightError, match="identity"):
        host._browser_installed(
            *COORDS, running=True, allow_service_failed=True, require_capacity=False
        )


@pytest.mark.parametrize("capabilities", [["SYS_CHROOT"], ["CAP_SYS_CHROOT"]])
def test_worker_accepts_only_exact_reviewed_capability_with_docker_canonical_prefix(
    monkeypatch: pytest.MonkeyPatch,
    capabilities: list[str],
) -> None:
    record = worker_record()
    record["HostConfig"]["CapAdd"] = capabilities
    monkeypatch.setattr(host, "_browser_inspect_record", lambda _: record)
    monkeypatch.setattr(host, "_browser_effective_seccomp_options", lambda *args: None)
    observed = []
    monkeypatch.setattr(host, "_browser_worker_probe", lambda cid: observed.append(cid))
    host._browser_worker_postflight(WORKER_ID, BROWSER_IMAGE, SOURCE, ATTEMPT, SECCOMP_SHA)
    assert observed == [WORKER_ID]


@pytest.mark.parametrize(
    "capabilities",
    [
        [],
        None,
        "CAP_SYS_CHROOT",
        ["cap_sys_chroot"],
        ["CAP_CAP_SYS_CHROOT"],
        ["CAP_SYS_ADMIN"],
        ["CAP_SYS_CHROOT", "CAP_SYS_ADMIN"],
        ["CAP_SYS_CHROOT", "CAP_SYS_CHROOT"],
        ["SYS_CHROOT", "CAP_SYS_CHROOT"],
    ],
)
def test_worker_capability_prefix_never_accepts_extra_duplicate_or_unreviewed_privileges(
    monkeypatch: pytest.MonkeyPatch,
    capabilities: object,
) -> None:
    record = worker_record()
    record["HostConfig"]["CapAdd"] = capabilities
    monkeypatch.setattr(host, "_browser_inspect_record", lambda _: record)
    monkeypatch.setattr(host, "_browser_effective_seccomp_options", lambda *args: None)
    monkeypatch.setattr(
        host,
        "_browser_worker_probe",
        lambda _: pytest.fail("unreviewed capability reached kernel probe"),
    )
    with pytest.raises(host.PreflightError, match="isolation"):
        host._browser_worker_postflight(WORKER_ID, BROWSER_IMAGE, SOURCE, ATTEMPT, SECCOMP_SHA)
