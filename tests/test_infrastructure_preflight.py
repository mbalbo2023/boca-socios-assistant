"""The pre-release probe observes capacity without installing an application."""

from __future__ import annotations

import json
import os
import runpy
import subprocess
import sys
import textwrap
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from unittest.mock import Mock

import pytest

from boca_socios import host_first_deploy as host
from boca_socios import host_rootless_setup as rootless
from boca_socios.deploy_inputs import DeployInputError, validate_deploy_inputs
from test_host_first_deploy import safe_storage

SHA = "a" * 40
BUDGET = "1.5cpu-1024m-192pids"
FULL_BUDGET = "1.75cpu-1152m-224pids"
HOME = Path("/home/boca-deploy")
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("budget", [BUDGET, FULL_BUDGET])
def test_preflight_inputs_need_no_release_or_image(budget: str) -> None:
    validate_deploy_inputs("", SHA, "controller", budget, "", infrastructure_preflight=True)


@pytest.mark.parametrize(
    ("image", "budget", "release", "browser", "sender"),
    [
        ("ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64, BUDGET, "", False, False),
        ("", BUDGET, "123", False, False),
        ("", "0.5cpu-256m-64pids", "", False, False),
        ("", BUDGET, "", True, False),
        ("", FULL_BUDGET, "", True, True),
    ],
)
def test_preflight_cannot_disguise_install_coordinates(
    image: str, budget: str, release: str, browser: bool, sender: bool
) -> None:
    with pytest.raises(DeployInputError):
        validate_deploy_inputs(
            image,
            SHA,
            "controller",
            budget,
            release,
            infrastructure_preflight=True,
            browser_ipc_v2=browser,
            telegram_runtime=sender,
        )


def test_inactive_preflight_checks_offline_containers_before_start(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    events: list[str] = []
    monkeypatch.setattr(rootless, "_existing_daemon_boundary", lambda *_a, **_k: (HOME, "inactive"))
    monkeypatch.setattr(rootless, "_require_stopped_runtime", lambda: events.append("runtime"))
    monkeypatch.setattr(rootless, "_preflight_effective_unit", lambda _h: events.append("unit"))
    monkeypatch.setattr(rootless, "_preflight_empty_containers", lambda _h: events.append("empty"))
    monkeypatch.setattr(rootless, "_start_stopped_daemon", lambda _s, **_k: events.append("start"))
    monkeypatch.setattr(rootless, "_verified_containers", lambda _h, **_k: ([], []))
    rootless.infrastructure_start(SHA)
    assert events == ["unit", "runtime", "empty", "start"]
    assert "state=STARTED" in capsys.readouterr().out


@pytest.mark.parametrize("state", ["active", "failed"])
def test_preflight_never_adopts_an_initially_active_or_failed_daemon(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    monkeypatch.setattr(rootless, "_existing_daemon_boundary", lambda *_a, **_k: (HOME, state))
    start = Mock()
    monkeypatch.setattr(rootless, "_start_stopped_daemon", start)
    with pytest.raises(rootless.SetupError):
        rootless.infrastructure_start(SHA)
    start.assert_not_called()


def test_offline_container_entry_blocks_daemon_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ("b" * 64)).mkdir()
    monkeypatch.setattr(rootless, "_directory", lambda *_a, **_k: os.open(tmp_path, os.O_RDONLY))
    with pytest.raises(rootless.SetupError, match="existing_container"):
        rootless._preflight_empty_containers(HOME)
    assert len(list(tmp_path.iterdir())) == 1


def test_private_fifo_is_rejected_without_blocking(tmp_path: Path) -> None:
    path = tmp_path / "daemon.json"
    os.mkfifo(path, 0o600)
    code = (
        "import os,sys; from pathlib import Path; "
        "from boca_socios import host_rootless_setup as h; "
        "h._directory=lambda *a,**k:os.open(sys.argv[1],os.O_RDONLY); "
        "h._read_private(Path(sys.argv[1]),('daemon.json',),'expected')"
    )
    try:
        result = subprocess.run(  # noqa: S603 - fixed local FIFO regression, no host or Docker
            [sys.executable, "-c", code, str(tmp_path)], capture_output=True, timeout=2, check=False
        )
    except subprocess.TimeoutExpired:
        pytest.fail("private FIFO blocked before the metadata check")
    assert result.returncode != 0
    assert b"reviewed_service_configuration_unsafe" in result.stderr


def _effective_unit(**changes: str) -> str:
    fields = {
        "LoadState": "loaded",
        "NeedDaemonReload": "no",
        "Type": "exec",
        "Restart": "no",
        "Delegate": "yes",
        "KillMode": "mixed",
        "ExecCondition": "",
        "ExecStartPre": "",
        "ExecStartPost": "",
        "ExecStop": "",
        "ExecStopPost": "",
        "ExecStart": "{ path=/usr/bin/env ; argv[]=/usr/bin/env -i HOME=/home/boca-deploy "
        "USER=boca-deploy LOGNAME=boca-deploy PATH=/usr/bin:/bin:/usr/sbin:/sbin "
        "XDG_RUNTIME_DIR=/run/user/10001 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/10001/bus "
        "/usr/bin/dockerd-rootless.sh --config-file=/home/boca-deploy/.config/docker/daemon.json "
        "; ignore_errors=no ; start_time=[Mon 2026-11-02 10:00:00 UTC] ; "
        "stop_time=[Mon 2026-11-02 10:01:00 UTC] ; pid=123 ; code=exited ; status=0 }",
    }
    fields.update(changes)
    return "\n".join(f"{key}={value}" for key, value in fields.items())


def test_effective_unit_accepts_previous_runtime_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rootless, "_command", lambda *_a, **_k: _effective_unit())
    rootless._preflight_effective_unit(HOME)


@pytest.mark.parametrize(
    "changes",
    [
        {"NeedDaemonReload": "yes"},
        {"ExecCondition": "/bin/other"},
        {"ExecStartPre": "/bin/other"},
        {"ExecStopPost": "/bin/other"},
        {"Restart": "always"},
        {"Delegate": "no"},
        {"ExecStart": "{ path=/bin/other ; argv[]=/bin/other ; ignore_errors=no ; pid=0 }"},
    ],
)
def test_effective_unit_rejects_loaded_configuration_drift(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, str]
) -> None:
    monkeypatch.setattr(rootless, "_command", lambda *_a, **_k: _effective_unit(**changes))
    with pytest.raises(rootless.SetupError, match="effective"):
        rootless._preflight_effective_unit(HOME)


def test_restore_never_stops_a_container_that_appeared(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rootless, "_existing_daemon_boundary", lambda *_a, **_k: (HOME, "active"))
    monkeypatch.setattr(rootless, "_preflight_effective_unit", lambda _h: None)
    monkeypatch.setattr(rootless, "_preflight_empty_containers", lambda _h: None)
    monkeypatch.setattr(rootless, "_socket", lambda _p: None)
    monkeypatch.setattr(rootless, "_verified_containers", lambda _h, **_k: (["b" * 64], []))
    command = Mock()
    monkeypatch.setattr(rootless, "_command", command)
    with pytest.raises(rootless.SetupError, match="existing_container"):
        rootless.infrastructure_stop(SHA)
    command.assert_not_called()


def test_existing_capacity_policy_is_unchanged() -> None:
    assert host._infrastructure_budget(BUDGET) == (1536, 1.75, 256)
    assert host._infrastructure_budget(FULL_BUDGET) == (1792, 2.0, 288)
    with pytest.raises(host.PreflightError):
        host._infrastructure_budget("0.5cpu-256m-64pids")


def _observe_ready(
    monkeypatch: pytest.MonkeyPatch,
    *,
    memory: int = 2048 * 1024,
    load: float | None = 0.0,
    cpu: float = 2.0,
    storage: host.StorageSnapshot | None = None,
) -> None:
    storage = storage or safe_storage()
    monkeypatch.setattr(host, "_require_dedicated_identity", lambda: 10001)
    monkeypatch.setattr(host, "_validate_docker_boundary", lambda: None)
    monkeypatch.setattr(host, "_browser_engine_version", lambda: "28.5.2")
    monkeypatch.setattr(host.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(host, "_browser_root_entries", lambda _e: None)
    monkeypatch.setattr(host, "_browser_inventory", lambda **_k: None)
    monkeypatch.setattr(host, "_browser_port_free", lambda: None)
    monkeypatch.setattr(
        host,
        "_observe_browser_capacity",
        lambda: (
            memory,
            host.CpuCapacity(2, 2, Fraction(str(cpu)), "configured"),
            load,
            512,
            storage,
        ),
    )
    monkeypatch.setattr(host, "_storage_snapshot", lambda: storage)

    def read_only(*args: str, **_kwargs: object) -> str:
        assert args in {
            ("docker", "compose", "up", "--help"),
            ("docker", "compose", "config", "--help"),
        }
        return "--wait --no-build --no-deps --format"

    monkeypatch.setattr(host, "_run", read_only)


@pytest.mark.parametrize("budget", [BUDGET, FULL_BUDGET])
def test_image_free_phase_needs_no_owner_and_preserves_policy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], budget: str
) -> None:
    _observe_ready(monkeypatch)
    host.phase("infrastructure-preflight", "", SHA, "b" * 64, infrastructure_budget=budget)
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert "daemon_startup_cpu_count=2 effective_cpus=2 cpu_ceiling=2.000000" in lines[0]
    assert "cpu_scope=configured load1=0.000000 load_policy=advisory" in lines[0]
    assert f"budget={budget}" in lines[1]
    assert "result=PASS meaning=configured_reserve_not_benchmark" in lines[1]
    assert "daemon=stopped" not in "\n".join(lines)


@pytest.mark.parametrize(
    "changes",
    [
        {"memory": 1000 * 1024},
        {"cpu": 1.99},
        {"storage": replace(safe_storage(), stage_free_bytes=1024)},
    ],
)
def test_observation_survives_unchanged_policy_failure_without_claiming_performance(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], changes: dict
) -> None:
    _observe_ready(monkeypatch, **changes)
    with pytest.raises(host.PreflightError, match="performance unmeasured"):
        host._infrastructure_preflight(SHA, FULL_BUDGET)
    raw = capsys.readouterr().out
    assert raw.startswith("BOCA_INFRA_OBSERVATION ")
    assert "result=NO_GO meaning=configured_reserve_not_benchmark" in raw


def test_changed_storage_prevents_an_observation_receipt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _observe_ready(monkeypatch)
    monkeypatch.setattr(host, "_storage_snapshot", lambda: replace(safe_storage(), socket_inode=99))
    with pytest.raises(host.PreflightError, match="topology changed"):
        host._infrastructure_preflight(SHA, BUDGET)
    assert not capsys.readouterr().out


def _workflow_step(name: str) -> str:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    return workflow.split("      - name: " + name + "\n", 1)[1].split("      - name:", 1)[0]


def _run_step(
    name: str,
    tmp_path: Path,
    *,
    receipt: str = "",
    code: int = 0,
    budget: str = BUDGET,
    overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    ssh = bindir / "ssh"
    ssh.write_text(
        '#!/bin/sh\ncat >/dev/null\nprintf "%s" "$FIXTURE_RECEIPT"\nexit "$FIXTURE_RC"\n'
    )
    ssh.chmod(0o700)
    (tmp_path / "boca-compose.sha").write_text("b" * 64)
    env = {
        "PATH": f"{bindir}:/usr/bin:/bin",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        "BOCA_SOURCE_SHA": SHA,
        "BOCA_BUDGET": budget,
        "FIXTURE_RECEIPT": receipt,
        "FIXTURE_RC": str(code),
        **(overrides or {}),
    }
    script = textwrap.dedent(_workflow_step(name).split("        run: |\n", 1)[1])
    return subprocess.run(  # noqa: S603 - checked-in workflow with fake SSH
        ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )


@pytest.mark.parametrize("budget", [BUDGET, FULL_BUDGET])
@pytest.mark.parametrize("load", [0.0, 0.3])
def test_actual_observation_stdout_passes_workflow_parser_without_hiding_policy_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    budget: str,
    load: float,
) -> None:
    _observe_ready(monkeypatch, load=load)
    code = 0
    try:
        host._infrastructure_preflight(SHA, budget)
    except host.PreflightError:
        code = 1
    raw = capsys.readouterr().out
    result = _run_step(
        "Observe infrastructure and evaluate unchanged reserve before release",
        tmp_path,
        receipt=raw,
        code=code,
        budget=budget,
    )
    assert (result.returncode == 0) == (code == 0), result.stderr
    assert raw in (tmp_path / "summary").read_text()


@pytest.mark.parametrize(
    "variant", ["empty", "duplicate", "truncated", "oversized", "no_newline", "ssh", "timeout"]
)
def test_workflow_rejects_missing_or_forged_observations(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    variant: str,
) -> None:
    _observe_ready(monkeypatch)
    host._infrastructure_preflight(SHA, BUDGET)
    raw = capsys.readouterr().out
    code = 0
    if variant == "empty":
        raw = ""
    elif variant == "duplicate":
        raw += raw
    elif variant == "truncated":
        raw = raw[:100]
    elif variant == "oversized":
        raw = "x" * 1025
    elif variant == "no_newline":
        raw = raw.rstrip("\n")
    elif variant == "ssh":
        code = 255
    elif variant == "timeout":
        code = 124
    result = _run_step(
        "Observe infrastructure and evaluate unchanged reserve before release",
        tmp_path,
        receipt=raw,
        code=code,
    )
    assert result.returncode != 0


@pytest.mark.parametrize("code", [0, 1, 124, 255])
def test_restore_receipt_must_match_successful_exit(tmp_path: Path, code: int) -> None:
    receipt = f"BOCA_INFRA_DAEMON state=STOPPED source_sha={SHA} containers=absent data=preserved\n"
    result = _run_step(
        "Always restore verified stopped daemon after infrastructure attempt",
        tmp_path,
        receipt=receipt,
        code=code,
    )
    assert (result.returncode == 0) == (code == 0)
    summary = (tmp_path / "summary").read_text()
    assert ("INDETERMINADO" in summary) == (code != 0)
    assert "BOCA_INFRA_PREFLIGHT state=PASS" not in summary


def test_cleanup_covers_cancellation_and_success_waits_for_verified_stop() -> None:
    restore = _workflow_step("Always restore verified stopped daemon after infrastructure attempt")
    assert "if: always()" in restore
    assert "steps.boca_infra_attempt.outputs.started == 'true'" in restore
    assert "failure()" not in restore and "cancelled()" not in restore
    final = _workflow_step("Record pre-release infrastructure result only after verified stop")
    assert "success() && steps.boca_infra_stop.outcome == 'success'" in final
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    names = [
        "Verify inactive prepared daemon before image-free infrastructure preflight",
        "Recheck current main immediately before temporary infrastructure daemon start",
        "Mark only temporary infrastructure daemon attempt",
        "Start only verified empty prepared daemon for infrastructure observation",
        "Observe infrastructure and evaluate unchanged reserve before release",
        "Always restore verified stopped daemon after infrastructure attempt",
        "Record pre-release infrastructure result only after verified stop",
    ]
    assert [workflow.index(name) for name in names] == sorted(
        workflow.index(name) for name in names
    )


@pytest.mark.parametrize("budget", [BUDGET, FULL_BUDGET])
def test_workflow_initial_gate_accepts_no_image_owner_or_release(
    tmp_path: Path, budget: str
) -> None:
    env = {
        "BOCA_OPERATION": "infrastructure-preflight",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "123",
        "GITHUB_SHA": SHA,
        "BOCA_SERVICE": "controller",
        "BOCA_HOST_READONLY_ENV_READY": "ready",
        "BOCA_DEPLOY_ENV_READY": "ready",
    }
    name = "Require verified protected environment and matching main commit"
    assert _run_step(name, tmp_path, budget=budget, overrides=env).returncode == 0
    for key in ("BOCA_HOST_READONLY_ENV_READY", "BOCA_DEPLOY_ENV_READY"):
        assert _run_step(name, tmp_path, budget=budget, overrides={**env, key: ""}).returncode != 0
    for key in ("BOCA_IMAGE_REF", "BOCA_BROWSER_IMAGE_REF", "BOCA_RELEASE_RUN_ID"):
        assert (
            _run_step(
                name, tmp_path, budget=budget, overrides={**env, key: "unexpected"}
            ).returncode
            != 0
        )


@pytest.mark.parametrize("state", ["inactive", "active", "failed", "starting"])
def test_stop_restores_only_empty_prepared_daemon_after_success_or_failed_start(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    state: str,
) -> None:
    effects: list[tuple] = []
    monkeypatch.setattr(rootless, "_existing_daemon_boundary", lambda *_a, **_k: (HOME, state))
    monkeypatch.setattr(rootless, "_preflight_effective_unit", lambda _h: None)
    monkeypatch.setattr(rootless, "_preflight_empty_containers", lambda _h: None)
    monkeypatch.setattr(rootless, "_require_stopped_runtime", lambda: None)
    monkeypatch.setattr(rootless, "_stop_service_state", lambda _h: "inactive")
    monkeypatch.setattr(rootless, "_entry", lambda *_a: None)
    monkeypatch.setattr(rootless, "_socket", lambda _p: None)
    monkeypatch.setattr(rootless, "_verified_containers", lambda _h, **_k: ([], []))
    monkeypatch.setattr(rootless, "_command", lambda *args, **_k: effects.append(args))
    rootless.infrastructure_stop(SHA)
    assert effects == (
        []
        if state == "inactive"
        else [(HOME, "/usr/bin/systemctl", "--user", "stop", "docker.service")]
    )
    assert "state=STOPPED" in capsys.readouterr().out


def test_stop_cannot_claim_restoration_while_service_remains_running(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(rootless, "_existing_daemon_boundary", lambda *_a, **_k: (HOME, "active"))
    monkeypatch.setattr(rootless, "_preflight_effective_unit", lambda _h: None)
    monkeypatch.setattr(rootless, "_preflight_empty_containers", lambda _h: None)
    monkeypatch.setattr(rootless, "_socket", lambda _p: None)
    monkeypatch.setattr(rootless, "_verified_containers", lambda _h, **_k: ([], []))
    monkeypatch.setattr(rootless, "_command", lambda *_a, **_k: "")
    monkeypatch.setattr(rootless, "_stop_service_state", lambda _h: "active")
    with pytest.raises(rootless.SetupError, match="stop_unverified"):
        rootless.infrastructure_stop(SHA)
    assert not capsys.readouterr().out


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "replacement"])
def test_private_control_file_redirect_or_replacement_is_preserved_and_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kind: str,
) -> None:
    path = tmp_path / "daemon.json"
    other = tmp_path / "other.json"
    other.write_text("expected")
    other.chmod(0o600)
    if kind == "symlink":
        path.symlink_to(other)
    elif kind == "hardlink":
        os.link(other, path)
    else:
        path.write_text("expected")
        path.chmod(0o600)
        original_fstat = os.fstat
        calls = 0

        def changed(fd: int) -> os.stat_result:
            nonlocal calls
            calls += 1
            if calls == 2:
                os.replace(other, path)
            return original_fstat(fd)

        monkeypatch.setattr(rootless.os, "fstat", changed)
    monkeypatch.setattr(rootless, "UID", os.getuid())
    monkeypatch.setattr(rootless, "_directory", lambda *_a, **_k: os.open(tmp_path, os.O_RDONLY))
    with pytest.raises(rootless.SetupError, match="reviewed_service_configuration"):
        rootless._read_private(HOME, ("daemon.json",), "expected")
    assert path.read_text() == "expected"


@pytest.mark.parametrize(
    "field",
    [
        "envelope",
        "beta_owner",
        "owner_envelope",
        "browser_image",
        "browser_attempt_id",
        "expected_bot_id",
        "telegram_attempt_id",
    ],
)
def test_preflight_rejects_private_context_before_host_access(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    observe = Mock()
    monkeypatch.setattr(host, "_infrastructure_preflight", observe)
    with pytest.raises(host.PreflightError):
        host.phase(
            "infrastructure-preflight",
            "",
            SHA,
            "b" * 64,
            infrastructure_budget=BUDGET,
            **{field: "unexpected"},
        )
    observe.assert_not_called()


def test_workflow_telemetry_reuses_each_existing_journey_exactly_once() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    assert workflow.count('pair running "$controller" "$worker" startup') == 1
    assert workflow.count('pair running "$controller" "$worker" restart') == 1
    assert workflow.count('pair stopped "$controller" "$worker"') == 1
    assert "UnixSyntheticBrowser(timeout_seconds=25).simulate_general_reservation()" not in workflow


@pytest.mark.parametrize(
    "runtime",
    [
        "start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0",
        "start_time=[Mon 2026-11-02 10:00:00 UTC] ; stop_time=[n/a] ; pid=123 ; code=(null) ; status=0/0",
        "start_time=[Mon 2026-11-02 10:00:00 UTC] ; stop_time=[Mon 2026-11-02 10:01:00 UTC] ; pid=123 ; code=killed ; status=15/TERM",
    ],
)
def test_effective_unit_accepts_official_nonexecution_and_runtime_metadata(
    monkeypatch: pytest.MonkeyPatch,
    runtime: str,
) -> None:
    raw = _effective_unit().split(" ; start_time=", 1)[0] + " ; " + runtime + " }"
    monkeypatch.setattr(rootless, "_command", lambda *_a, **_k: raw)
    rootless._preflight_effective_unit(HOME)


@pytest.mark.parametrize(
    "change", ["argv", "ignore_errors", "extra_command", "duplicate", "missing"]
)
def test_effective_unit_rejects_adversarial_execution_metadata(
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    raw = _effective_unit()
    if change == "argv":
        raw = raw.replace("--config-file=/home", "--config-file=/other")
    elif change == "ignore_errors":
        raw = raw.replace("ignore_errors=no", "ignore_errors=yes")
    elif change == "extra_command":
        raw += " { path=/bin/other ; argv[]=/bin/other ; ignore_errors=no ; pid=0 }"
    elif change == "duplicate":
        raw += "\nNeedDaemonReload=no"
    else:
        raw = raw.replace("ExecCondition=\n", "")
    monkeypatch.setattr(rootless, "_command", lambda *_a, **_k: raw)
    with pytest.raises(rootless.SetupError, match="effective"):
        rootless._preflight_effective_unit(HOME)


@pytest.mark.parametrize("budget", [BUDGET, FULL_BUDGET])
def test_infrastructure_cli_opt_in_does_not_enable_release_mode(
    monkeypatch: pytest.MonkeyPatch,
    budget: str,
) -> None:
    script = ROOT / "scripts/check_deploy_inputs.py"
    monkeypatch.setattr(
        sys, "argv", [str(script), "--infrastructure-preflight", "", SHA, "controller", budget, ""]
    )
    assert runpy.run_path(str(script))["main"]() == 0
    monkeypatch.setattr(sys, "argv", [str(script), "", SHA, "controller", budget, ""])
    assert runpy.run_path(str(script))["main"]() == 1


@pytest.mark.parametrize("count", [0, 1])
def test_empty_only_inventory_never_reads_container_details_or_browser_marker(
    monkeypatch: pytest.MonkeyPatch,
    count: int,
) -> None:
    calls: list[str] = []
    info = json.dumps(
        {
            "SecurityOptions": ["name=rootless"],
            "DockerRootDir": str(HOME.joinpath(*rootless.DATA)),
            "CgroupVersion": "2",
            "CgroupDriver": "systemd",
            "Driver": "overlay2",
            "Containers": count,
        }
    )

    def command(_home: Path, _binary: str, _endpoint: str, action: str, *_args: str) -> str:
        calls.append(action)
        if action == "info":
            return info
        if action == "ps":
            return "b" * 64 if count else ""
        pytest.fail("preflight inspected a container or image")

    monkeypatch.setattr(rootless, "_command", command)
    monkeypatch.setattr(rootless.Path, "lstat", lambda *_a: pytest.fail("browser marker read"))
    if count:
        with pytest.raises(rootless.SetupError, match="existing_container"):
            rootless._verified_containers(HOME, require_empty=True)
    else:
        assert rootless._verified_containers(HOME, require_empty=True) == ([], [])
    assert calls == ["info", "ps"]
