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
from boca_socios import host_boca_pair_observe as pair

FAILED_ATTEMPT = "43217075287"
SOURCE_SHA = "b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72"
CONTROLLER_ID = "85316ccec82b11fe2832b6f86473ac2e88167533dda82b5ab86bbe46d7bbf7c2"
WORKER_ID = "8fc47f7981b71a33ae836d6ae36253292c9ef915e463d6c83e2e4451b8cf7def"
PREFIX = b"BOCA_POSTCOMMIT_OBSERVE "
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_OWNER = Path("/home/boca-deploy")
_PARKED = _OWNER / f".boca-on-demand-parked-{FAILED_ATTEMPT}"
_INTENT = _OWNER / f".boca-on-demand-upgrade-{FAILED_ATTEMPT}"
_PATHS = (_PARKED, _INTENT, _PARKED / "socket", _PARKED / "socket" / "control.sock")
_KINDS = frozenset({"ABSENT", "DIRECTORY", "FILE", "SOCKET", "UNSAFE"})
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
_PAIR_REASONS = frozenset((*_REASONS.values(), "OTHER_UNVERIFIED", "NONE"))
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
        "observer_writes",
        "foreign_resources_touched",
        "cutover_authorized",
    }
)
_LIMIT = 768


class PostcommitNoGo(ValueError):
    """The bounded incident proof cannot be trusted."""


def _kind(path: Path) -> str:
    """Read only lstat type of a hard-coded owner path; never follow the node."""
    if path not in _PATHS:
        raise PostcommitNoGo("path escapes exact Boca incident")
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return "ABSENT"
    except OSError:
        return "UNSAFE"
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
    read_pair = pair.observe if pair_reader is None else pair_reader
    read_path = _kind if path_reader is None else path_reader
    first = read_inventory()
    census._topology(first)
    first_paths = tuple(read_path(path) for path in _PATHS)
    if any(kind not in _KINDS for kind in first_paths):
        raise PostcommitNoGo("unexpected file type")
    reason = "NONE"
    pair_state = "PASS"
    try:
        pair.verify(read_pair(run_id), run_id)
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
        or item["pair_reason"] not in _PAIR_REASONS
        or (item["pair"] == "PASS") != (item["pair_reason"] == "NONE")
        or any(
            item[key] not in _KINDS
            for key in ("parked", "intent", "socket_directory", "socket_node")
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
