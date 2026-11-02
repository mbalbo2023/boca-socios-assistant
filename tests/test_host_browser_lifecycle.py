"""#250: the installed dual-service topology must have a guarded lifecycle."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from boca_socios import host_rootless_setup as host
from test_host_stop_test import (
    _telegram_image,
    _telegram_test_inspect,
    _telegram_test_network,
)

ROOT = Path(__file__).resolve().parents[1]
HOME = Path("/home/boca-deploy")
SOURCE = "a" * 40
ATTEMPT = "123456"
CONTROLLER = "b" * 64
WORKER = "c" * 64
IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64
BROWSER = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "e" * 64
PROFILE = {"defaultAction": "SCMP_ACT_ERRNO", "syscalls": []}


def context() -> tuple[dict[str, object], dict[str, object]]:
    return {
        "version": "browser-ipc-new-only-v2",
        "attempt_id": ATTEMPT,
        "source_sha": SOURCE,
        "controller_digest": IMAGE,
        "browser_digest": BROWSER,
        "beta_compose_sha": "f" * 64,
        "overlay_compose_sha": "1" * 64,
        "seccomp_sha": hashlib.sha256(json.dumps(PROFILE).encode()).hexdigest(),
        "controller_image_absent": True,
        "browser_image_absent": True,
        "bridge_absent": True,
        "ipc_volume_absent": True,
    }, PROFILE


def record(*, worker: bool, running: bool = True) -> dict[str, object]:
    service = "browser-worker" if worker else "controller"
    image = BROWSER if worker else IMAGE
    mounts = [("boca-socios_boca_browser_ipc", "/run/boca-browser-ipc", worker)]
    if not worker:
        mounts += [
            ("boca-socios_boca_data", "/data", True),
            ("boca-socios_boca_key", "/run/secrets", False),
            ("boca-socios_boca_owner", "/run/owner", False),
        ]
    return {
        "Id": WORKER if worker else CONTROLLER,
        "Image": "sha256:" + ("2" if worker else "3") * 64,
        "Name": f"/boca-socios-{service}-1",
        "Config": {
            "Image": image,
            "User": "10002:10002" if worker else "10001:10001",
            "Cmd": ["python", "-m", "boca_socios.browser.ipc_worker"]
            if worker
            else ["python", "-m", "boca_socios.runtime", "serve-beta"],
            "Entrypoint": None,
            "Labels": {
                "com.docker.compose.project": "boca-socios",
                "com.docker.compose.service": service,
                "com.docker.compose.container-number": "1",
                "org.opencontainers.image.revision": SOURCE,
                "boca.socios.browser-ipc-attempt": ATTEMPT,
            },
            "Env": [
                "BOCA_ENVIRONMENT=staging",
                "BOCA_RUNTIME_MODE=simulation",
                "BOCA_ENGINE_MODE=off",
            ]
            + (["BOCA_OBSERVER_STOP=1"] if worker else ["BOCA_BROWSER_BACKEND=ipc"]),
        },
        "HostConfig": {
            "ReadonlyRootfs": True,
            "Privileged": False,
            "PublishAllPorts": False,
            "RestartPolicy": {"Name": "no"},
            "Init": True,
            "NetworkMode": "none" if worker else "boca-socios_boca_private",
            "PidMode": "",
            "IpcMode": "private",
            "CgroupnsMode": "private",
            "UsernsMode": "",
            "UTSMode": "",
            "Devices": [],
            "NanoCpus": 1_000_000_000 if worker else 500_000_000,
            "Memory": 768 * 1024**2 if worker else 256 * 1024**2,
            "PidsLimit": 128 if worker else 64,
            "CapDrop": ["ALL"],
            "CapAdd": ["SYS_CHROOT"] if worker else [],
            "SecurityOpt": ["no-new-privileges:true"]
            + (["seccomp=" + json.dumps(PROFILE)] if worker else []),
            "PortBindings": {}
            if worker
            else {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]},
            "ShmSize": 64 * 1024**2,
            "Tmpfs": {
                "/tmp": "rw,noexec,nosuid,size=32m",  # noqa: S108 - container tmpfs
                "/home/boca-browser": "rw,noexec,nosuid,size=16m",
            }  # noqa: S108 - private container tmpfs
            if worker
            else {"/tmp": "rw,noexec,nosuid,size=16m"},  # noqa: S108 - private container tmpfs
        },
        "Mounts": [
            {"Type": "volume", "Name": name, "Destination": dest, "RW": rw, "Driver": "local"}
            for name, dest, rw in mounts
        ],
        "NetworkSettings": {
            "Ports": {} if worker else {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]},
            "Networks": {"none" if worker else "boca-socios_boca_private": {}},
        },
        "State": {"Running": running},
    }


def fake_command(records: list[dict[str, object]], calls: list[tuple[str, ...]]):
    def invoke(home: Path, *argv: str, **kwargs: object) -> str:
        calls.append(argv)
        if argv[2] == "info":
            return json.dumps(
                {
                    "SecurityOptions": ["name=rootless"],
                    "DockerRootDir": str(HOME.joinpath(*host.DATA)),
                    "CgroupVersion": "2",
                    "CgroupDriver": "systemd",
                    "Driver": "overlay2",
                    "Containers": len(records),
                }
            )
        if argv[2] == "ps":
            return "\n".join(str(item["Id"]) for item in records)
        if argv[2] == "image":
            item = next(item for item in records if item["Image"] == argv[-1])
            return json.dumps(
                {
                    "Id": item["Image"],
                    "RepoDigests": [item["Config"]["Image"]],
                    "Config": {"Labels": {"org.opencontainers.image.revision": SOURCE}},
                }
            )
        item = next(item for item in records if item["Id"] == argv[-1])
        if argv[2] == "stop":
            item["State"]["Running"] = False
            return str(item["Id"])
        assert argv[2] == "inspect"
        return json.dumps(item)

    return invoke


def test_guarded_stop_accepts_exact_installed_controller_and_browser_worker() -> None:
    records = [record(worker=False), record(worker=True)]
    calls: list[tuple[str, ...]] = []
    with (
        patch.object(host, "_browser_stop_context", return_value=context(), create=True),
        patch.object(host, "_command", side_effect=fake_command(records, calls)),
    ):
        assert host._stop_test_containers(HOME) == 2
    assert [argv[-1] for argv in calls if argv[2] == "stop"] == [CONTROLLER, WORKER]


@pytest.mark.parametrize(
    "capabilities,allowed",
    [
        (["SYS_CHROOT"], True),
        (["CAP_SYS_CHROOT"], True),  # Real Compose inspect in run 41485137010.
        (["SYS_CHROOT", "CAP_SYS_CHROOT"], False),
        (["CAP_SYS_CHROOT", "CAP_SYS_CHROOT"], False),
        (["CAP_SYS_CHROOT", "CAP_SYS_ADMIN"], False),
        (["CAP_SYS_ADMIN"], False),
        (["cap_sys_chroot"], False),
        ([], False),
        ("CAP_SYS_CHROOT", False),
    ],
)
def test_observed_compose_capability_keeps_exact_single_exception(
    capabilities: object, allowed: bool
) -> None:
    records = [record(worker=False), record(worker=True)]
    records[1]["HostConfig"]["CapAdd"] = capabilities
    calls: list[tuple[str, ...]] = []
    with (
        patch.object(host, "_browser_stop_context", return_value=context()),
        patch.object(host, "_command", side_effect=fake_command(records, calls)),
    ):
        if allowed:
            assert host._stop_test_containers(HOME) == 2
        else:
            with pytest.raises(host.SetupError, match="unknown_container_preserved_no_stop"):
                host._stop_test_containers(HOME)
    assert len([argv for argv in calls if argv[2] == "stop"]) == (2 if allowed else 0)


@pytest.mark.parametrize(
    "scope,field,value",
    [
        ("HostConfig", "NetworkMode", "host"),
        ("HostConfig", "CapAdd", ["SYS_ADMIN"]),
        ("HostConfig", "Memory", 2 * 1024**3),
        ("HostConfig", "SecurityOpt", ["seccomp=unconfined"]),
        ("HostConfig", "PidMode", "host"),
        ("Config", "User", "0:0"),
        ("Config", "Cmd", ["sh", "-c", "unknown"]),
        ("Config", "Image", IMAGE),
    ],
)
def test_changed_browser_identity_blocks_all_stops(scope: str, field: str, value: object) -> None:
    records = [record(worker=False), record(worker=True)]
    records[1][scope][field] = value
    calls: list[tuple[str, ...]] = []
    with (
        patch.object(host, "_browser_stop_context", return_value=context(), create=True),
        patch.object(host, "_command", side_effect=fake_command(records, calls)),
    ):
        with pytest.raises(host.SetupError, match="unknown_container_preserved_no_stop"):
            host._stop_test_containers(HOME)
    assert all(argv[2] != "stop" for argv in calls)


def test_foreign_browser_mount_or_attempt_never_stops_any_container() -> None:
    for mutate in ("mount", "attempt", "source"):
        records = [record(worker=False), record(worker=True)]
        if mutate == "mount":
            records[1]["Mounts"][0]["Name"] = "foreign_volume"
        else:
            key = (
                "boca.socios.browser-ipc-attempt"
                if mutate == "attempt"
                else "org.opencontainers.image.revision"
            )
            records[1]["Config"]["Labels"][key] = "9" * 40
        calls: list[tuple[str, ...]] = []
        with (
            patch.object(host, "_browser_stop_context", return_value=context(), create=True),
            patch.object(host, "_command", side_effect=fake_command(records, calls)),
        ):
            with pytest.raises(host.SetupError, match="unknown_container_preserved_no_stop"):
                host._stop_test_containers(HOME)
        assert all(argv[2] != "stop" for argv in calls)


def test_controller_cannot_fall_back_to_legacy_when_browser_worker_exists() -> None:
    records = [record(worker=False), record(worker=True)]
    del records[0]["Config"]["Labels"]["boca.socios.browser-ipc-attempt"]
    records[0]["Config"]["Image"] = "unrelated-image:latest"
    records[0]["Config"]["User"] = "0:0"
    records[0]["Mounts"] = [{"Type": "bind", "Source": "/foreign"}]
    calls: list[tuple[str, ...]] = []
    with (
        patch.object(host, "_browser_stop_context", return_value=context()),
        patch.object(host, "_command", side_effect=fake_command(records, calls)),
    ):
        with pytest.raises(host.SetupError, match="unknown_container_preserved_no_stop"):
            host._stop_test_containers(HOME)
    assert all(argv[2] != "stop" for argv in calls)


def test_pinned_telegram_sender_is_recognized_only_with_fixed_isolation() -> None:
    candidate = _telegram_test_inspect(WORKER)
    candidate["Name"] = "/boca-socios-telegram-1"
    candidate["Config"]["Labels"]["com.docker.compose.service"] = "telegram"
    candidate["Config"]["Labels"]["boca.socios.telegram-runtime-attempt"] = "987654321"
    candidate["Config"]["Labels"]["boca.socios.browser-ipc-attempt"] = ATTEMPT
    candidate["Config"]["Cmd"] = [
        "python",
        "-m",
        "boca_socios.notify.telegram_worker",
        "serve",
        SOURCE,
        "12345",
        "e" * 64,
    ]
    candidate["Config"]["Env"].append("BOCA_DB_PATH=/data/boca.sqlite3")
    candidate["HostConfig"].update(
        Init=True,
        RestartPolicy={"Name": "no", "MaximumRetryCount": 0},
        IpcMode="private",
        CgroupnsMode="private",
        PidMode="",
        UsernsMode="",
        UTSMode="",
        Devices=[],
        SecurityOpt=["no-new-privileges:true"],
    )
    network = json.loads(_telegram_test_network(WORKER))
    network["Labels"].update(
        {
            "boca.socios.telegram-runtime-attempt": "987654321",
            "boca.socios.browser-ipc-attempt": ATTEMPT,
        }
    )
    with patch.object(
        host,
        "_command",
        side_effect=[json.dumps(network), json.dumps(_telegram_image())],
    ):
        assert host._verified_telegram_image(HOME, "endpoint", candidate, candidate["Config"])
    candidate["HostConfig"]["CapAdd"] = ["SYS_ADMIN"]
    with patch.object(host, "_command") as command:
        assert not host._verified_telegram_image(HOME, "endpoint", candidate, candidate["Config"])
    command.assert_not_called()


def test_browser_install_starts_prepared_daemon_before_preflight() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    preflight = workflow.index(
        "      - name: Read-only owner and new-only browser IPC host preflight"
    )
    steps = workflow[workflow.index("\n  deploy:\n") : preflight].split("      - name: ")
    assert any(
        "start-existing" in step and "beta-browser-install" in step.split("        run:", 1)[0]
        for step in steps
    )


def test_browser_main_recheck_precedes_daemon_marker_and_start() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    names = [
        "Recheck current main immediately before browser daemon start",
        "Mark protected browser daemon start attempt",
        "Start prepared Boca daemon before browser installation or explicit resume",
        "Read-only owner and new-only browser IPC host preflight",
    ]
    assert [workflow.index(name) for name in names] == sorted(
        workflow.index(name) for name in names
    )
    step = workflow.split("      - name: " + names[0] + "\n", 1)[1].split("      - name:", 1)[0]
    assert "python scripts/check_main_ref.py" in step
    assert "continue-on-error" not in step


@pytest.mark.parametrize(
    "operation",
    [
        "beta-browser-start",
        "beta-browser-restart",
        "beta-browser-status",
        "beta-browser-acceptance",
        "beta-browser-telegram-start",
        "beta-browser-telegram-recover",
    ],
)
def test_browser_lifecycle_gate_requires_all_protected_coordinates(operation: str) -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    step = workflow.split(
        "      - name: Require verified protected environment and matching main commit\n", 1
    )[1].split("      - name:", 1)[0]
    script = textwrap.dedent(step.split("        run: |\n", 1)[1])
    env = {
        "PATH": "/usr/bin:/bin",
        "BOCA_OPERATION": operation,
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "123456789",
        "GITHUB_SHA": SOURCE,
        "BOCA_SOURCE_SHA": SOURCE,
        "BOCA_SERVICE": "controller",
        "BOCA_BUDGET": "1.75cpu-1152m-224pids",
        "BOCA_IMAGE_REF": IMAGE,
        "BOCA_BROWSER_IMAGE_REF": BROWSER,
        "BOCA_RELEASE_RUN_ID": "123",
        "BOCA_DEPLOY_ENV_READY": "ready",
        "BOCA_BETA_ENV_READY": "ready",
        "BOCA_BROWSER_ENV_READY": "ready",
        "BOCA_TELEGRAM_ENV_READY": "ready",
        "BOCA_TELEGRAM_OWNER_READY": "ready",
        "BOCA_TELEGRAM_EXPECTED_BOT_ID": "123",
        "BOCA_TELEGRAM_EXPECTED_CHAT_HMAC": "a" * 64,
        "BOCA_BETA_PANEL_ORIGIN": "http://localhost:8443",
        "BOCA_BETA_OWNER_SUBJECT": "owner",
        "BOCA_FAILED_TELEGRAM_RUN_ID": "789012"
        if operation == "beta-browser-telegram-recover"
        else "",
    }
    variants = [({}, True)] + [
        ({key: ""}, False)
        for key in (
            "BOCA_DEPLOY_ENV_READY",
            "BOCA_BETA_ENV_READY",
            "BOCA_BROWSER_ENV_READY",
            "BOCA_BROWSER_IMAGE_REF",
            "BOCA_RELEASE_RUN_ID",
        )
    ]
    variants += [
        ({"GITHUB_RUN_ATTEMPT": "2"}, False),
        ({"BOCA_SOURCE_SHA": "f" * 40}, False),
        ({"BOCA_BUDGET": "0.5cpu-256m-64pids"}, False),
        ({"BOCA_BUDGET": "1.5cpu-1024m-192pids"}, False),
    ]
    if operation in {"beta-browser-telegram-start", "beta-browser-telegram-recover"}:
        variants += [
            ({key: ""}, False)
            for key in (
                "BOCA_TELEGRAM_OWNER_READY",
                "BOCA_TELEGRAM_ENV_READY",
                "BOCA_TELEGRAM_EXPECTED_CHAT_HMAC",
                "BOCA_TELEGRAM_EXPECTED_BOT_ID",
            )
        ]
    if operation == "beta-browser-telegram-recover":
        variants += [
            ({"BOCA_FAILED_TELEGRAM_RUN_ID": value}, False)
            for value in ("", "0", "001", "123456789", "9" * 21, "../foreign")
        ]
    else:
        variants.append(({"BOCA_FAILED_TELEGRAM_RUN_ID": "789012"}, False))
    for changed, allowed in variants:
        result = subprocess.run(  # noqa: S603 - actual local builtin-only gate, no provider
            ["/usr/bin/bash", "-e", "-o", "pipefail"],
            input=script,
            env={**env, **changed},
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        assert (result.returncode == 0) is allowed, changed


def test_private_browser_control_reader_rejects_fifo_symlink_and_hardlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host, "UID", os.getuid())
    monkeypatch.setattr(host, "BROWSER_STAGE", tmp_path)
    monkeypatch.setattr(
        host, "_directory", lambda *args, **kwargs: os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    )
    path = tmp_path / "browser-ipc-attempt.json"
    path.write_bytes(b"{}")
    path.chmod(0o600)
    assert host._browser_control_file(path.name, 1024) == b"{}"
    os.link(path, tmp_path / "second-link")
    with pytest.raises(host.SetupError, match="unsafe"):
        host._browser_control_file(path.name, 1024)
    path.unlink()
    path.symlink_to(tmp_path / "second-link")
    with pytest.raises(host.SetupError, match="unavailable"):
        host._browser_control_file(path.name, 1024)
    path.unlink()
    os.mkfifo(path, 0o600)
    with pytest.raises(host.SetupError, match="unsafe"):
        host._browser_control_file(path.name, 1024)


def test_private_browser_control_reader_rejects_replaced_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(host, "UID", os.getuid())
    monkeypatch.setattr(host, "BROWSER_STAGE", tmp_path)
    monkeypatch.setattr(
        host, "_directory", lambda *args, **kwargs: os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    )
    path = tmp_path / "browser-ipc-attempt.json"
    path.write_bytes(b"{}")
    path.chmod(0o600)
    real_read = os.read
    replaced = False

    def replacing_read(fd: int, length: int) -> bytes:
        nonlocal replaced
        raw = real_read(fd, length)
        if not replaced:
            replaced = True
            path.rename(tmp_path / "old")
            path.write_bytes(b"{}")
            path.chmod(0o600)
        return raw

    monkeypatch.setattr(host.os, "read", replacing_read)
    with pytest.raises(host.SetupError, match="changed"):
        host._browser_control_file(path.name, 1024)


@pytest.mark.parametrize("ports", [None, {}, {"8443/tcp": None}])
def test_stopped_controller_ports_do_not_block_verified_resume(ports: object) -> None:
    candidate = record(worker=False, running=False)
    candidate["NetworkSettings"]["Ports"] = ports
    calls: list[tuple[str, ...]] = []
    with patch.object(host, "_command", side_effect=fake_command([candidate], calls)):
        assert host._verified_browser_ipc_image(HOME, "endpoint", candidate, context())
    candidate["State"]["Running"] = True
    with patch.object(host, "_command") as command:
        assert not host._verified_browser_ipc_image(HOME, "endpoint", candidate, context())
    command.assert_not_called()


def test_stop_context_binds_exact_marker_and_all_three_reviewed_files() -> None:
    marker, profile = context()
    files = {
        "compose.beta.yaml": b"base",
        "compose.beta.browser.yaml": b"overlay",
        "seccomp_profile.json": json.dumps(profile).encode(),
    }
    for key, name in (
        ("beta_compose_sha", "compose.beta.yaml"),
        ("overlay_compose_sha", "compose.beta.browser.yaml"),
        ("seccomp_sha", "seccomp_profile.json"),
    ):
        marker[key] = hashlib.sha256(files[name]).hexdigest()
    files["browser-ipc-attempt.json"] = json.dumps(
        marker, sort_keys=True, separators=(",", ":")
    ).encode()
    with patch.object(host, "_browser_control_file", side_effect=lambda name, limit: files[name]):
        assert host._browser_stop_context() == (marker, profile)
        files["compose.beta.browser.yaml"] = b"replaced"
        with pytest.raises(host.SetupError, match="hash_changed"):
            host._browser_stop_context()


def test_sender_cleanup_only_after_absent_proof_and_on_failure_or_cancellation() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    ordered = [
        "Prove Telegram sender and egress absent before any attempt",
        "Recheck main before explicit Telegram sender creation",
        "Mark only new Telegram sender attempt for immediate cleanup",
        "Operate only proven existing browser IPC services",
        "Immediately remove only the failed new Telegram sender and empty egress",
        "Stop proven Boca browser services after acceptance or failed lifecycle",
    ]
    assert [workflow.index("      - name: " + name + "\n") for name in ordered] == sorted(
        workflow.index("      - name: " + name + "\n") for name in ordered
    )
    cleanup = workflow.split("      - name: " + ordered[-2] + "\n", 1)[1].split("      - name:", 1)[
        0
    ]
    assert "always() &&" in cleanup and "(failure() || cancelled())" in cleanup
    assert "steps.boca_browser_telegram_attempt.outputs.started == 'true'" in cleanup
    assert '--telegram-attempt-id "$runtime_attempt"' in cleanup
    assert 'runtime_attempt="$GITHUB_RUN_ID"' in cleanup
    assert 'runtime_attempt="$BOCA_FAILED_TELEGRAM_RUN_ID"' in cleanup
    assert "browser-telegram-cleanup" in cleanup
    assert "NO_GO INDETERMINADO" in cleanup
    assert "180s ssh" in cleanup
    assert "prune" not in cleanup and "volume rm" not in cleanup


def _workflow_receipt_check(
    tmp_path: Path, output: str, *, cleanup: bool = False
) -> subprocess.CompletedProcess[str]:
    from test_host_browser_runtime_lifecycle import RUNTIME_ATTEMPT, SOURCE

    name = (
        "Immediately remove only the failed new Telegram sender and empty egress"
        if cleanup
        else "Operate only proven existing browser IPC services"
    )
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    step = workflow.split("      - name: " + name + "\n", 1)[1].split("      - name:", 1)[0]
    script = textwrap.dedent(step.split("        run: |\n", 1)[1])
    script = script[script.index("receipt=''\n") :]
    receipt_name = "boca-browser-telegram-cleanup" if cleanup else "boca-browser-lifecycle"
    (tmp_path / (receipt_name + ".receipt")).write_text(output)
    return subprocess.run(  # noqa: S603 - actual parser, no SSH or provider commands
        ["/usr/bin/bash", "-e", "-o", "pipefail"],
        input=script,
        env={
            "PATH": "/usr/bin:/bin",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
            "GITHUB_RUN_ID": RUNTIME_ATTEMPT,
            "runtime_attempt": RUNTIME_ATTEMPT,
            "BOCA_SOURCE_SHA": SOURCE,
            "phase": "browser-acceptance",
            "lifecycle_rc": "0",
            "cleanup_rc": "0",
        },
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )


def test_actual_acceptance_stdout_passes_workflow_receipt_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from boca_socios import host_first_deploy as deploy
    from test_host_browser_runtime_lifecycle import COORDS, lifecycle

    lifecycle(monkeypatch)
    deploy._browser_lifecycle("browser-acceptance", *COORDS)
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 2
    assert _workflow_receipt_check(tmp_path, output).returncode == 0
    for changed in (
        output.splitlines()[1] + "\n",
        output + "unexpected diagnostic\n",
        output.replace("state=PASS", "state=NO_GO"),
        output.replace("operation=browser-acceptance", "operation=browser-start"),
        output.replace("source_sha=" + SOURCE, "source_sha=" + "0" * 40),
    ):
        assert _workflow_receipt_check(tmp_path, changed).returncode != 0


def test_actual_sender_cleanup_stdout_passes_workflow_receipt_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from boca_socios import host_first_deploy as deploy
    from test_host_browser_runtime_lifecycle import (
        BOT_ID,
        CHAT_HMAC,
        COORDS,
        RUNTIME_ATTEMPT,
        sender_phase_fixture,
    )

    sender_phase_fixture(monkeypatch, sender=True, network=True)
    deploy._browser_telegram_phase(
        "browser-telegram-cleanup", *COORDS, BOT_ID, CHAT_HMAC, RUNTIME_ATTEMPT
    )
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 2
    assert _workflow_receipt_check(tmp_path, output, cleanup=True).returncode == 0
    for changed in (
        output.splitlines()[1] + "\n",
        output + "unexpected diagnostic\n",
        output.replace("STORAGE attempt=" + RUNTIME_ATTEMPT, "STORAGE attempt=999"),
        output.replace("before_stage_free_bytes=", "before_stage_free_bytes=-"),
        output.replace("source_sha=" + SOURCE, "source_sha=" + "0" * 40),
    ):
        assert _workflow_receipt_check(tmp_path, changed, cleanup=True).returncode != 0


@pytest.mark.parametrize("active", [False, True])
def test_recovery_preflight_has_no_daemon_or_application_effect(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], active: bool
) -> None:
    from test_host_start_existing import _ready

    _ready(monkeypatch)
    monkeypatch.setattr(host, "_verified_enablement", lambda _home: None)
    monkeypatch.setattr(
        host, "_stop_service_state", lambda _home: "active" if active else "inactive"
    )
    with (
        patch.object(host, "_verified_containers", return_value=([], [])) as inventory,
        patch.object(host, "_command") as command,
    ):
        host.inspect_existing(SOURCE)
    assert inventory.call_count == int(active)
    command.assert_not_called()
    assert capsys.readouterr().out == (
        f"BOCA_ROOTLESS_RECOVERY state={'ACTIVE' if active else 'INACTIVE'} source_sha={SOURCE}"
        " config=verified application_start=forbidden\n"
    )


def test_recovery_requires_exact_failed_run_and_never_calls_application_start(
    tmp_path: Path,
) -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    step = workflow.split(
        "      - name: Validate exact failed GitHub run before explicit Telegram recovery\n", 1
    )[1].split("      - name:", 1)[0]
    code = textwrap.dedent(step.split(" <<'PY'\n", 1)[1].rsplit("          PY", 1)[0])
    path = tmp_path / "failed-run.json"
    jobs_path = tmp_path / "failed-jobs.json"
    record = {
        "id": 789012,
        "head_sha": SOURCE,
        "head_branch": "main",
        "event": "workflow_dispatch",
        "path": ".github/workflows/boca-first-deploy.yml",
        "status": "completed",
        "run_attempt": 1,
        "conclusion": "failure",
        "repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
        "head_repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
        "actor": {"login": "mbalbo2023"},
        "triggering_actor": {"login": "mbalbo2023"},
    }
    jobs = {
        "total_count": 1,
        "jobs": [
            {
                "name": "approved-boca-manual-operation",
                "run_id": 789012,
                "head_sha": SOURCE,
                "status": "completed",
                "steps": [
                    {
                        "name": "Mark only new Telegram sender attempt for immediate cleanup",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ],
            }
        ],
    }
    jobs_path.write_text(json.dumps(jobs))
    for changed, allowed in (
        ({}, True),
        ({"conclusion": "cancelled"}, True),
        ({"conclusion": "success"}, False),
        ({"run_attempt": 2}, False),
        ({"id": 999}, False),
        ({"head_sha": "0" * 40}, False),
        ({"head_branch": "feature/foreign"}, False),
        ({"event": "pull_request"}, False),
        ({"status": "in_progress"}, False),
        ({"path": ".github/workflows/other.yml"}, False),
        ({"actor": {"login": "foreign"}}, False),
        ({"head_repository": {"full_name": "foreign/repo"}}, False),
    ):
        path.write_text(json.dumps({**record, **changed}))
        result = subprocess.run(  # noqa: S603 - actual local read-only metadata predicate
            [sys.executable, "-", str(path), "789012", SOURCE, str(jobs_path)],
            input=code,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        assert (result.returncode == 0) is allowed, changed
    path.write_text(json.dumps(record))
    for conclusion in ("failure", "cancelled", "skipped", None):
        jobs["jobs"][0]["steps"][0]["conclusion"] = conclusion
        jobs_path.write_text(json.dumps(jobs))
        result = subprocess.run(  # noqa: S603 - same actual metadata predicate
            [sys.executable, "-", str(path), "789012", SOURCE, str(jobs_path)],
            input=code,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        assert result.returncode != 0
    operation = workflow.split(
        "      - name: Operate only proven existing browser IPC services\n", 1
    )[1].split("      - name:", 1)[0]
    assert "inputs.operation != 'beta-browser-telegram-recover'" in operation
    stop = workflow.split(
        "      - name: Stop proven Boca browser services after acceptance or failed lifecycle\n", 1
    )[1].split("      - name:", 1)[0]
    assert "inputs.operation == 'beta-browser-telegram-recover'" in stop
    assert "steps.boca_browser_telegram_recovery_attempt.outputs.started == 'true'" in stop


def _runtime_smoke_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "boca_lifecycle_runtime_probe", ROOT / "scripts/check_browser_lifecycle_runtime.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_docker_diagnostic_does_not_serialize_private_configuration() -> None:
    module = _runtime_smoke_module()

    candidate = record(worker=True)
    candidate["Config"].update(
        Cmd=["private-command-value"],
        Entrypoint=["private-entrypoint-value"],
        Labels={"private-label": "private-label-value"},
    )
    candidate["Config"]["Env"].append("BOCA_TELEGRAM_TOKEN=private-token-value")
    candidate["Config"]["Env"].append("SECRET=private-environment-value")
    candidate["HostConfig"]["Binds"] = ["private-bind-value"]
    candidate["Mounts"] = [{"Source": "private-mount-value"}]
    candidate["NetworkSettings"]["Networks"]["none"] = {"IPAddress": "private-address-value"}
    summary = module.inspection_summary(candidate, service="browser-worker")
    assert summary["isolation"]["CapAdd"] == ["SYS_CHROOT"]
    assert summary["worker_command_matches"] is False
    assert summary["entrypoint_absent"] is False
    assert "BOCA_TELEGRAM_TOKEN" in summary["boca_environment_keys"]
    assert summary["network_names"] == ["none"]
    assert "private-" not in json.dumps(summary)


@pytest.mark.parametrize(
    "raw",
    [
        '{"pid":0,"uid":10002,"gid":10002,"secret":"private"}',
        '{"pid":true,"uid":10002,"gid":10002}',
        '{"pid":0,"uid":10002}',
        '{"pid":0,"uid":10002,"gid":2147483648}',
        '{"pid":0,"uid":"10002","gid":10002}',
        "[0,10002,10002]",
        '"private"',
        " " * 161,
    ],
)
def test_peer_diagnostic_refuses_unbounded_or_non_numeric_output(raw: str) -> None:
    module = _runtime_smoke_module()
    assert module.peer_receipt('{"pid":0,"uid":10002,"gid":10002}') == {
        "pid": 0,
        "uid": 10002,
        "gid": 10002,
    }
    with pytest.raises(ValueError):
        module.peer_receipt(raw)


@pytest.mark.parametrize(
    "chunks,expire,error",
    [
        ([b"\x00", b"\x18BOCA_SYNTHETIC_V1_NO_GO", b""], False, None),
        ([b"x" * 66, b""], False, None),
        ([b"x" * 67], False, RuntimeError),
        ([b"\x00", b""], True, TimeoutError),
    ],
)
def test_peer_diagnostic_drains_fragmented_stream_with_total_byte_and_time_bounds(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    chunks: list[bytes],
    expire: bool,
    error: type[Exception] | None,
) -> None:
    import socket
    import struct
    import time

    module = _runtime_smoke_module()
    clock = [0.0]
    answers = iter(chunks)
    reads: list[int] = []

    class Endpoint:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def settimeout(self, seconds):
            assert 0 < seconds <= 3

        def connect(self, path):
            assert path == "/run/boca-browser-ipc/synthetic.sock"

        def getsockopt(self, level, option, length):
            assert (level, option, length) == (socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            return struct.pack("3i", 0, 10002, 10002)

        def shutdown(self, direction):
            assert direction == socket.SHUT_WR

        def recv(self, limit):
            reads.append(limit)
            assert 0 < limit <= 67
            if expire:
                clock[0] = 4.0
            return next(answers)

    monkeypatch.setattr(socket, "socket", lambda *args: Endpoint())
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    if error:
        with pytest.raises(error):
            exec(module.PEER_DIAGNOSTIC, {})  # noqa: S102 - exact repository diagnostic
        assert not capsys.readouterr().out
    else:
        exec(module.PEER_DIAGNOSTIC, {})  # noqa: S102 - exact repository diagnostic
        assert module.peer_receipt(capsys.readouterr().out.strip()) == {
            "pid": 0,
            "uid": 10002,
            "gid": 10002,
        }
    assert reads


@pytest.mark.parametrize(
    "reply,error,uid",
    [
        (b"", None, 10003),
        (ConnectionResetError, None, 10003),
        (b"\x00", RuntimeError, 10003),
        (TimeoutError, TimeoutError, 10003),
        (b"", AssertionError, 10001),
    ],
)
def test_foreign_uid_probe_requires_actual_foreign_identity_and_eof_without_sending(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reply: bytes | type[Exception],
    error: type[Exception] | None,
    uid: int,
) -> None:
    import socket
    import time

    module = _runtime_smoke_module()
    connections: list[str] = []

    class Endpoint:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def settimeout(self, seconds):
            assert 0 < seconds <= 3

        def connect(self, path):
            assert path == "/run/boca-browser-ipc/synthetic.sock"
            connections.append(path)

        def recv(self, limit):
            assert limit == 1
            if isinstance(reply, type):
                raise reply
            return reply

        # send/sendall/shutdown are deliberately absent: the probe sends nothing.

    monkeypatch.setattr(os, "geteuid", lambda: uid)
    monkeypatch.setattr(os, "getegid", lambda: uid)
    monkeypatch.setattr(socket, "socket", lambda *args: Endpoint())
    monkeypatch.setattr(time, "monotonic", lambda: 0.0)
    if error:
        with pytest.raises(error):
            exec(module.FOREIGN_UID_PROBE, {})  # noqa: S102 - exact repository negative probe
        assert not capsys.readouterr().out
    else:
        exec(module.FOREIGN_UID_PROBE, {})  # noqa: S102 - exact repository negative probe
        assert capsys.readouterr().out.strip() == module.FOREIGN_UID_RECEIPT
    assert len(connections) == (1 if uid == 10003 else 0)


@pytest.mark.parametrize("field", ["Id", "Image", "RestartCount", "StartedAt", "Running", "Health"])
def test_foreign_uid_probe_requires_services_to_retain_runtime_identity(field: str) -> None:
    import copy

    module = _runtime_smoke_module()
    candidate = record(worker=True)
    candidate["RestartCount"] = 0
    candidate["State"].update(StartedAt="synthetic-start", Health={"Status": "healthy"})
    original = module.runtime_identity(candidate)
    changed = copy.deepcopy(candidate)
    if field in {"Id", "Image", "RestartCount"}:
        changed[field] = "changed"
    elif field == "Health":
        changed["State"]["Health"]["Status"] = "unhealthy"
    else:
        changed["State"][field] = "changed"
    assert module.runtime_identity(changed) != original
