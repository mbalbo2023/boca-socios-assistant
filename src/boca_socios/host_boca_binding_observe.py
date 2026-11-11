"""Attest already-installed Boca systemd binding READ_ONLY, never upgrade.

The pair inventory is independently rechecked before and after two reads of
the existing digest-pinned owner socket binding. `host_on_demand_service`
already validates the exact unit fragments, hardlinks, manager socket state,
archive digest, owner UID and canonical installation without taking a lease.
This diagnostic never opens SQLite, prints its path, reads Env or mutates a
Docker/systemd resource. A receipt is *not* approval to replace the pair.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable, Sequence

from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_on_demand_service as service
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

PREFIX = b"BOCA_INSTALLED_BINDING "
_NO_GO = b"BOCA_INSTALLED_BINDING state=NO_GO reason=BINDING_UNVERIFIED observer_writes=0\n"
_MAX_BYTES = 1_664
_ID = re.compile(r"[0-9a-f]{64}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
CANONICAL_DATABASE = service._HOME / service._DB
_FIELDS = frozenset(
    {
        "schema",
        "state",
        "observation_run_id",
        "source_sha",
        "installation_run_id",
        "controller_id",
        "worker_id",
        "binding_systemd",
        "binding_archive",
        "binding_pair",
        "sqlite_inode",
        "worker_exit_code",
        "observer_writes",
        "foreign_resources_touched",
        "apply_authorized",
    }
)


class BindingNoGo(ValueError):
    """Installed Boca control binding absent, stale or unverifiable."""


def _read_host_binding() -> OnDemandInstallation:
    # Reuse the sole canonical on-demand binder's already-reviewed filesystem
    # and systemctl attestation. This private function reads but never creates
    # the protected lock or writes a file; unlike read_installed_binding(lease).
    return service._verified_installation(service._home())


def _unique(entries: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in entries:
        if key in result:
            raise BindingNoGo("duplicate receipt field")
        result[key] = value
    return result


def _canonical(value: dict[str, object]) -> bytes:
    return PREFIX + json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"


def _attest(run_id: str, pair_raw: bytes, item: OnDemandInstallation) -> dict[str, object]:
    pair.verify(pair_raw, run_id)
    payload = json.loads(pair_raw[len(pair._PREFIX) :], object_pairs_hook=_unique)
    controller, worker = payload["services"]
    if (
        type(item) is not OnDemandInstallation
        or item.database_path != CANONICAL_DATABASE
        or item.source_sha != payload["source_sha"]
        or item.installation_run_id != payload["attempt_id"]
        or item.controller_id != controller["container_id"]
        or item.worker_id != worker["container_id"]
        or item.controller_image != controller["image_ref"]
        or item.worker_image != worker["image_ref"]
        or item.pair.original_browser_attempt != item.installation_run_id
        or item.pair.controller_config_hash != controller["config_hash"]
        or item.pair.worker_config_hash != worker["config_hash"]
        or item.pair.sender_id
        or item.pair.sender_config_hash
        or item.pair.sender_attempt_id
        or item.pair.sender_running
        or controller["status"] != "running"
        or controller["health"] != "healthy"
        or worker["running"] is not False
        or worker["status"] not in ("created", "exited")
        or worker["pid"] != 0
        or payload["ipc_volume"] != "BOTH"
    ):
        raise BindingNoGo("systemd binding does not match installed Boca pair")
    return {
        "schema": 1,
        "state": "OBSERVED_NO_GO",
        "observation_run_id": run_id,
        "source_sha": item.source_sha,
        "installation_run_id": item.installation_run_id,
        "controller_id": item.controller_id,
        "worker_id": item.worker_id,
        "binding_systemd": "VERIFIED_LISTENING",
        "binding_archive": "VERIFIED_SHA256",
        "binding_pair": "MATCHED_EXACT",
        "sqlite_inode": "UNVERIFIED",
        "worker_exit_code": worker["exit_code"],
        "observer_writes": 0,
        "foreign_resources_touched": 0,
        "apply_authorized": False,
    }


def observe(
    run_id: str,
    *,
    pair_reader: Callable[[str], bytes] | None = None,
    binding_reader: Callable[[], OnDemandInstallation] | None = None,
    effective_uid: int | None = None,
    effective_gid: int | None = None,
) -> bytes:
    """Take four independent Docker inventories and two systemd checks."""
    uid = os.geteuid() if effective_uid is None else effective_uid
    gid = os.getegid() if effective_gid is None else effective_gid
    if not isinstance(run_id, str) or not _RUN.fullmatch(run_id) or (uid, gid) != (10001, 10001):
        raise BindingNoGo("dedicated rootless observer identity invalid")
    observe_pair = pair.observe if pair_reader is None else pair_reader
    read_binding = _read_host_binding if binding_reader is None else binding_reader
    first_pair = observe_pair(run_id)
    first_binding = read_binding()
    second_binding = read_binding()
    second_pair = observe_pair(run_id)
    if first_pair != second_pair or first_binding != second_binding:
        raise BindingNoGo("pair or systemd binding changed during observation")
    raw = _canonical(_attest(run_id, second_pair, second_binding))
    verify(raw, run_id)
    return raw


def verify(raw: bytes, run_id: str) -> bytes:
    """Runner must separately verify an exact compact no-GO receipt."""
    if (
        not isinstance(raw, bytes)
        or len(raw) > _MAX_BYTES
        or not raw.startswith(PREFIX)
        or not raw.endswith(b"\n")
        or not isinstance(run_id, str)
        or not _RUN.fullmatch(run_id)
    ):
        raise BindingNoGo("binding receipt framing invalid")
    try:
        value = json.loads(raw[len(PREFIX) :], object_pairs_hook=_unique)
    except (ValueError, UnicodeError):
        raise BindingNoGo("binding receipt JSON invalid") from None
    if (
        not isinstance(value, dict)
        or value.keys() != _FIELDS
        or type(value["schema"]) is not int
        or value["schema"] != 1
        or value["state"] != "OBSERVED_NO_GO"
        or value["observation_run_id"] != run_id
        or not isinstance(value["source_sha"], str)
        or not _SHA.fullmatch(value["source_sha"])
        or not isinstance(value["installation_run_id"], str)
        or not _RUN.fullmatch(value["installation_run_id"])
        or any(
            not isinstance(value[key], str) or not _ID.fullmatch(value[key])
            for key in ("controller_id", "worker_id")
        )
        or value["controller_id"] == value["worker_id"]
        or value["binding_systemd"] != "VERIFIED_LISTENING"
        or value["binding_archive"] != "VERIFIED_SHA256"
        or value["binding_pair"] != "MATCHED_EXACT"
        or value["sqlite_inode"] != "UNVERIFIED"
        or type(value["worker_exit_code"]) is not int
        or not -1 <= value["worker_exit_code"] <= 255
        or type(value["observer_writes"]) is not int
        or value["observer_writes"] != 0
        or type(value["foreign_resources_touched"]) is not int
        or value["foreign_resources_touched"] != 0
        or value["apply_authorized"] is not False
        or raw != _canonical(value)
    ):
        raise BindingNoGo("binding receipt assertions invalid")
    return raw


def main(argv: Sequence[str]) -> int:
    try:
        if len(argv) != 2 or argv[0] not in ("host", "verify"):
            raise BindingNoGo("unknown observer mode")
        raw = (
            observe(argv[1])
            if argv[0] == "host"
            else verify(sys.stdin.buffer.read(_MAX_BYTES + 1), argv[1])
        )
        sys.stdout.buffer.write(raw)
        return 0
    except Exception:
        sys.stdout.buffer.write(_NO_GO)
        return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
