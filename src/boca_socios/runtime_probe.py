"""Read only the controller's effective cgroup v2 limits inside its container.

The host helper runs this fixed module as the controller UID through the
already verified Boca container ID. No key, database or network access is used.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CGROUP_ROOT = Path("/sys/fs/cgroup")
SELF_CGROUP = Path("/proc/self/cgroup")


class RuntimeProbeError(ValueError):
    """Effective controller limits cannot be proven."""


def _read_ascii(path: Path, *, limit: int = 128) -> str:
    try:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
    except OSError as exc:
        raise RuntimeProbeError("cgroup metadata is unavailable") from exc
    if len(raw) > limit:
        raise RuntimeProbeError("cgroup metadata exceeds bounded output")
    try:
        value = raw.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise RuntimeProbeError("cgroup metadata is invalid") from exc
    if not value or "\n" in value or "\r" in value:
        raise RuntimeProbeError("cgroup metadata is invalid")
    return value


def effective_limits() -> dict[str, int]:
    if not (CGROUP_ROOT / "cgroup.controllers").is_file():
        raise RuntimeProbeError("cgroup v2 is unavailable")
    # The private cgroup namespace exposes this container's cgroup as root;
    # in a host namespace, root-level files could describe an ancestor.
    if _read_ascii(SELF_CGROUP, limit=256) != "0::/":
        raise RuntimeProbeError("private container cgroup is unproven")
    cpu = _read_ascii(CGROUP_ROOT / "cpu.max").split()
    if len(cpu) != 2 or any(not re.fullmatch(r"[0-9]+", value) for value in cpu):
        raise RuntimeProbeError("CPU quota is unproven")
    quota, period = (int(value) for value in cpu)
    memory_raw = _read_ascii(CGROUP_ROOT / "memory.max")
    pids_raw = _read_ascii(CGROUP_ROOT / "pids.max")
    if not re.fullmatch(r"[0-9]+", memory_raw) or not re.fullmatch(r"[0-9]+", pids_raw):
        raise RuntimeProbeError("memory or PID limit is unproven")
    memory, pids = int(memory_raw), int(pids_raw)
    if not (0 < period <= 1_000_000) or quota * 2 != period or memory != 268_435_456 or pids != 64:
        raise RuntimeProbeError("effective controller cgroup limits differ from budget")
    return {
        "cpu_quota": quota,
        "cpu_period": period,
        "memory_bytes": memory,
        "pids_limit": pids,
    }


def main() -> int:
    try:
        result = effective_limits()
    except (RuntimeProbeError, OSError, ValueError):
        print("BOCA_CGROUP_NO_GO", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
