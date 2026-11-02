"""Report only canonical, bounded diagnostics from the read-only daemon check."""

from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path

LIMIT = 1024
# Only reasons reachable from host_rootless_setup.infrastructure_check. Unknown
# future reasons fail closed until explicitly reviewed; stderr is never echoed.
REASONS = frozenset(
    {
        "invalid_start_coordinates",
        "dedicated_identity_required",
        "dedicated_account_required",
        "home_unsafe",
        "directory_path_unsafe",
        "directory_owner_or_mode_unsafe",
        "directory_inaccessible_or_redirected",
        "private_directory_required",
        "private_socket_required",
        "rootful_access_forbidden",
        "reviewed_service_configuration_missing",
        "reviewed_service_configuration_unsafe",
        "reviewed_service_configuration_changed",
        "reviewed_service_configuration_mismatch",
        "reviewed_service_configuration_unavailable",
        "reviewed_service_enablement_missing",
        "reviewed_service_enablement_mismatch",
        "dedicated_service_state_unverified",
        "effective_unit_override_preserved_no_stop",
        "dedicated_command_output_unbounded",
        "infrastructure_preflight_requires_stopped_daemon",
        "effective_preflight_unit_unverified",
        "effective_preflight_unit_changed",
        "effective_preflight_command_changed",
        "stale_dedicated_socket_unverified",
        "prepared_container_metadata_unavailable",
        "existing_container_metadata_preserved_no_preflight",
        "metadata_or_io_unavailable",
    }
)
COMMAND_REASON = re.compile(
    rb"user_service_metadata_failed_(?:timeout|unavailable|exit_(?:[1-9][0-9]{0,2}|-[1-9][0-9]?))"
)
ERROR = re.compile(
    rb"BOCA_INFRA_DAEMON state=NO_GO reason=([a-z0-9_-]+)"
    rb" files=preserved_or_partial enablement=UNVERIFIED application_database=not_accessed\n"
)


def _read_bounded(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.getuid()
            or before.st_nlink != 1
            or before.st_size > LIMIT
        ):
            raise ValueError("unverified capture")
        raw = os.read(descriptor, LIMIT + 1)
        after = os.fstat(descriptor)
        linked = path.lstat()
        if (
            len(raw) != before.st_size
            or len(raw) > LIMIT
            or (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns)
            or (after.st_dev, after.st_ino) != (linked.st_dev, linked.st_ino)
            or after.st_nlink != 1
        ):
            raise ValueError("changed capture")
        return raw
    finally:
        os.close(descriptor)


def classify(source_sha: str, code: int, stdout: bytes, stderr: bytes) -> tuple[int, str]:
    if re.fullmatch(r"[0-9a-f]{40}", source_sha) is None:
        raise ValueError("invalid source coordinate")
    state, transport, reason = "INDETERMINATE", "unverified_exit", "unverified_receipt"
    expected = (
        f"BOCA_INFRA_DAEMON state=PREPARED source_sha={source_sha}"
        " containers=absent daemon=stopped\n"
    ).encode("ascii")
    bounded = (
        type(code) is int and 0 <= code <= 255 and len(stdout) <= LIMIT and len(stderr) <= LIMIT
    )
    if code == 0 and bounded and stdout == expected and stderr == b"":
        state, transport, reason = "PREPARED", "confirmed", "none"
    elif code == 1 and bounded and stdout == b"":
        match = ERROR.fullmatch(stderr)
        if match is not None:
            candidate = match[1]
            if candidate.decode("ascii") in REASONS or COMMAND_REASON.fullmatch(candidate):
                state, transport, reason = "NO_GO", "confirmed", candidate.decode("ascii")
    elif code in {124, 137, 255}:
        transport = {124: "timeout", 137: "terminated", 255: "ssh_error"}[code]
    rc = str(code) if type(code) is int and 0 <= code <= 255 else "UNKNOWN"
    receipt = (
        f"BOCA_INFRA_CHECK state={state} source_sha={source_sha} rc={rc}"
        f" transport={transport} reason={reason} start_attempted=no"
    )
    return (0 if state == "PREPARED" else 1), receipt


def main() -> int:
    if len(sys.argv) != 5 or re.fullmatch(r"[0-9a-f]{40}", sys.argv[1]) is None:
        print("BOCA_INFRA_CHECK state=INDETERMINATE reason=invalid_diagnostic_coordinates")
        return 2
    source_sha, raw_code, output, error = sys.argv[1:]
    code = int(raw_code) if re.fullmatch(r"0|[1-9][0-9]{0,2}", raw_code) else -1
    try:
        stdout, stderr = _read_bounded(Path(output)), _read_bounded(Path(error))
    except (OSError, ValueError):
        stdout, stderr = b"", b""
    result, receipt = classify(source_sha, code, stdout, stderr)
    print(receipt)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
