"""R183 READ_ONLY forensic lens for the exact #43217075287 post-commit incident.

No Docker effects, systemd commands, file contents, SQLite bytes, host lease,
network requests, app state changes, worker start or retry. The observer reads
two Boca-only census snapshots and publishes a finite reason from the existing
pair verifier, plus *types only* of four fixed owner-path objects. Its result
never constitutes a Cutover or postcommit recovery authorization.
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from boca_socios import host_boca_census as census
from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair
from boca_socios.host_cutover_inventory_observe import CutoverInventoryNoGo

FAILED_ATTEMPT = "43217075287"
SOURCE_SHA = "b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72"
CONTROLLER_ID = "85316ccec82b11fe2832b6f86473ac2e88167533dda82b5ab86bbe46d7bbf7c2"
WORKER_ID = "8fc47f7981b71a33ae836d6ae36253292c9ef915e463d6c83e2e4451b8cf7def"
CONTROLLER_IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:"
    "b13d08fae35ca48799cbd3134b32bbcb94098f6616692ef86820f81544d5a256"
)
WORKER_IMAGE = (
    "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
    "fa40e8f0e3937c42082be5854ab3fcfc0e83218fb1313a310402f7d54a628d98"
)
PREFIX = b"BOCA_POSTCOMMIT_OBSERVE "
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_OWNER = Path("/home/boca-deploy")
_PARKED = _OWNER / f".boca-on-demand-parked-{FAILED_ATTEMPT}"
_INTENT = _OWNER / f".boca-on-demand-upgrade-{FAILED_ATTEMPT}"
_PATHS = (
    _PARKED,
    _INTENT,
    _PARKED / "socket",
    _PARKED / "socket" / "control.sock",
    _PARKED / "attempt",
    _PARKED / "binding.json",
    _PARKED / "handler.pyz",
    _PARKED / "boca-bot-control.socket",
    _PARKED / "boca-bot-control@.service",
)
_KINDS = frozenset({"ABSENT", "DIRECTORY", "FILE", "SOCKET", "UNSAFE"})
_FIELD_STAGES = {
    "Image": "IMAGE_ID",
    "Config.Image": "IMAGE_REF",
    "State.Health.Status": "HEALTH",
    "State.Status": "STATUS",
    "State.Pid": "PID",
    "State.ExitCode": "EXIT",
    "HostConfig.PortBindings": "PORT",
    "NetworkSettings.Networks": "NETWORK",
    "Mounts": "MOUNTS",
}
_PROBE_STAGES = frozenset(
    {"CENSUS"}
    | {
        f"{role}_{field}"
        for role in ("CONTROLLER", "WORKER")
        for field in (*_FIELD_STAGES.values(), "OCI_LABEL")
    }
)
_PROBE_REASONS = frozenset(
    f"{stage}_{failure}" for stage in _PROBE_STAGES for failure in ("UNAVAILABLE", "EXCEPTION")
) | {"PAIR_INTERNAL_EXCEPTION"}
_REASONS = {
    "unapproved Boca field": "INSPECT_FIELD",
    "Boca process state field unavailable": "PROCESS_FIELD",
    "unverified service mounts": "MOUNTS_UNVERIFIED",
    "unverified mount entry": "MOUNT_ENTRY",
    "duplicated service mount": "MOUNT_DUPLICATED",
    "browser has member data or owner credential volume": "WORKER_DATA_MOUNT",
    "installed Boca pair or volumes unverified": "PAIR_OR_VOLUMES",
    "Boca pair volumes malformed": "VOLUMES_MALFORMED",
    "Boca service labels unverified": "LABELS",
    "OCI image provenance unverified": "OCI_PROVENANCE",
    "Docker health unverified": "HEALTH_FIELD",
    "Boca-only panel host binding unverified": "PORT_BINDING",
    "Boca service process state unverified": "PROCESS_STATE",
    "Boca controller/worker isolation networks identical": "NETWORKS_IDENTICAL",
    "service network isolation unverified": "NETWORK_PROFILE",
    "service network attachment unverified": "NETWORK_ATTACHMENT",
    "service network ID outside Boca census": "NETWORK_ID",
    "historical worker network identity unverified": "HISTORICAL_NETWORK",
    "historical worker received IP address": "HISTORICAL_IP",
    "historical worker gained IP network": "HISTORICAL_EGRESS",
    "historical V3 source and attempt differ": "HISTORICAL_SOURCE",
    "installed Boca mount profile unverified": "MOUNT_PROFILE",
    "controller bind outside Boca control boundary": "CONTROL_BIND",
    "volume not Boca-owned": "VOLUME_OWNER",
    "installed Boca pair changed between reads": "DRIFT",
    "pair provenance ambiguous": "PROVENANCE",
    "invalid pair receipt values": "RECEIPT_VALUES",
    "invalid service provenance or host binding": "RECEIPT_SERVICE",
    "dedicated rootless user identity unverified": "ROOTLESS_IDENTITY",
    "installed pair receipt too long": "RECEIPT_TOO_LONG",
    "unbounded or unbound pair receipt": "RECEIPT_BOUND",
    "bad pair receipt JSON": "RECEIPT_JSON",
    "duplicate receipt fields": "RECEIPT_DUPLICATES",
    "unallowlisted receipt keys": "RECEIPT_KEYS",
    "unexpected pair service fields": "RECEIPT_SCHEMA",
    "pair receipt identity or canonical encoding invalid": "RECEIPT_CANONICAL",
    "observation run ID unverified": "RUN_ID",
    "unknown pair observer mode": "OBSERVER_MODE",
}
_PAIR_REASONS = (
    frozenset((*_REASONS.values(), "PAIR_IDENTITY_MISMATCH", "OTHER_UNVERIFIED", "NONE"))
    | _PROBE_REASONS
)
_FIELDS = frozenset(
    {
        "schema",
        "state",
        "observation_run_id",
        "failed_attempt",
        "new_pair_only",
        "old_ids_absent",
        "pair",
        "pair_reason",
        "parked",
        "intent",
        "socket_directory",
        "socket_node",
        "parked_marker",
        "parked_binding",
        "parked_archive",
        "parked_unit_socket",
        "parked_unit_service",
        "observer_writes",
        "foreign_resources_touched",
        "cutover_authorized",
    }
)
_LIMIT = 768


class PostcommitNoGo(ValueError):
    """The bounded incident proof cannot be trusted."""


class _PairReadFailure(Exception):
    """Only a fixed enumerated stage, never a Docker exception/message."""

    def __init__(self, code: str):
        if code not in _PROBE_REASONS:
            raise PostcommitNoGo("non-allowlisted diagnostic stage")
        self.code = code
        super().__init__("redacted pair field failure")


def _observe_pair_with_failure_stage(run_id: str) -> bytes:
    """Use the same exact pair attestation with bounded provenance on failure.

    The callbacks delegate unchanged to the existing narrow readers. The
    diagnostic publishes only the role/field and coarse exception family,
    never the raw field, failure string, Docker stderr or secret data.
    """
    role = "CONTROLLER"

    def read_census() -> census.CensusSnapshot:
        try:
            return census.capture_container_census()
        except (cleanup.CleanupError, CutoverInventoryNoGo):
            raise _PairReadFailure("CENSUS_UNAVAILABLE") from None
        except Exception:
            raise _PairReadFailure("CENSUS_EXCEPTION") from None

    def read_field(ident: str, field: str) -> object:
        nonlocal role
        role = "CONTROLLER" if ident == CONTROLLER_ID else "WORKER" if ident == WORKER_ID else ""
        if not role or field not in _FIELD_STAGES:
            raise pair.PairNoGo("unapproved Boca field")
        stage = f"{role}_{_FIELD_STAGES[field]}"
        try:
            return pair._fields_from_proven_boca(ident, field)
        except (cleanup.CleanupError, CutoverInventoryNoGo):
            raise _PairReadFailure(f"{stage}_UNAVAILABLE") from None
        except pair.PairNoGo:
            raise
        except Exception:
            raise _PairReadFailure(f"{stage}_EXCEPTION") from None

    def read_oci_label(ident: str, field: str) -> str | None:
        stage = f"{role}_OCI_LABEL"
        try:
            return cleanup._inspect_image_public_oci_label(ident, field)
        except cleanup.CleanupError:
            raise _PairReadFailure(f"{stage}_UNAVAILABLE") from None
        except Exception:
            raise _PairReadFailure(f"{stage}_EXCEPTION") from None

    try:
        return pair.observe(
            run_id,
            inventory_reader=read_census,
            container_field_reader=read_field,
            image_label_reader=read_oci_label,
        )
    except (pair.PairNoGo, _PairReadFailure):
        raise
    except Exception:
        raise _PairReadFailure("PAIR_INTERNAL_EXCEPTION") from None


def _kind(path: Path) -> str:
    """Read only lstat type with an O_NOFOLLOW fd for *every* parent."""
    if path not in _PATHS or not path.is_absolute() or ".." in path.parts:
        raise PostcommitNoGo("path escapes exact Boca incident")
    directory: int | None = None
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        directory = os.open("/", flags)
        for part in path.parts[1:-1]:
            child = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        mode = os.stat(path.name, dir_fd=directory, follow_symlinks=False).st_mode
    except FileNotFoundError:
        return "ABSENT"
    except OSError:
        return "UNSAFE"
    finally:
        if directory is not None:
            os.close(directory)
    if stat.S_ISDIR(mode):
        return "DIRECTORY"
    if stat.S_ISREG(mode):
        return "FILE"
    if stat.S_ISSOCK(mode):
        return "SOCKET"
    return "UNSAFE"


def _pair_only(snapshot: census.CensusSnapshot) -> bool:
    """Only these exact two known Boca CIDs, never a match inferred by name."""
    ids = {item.ident for item in snapshot.containers}
    return len(snapshot.containers) == 2 and ids == {CONTROLLER_ID, WORKER_ID}


def _expected_pair(raw: bytes) -> bool:
    """The generic pair observer must identify *this* failed upgrade exactly."""
    try:
        observed = json.loads(raw.removeprefix(b"BOCA_INSTALLED_PAIR "))
    except (ValueError, TypeError, UnicodeError):
        return False
    if not isinstance(observed, dict):
        return False
    services = observed.get("services")
    if not isinstance(services, list) or len(services) != 2:
        return False
    controller, worker = services
    return bool(
        observed.get("source_sha") == SOURCE_SHA
        and observed.get("attempt_id") == FAILED_ATTEMPT
        and isinstance(controller, dict)
        and isinstance(worker, dict)
        and controller.get("container_id") == CONTROLLER_ID
        and worker.get("container_id") == WORKER_ID
        and controller.get("image_ref") == CONTROLLER_IMAGE
        and worker.get("image_ref") == WORKER_IMAGE
        and controller.get("running") is True
        and controller.get("health") == "healthy"
        and controller.get("port_8443") == "LOOPBACK"
        and worker.get("status") == "created"
        and type(worker.get("pid")) is int
        and worker["pid"] == 0
    )


def _canonical(result: dict[str, object]) -> bytes:
    return (
        PREFIX + json.dumps(result, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
    )


def observe(
    run_id: str,
    *,
    inventory_reader: Callable[[], census.CensusSnapshot] | None = None,
    pair_reader: Callable[[str], bytes] | None = None,
    path_reader: Callable[[Path], str] | None = None,
    effective_uid: int | None = None,
    effective_gid: int | None = None,
) -> bytes:
    if not isinstance(run_id, str) or not _RUN.fullmatch(run_id) or run_id == FAILED_ATTEMPT:
        raise PostcommitNoGo("observation run unverified")
    uid = os.geteuid() if effective_uid is None else effective_uid
    gid = os.getegid() if effective_gid is None else effective_gid
    if (uid, gid) != (10001, 10001):
        raise PostcommitNoGo("dedicated rootless identity absent")
    read_inventory = (
        census.capture_container_census if inventory_reader is None else inventory_reader
    )
    read_pair = _observe_pair_with_failure_stage if pair_reader is None else pair_reader
    read_path = _kind if path_reader is None else path_reader
    first = read_inventory()
    census._topology(first)
    first_paths = tuple(read_path(path) for path in _PATHS)
    if any(kind not in _KINDS for kind in first_paths):
        raise PostcommitNoGo("unexpected file type")
    reason = "NONE"
    pair_state = "PASS"
    try:
        validated = pair.verify(read_pair(run_id), run_id)
        if not _expected_pair(validated):
            reason = "PAIR_IDENTITY_MISMATCH"
            pair_state = "NO_GO"
    except _PairReadFailure as exc:
        reason = exc.code
        pair_state = "NO_GO"
    except pair.PairNoGo as exc:
        reason = _REASONS.get(str(exc), "OTHER_UNVERIFIED")
        pair_state = "NO_GO"
    except Exception:
        reason = "OTHER_UNVERIFIED"
        pair_state = "NO_GO"
    second = read_inventory()
    census._topology(second)
    second_paths = tuple(read_path(path) for path in _PATHS)
    if first != second or first_paths != second_paths or any(k not in _KINDS for k in second_paths):
        raise PostcommitNoGo("forensic read changed between samples")
    pair_only = _pair_only(second)
    if not pair_only and pair_state == "PASS":
        reason = "PAIR_IDENTITY_MISMATCH"
        pair_state = "NO_GO"
    result: dict[str, object] = {
        "schema": 1,
        "state": "OBSERVED",
        "observation_run_id": run_id,
        "failed_attempt": FAILED_ATTEMPT,
        "new_pair_only": pair_only,
        "old_ids_absent": pair_only,
        "pair": pair_state,
        "pair_reason": reason,
        "parked": second_paths[0],
        "intent": second_paths[1],
        "socket_directory": second_paths[2],
        "socket_node": second_paths[3],
        "parked_marker": second_paths[4],
        "parked_binding": second_paths[5],
        "parked_archive": second_paths[6],
        "parked_unit_socket": second_paths[7],
        "parked_unit_service": second_paths[8],
        "observer_writes": 0,
        "foreign_resources_touched": 0,
        "cutover_authorized": False,
    }
    raw = _canonical(result)
    verify(raw, run_id)
    return raw


def _unique(items: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in items:
        if key in value:
            raise PostcommitNoGo("duplicate forensic receipt key")
        value[key] = item
    return value


def verify(raw: bytes, run_id: str) -> bytes:
    if (
        not isinstance(run_id, str)
        or not _RUN.fullmatch(run_id)
        or type(raw) is not bytes
        or len(raw) > _LIMIT
        or not raw.startswith(PREFIX)
        or not raw.endswith(b"\n")
        or raw.count(b"\n") != 1
    ):
        raise PostcommitNoGo("unbounded forensic receipt")
    try:
        item = json.loads(raw[len(PREFIX) :], object_pairs_hook=_unique)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise PostcommitNoGo("malformed forensic receipt") from exc
    if (
        not isinstance(item, dict)
        or item.keys() != _FIELDS
        or type(item["schema"]) is not int
        or item["schema"] != 1
        or item["state"] != "OBSERVED"
        or item["failed_attempt"] != FAILED_ATTEMPT
        or item["observation_run_id"] != run_id
        or type(item["new_pair_only"]) is not bool
        or item["old_ids_absent"] is not item["new_pair_only"]
        or item["pair"] not in ("PASS", "NO_GO")
        or (item["pair"] == "PASS" and item["new_pair_only"] is not True)
        or item["pair_reason"] not in _PAIR_REASONS
        or (item["pair"] == "PASS") != (item["pair_reason"] == "NONE")
        or any(
            item[key] not in _KINDS
            for key in (
                "parked",
                "intent",
                "socket_directory",
                "socket_node",
                "parked_marker",
                "parked_binding",
                "parked_archive",
                "parked_unit_socket",
                "parked_unit_service",
            )
        )
        or type(item["observer_writes"]) is not int
        or item["observer_writes"] != 0
        or type(item["foreign_resources_touched"]) is not int
        or item["foreign_resources_touched"] != 0
        or item["cutover_authorized"] is not False
        or raw != _canonical(item)
    ):
        raise PostcommitNoGo("untrusted forensic receipt fields")
    return raw


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] not in ("host", "verify"):
        return 3
    try:
        raw = (
            observe(args[1])
            if args[0] == "host"
            else verify(sys.stdin.buffer.read(_LIMIT + 1), args[1])
        )
    except Exception:
        return 3
    sys.stdout.buffer.write(raw)
    return 0


if __name__ == "__main__":  # pragma: no cover - protected ZIP entrypoint
    raise SystemExit(main())
