"""Read bounded cgroup v2 counters and measure one offline Chromium startup.

The default mode retains its strict single-startup contract. The portable
snapshot mode observes an existing CI service without launching a browser.
Neither mode estimates site latency, droplet capacity or parallel-session scale.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

CGROUP = Path("/sys/fs/cgroup")
MEMORY_LIMIT = 768 * 1024 * 1024
PIDS_LIMIT = 128
UNKNOWN = "UNKNOWN"
MAX_COUNTER = 2**63 - 1
COUNTER_FILES = {
    "memory_current_bytes": "memory.current",
    "memory_peak_bytes": "memory.peak",
    "pids_current": "pids.current",
    "pids_peak": "pids.peak",
}
CPU_FIELDS = {
    "cpu_usage_usec": "usage_usec",
    "cpu_user_usec": "user_usec",
    "cpu_system_usec": "system_usec",
    "cpu_nr_periods": "nr_periods",
    "cpu_nr_throttled": "nr_throttled",
    "cpu_throttled_usec": "throttled_usec",
}
# These are the existing service contracts, never proposed host capacity.
SERVICE_LIMITS = {
    "controller": (10001, 256 * 1024 * 1024, 64, 500_000_000),
    "browser-worker": (10002, MEMORY_LIMIT, PIDS_LIMIT, 1_000_000_000),
    "telegram-offline": (10001, 128 * 1024 * 1024, 32, 250_000_000),
}


class BudgetError(RuntimeError):
    """A measurement would misrepresent an unbounded or unreadable cgroup."""


def _bounded_text(path: Path) -> str:
    with path.open("rb") as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise ValueError("counter_invalid")
    return raw.decode("ascii").strip()


def _counter(value: str) -> int | str:
    if not value.isascii() or not value.isdecimal() or len(value) > 19:
        return UNKNOWN
    number = int(value)
    return number if number <= MAX_COUNTER else UNKNOWN


def read_counters(root: Path) -> dict[str, int | str]:
    """Read only fixed files; optional/malformed fields remain individually UNKNOWN."""
    result: dict[str, int | str] = {}
    for key, name in COUNTER_FILES.items():
        try:
            result[key] = _counter(_bounded_text(root / name))
        except (OSError, ValueError):
            result[key] = UNKNOWN
    try:
        lines = _bounded_text(root / "cpu.stat").splitlines()
    except (OSError, ValueError):
        lines = []
    for key, name in CPU_FIELDS.items():
        fields = [line.split() for line in lines if line.split()[:1] == [name]]
        result[key] = (
            _counter(fields[0][1]) if len(fields) == 1 and len(fields[0]) == 2 else UNKNOWN
        )
    return result


def _limits(root: Path) -> tuple[int, int, int, int]:
    try:
        memory = int(_bounded_text(root / "memory.max"))
        pids = int(_bounded_text(root / "pids.max"))
        quota, period = map(int, _bounded_text(root / "cpu.max").split())
    except (OSError, ValueError):
        raise BudgetError("cgroup_unavailable") from None
    if min(memory, pids, quota, period) <= 0:
        raise BudgetError("resource_limit_missing")
    return memory, pids, quota, period


def resource_snapshot(root: Path, service: str) -> dict[str, object]:
    """Generic lifecycle observation; limits remain mandatory and exact."""
    if service not in SERVICE_LIMITS:
        raise BudgetError("service_unverified")
    _uid, required_memory, required_pids, required_cpu = SERVICE_LIMITS[service]
    memory, pids, quota, period = _limits(root)
    if (memory, pids) != (required_memory, required_pids) or (
        quota * 1_000_000_000 != required_cpu * period
    ):
        raise BudgetError("resource_limit_mismatch")
    metadata = root.stat()
    return {
        "cgroup": [metadata.st_dev, metadata.st_ino],
        "counters": read_counters(root),
    }


def snapshot_main(service: str) -> int:
    """Portable stdlib-only probe transported into an already verified CI container."""
    try:
        uid = SERVICE_LIMITS[service][0]
        if os.geteuid() != uid or os.getegid() != uid:
            raise BudgetError("identity_unverified")
        print(json.dumps(resource_snapshot(CGROUP, service), sort_keys=True))
    except (OSError, ValueError, KeyError, BudgetError):
        print("BOCA_CI_RESOURCE_NO_GO", file=sys.stderr)
        return 1
    return 0


def read_snapshot(root: Path) -> dict[str, int]:
    """Require the worker's Docker limits before trusting cgroup counters."""
    memory_max, pids_max, cpu_quota, cpu_period = _limits(root)
    if not (0 < memory_max <= MEMORY_LIMIT and 0 < pids_max <= PIDS_LIMIT):
        raise BudgetError("resource_limit_missing")
    if cpu_quota <= 0 or cpu_period <= 0 or cpu_quota > cpu_period:
        raise BudgetError("cpu_limit_missing")
    counters = read_counters(root)
    memory_peak = counters["memory_peak_bytes"]
    pids_peak = counters["pids_peak"]
    cpu_usage = counters["cpu_usage_usec"]
    if (
        not isinstance(memory_peak, int)
        or not isinstance(pids_peak, int)
        or not isinstance(cpu_usage, int)
    ):
        raise BudgetError("cgroup_unavailable")
    return {
        "peak_memory_bytes": memory_peak,
        "peak_pids": pids_peak,
        "cpu_usage_us": cpu_usage,
    }


def main() -> int:
    from scripts.verify_chromium_worker import verify

    try:
        before = read_snapshot(CGROUP)
        start_ns = time.monotonic_ns()
        asyncio.run(asyncio.wait_for(verify(), timeout=35))
        elapsed_ms = (time.monotonic_ns() - start_ns) // 1_000_000
        after = read_snapshot(CGROUP)
        if after["cpu_usage_us"] < before["cpu_usage_us"]:
            raise BudgetError("counter_invalid")
    except (Exception, KeyboardInterrupt) as error:
        print(f"browser_budget_stopped: {type(error).__name__}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "mode": "one_offline_chromium",
                "peak_memory_mib": round(after["peak_memory_bytes"] / (1024 * 1024), 1),
                "peak_pids": after["peak_pids"],
                "cpu_ms": (after["cpu_usage_us"] - before["cpu_usage_us"]) // 1000,
                "elapsed_ms": elapsed_ms,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "snapshot":
        raise SystemExit(snapshot_main(sys.argv[2]))
    raise SystemExit(main())
