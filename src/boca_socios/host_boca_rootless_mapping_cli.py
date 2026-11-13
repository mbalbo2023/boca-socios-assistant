"""R259 standalone Boca-rootless metadata preflight; never a deploy receipt.

Obtain the *existing* canonical flock without creating a lock file. Bind the
live controller PID to R177's Boca-only global census and exact installed
systemd archive, then compare actual rootless UID/GID maps and three private
file inodes twice. No cleanup SUCCESS or PostflightExpected is synthesized:
the resulting category is PRELIMINARY_PREDEPLOY, never BETA acceptance.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from boca_socios import host_boca_binding_observe as binding
from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_rootless_mapped_custody as custody
from boca_socios import host_first_deploy as host
from boca_socios import host_on_demand_service as service

_PREFIX = b"BOCA_ROOTLESS_MAPPING "
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_CID = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = frozenset(
    {
        "schema",
        "attempt_id",
        "stage",
        "state",
        "observer_writes",
        "foreign_resources_touched",
        "cutover_authorized",
        "lease_verified",
    }
)
_FAILURE_FIELDS = _FIELDS | {"failed_boundary"}
_BOUNDARIES = frozenset(
    {"LEASE", "PAIR_BINDING", "VOLUMES", "PID_MAP", "INODES", "STABILITY", "INTERNAL"}
    | {f"INODES_{reason}" for reason in custody._REASONS}
)
_MAX_BYTES = 1024


class MappingBridgeNoGo(ValueError):
    """Public refusal never carries Docker, /proc, volume or private data."""

    def __init__(self, failed_boundary: str = "INTERNAL") -> None:
        super().__init__("BOCA_ROOTLESS_MAPPING NO_GO")
        self.failed_boundary = failed_boundary if failed_boundary in _BOUNDARIES else "INTERNAL"


def _fail() -> MappingBridgeNoGo:
    return MappingBridgeNoGo("BOCA_ROOTLESS_MAPPING NO_GO")


def _unique(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise _fail()
        result[key] = value
    return result


def encode(
    run_id: str, state: str, *, lease_verified: bool, failed_boundary: str = "NONE"
) -> bytes:
    if (
        type(run_id) is not str
        or _RUN.fullmatch(run_id) is None
        or type(lease_verified) is not bool
        or (state, lease_verified) not in (("PRELIMINARY_PREDEPLOY", True), ("NO_GO", False))
        or (
            failed_boundary != "NONE"
            if state == "PRELIMINARY_PREDEPLOY"
            else failed_boundary not in _BOUNDARIES
        )
    ):
        raise _fail()
    payload = {
        "schema": 1 if state == "PRELIMINARY_PREDEPLOY" else 2,
        "attempt_id": run_id,
        "stage": "PREDEPLOY",
        "state": state,
        "observer_writes": 0,
        "foreign_resources_touched": 0,
        "cutover_authorized": False,
        "lease_verified": lease_verified,
    }
    if state == "NO_GO":
        payload["failed_boundary"] = failed_boundary
    return _PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def verify(raw: bytes, run_id: str) -> bytes:
    try:
        if (
            type(raw) is not bytes
            or not 0 < len(raw) <= _MAX_BYTES
            or not raw.startswith(_PREFIX)
            or not raw.endswith(b"\n")
            or raw.count(b"\n") != 1
        ):
            raise _fail()
        value = json.loads(raw[len(_PREFIX) :], object_pairs_hook=_unique)
        if (
            type(value) is not dict
            or value.keys()
            != (_FIELDS if value.get("state") == "PRELIMINARY_PREDEPLOY" else _FAILURE_FIELDS)
            or type(value["schema"]) is not int
            or value["schema"] != (1 if value.get("state") == "PRELIMINARY_PREDEPLOY" else 2)
            or value["attempt_id"] != run_id
            or value["stage"] != "PREDEPLOY"
            or type(value["observer_writes"]) is not int
            or value["observer_writes"] != 0
            or type(value["foreign_resources_touched"]) is not int
            or value["foreign_resources_touched"] != 0
            or value["cutover_authorized"] is not False
            or (value["state"], value["lease_verified"])
            not in (("PRELIMINARY_PREDEPLOY", True), ("NO_GO", False))
            or type(value["lease_verified"]) is not bool
            or encode(
                run_id,
                value["state"],
                lease_verified=value["lease_verified"],
                failed_boundary=value.get("failed_boundary", "NONE"),
            )
            != raw
        ):
            raise _fail()
        return raw
    except Exception:
        raise _fail() from None


@contextmanager
def _readonly_lease(run_id: str) -> Iterator[cleanup.BocaJobLease]:
    """Use existing Boca flock, O_CREAT forbidden even on first observation."""
    folder = -1
    handle = -1
    lease: cleanup.BocaJobLease | None = None
    try:
        if (
            type(run_id) is not str
            or _RUN.fullmatch(run_id) is None
            or (os.geteuid(), os.getegid()) != (cleanup.EXPECTED_UID, cleanup.EXPECTED_GID)
        ):
            raise _fail()
        folder = os.open(
            cleanup.LEASE_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        directory = os.fstat(folder)
        if (
            not stat.S_ISDIR(directory.st_mode)
            or (directory.st_uid, directory.st_gid) != (cleanup.EXPECTED_UID, cleanup.EXPECTED_GID)
            or stat.S_IMODE(directory.st_mode) != 0o700
        ):
            raise _fail()
        handle = os.open(
            cleanup.LEASE_FILE, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=folder
        )
        item = os.fstat(handle)
        if (
            not stat.S_ISREG(item.st_mode)
            or (item.st_uid, item.st_gid) != (cleanup.EXPECTED_UID, cleanup.EXPECTED_GID)
            or stat.S_IMODE(item.st_mode) != 0o600
            or item.st_nlink != 1
            or item.st_size != 0
        ):
            raise _fail()
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lease = cleanup.BocaJobLease(run_id, handle, os.getpid(), True)
        cleanup.verify_protected_boca_job_lease(lease, run_id)
        yield lease
    except Exception:
        raise _fail() from None
    finally:
        if lease is not None:
            lease.active = False
        if handle >= 0:
            os.close(handle)
        if folder >= 0:
            os.close(folder)


def _pair_and_archive(run_id: str, lease: cleanup.BocaJobLease) -> tuple[bytes, object, str, int]:
    """Use only fresh R177 Docker proof and the digest-pinned systemd archive."""
    cleanup.verify_protected_boca_job_lease(lease, run_id)
    raw = pair.observe(run_id)
    pair.verify(raw, run_id)
    installed = service.read_installed_binding(lease)
    binding._attest(run_id, raw, installed)
    controller = json.loads(raw[len(pair._PREFIX) :])["services"][0]
    cid, pid = controller["container_id"], controller["pid"]
    if (
        type(cid) is not str
        or _CID.fullmatch(cid) is None
        or type(pid) is not int
        or not 1 < pid < 2**31
    ):
        raise _fail()
    cleanup.verify_protected_boca_job_lease(lease, run_id)
    return raw, installed, cid, pid


def _mapped_owner(cid: str, pid: int) -> custody.MappedOwner:
    """Exact verified Boca CID must still point to original PID at both reads."""
    if type(cid) is not str or _CID.fullmatch(cid) is None:
        raise _fail()

    def pinned_pid() -> int:
        value = json.loads(cleanup._docker("inspect", "--format", "{{json .State.Pid}}", cid))
        if type(value) is not int or value != pid:
            raise _fail()
        return value

    pinned_pid()
    owner = custody.read_proc_mapped_owner(pid)
    pinned_pid()
    if type(owner) is not custody.MappedOwner:
        raise _fail()
    return owner


def _volumes() -> None:
    """Existing reviewed exact Boca local volume/label/root attestors only."""
    if host._checked_docker_storage_dir() != custody._DOCKER_ROOT:
        raise _fail()
    host._validate_data_volume()
    host._validate_key_volume()
    host._validate_owner_volume()


def observe_predeploy(run_id: str) -> bytes:
    """No host writes, no external probes, no final postflight/upgrade GO."""
    boundary = "LEASE"
    try:
        with _readonly_lease(run_id) as lease:
            boundary = "PAIR_BINDING"
            first = _pair_and_archive(run_id, lease)
            boundary = "VOLUMES"
            _volumes()
            boundary = "PID_MAP"
            first_owner = _mapped_owner(first[2], first[3])
            boundary = "INODES"
            first_files = custody.capture_mapped_custody(
                custody._DOCKER_ROOT, first_owner, trusted_root=custody._DOCKER_ROOT
            )
            boundary = "VOLUMES"
            _volumes()
            boundary = "PAIR_BINDING"
            second = _pair_and_archive(run_id, lease)
            boundary = "PID_MAP"
            second_owner = _mapped_owner(second[2], second[3])
            boundary = "INODES"
            second_files = custody.capture_mapped_custody(
                custody._DOCKER_ROOT, second_owner, trusted_root=custody._DOCKER_ROOT
            )
            boundary = "VOLUMES"
            _volumes()
            boundary = "PAIR_BINDING"
            third = _pair_and_archive(run_id, lease)
            boundary = "STABILITY"
            if (
                first != second
                or second != third
                or first_owner != second_owner
                or first_files != second_files
            ):
                raise _fail()
            cleanup.verify_protected_boca_job_lease(lease, run_id)
        return encode(run_id, "PRELIMINARY_PREDEPLOY", lease_verified=True)
    except custody.MappedCustodyNoGo as exc:
        if boundary == "INODES":
            boundary = f"INODES_{exc.reason}"
        raise MappingBridgeNoGo(boundary) from None
    except Exception:
        raise MappingBridgeNoGo(boundary) from None


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] not in ("observe", "verify") or _RUN.fullmatch(args[1]) is None:
        return 3
    if args[0] == "verify":
        try:
            raw = verify(sys.stdin.buffer.read(_MAX_BYTES + 1), args[1])
        except Exception:
            return 4  # Never convert malformed/forged host bytes into authenticated NO_GO.
    else:
        try:
            raw = observe_predeploy(args[1])
        except MappingBridgeNoGo as exc:
            raw = encode(
                args[1], "NO_GO", lease_verified=False, failed_boundary=exc.failed_boundary
            )
        except Exception:
            raw = encode(args[1], "NO_GO", lease_verified=False, failed_boundary="INTERNAL")
    state = json.loads(raw[len(_PREFIX) :])["state"]
    sys.stdout.buffer.write(raw)
    return 0 if state == "PRELIMINARY_PREDEPLOY" else 3


if __name__ == "__main__":  # pragma: no cover - protected memfd CLI entrypoint
    raise SystemExit(main())
