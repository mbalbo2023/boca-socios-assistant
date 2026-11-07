"""Classify one failed Cutover-A observation from private, bounded runner files.

Never publish host stderr, its paths or arbitrary exception messages. The
fixed-literal allowlist is intentionally *not* a parser of `str(exc)` in
general. Unknown changes to host error wording remain NO_GO/UNVERIFIED.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from check_infrastructure_diagnostic import _read_bounded

_EXACT_READY_BYTES = 710
_READY_PREFIX = b"BOCA_CUTOVER_A_OBSERVE state=READY "

# Each right-hand side is a public category; each left-hand side is an exact,
# constant error from the previously reviewed host_first_deploy.py. No dynamic
# Docker stderr, OSError, path, input, envelope or subject is admitted.
_KNOWN_ERRORS = {
    b"cutover A historical and target release identities are unproven": "RELEASE_IDENTITY",
    b"invalid immutable deployment coordinates": "RELEASE_IDENTITY",
    b"invalid private owner origin": "OWNER_CONTEXT",
    b"invalid private BETA coordinates": "OWNER_CONTEXT",
    b"invalid private BETA port": "OWNER_CONTEXT",
    b"Docker Engine >=28 required for private localhost publication": "DOCKER_VERSION",
    b"dedicated rootless socket or rootful Docker access is unsafe": "ROOTLESS_BOUNDARY",
    b"Docker daemon must be rootless for the dedicated Boca identity": "ROOTLESS_BOUNDARY",
    b"rootless Docker cannot prove enforceable cgroup limits": "ROOTLESS_BOUNDARY",
    b"rootless CPU, memory and PID controllers must be delegated": "ROOTLESS_BOUNDARY",
    b"unsafe staged BETA directory": "LEGACY_COMPOSE",
    b"staged BETA Compose differs from reviewed file": "LEGACY_COMPOSE",
    b"installed Boca namespace differs from reviewed BETA": "VOLUME_INVENTORY",
    b"installed Boca network inventory differs from reviewed BETA": "NETWORK_INVENTORY",
    b"installed Boca controller identity or resources are unsafe": "CONTROLLER_IDENTITY",
    b"invalid host MemAvailable observation": "HOST_OBSERVATION",
    b"invalid host CPU headroom observation": "HOST_OBSERVATION",
    b"Boca owner volume identity is unsafe": "VOLUME_IDENTITY",
    b"Boca key volume identity is unsafe": "VOLUME_IDENTITY",
    b"Boca data volume identity is unsafe": "VOLUME_IDENTITY",
    b"expected exactly one Boca controller": "CONTROLLER_SINGLETON",
    b"dedicated BETA daemon has an unexpected container": "DOCKER_INVENTORY",
    b"installed Boca network identity changed": "NETWORK_INVENTORY",
    b"BETA host loopback health unavailable": "LOOPBACK_HTTP",
    b"BETA host SSH-loopback HTTP unavailable": "LOOPBACK_HTTP",
    b"insufficient Boca staging or rootless Docker storage": "STORAGE",
    b"cutover A installed controller ID differs from historic receipt": "CONTROLLER_IDENTITY",
    b"cutover A original persistent Boca inventory changed": "VOLUME_INVENTORY",
    b"dedicated Boca daemon contains an unexpected container": "DOCKER_INVENTORY",
    b"dedicated Boca volume inventory changed": "VOLUME_INVENTORY",
    b"dedicated Boca network inventory changed": "NETWORK_INVENTORY",
    b"private Boca staging directory is unsafe": "STAGING",
    b"private Boca staging directory identity changed": "STAGING",
    b"Boca staging directory cannot be inventoried": "STAGING",
    b"Boca browser staging contains unexpected files": "STAGING",
    b"cutover A original controller is not healthy": "CONTROLLER_HEALTH",
}


def classify(code: int, stdout: bytes, stderr: bytes) -> tuple[int, str]:
    """Return (decision code, public receipt); only genuine READY can proceed.

    A fixed remote message is a *claim* of validation failure, not an
    independent attestation of host state or a GO for another operation.
    """
    category, reason, evidence = "UNVERIFIED", "UNVERIFIED", "UNVERIFIED"
    if code == 0 and type(code) is int:
        if (
            stderr == b""
            and stdout.startswith(_READY_PREFIX)
            and len(stdout) == _EXACT_READY_BYTES
            and stdout.endswith(b"\n")
            and stdout.count(b"\n") == 1
            and all(32 <= byte <= 126 for byte in stdout[:-1])
        ):
            return 0, ""
    elif type(code) is int and code in (124, 137):
        category, reason = "TIMEOUT", "TIMEOUT"
    elif type(code) is int and code == 255:
        category, reason = "SSH_255", "SSH_255"
    elif type(code) is int and code == 1 and stdout == b"" and len(stderr) <= 1024:
        if stderr.startswith(b"BOCA_NO_GO: ") and stderr.endswith(b"\n"):
            message = stderr[len(b"BOCA_NO_GO: ") : -1]
            matched = _KNOWN_ERRORS.get(message)
            if matched is not None:
                category, reason, evidence = "HOST_VALIDATION", matched, "REMOTE_CLAIM"

    receipt = (
        f"BOCA_CUTOVER_A_OBSERVE state=NO_GO class={category} reason={reason}"
        f" evidence={evidence} host=UNVERIFIED original=UNVERIFIED"
        " effects=UNVERIFIED cutover=NO_GO no_retry=1"
    )
    return 1, receipt


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3 or re.fullmatch(r"0|[1-9][0-9]{0,2}", args[0]) is None:
        status, report = classify(-1, b"", b"")
    else:
        code = int(args[0])
        try:
            stdout = _read_bounded(Path(args[1]))
            stderr = _read_bounded(Path(args[2]))
        except (OSError, ValueError):
            # A changed or redirected private runner file cannot establish
            # either a successful observation or a specific host rejection.
            if code in (124, 137, 255):
                status, report = classify(code, b"", b"")
            else:
                status, report = classify(-1, b"", b"")
        else:
            status, report = classify(code, stdout, stderr)
    if report:
        print(report)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
