"""Boca-only exact-origin loopback diagnostic; never deployment acceptance.

The host entrypoint is streamed by the existing protected GitHub Action as
``python3 - host <run-id> <main-sha>``. This stdlib-only module never reads a
private file's bytes, enters a user namespace, invokes Docker/systemd, follows
symlinks, contacts a public destination, or changes persistent host state.
It reports only finite categories; in particular a different host UID is
*not* proof of any subordinate-user mapping or trusted Docker mount.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

_PREFIX = b"BOCA_PANEL_ORIGIN_READONLY_V1 "
_FAILURE_PREFIX = b"BOCA_PANEL_ORIGIN_FAILURE_V1 "
_ROOT = Path("/home/boca-deploy/.local/share/docker")
_DIR = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE = os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_HEALTH = frozenset(("HEALTH_HTTP_200", "HEALTH_NON_200", "HEALTH_UNAVAILABLE"))
_SITE = frozenset(("BOTH_FILES_ABSENT", "PRESENT_UNVERIFIED"))
_UID = frozenset(("UID_EQUALS_HOST", "UID_DIFFERS_FROM_HOST", "UID_UNVERIFIED"))
_HOST_FAILURES = frozenset(
    (
        "HOST_INPUT_UNVERIFIED",
        "HOST_SCRIPT_VALIDATION_UNVERIFIED",
        "HOST_UID_UNVERIFIED",
        "HOST_SITE_METADATA_UNVERIFIED",
        "HOST_STORAGE_METADATA_UNVERIFIED",
        "HOST_METADATA_DRIFT_UNVERIFIED",
        "HOST_HEALTH_DRIFT_UNVERIFIED",
    )
)
_SITE_FILES = (
    ("boca-socios_boca_data", "boca-site-url.json", (0o600,)),
    ("boca-socios_boca_site_config", "boca-site-url.runtime.json", (0o644,)),
)
_STORAGE_FILES = (
    ("boca-socios_boca_data", "boca.sqlite3", (0o600,)),
    ("boca-socios_boca_key", "boca_master_key", (0o400, 0o600)),
    ("boca-socios_boca_data", "boca_owner_session.sqlite3", (0o600,)),
)


class ReadonlyWitnessError(ValueError):
    """Fixed redacted NO_GO without paths, URL, identities or host bytes."""


class HostPhaseError(ReadonlyWitnessError):
    """A bounded, advisory failure phase; never a host-acceptance receipt."""

    def __init__(self, phase: str) -> None:
        super().__init__("BOCA_PANEL_DIAG NO_GO")
        self.phase = phase


@dataclass(frozen=True, slots=True)
class _Inode:
    uid: int
    gid: int
    device: int
    number: int
    mode: int
    size: int
    links: int


def probe_health(*, port: int = 8443) -> str:
    """GET exactly `/healthz` at 127.0.0.1 with configured Origin's Host.

    ``port`` injection is only for an offline local HTTP test; host CLI has
    no address, port, path or header input from GitHub or the owner.
    """
    connection: http.client.HTTPConnection | None = None
    try:
        if type(port) is not int or not 1 <= port <= 65535:
            raise ReadonlyWitnessError("BOCA_PANEL_DIAG NO_GO")
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        connection.request(
            "GET", "/healthz", headers={"Host": "localhost:8443", "Connection": "close"}
        )
        response = connection.getresponse()
        if response.status != 200:
            return "HEALTH_NON_200"
        if (
            response.getheader("Content-Length") != "15"
            or response.getheader("Content-Type") != "text/plain; charset=utf-8"
            or response.read(65) != b"BOCA_BETA_READY"
        ):
            return "HEALTH_NON_200"
        return "HEALTH_HTTP_200"
    except (TimeoutError, OSError, http.client.HTTPException):
        return "HEALTH_UNAVAILABLE"
    finally:
        if connection is not None:
            connection.close()


def _metadata(root: Path, volume: str, name: str, modes: tuple[int, ...]) -> _Inode | None:
    """Stat one fixed Boca inode without reading it, following links or globbing."""
    directory = -1
    try:
        if not root.is_absolute() or root == Path("/"):
            raise ReadonlyWitnessError("BOCA_PANEL_DIAG NO_GO")
        directory = os.open("/", _DIR)
        parts = (*root.parts[1:], "volumes", volume, "_data")
        for part in parts:
            child = os.open(part, _DIR, dir_fd=directory)
            os.close(directory)
            directory = child
            info = os.fstat(directory)
            if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o022:
                raise ReadonlyWitnessError("BOCA_PANEL_DIAG NO_GO")
        try:
            descriptor = os.open(name, _FILE, dir_fd=directory)
        except FileNotFoundError:
            return None
        try:
            actual = os.fstat(descriptor)
            named = os.stat(name, dir_fd=directory, follow_symlinks=False)
        finally:
            os.close(descriptor)
        if (
            not stat.S_ISREG(actual.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or actual.st_dev != named.st_dev
            or actual.st_ino != named.st_ino
            or actual.st_uid != named.st_uid
            or actual.st_gid != named.st_gid
            or stat.S_IMODE(actual.st_mode) not in modes
            or actual.st_nlink != 1
            or actual.st_dev <= 0
            or actual.st_ino <= 0
        ):
            raise ReadonlyWitnessError("BOCA_PANEL_DIAG NO_GO")
        return _Inode(
            actual.st_uid,
            actual.st_gid,
            actual.st_dev,
            actual.st_ino,
            stat.S_IMODE(actual.st_mode),
            actual.st_size,
            actual.st_nlink,
        )
    except (OSError, TypeError, ValueError, OverflowError):
        raise ReadonlyWitnessError("BOCA_PANEL_DIAG NO_GO") from None
    finally:
        if directory >= 0:
            os.close(directory)


def snapshot_site_files(root: Path = _ROOT) -> tuple[_Inode | None, ...]:
    """Private metadata needed to reject a concurrent replacement."""
    return tuple(_metadata(root, volume, name, modes) for volume, name, modes in _SITE_FILES)


def probe_site_files(root: Path = _ROOT) -> str:
    """Missing files mean only files absent, never worker or owner readiness."""
    values = snapshot_site_files(root)
    return "BOTH_FILES_ABSENT" if all(item is None for item in values) else "PRESENT_UNVERIFIED"


def snapshot_storage_files(root: Path = _ROOT) -> tuple[_Inode | None, ...]:
    return tuple(_metadata(root, volume, name, modes) for volume, name, modes in _STORAGE_FILES)


def require_stable(first: tuple[_Inode | None, ...], second: tuple[_Inode | None, ...]) -> None:
    if first != second:
        raise ReadonlyWitnessError("BOCA_PANEL_DIAG NO_GO")


def _storage_uid_category(values: tuple[_Inode | None, ...]) -> str:
    if any(item is None for item in values):
        return "UID_UNVERIFIED"
    inodes = [item for item in values if item is not None]
    owner = {(item.uid, item.gid) for item in inodes}
    if len(owner) != 1:
        return "UID_UNVERIFIED"
    return (
        "UID_EQUALS_HOST"
        if next(iter(owner)) == (os.geteuid(), os.getegid())
        else "UID_DIFFERS_FROM_HOST"
    )


def probe_storage_uid(root: Path = _ROOT) -> str:
    """Metadata only; true namespace mapping requires a separate trusted proof."""
    return _storage_uid_category(snapshot_storage_files(root))


def _valid_coordinates(run_id: str, sha: str) -> bool:
    return (
        type(run_id) is str
        and _RUN.fullmatch(run_id) is not None
        and type(sha) is str
        and _HEX40.fullmatch(sha) is not None
    )


def make_receipt(run_id: str, sha: str, health: str, site: str, uid: str) -> bytes:
    if (
        not _valid_coordinates(run_id, sha)
        or health not in _HEALTH
        or site not in _SITE
        or uid not in _UID
    ):
        raise ReadonlyWitnessError("BOCA_PANEL_DIAG NO_GO")
    data = {
        "schema": 1,
        "run_id": run_id,
        "source_sha": sha,
        "health": health,
        "site_files": site,
        "storage_inode_owner": uid,
        "namespace_map": "UNVERIFIED",
        "volume_provenance": "UNVERIFIED",
        "state": "OBSERVED_NO_GO",
        "observer_writes": 0,
        "deploy": "NO_GO",
    }
    return _PREFIX + json.dumps(data, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"


def make_host_failure_marker(run_id: str, sha: str, phase: str) -> bytes:
    """An advisory, run-bound marker with no private paths or host bytes."""
    if not _valid_coordinates(run_id, sha) or phase not in _HOST_FAILURES:
        raise ReadonlyWitnessError("BOCA_PANEL_DIAG NO_GO")
    return _FAILURE_PREFIX + f"{run_id} {sha} {phase}\n".encode("ascii")


def _no_go(reason: str) -> bytes:
    return (
        f"BOCA_PANEL_ORIGIN_READONLY state=NO_GO reason={reason} observer_writes=0 deploy=NO_GO\n"
    ).encode("ascii")


def classify_remote_observation(
    raw: bytes, remote_rc: int, run_id: str, sha: str
) -> tuple[bytes, bool]:
    """Project untrusted SSH output to a finite reason; success remains strict."""
    if (
        type(raw) is not bytes
        or type(remote_rc) is not int
        or not 0 <= remote_rc <= 255
        or not _valid_coordinates(run_id, sha)
    ):
        raise ReadonlyWitnessError("BOCA_PANEL_DIAG NO_GO")
    # OpenSSH 255 and timeout-generated codes are not host-script findings.
    if remote_rc in (124, 137, 143, 255):
        return _no_go("SSH_TRANSPORT_UNVERIFIED"), False
    if remote_rc == 3:
        for phase in _HOST_FAILURES:
            if raw == make_host_failure_marker(run_id, sha, phase):
                return _no_go(phase), False
    if remote_rc != 0 and remote_rc != 3:
        return _no_go("REMOTE_EXECUTION_UNVERIFIED"), False
    if not raw:
        return _no_go("RECEIPT_MISSING" if remote_rc == 0 else "REMOTE_EXECUTION_UNVERIFIED"), False
    if remote_rc != 0:
        return _no_go("RECEIPT_MALFORMED"), False
    try:
        return verify_receipt(raw, run_id, expected_sha=sha), True
    except ReadonlyWitnessError:
        return _no_go("RECEIPT_MALFORMED"), False


def verify_receipt(raw: bytes, run_id: str, *, expected_sha: str | None = None) -> bytes:
    """Bounded canonical projection; no extra host text may enter the summary."""
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= 512 or not raw.startswith(_PREFIX):
            raise ReadonlyWitnessError("BOCA_PANEL_DIAG NO_GO")
        body = json.loads(raw[len(_PREFIX) :])
        if type(body) is not dict or set(body) != {
            "schema",
            "run_id",
            "source_sha",
            "health",
            "site_files",
            "storage_inode_owner",
            "namespace_map",
            "volume_provenance",
            "state",
            "observer_writes",
            "deploy",
        }:
            raise ReadonlyWitnessError("BOCA_PANEL_DIAG NO_GO")
        if (
            type(body["schema"]) is not int
            or body["schema"] != 1
            or body["namespace_map"] != "UNVERIFIED"
            or body["volume_provenance"] != "UNVERIFIED"
            or body["state"] != "OBSERVED_NO_GO"
            or type(body["observer_writes"]) is not int
            or body["observer_writes"] != 0
            or body["deploy"] != "NO_GO"
            or make_receipt(
                body["run_id"],
                body["source_sha"],
                body["health"],
                body["site_files"],
                body["storage_inode_owner"],
            )
            != raw
            or body["run_id"] != run_id
            or (expected_sha is not None and body["source_sha"] != expected_sha)
        ):
            raise ReadonlyWitnessError("BOCA_PANEL_DIAG NO_GO")
        return raw
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise ReadonlyWitnessError("BOCA_PANEL_DIAG NO_GO") from None


def capture(run_id: str, sha: str) -> bytes:
    if not _valid_coordinates(run_id, sha):
        raise HostPhaseError("HOST_INPUT_UNVERIFIED")
    if (os.geteuid(), os.getegid()) != (10001, 10001):
        raise HostPhaseError("HOST_UID_UNVERIFIED")
    first_health = probe_health()
    try:
        first_site = snapshot_site_files()
    except ReadonlyWitnessError:
        raise HostPhaseError("HOST_SITE_METADATA_UNVERIFIED") from None
    try:
        first_storage = snapshot_storage_files()
    except ReadonlyWitnessError:
        raise HostPhaseError("HOST_STORAGE_METADATA_UNVERIFIED") from None
    second_health = probe_health()
    try:
        second_site = snapshot_site_files()
    except ReadonlyWitnessError:
        raise HostPhaseError("HOST_SITE_METADATA_UNVERIFIED") from None
    try:
        second_storage = snapshot_storage_files()
    except ReadonlyWitnessError:
        raise HostPhaseError("HOST_STORAGE_METADATA_UNVERIFIED") from None
    try:
        require_stable(first_site, second_site)
        require_stable(first_storage, second_storage)
    except ReadonlyWitnessError:
        raise HostPhaseError("HOST_METADATA_DRIFT_UNVERIFIED") from None
    if first_health != second_health:
        raise HostPhaseError("HOST_HEALTH_DRIFT_UNVERIFIED")
    return make_receipt(
        run_id,
        sha,
        first_health,
        "BOTH_FILES_ABSENT" if all(value is None for value in first_site) else "PRESENT_UNVERIFIED",
        _storage_uid_category(first_storage),
    )


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if len(args) == 3 and args[0] == "host":
            try:
                receipt = capture(args[1], args[2])
            except HostPhaseError as exc:
                sys.stdout.buffer.write(make_host_failure_marker(args[1], args[2], exc.phase))
                return 3
            except ReadonlyWitnessError:
                sys.stdout.buffer.write(
                    make_host_failure_marker(args[1], args[2], "HOST_SCRIPT_VALIDATION_UNVERIFIED")
                )
                return 3
            sys.stdout.buffer.write(receipt)
            return 0
        if len(args) == 4 and args[0] == "classify":
            if re.fullmatch(r"0|[1-9][0-9]{0,2}", args[1]) is None:
                raise ReadonlyWitnessError("BOCA_PANEL_DIAG NO_GO")
            receipt, accepted = classify_remote_observation(
                sys.stdin.buffer.read(513), int(args[1]), args[2], args[3]
            )
            sys.stdout.buffer.write(receipt)
            return 0 if accepted else 3
        if len(args) == 2 and args[0] == "verify":
            receipt = verify_receipt(sys.stdin.buffer.read(513), args[1])
            sys.stdout.buffer.write(receipt)
            return 0
    except ReadonlyWitnessError:
        pass
    print("BOCA_PANEL_ORIGIN_READONLY state=NO_GO reason=UNVERIFIED observer_writes=0 deploy=NO_GO")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
