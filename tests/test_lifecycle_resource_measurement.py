"""Resource observations cannot invent absent counters or replace lifecycle gates."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    value = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT))
    try:
        spec.loader.exec_module(value)
    finally:
        sys.path.pop(0)
    return value


def cgroup(root: Path, *, service: str = "controller") -> None:
    limits = {
        "controller": (268435456, 64, 50000),
        "browser-worker": (805306368, 128, 100000),
        "telegram-offline": (134217728, 32, 25000),
    }
    memory, pids, quota = limits[service]
    values = {
        "memory.max": str(memory),
        "pids.max": str(pids),
        "cpu.max": f"{quota} 100000",
        "memory.current": "1000000",
        "memory.peak": "2000000",
        "pids.current": "4",
        "pids.peak": "12",
        "cpu.stat": (
            "usage_usec 10000\nuser_usec 6000\nsystem_usec 4000\n"
            "nr_periods 10\nnr_throttled 2\nthrottled_usec 1000\n"
        ),
    }
    for name, value in values.items():
        (root / name).write_text(value, encoding="ascii")


@pytest.mark.parametrize("service", ["controller", "browser-worker", "telegram-offline"])
def test_lifecycle_cgroup_snapshot_keeps_exact_component_limits_and_counters(
    tmp_path: Path, service: str
) -> None:
    budget = module("measure_browser_budget")
    cgroup(tmp_path, service=service)
    snapshot = budget.resource_snapshot(tmp_path, service)
    assert snapshot["cgroup"] == [tmp_path.stat().st_dev, tmp_path.stat().st_ino]
    assert snapshot["counters"] == {
        "memory_current_bytes": 1000000,
        "memory_peak_bytes": 2000000,
        "pids_current": 4,
        "pids_peak": 12,
        "cpu_usage_usec": 10000,
        "cpu_user_usec": 6000,
        "cpu_system_usec": 4000,
        "cpu_nr_periods": 10,
        "cpu_nr_throttled": 2,
        "cpu_throttled_usec": 1000,
    }


@pytest.mark.parametrize("value", [None, "", "max", "-1", "private-value", "9" * 4097, "é"])
def test_lifecycle_missing_or_invalid_counter_is_individually_unknown(
    tmp_path: Path, value: str | None
) -> None:
    budget = module("measure_browser_budget")
    cgroup(tmp_path)
    path = tmp_path / "memory.peak"
    if value is None:
        path.unlink()
    else:
        path.write_text(value, encoding="utf-8")
    result = budget.resource_snapshot(tmp_path, "controller")["counters"]
    assert result["memory_peak_bytes"] == "UNKNOWN"
    assert result["memory_current_bytes"] == 1000000
    assert result["pids_peak"] == 12
    assert result["cpu_usage_usec"] == 10000


def test_lifecycle_cpu_missing_duplicate_and_invalid_fields_are_not_zero(tmp_path: Path) -> None:
    budget = module("measure_browser_budget")
    cgroup(tmp_path)
    (tmp_path / "cpu.stat").write_text(
        "usage_usec 100\nusage_usec 200\nuser_usec 0\n"
        "nr_periods private\nnr_throttled -1\nfuture_field private-value\n",
        encoding="ascii",
    )
    result = budget.resource_snapshot(tmp_path, "controller")["counters"]
    assert result["cpu_usage_usec"] == "UNKNOWN"
    assert result["cpu_user_usec"] == 0
    for key in ("cpu_system_usec", "cpu_nr_periods", "cpu_nr_throttled", "cpu_throttled_usec"):
        assert result[key] == "UNKNOWN"
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize(
    "name,value",
    [
        ("memory.max", "max"),
        ("memory.max", "536870912"),
        ("pids.max", "65"),
        ("cpu.max", "60000 100000"),
        ("cpu.max", "0 100000"),
    ],
)
def test_lifecycle_missing_or_different_limits_still_fail_closed(
    tmp_path: Path, name: str, value: str
) -> None:
    budget = module("measure_browser_budget")
    cgroup(tmp_path)
    (tmp_path / name).write_text(value, encoding="ascii")
    with pytest.raises(budget.BudgetError):
        budget.resource_snapshot(tmp_path, "controller")


def test_legacy_budget_keeps_missing_required_counter_as_error(tmp_path: Path) -> None:
    budget = module("measure_browser_budget")
    cgroup(tmp_path, service="browser-worker")
    (tmp_path / "pids.peak").unlink()
    with pytest.raises(budget.BudgetError):
        budget.read_snapshot(tmp_path)


def test_lifecycle_cpu_delta_requires_same_runtime_and_never_clamps_regressions() -> None:
    runtime = module("check_browser_lifecycle_runtime")
    before = {key: 100 for key in runtime.cpu_counter_names()}
    after = {key: 140 for key in before}
    assert runtime.cpu_deltas(before, after, same_runtime=True) == dict.fromkeys(before, 40)
    assert set(runtime.cpu_deltas(before, after, same_runtime=False).values()) == {"UNKNOWN"}
    after["cpu_usage_usec"] = 99
    assert set(runtime.cpu_deltas(before, after, same_runtime=True).values()) == {"UNKNOWN"}
    after["cpu_usage_usec"] = "UNKNOWN"
    result = runtime.cpu_deltas(before, after, same_runtime=True)
    assert result["cpu_usage_usec"] == "UNKNOWN"
    assert result["cpu_throttled_usec"] == 40


@pytest.mark.parametrize("started", ["private-value", "2099-01-01T00:00:00Z", "", None])
def test_lifecycle_uptime_is_unknown_for_invalid_or_future_start(started: object) -> None:
    runtime = module("check_browser_lifecycle_runtime")
    assert runtime.observed_uptime_ms(started, now_ns=1_000_000_000) == "UNKNOWN"
    assert runtime.observed_uptime_ms("1970-01-01T00:00:00Z", now_ns=1_000_000_000) == 1000


def test_lifecycle_resource_receipt_cannot_claim_complete_with_unknown(tmp_path: Path) -> None:
    runtime = module("check_browser_lifecycle_runtime")
    budget = module("measure_browser_budget")
    cgroup(tmp_path)
    sample = budget.resource_snapshot(tmp_path, "controller")
    sample["counters"]["pids_peak"] = "UNKNOWN"
    receipt = runtime.resource_receipt(
        source="a" * 40,
        service="controller",
        phase="startup",
        after=sample["counters"],
        elapsed_ms=20,
        duration_kind="uptime_at_healthy_observation",
    )
    assert receipt["measurement"] == "UNKNOWN"
    assert receipt["counters"]["pids_peak"] == "UNKNOWN"
    assert receipt["peak_scope"] == "cgroup_lifetime_current_start"
    assert receipt["sampling"] == "sequential_exec_observer_included"
    assert receipt["full_three_service_concurrency"] == "UNMEASURED"
    assert len(json.dumps(receipt)) < 4096


@pytest.mark.parametrize(
    "raw", ["private-value", " " * 4097, '{"cgroup":[1,2],"counters":{},"secret":"private"}']
)
def test_lifecycle_snapshot_parser_rejects_unbounded_or_private_fields(raw: str) -> None:
    runtime = module("check_browser_lifecycle_runtime")
    with pytest.raises(ValueError):
        runtime.parse_resource_snapshot(raw)


@pytest.mark.parametrize("tamper", ["bool", "negative", "text", "extra", "duplicate", "cgroup"])
def test_lifecycle_snapshot_parser_accepts_only_fixed_numeric_schema(
    tmp_path: Path, tamper: str
) -> None:
    runtime = module("check_browser_lifecycle_runtime")
    cgroup(tmp_path)
    snapshot = module("measure_browser_budget").resource_snapshot(tmp_path, "controller")
    assert runtime.parse_resource_snapshot(json.dumps(snapshot)) == snapshot
    if tamper == "cgroup":
        snapshot["cgroup"] = [1, True]
    elif tamper == "extra":
        snapshot["counters"]["private-name"] = 1
    else:
        snapshot["counters"]["cpu_usage_usec"] = {
            "bool": True,
            "negative": -1,
            "text": "private-value",
            "duplicate": 100,
        }[tamper]
    raw = json.dumps(snapshot)
    if tamper == "duplicate":
        raw = raw.replace('"cpu_usage_usec": 100', '"cpu_usage_usec": 100,"cpu_usage_usec": 200')
    with pytest.raises(ValueError):
        runtime.parse_resource_snapshot(raw)


def observed_sample(tmp_path: Path) -> dict:
    cgroup(tmp_path)
    sample = module("measure_browser_budget").resource_snapshot(tmp_path, "controller")
    sample.update(
        runtime=("same-container", "same-image", 0, "same-start", True, "healthy"), uptime_ms=1000
    )
    return sample


@pytest.mark.parametrize("phase", ["startup", "restart"])
def test_lifecycle_pair_measures_exactly_one_existing_journey_per_phase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], phase: str
) -> None:
    runtime = module("check_browser_lifecycle_runtime")
    sample = observed_sample(tmp_path)
    controller, worker = "c" * 64, "b" * 64
    captures, commands = [], []

    def capture(container, service, identity):
        captures.append((container, service, identity))
        return sample

    def docker(*args, **kwargs):
        commands.append((args, kwargs))
        return ""

    monkeypatch.setattr(runtime, "capture_resources", capture)
    monkeypatch.setattr(runtime, "docker", docker)
    runtime.measure_pair("a" * 40, phase, controller, worker, {controller: "c", worker: "b"})
    assert commands == [
        (
            ("exec", "--user", "10001:10001", controller, "python", "-c", runtime.IPC_JOURNEY),
            {"timeout": 30},
        )
    ]
    assert [item[:2] for item in captures] == [
        (controller, "controller"),
        (worker, "browser-worker"),
        (controller, "controller"),
        (worker, "browser-worker"),
    ]
    receipts = [
        json.loads(line.removeprefix("BOCA_CI_RESOURCE "))
        for line in capsys.readouterr().out.splitlines()
    ]
    assert [item["phase"] for item in receipts] == [phase, phase, f"{phase}_ipc", f"{phase}_ipc"]
    assert all(item["measurement"] == "OBSERVED" for item in receipts)
    assert receipts[-1]["counters"]["memory_peak_bytes"] == 2000000
    assert receipts[-1]["cpu_delta"]["cpu_usage_usec"] == 0


def test_lifecycle_ipc_failure_does_not_emit_successful_journey_measurement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runtime = module("check_browser_lifecycle_runtime")
    sample = observed_sample(tmp_path)
    monkeypatch.setattr(runtime, "capture_resources", lambda *args: sample)

    def failed(*args, **kwargs):
        raise RuntimeError("workload refused")

    monkeypatch.setattr(runtime, "docker", failed)
    with pytest.raises(RuntimeError, match="workload refused"):
        runtime.measure_pair("a" * 40, "startup", "c", "b", {"c": "c", "b": "b"})
    output = capsys.readouterr().out
    assert '"phase": "startup_ipc"' not in output
    assert "state=PASS" not in output


ACCEPTANCE = (
    "BOCA_SYNTHETIC_ACCEPTANCE state=PASS scope=container_loopback requests=20 median_ms=1.00"
    " p95_ms=2.00 elapsed_ms=30.00 cpu_ms=20.00 process_peak_rss_kib=1000 scratch_bytes=10000"
    " members=1 intents=1 notices=1 local_http=verified engine=off site=not_contacted telegram=not_sent"
)


@pytest.mark.parametrize(
    "raw", [ACCEPTANCE + "\n", ACCEPTANCE, ACCEPTANCE + "\n\n", "private\n", "x" * 386]
)
def test_lifecycle_http_acceptance_runs_once_and_keeps_original_receipt_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], raw: str
) -> None:
    runtime = module("check_browser_lifecycle_runtime")
    sample = observed_sample(tmp_path)
    commands = []
    monkeypatch.setattr(runtime, "capture_resources", lambda *args: sample)

    def docker(*args, **kwargs):
        commands.append((args, kwargs))
        return raw

    monkeypatch.setattr(runtime, "docker", docker)
    if raw == ACCEPTANCE + "\n":
        runtime.measure_acceptance("a" * 40, "c" * 64, sample["runtime"])
        output = capsys.readouterr().out
        assert output.endswith(ACCEPTANCE + "\n")
        assert '"phase": "http_acceptance"' in output
    else:
        with pytest.raises((RuntimeError, ValueError)):
            runtime.measure_acceptance("a" * 40, "c" * 64, sample["runtime"])
        assert capsys.readouterr().out == ""
    assert commands == [
        (
            (
                "exec",
                "--user",
                "10001:10001",
                "c" * 64,
                "python",
                "-m",
                "boca_socios.acceptance.host_probe",
            ),
            {"timeout": 135, "strip": False},
        )
    ]


@pytest.mark.parametrize("condition", ["stopped", "identity", "namespace"])
def test_lifecycle_resource_probe_never_executes_without_running_identity(
    monkeypatch: pytest.MonkeyPatch, condition: str
) -> None:
    runtime = module("check_browser_lifecycle_runtime")
    record = {
        "Id": "c" * 64,
        "Image": "i",
        "RestartCount": 0,
        "State": {"StartedAt": "s", "Running": True},
        "HostConfig": {"CgroupnsMode": "private"},
    }
    expected = runtime.runtime_identity(record)
    if condition == "stopped":
        record["State"]["Running"] = False
    elif condition == "identity":
        record["Id"] = "b" * 64
    else:
        record["HostConfig"]["CgroupnsMode"] = "host"
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        assert args[0] == "inspect"
        return json.dumps(record)

    monkeypatch.setattr(runtime, "docker", docker)
    with pytest.raises(RuntimeError):
        runtime.capture_resources("c" * 64, "controller", expected)
    assert len(calls) == 1


def test_lifecycle_legacy_default_namespace_is_unknown_without_reconfiguring_or_exec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = module("check_browser_lifecycle_runtime")
    record = {
        "Id": "c" * 64,
        "Image": "i",
        "RestartCount": 0,
        "State": {"StartedAt": "s", "Running": True},
        "HostConfig": {"CgroupnsMode": ""},
    }
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        assert args[0] == "inspect"
        return json.dumps(record)

    monkeypatch.setattr(runtime, "docker", docker)
    sample = runtime.capture_resources("c" * 64, "controller", runtime.runtime_identity(record))
    assert sample["cgroup"] is None
    assert set(sample["counters"].values()) == {"UNKNOWN"}
    assert len(calls) == 1


@pytest.mark.parametrize("changed", [False, True])
def test_lifecycle_probe_uses_fixed_source_uid_and_rechecks_runtime_after_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed: bool,
) -> None:
    runtime = module("check_browser_lifecycle_runtime")
    cgroup(tmp_path)
    snapshot = module("measure_browser_budget").resource_snapshot(tmp_path, "controller")
    record = {
        "Id": "c" * 64,
        "Image": "i",
        "RestartCount": 0,
        "State": {"StartedAt": "s", "Running": True},
        "HostConfig": {"CgroupnsMode": "private"},
    }
    expected = runtime.runtime_identity(record)
    calls = []

    def docker(*args, **kwargs):
        calls.append(args)
        if args[0] == "inspect":
            if changed and len(calls) == 3:
                record["State"]["StartedAt"] = "changed"
            return json.dumps(record)
        assert args[:6] == ("exec", "--user", "10001:10001", "c" * 64, "python", "-c")
        assert args[6] == (ROOT / "scripts/measure_browser_budget.py").read_text(encoding="utf-8")
        assert args[7:] == ("snapshot", "controller")
        assert kwargs == {"timeout": 8}
        return json.dumps(snapshot)

    monkeypatch.setattr(runtime, "docker", docker)
    if changed:
        with pytest.raises(RuntimeError, match="service changed during"):
            runtime.capture_resources("c" * 64, "controller", expected)
    else:
        sample = runtime.capture_resources("c" * 64, "controller", expected)
        assert sample["counters"] == snapshot["counters"]
    assert [call[0] for call in calls] == ["inspect", "exec", "inspect"]


@pytest.mark.parametrize("failure", ["exit", "timeout"])
def test_lifecycle_docker_failure_withholds_arbitrary_stdout_and_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: str
) -> None:
    runtime = module("check_browser_lifecycle_runtime")

    def run(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("docker", 1, output="private", stderr="private")
        return subprocess.CompletedProcess(
            args=[], returncode=1, stdout="private", stderr="private"
        )

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(RuntimeError) as caught:
        runtime.docker("inspect", "c" * 64)
    assert "private" not in str(caught.value)
    assert capsys.readouterr().out == ""


def test_lifecycle_portable_probe_needs_no_scripts_or_playwright_package() -> None:
    source = (ROOT / "scripts/measure_browser_budget.py").read_text(encoding="utf-8")
    result = subprocess.run(  # noqa: S603 - exact stdlib-only source under an isolated interpreter
        [sys.executable, "-I", "-c", source, "snapshot", "unrecognized"],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    # Unknown service fails before reading any cgroup. The fixed result also
    # proves the portable probe never imports the browser-only scripts package.
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "BOCA_CI_RESOURCE_NO_GO\n"
