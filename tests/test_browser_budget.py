"""The single-browser measurement must reject unbounded cgroup readings."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def budget():  # type: ignore[no-untyped-def]
    path = Path(__file__).resolve().parents[1] / "scripts" / "measure_browser_budget.py"
    spec = importlib.util.spec_from_file_location("browser_budget", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_cgroup(root: Path, **overrides: str) -> None:
    values = {
        "memory.max": "805306368",
        "memory.peak": "134217728",
        "pids.max": "128",
        "pids.peak": "23",
        "cpu.max": "100000 100000",
        "cpu.stat": "usage_usec 321000\nuser_usec 250000\nsystem_usec 71000\n",
    }
    values.update(overrides)
    for name, content in values.items():
        (root / name).write_text(content, encoding="ascii")


def test_reads_bounded_container_cgroup_metrics(tmp_path: Path) -> None:
    write_cgroup(tmp_path)
    assert budget().read_snapshot(tmp_path) == {
        "peak_memory_bytes": 134217728,
        "peak_pids": 23,
        "cpu_usage_us": 321000,
    }


@pytest.mark.parametrize(
    "override",
    [
        {"memory.max": "max"},
        {"pids.max": "max"},
        {"cpu.max": "max 100000"},
        {"memory.max": "1073741824"},
        {"pids.max": "256"},
        {"cpu.max": "200000 100000"},
        {"memory.peak": "not-a-number"},
    ],
)
def test_rejects_missing_or_excessive_limits(tmp_path: Path, override: dict[str, str]) -> None:
    module = budget()
    write_cgroup(tmp_path, **override)
    with pytest.raises(module.BudgetError):
        module.read_snapshot(tmp_path)
