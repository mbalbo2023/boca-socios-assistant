"""Measure one offline Chromium startup inside a bounded cgroup v2 container.

This intentionally never visits Boca, a fake booking page, or any network URL.
It does not estimate site latency, droplet capacity or parallel-session scale.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from scripts.verify_chromium_worker import verify

CGROUP = Path("/sys/fs/cgroup")
MEMORY_LIMIT = 768 * 1024 * 1024
PIDS_LIMIT = 128


class BudgetError(RuntimeError):
    """A measurement would misrepresent an unbounded or unreadable cgroup."""


def read_snapshot(root: Path) -> dict[str, int]:
    """Require the worker's Docker limits before trusting cgroup counters."""
    try:
        memory_max = int((root / "memory.max").read_text(encoding="ascii").strip())
        memory_peak = int((root / "memory.peak").read_text(encoding="ascii").strip())
        pids_max = int((root / "pids.max").read_text(encoding="ascii").strip())
        pids_peak = int((root / "pids.peak").read_text(encoding="ascii").strip())
        cpu_quota, cpu_period = map(int, (root / "cpu.max").read_text(encoding="ascii").split())
        cpu_usage = next(
            int(line.split()[1])
            for line in (root / "cpu.stat").read_text(encoding="ascii").splitlines()
            if line.startswith("usage_usec ")
        )
    except (OSError, ValueError, StopIteration):
        raise BudgetError("cgroup_unavailable") from None
    if not (0 < memory_max <= MEMORY_LIMIT and 0 < pids_max <= PIDS_LIMIT):
        raise BudgetError("resource_limit_missing")
    if cpu_quota <= 0 or cpu_period <= 0 or cpu_quota > cpu_period:
        raise BudgetError("cpu_limit_missing")
    if min(memory_peak, pids_peak, cpu_usage) < 0:
        raise BudgetError("counter_invalid")
    return {
        "peak_memory_bytes": memory_peak,
        "peak_pids": pids_peak,
        "cpu_usage_us": cpu_usage,
    }


def main() -> int:
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
    raise SystemExit(main())
