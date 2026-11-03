"""Expose only reviewed, fixed owner-enroll failure phase codes to Actions.

The host's raw stderr and all private details stay on the short-lived GitHub
runner. Unrecognised content, SSH diagnostics and multiple lines fail closed
to one generic code. No raw error text is printed or uploaded.
"""

from __future__ import annotations

import os
import re
import stat
import sys

_MAX_BYTES = 2048
_PHASES = frozenset(
    {
        "coordinates",
        "preflight",
        "port",
        "storage",
        "image_inventory",
        "marker",
        "pull",
        "image_provenance",
        "storage_continuity",
        "recipient",
        "volume_create",
        "volume_verify",
        "volume_permissions",
        "network_create",
        "network_verify",
        "container_create",
        "container_verify",
        "listener_health",
    }
)
_PATTERN = re.compile(rb"BOCA_NO_GO: owner enrollment phase=([a-z_]+)\n\Z")


def classify(payload: bytes) -> str:
    """Map only a single exact, ASCII, host-generated failure to a safe code."""
    if not payload or len(payload) > _MAX_BYTES:
        return "unclassified"
    match = _PATTERN.fullmatch(payload)
    if match is None:
        return "unclassified"
    try:
        phase = match[1].decode("ascii")
    except UnicodeError:
        return "unclassified"
    return phase if phase in _PHASES else "unclassified"


def _read_private_stderr(filename: str) -> bytes:
    """Bounded read of a runner-local regular file; never follow symlinks."""
    try:
        descriptor = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        with os.fdopen(descriptor, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                return b""
            return source.read(_MAX_BYTES + 1)
    except OSError:
        return b""


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        return 2
    print(classify(_read_private_stderr(arguments[0])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
