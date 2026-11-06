"""CPU ceiling is structural; loadavg is neither idle CPU nor an admission veto."""

import os
from fractions import Fraction
from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host


def test_io_load_does_not_reject_two_cpu_browser_and_telegram(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = object()
    monkeypatch.setattr(
        host,
        "_observe_browser_capacity",
        lambda: (
            2048 * 1024,
            host.CpuCapacity(2, 2, Fraction(2), "materialized"),
            64.0,
            512,
            storage,
        ),
    )
    monkeypatch.setattr(host, "_validate_storage_capacity", lambda _, **kwargs: None)
    assert host._browser_capacity()[1] == 2.0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("infinity", None),
        ("2s", Fraction(2)),
        ("1.750000s", Fraction(7, 4)),
        ("250ms", Fraction(1, 4)),
        ("250.001ms", Fraction(250001, 1000000)),
        ("1min 2s", Fraction(62)),
    ],
)
def test_systemd_quota_renderer_uses_exact_seconds(value: str, expected: Fraction | None) -> None:
    assert host._cpu_systemd_quota(value) == expected


@pytest.mark.parametrize("value", ["", "0", "0s", "nan", "2", "-1s", "1s 1s", "1.2.3s"])
def test_unknown_or_nonpositive_systemd_quota_is_not_unlimited(value: str) -> None:
    with pytest.raises(host.PreflightError, match="CPU"):
        host._cpu_systemd_quota(value)


def _hierarchy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    materialized: bool = True,
    cpuset_delegated: bool = True,
) -> tuple[Path, Path, dict[str, str], dict[str, str]]:
    root = tmp_path / "cgroup"
    manager = root / "user.slice/user-10001.slice/user@10001.service"
    manager.mkdir(parents=True)
    for directory in (root, root / "user.slice", root / "user.slice/user-10001.slice", manager):
        (directory / "cgroup.controllers").write_text("cpu cpuset memory pids\n")
        enabled = "cpu cpuset memory pids\n"
        if directory == manager and not cpuset_delegated:
            enabled = "cpu memory pids\n"
        (directory / "cgroup.subtree_control").write_text(enabled)
        (directory / "cpuset.cpus.effective").write_text("0-3\n")
        if directory != root:
            (directory / "cpu.max").write_text("max 100000\n")
    branch = manager / "user.slice"
    if materialized:
        branch.mkdir()
        (branch / "cpu.max").write_text("max 100000\n")
        (branch / "cgroup.controllers").write_text(
            "cpu cpuset memory pids\n" if cpuset_delegated else "cpu memory pids\n"
        )
        (branch / "cgroup.subtree_control").write_text("\n")
        if cpuset_delegated:
            (branch / "cpuset.cpus.effective").write_text("0-3\n")
    manager_properties = {
        "ControlGroup": "/user.slice/user-10001.slice/user@10001.service",
        "SystemState": "running",
    }
    slice_properties = {
        "LoadState": "loaded",
        "NeedDaemonReload": "no",
        "ActiveState": "active" if materialized else "inactive",
        "ControlGroup": manager_properties["ControlGroup"] + "/user.slice" if materialized else "",
        "CPUQuotaPerSecUSec": "infinity",
        "AllowedCPUs": "",
    }
    monkeypatch.setattr(host, "CPU_CGROUP_ROOT", root)
    monkeypatch.setattr(host, "CGROUP_CONTROLLERS", manager / "cgroup.controllers")
    monkeypatch.setattr(host, "_cpu_default_parent", lambda: None)
    monkeypatch.setattr(host, "_cpu_online", lambda: frozenset(range(4)))

    def properties(unit: str | None, keys: tuple[str, ...]) -> dict[str, str]:
        assert unit in {None, "user.slice"}
        value = manager_properties if unit is None else slice_properties
        assert set(keys) == value.keys()
        return value.copy()

    monkeypatch.setattr(host, "_cpu_systemd_properties", properties)
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: '{"NCPU":4}')
    return manager, branch, manager_properties, slice_properties


@pytest.mark.parametrize("location", ["slice", "manager", "user", "global_user"])
def test_every_container_ancestor_quota_limits_ceiling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, location: str
) -> None:
    manager, branch, _, _ = _hierarchy(monkeypatch, tmp_path)
    directory = {
        "slice": branch,
        "manager": manager,
        "user": manager.parent,
        "global_user": manager.parent.parent,
    }[location]
    (directory / "cpu.max").write_text("174999 100000\n")
    capacity = host._cpu_structural_capacity()
    assert capacity.ceiling == Fraction(174999, 100000)
    assert capacity.ceiling < Fraction(7, 4)


def test_cpuset_and_quota_both_constrain_container_branch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, branch, _, _ = _hierarchy(monkeypatch, tmp_path)
    (branch / "cpuset.cpus.effective").write_text("1,3\n")
    assert host._cpu_structural_capacity().ceiling == 2
    (branch / "cpu.max").write_text("175000 100000\n")
    assert host._cpu_structural_capacity().ceiling == Fraction(7, 4)


@pytest.mark.parametrize("materialized", [True, False])
def test_absent_cpuset_delegation_inherits_proven_ancestor_mask(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, materialized: bool
) -> None:
    manager, _, _, _ = _hierarchy(
        monkeypatch, tmp_path, materialized=materialized, cpuset_delegated=False
    )
    (manager / "cpuset.cpus.effective").write_text("0-1\n")
    capacity = host._cpu_structural_capacity()
    assert capacity.ceiling == 2
    assert capacity.scope == ("materialized" if materialized else "configured")


def test_unmaterialized_slice_uses_loaded_quota_and_space_separated_mask(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, branch, _, props = _hierarchy(monkeypatch, tmp_path, materialized=False)
    props["CPUQuotaPerSecUSec"] = "1.750000s"
    props["AllowedCPUs"] = "0-1 3"
    capacity = host._cpu_structural_capacity()
    assert capacity.ceiling == Fraction(7, 4)
    assert capacity.effective_cpus == 3
    assert not branch.exists()


@pytest.mark.parametrize("filename", ["cpu.max", "cpuset.cpus.effective"])
def test_expected_kernel_control_missing_is_unknown_not_unlimited(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, filename: str
) -> None:
    _, branch, _, _ = _hierarchy(monkeypatch, tmp_path)
    (branch / filename).unlink()
    with pytest.raises(host.PreflightError, match="CPU.*UNKNOWN"):
        host._cpu_structural_capacity()


@pytest.mark.parametrize(
    ("target", "key", "value"),
    [
        ("manager", "ControlGroup", "/other.slice/user@10001.service"),
        ("manager", "SystemState", "starting"),
        ("slice", "ControlGroup", "/other.slice"),
        ("slice", "NeedDaemonReload", "yes"),
        ("slice", "LoadState", "not-found"),
    ],
)
def test_unproven_branch_identity_or_loading_state_is_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, target: str, key: str, value: str
) -> None:
    _, _, manager, slice_properties = _hierarchy(monkeypatch, tmp_path)
    (manager if target == "manager" else slice_properties)[key] = value
    with pytest.raises(host.PreflightError, match="CPU.*UNKNOWN"):
        host._cpu_structural_capacity()


def test_daemon_startup_cpu_count_is_only_an_additional_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, branch, _, _ = _hierarchy(monkeypatch, tmp_path)
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: '{"NCPU":2}')
    (branch / "cpu.max").write_text("150000 100000\n")
    capacity = host._cpu_structural_capacity()
    assert capacity.daemon_startup_count == 2
    assert capacity.ceiling == Fraction(3, 2)


def test_inactive_materialized_slice_without_cpu_enabled_uses_effective_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager, branch, _, props = _hierarchy(monkeypatch, tmp_path)
    (manager / "cgroup.subtree_control").write_text("cpuset memory pids\n")
    (branch / "cpu.max").unlink()
    props["ActiveState"] = "inactive"
    props["CPUQuotaPerSecUSec"] = "1.750000s"
    assert host._cpu_structural_capacity().ceiling == Fraction(7, 4)


def test_missing_cpuset_in_manager_inherits_nearest_enabled_ancestor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager, _, _, _ = _hierarchy(monkeypatch, tmp_path, materialized=False)
    (manager.parent / "cgroup.subtree_control").write_text("cpu memory pids\n")
    (manager / "cgroup.subtree_control").write_text("cpu memory pids\n")
    (manager / "cgroup.controllers").write_text("cpu memory pids\n")
    (manager / "cpuset.cpus.effective").unlink()
    (manager.parent / "cpuset.cpus.effective").write_text("0-1\n")
    assert host._cpu_structural_capacity().ceiling == 2


@pytest.mark.parametrize("value", ["max", "0 100000", "-1 100000", "max 0", "100000 0", "garbage"])
def test_invalid_kernel_quota_is_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str
) -> None:
    _, branch, _, _ = _hierarchy(monkeypatch, tmp_path)
    (branch / "cpu.max").write_text(value)
    with pytest.raises(host.PreflightError, match="CPU.*UNKNOWN"):
        host._cpu_structural_capacity()


def test_cpu_reader_rejects_fifo_and_symlink_without_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    os.mkfifo(tmp_path / "fifo", mode=0o600)
    (tmp_path / "target").write_text("max 100000\n")
    (tmp_path / "link").symlink_to(tmp_path / "target")
    descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    original_open = os.open

    def bounded_open(path: str, flags: int, **kwargs: object) -> int:
        assert flags & os.O_NONBLOCK
        return original_open(path, flags, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(host.os, "open", bounded_open)
    try:
        with pytest.raises(host.PreflightError):
            host._cpu_read(descriptor, "fifo")
        with pytest.raises(OSError):
            host._cpu_read(descriptor, "link")
        expected = (tmp_path / "target").stat()
        assert host._cpu_read(descriptor, "target", expected=expected) == "max 100000"
        (tmp_path / "target").write_text("100000 100000\n")
        with pytest.raises(host.PreflightError, match="changed"):
            host._cpu_read(descriptor, "target", expected=expected)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("value", [True, 0, -1, "2", None])
def test_unknown_daemon_startup_count_is_not_substituted_with_ssh_affinity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: object
) -> None:
    import json

    _hierarchy(monkeypatch, tmp_path)
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: json.dumps({"NCPU": value}))
    monkeypatch.setattr(host.os, "sched_getaffinity", lambda _: pytest.fail("SSH affinity read"))
    with pytest.raises(host.PreflightError, match="CPU.*UNKNOWN"):
        host._cpu_structural_capacity()


def test_manager_transition_during_cpu_observation_is_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, _, manager, props = _hierarchy(monkeypatch, tmp_path)
    count = 0

    def properties(unit: str | None, keys: tuple[str, ...]) -> dict[str, str]:
        nonlocal count
        count += 1
        if unit is None:
            return dict(manager, SystemState="running" if count == 1 else "stopping")
        return props.copy()

    monkeypatch.setattr(host, "_cpu_systemd_properties", properties)
    with pytest.raises(host.PreflightError, match="CPU.*UNKNOWN"):
        host._cpu_structural_capacity()


@pytest.mark.parametrize(
    ("raw", "accepted"),
    [
        ('{"exec-opts":["native.cgroupdriver=systemd"]}', True),
        ('{"exec-opts":["native.cgroupdriver=systemd"],"cgroup-parent":""}', True),
        ('{"exec-opts":["native.cgroupdriver=systemd"],"cgroup-parent":"other.slice"}', False),
        ('{"exec-opts":["native.cgroupdriver=cgroupfs"]}', False),
        ('{"exec-opts":[],"exec-opts":["native.cgroupdriver=systemd"]}', False),
        ('[["exec-opts",["native.cgroupdriver=systemd"]]]', False),
    ],
)
def test_only_reviewed_default_parent_can_select_user_slice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw: str, accepted: bool
) -> None:
    from types import SimpleNamespace

    home = tmp_path / "home"
    directory = home / ".config/docker"
    directory.mkdir(parents=True, mode=0o700)
    for part in (home, home / ".config", directory):
        part.chmod(0o700)
    config = directory / "daemon.json"
    config.write_text(raw)
    config.chmod(0o600)
    monkeypatch.setattr(host.pwd, "getpwuid", lambda _: SimpleNamespace(pw_dir=str(home)))
    original_stat, original_fstat = os.stat, os.fstat

    def owned(value: os.stat_result) -> object:
        fields = {name: getattr(value, name) for name in dir(value) if name.startswith("st_")}
        return SimpleNamespace(**dict(fields, st_uid=10001))

    def fixture_stat(*args: object, **kwargs: object) -> object:
        result = original_stat(*args, **kwargs)  # type: ignore[call-overload]
        return owned(result) if "dir_fd" in kwargs else result

    monkeypatch.setattr(host.os, "stat", fixture_stat)
    monkeypatch.setattr(host.os, "fstat", lambda descriptor: owned(original_fstat(descriptor)))
    if accepted:
        host._cpu_default_parent()
    else:
        with pytest.raises(host.PreflightError, match="CPU.*UNKNOWN"):
            host._cpu_default_parent()


@pytest.mark.parametrize("load", [64.0, None])
def test_advisory_load_survives_exact_real_receipt_workflow_parser(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    load: float | None,
) -> None:
    from test_infrastructure_preflight import (
        FULL_BUDGET,
        SHA,
        _observe_ready,
        _run_step,
    )

    _observe_ready(monkeypatch, load=load)
    host._infrastructure_preflight(SHA, FULL_BUDGET)
    receipt = capsys.readouterr().out
    assert "cpu_ceiling=2.000000" in receipt
    assert "load_policy=advisory" in receipt
    assert "cpu=PASS" in receipt
    result = _run_step(
        "Observe infrastructure and evaluate unchanged reserve before release",
        tmp_path,
        receipt=receipt,
        budget=FULL_BUDGET,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("operation", ["browser-preflight", "browser-stage"])
def test_browser_capacity_receipt_names_ceiling_and_passes_actual_shell_gate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], operation: str
) -> None:
    import subprocess

    from test_browser_ipc_workflow import _step
    from test_host_browser_ipc_install import ATTEMPT, coordinates
    from test_host_first_deploy import safe_storage

    monkeypatch.setattr(host, "_browser_engine_version", lambda: "29.7.2")
    monkeypatch.setattr(
        host, "_browser_preflight_inventory", lambda: (2048 * 1024, 2.0, 512, safe_storage())
    )
    monkeypatch.setattr(host, "_browser_image_absent", lambda *args: False)
    monkeypatch.setattr(host, "_browser_write_marker", lambda _: None)
    host._browser_phase(operation, **coordinates())
    receipt = capsys.readouterr().out.strip()
    assert "cpu_ceiling=2.00" in receipt and "cpu_headroom=" not in receipt
    if operation == "browser-preflight":
        step = _step("Read-only owner and new-only browser IPC host preflight")
        pattern = step.split("pattern='", 1)[1].split("'", 1)[0]
    else:
        step = _step("Record preexisting Boca images and atomically stage reviewed browser files")
        pattern = step.split('stage_pattern="', 1)[1].split('"', 1)[0]
        pattern = pattern.replace("$GITHUB_RUN_ID", ATTEMPT)
    result = subprocess.run(
        ["/bin/bash", "-c", '[[ "$RECEIPT" =~ $PATTERN ]]'],
        env={"PATH": os.environ["PATH"], "RECEIPT": receipt, "PATTERN": pattern},
        text=True,
        capture_output=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
