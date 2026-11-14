"""Current-pair resource custody, separate from the immutable R188 V1 lens.

The original resource creators remain pinned. Installed source, binding,
container IDs and control inode come only from two genuine current reads.
No host mutation, migration, worker start or provider request is performed.
Canonical integrity alone never authenticates an Actions artifact.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_retained_resources as legacy

if TYPE_CHECKING:
    from boca_socios.host_on_demand_lifecycle import OnDemandInstallation, PanelStatus

PREFIX = b"BOCA_CURRENT_RETAINED_V2 "
LIMIT = 8192
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_FIELDS = frozenset(
    {
        "schema",
        "state",
        "scope",
        "observation_run_id",
        "source_sha",
        "installation_attempt",
        "pair",
        "volumes",
        "egress",
        "control_socket_directory_inode_sha256",
        "binding_fingerprint",
        "worker_idle",
        "observer_writes",
        "foreign_resources_touched",
        "successor_apply_authorized",
    }
)
_CREATORS = ((legacy._IPC, "42806447101"), (legacy._SITE, "43217075287"))


class CurrentRetainedNoGo(ValueError):
    """A fixed, redacted refusal; never raw host data or exception text."""


def _fail() -> CurrentRetainedNoGo:
    return CurrentRetainedNoGo("current Boca retained custody unverified")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def _uuid(value: object) -> bool:
    try:
        return type(value) is str and str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def read_panel_status(installation: OnDemandInstallation) -> PanelStatus | None:
    # Host-only dependency: the runner verifies canonical receipts using the
    # standard library, without importing the application's package initializers.
    from boca_socios.host_on_demand_lifecycle import read_panel_status as read

    return read(installation)


def idle_evidence(worker: dict[str, Any], status: PanelStatus | None) -> dict[str, object]:
    """An exited old worker needs an actual terminal STOP for this binding.

    The caller must use read_panel_status() after exact binding attestation;
    that existing reader verifies the operation's installation fingerprint.
    This function does not bless arbitrary status dictionaries as authority.
    """
    if (
        worker.get("running") is not False
        or type(worker.get("pid")) is not int
        or worker["pid"] != 0
        or type(worker.get("exit_code")) is not int
        or worker["exit_code"] != 0
    ):
        raise _fail()
    if worker.get("status") == "created":
        return {"state": "CREATED", "operation_id": None}
    from boca_socios.host_on_demand_lifecycle import PanelStatus, validate_panel_status

    if worker.get("status") != "exited" or type(status) is not PanelStatus:
        raise _fail()
    validate_panel_status(status)
    if (status.target, status.status, status.cause) != ("stop", "APPLIED", "NONE"):
        raise _fail()
    return {"state": "STOP_APPLIED", "operation_id": status.operation_id}


def verify(raw: bytes, run_id: str) -> dict[str, Any]:
    """Verify the distinct V2 schema; this does not authenticate origin."""
    try:
        if (
            type(raw) is not bytes
            or not 0 < len(raw) <= LIMIT
            or not raw.startswith(PREFIX)
            or not raw.endswith(b"\n")
            or raw.count(b"\n") != 1
            or type(run_id) is not str
            or _RUN.fullmatch(run_id) is None
        ):
            raise _fail()
        value = json.loads(raw[len(PREFIX) :], object_pairs_hook=pair._unique)
        if (
            type(value) is not dict
            or value.keys() != _FIELDS
            or raw != PREFIX + _canonical(value) + b"\n"
        ):
            raise _fail()
        if (
            type(value["schema"]) is not int
            or value["schema"] != 2
            or value["state"] != "READ_ONLY"
            or value["scope"] != "CURRENT_PAIR"
            or value["observation_run_id"] != run_id
            or type(value["observer_writes"]) is not int
            or value["observer_writes"] != 0
            or type(value["foreign_resources_touched"]) is not int
            or value["foreign_resources_touched"] != 0
            or value["successor_apply_authorized"] is not False
            or any(
                type(value[key]) is not str or _HASH.fullmatch(value[key]) is None
                for key in ("control_socket_directory_inode_sha256", "binding_fingerprint")
            )
        ):
            raise _fail()
        observed = value["pair"]
        pair.verify(pair._canonical(observed), run_id)
        controller, worker = observed["services"]
        if (
            value["source_sha"] != observed["source_sha"]
            or value["installation_attempt"] != observed["attempt_id"]
            or int(value["installation_attempt"]) >= int(run_id)
            or controller["running"] is not True
            or controller["status"] != "running"
            or controller["health"] != "healthy"
            or observed["ipc_volume"] != "BOTH"
            or worker["running"] is not False
            or worker["pid"] != 0
            or worker["exit_code"] != 0
        ):
            raise _fail()
        idle = value["worker_idle"]
        if type(idle) is not dict or idle.keys() != {"state", "operation_id"}:
            raise _fail()
        if worker["status"] == "created":
            if idle != {"state": "CREATED", "operation_id": None}:
                raise _fail()
        elif (
            worker["status"] != "exited"
            or idle["state"] != "STOP_APPLIED"
            or not _uuid(idle["operation_id"])
        ):
            raise _fail()
        volumes = value["volumes"]
        if type(volumes) is not list or len(volumes) != 2:
            raise _fail()
        for volume, (name, creator) in zip(volumes, _CREATORS, strict=True):
            if (
                type(volume) is not dict
                or volume.keys()
                != {"name", "creator_attempt", "inode_sha256", "container_references"}
                or volume["name"] != name
                or volume["creator_attempt"] != creator
                or type(volume["inode_sha256"]) is not str
                or _HASH.fullmatch(volume["inode_sha256"]) is None
                or type(volume["container_references"]) is not int
                or volume["container_references"] != 2
            ):
                raise _fail()
        network = value["egress"]
        if (
            type(network) is not dict
            or network.keys() != {"name", "id", "peer_ids", "creator_attempt"}
            or network["name"] != legacy._EGRESS
            or network["creator_attempt"] != "43217075287"
            or type(network["id"]) is not str
            or _HASH.fullmatch(network["id"]) is None
            or network["peer_ids"] != []
        ):
            raise _fail()
        return cast(dict[str, Any], value)
    except Exception:
        raise _fail() from None


def require_pair(raw: bytes, run_id: str, pair_raw: bytes, pair_run: str) -> dict[str, Any]:
    """Cross-bind a current receipt to the independently authenticated pair."""
    value = verify(raw, run_id)
    pair.verify(pair_raw, pair_run)
    expected = json.loads(pair_raw.removeprefix(pair._PREFIX))
    actual = dict(value["pair"])
    actual["observation_run_id"] = pair_run
    if actual != expected:
        raise _fail()
    return value


def decode(raw: bytes) -> dict[str, Any]:
    """Read a run coordinate only to invoke the strict bounded verifier."""
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= LIMIT or not raw.startswith(PREFIX):
            raise _fail()
        value = json.loads(raw[len(PREFIX) :], object_pairs_hook=pair._unique)
        return verify(raw, value["observation_run_id"])
    except Exception:
        raise _fail() from None


def require_worker(worker: dict[str, Any], ident: str, raw: bytes | None = None) -> None:
    """Keep CREATED default; permit clean EXITED only for the proven old CID.

    An authenticated current receipt supplies the stopped-worker exception.
    No successor candidate, arbitrary CID or legacy V1 gets that exception.
    """
    if worker.get("status") == "created":
        idle_evidence(worker, None)
        return
    if raw is None:
        raise _fail()
    value = decode(raw)
    old = value["pair"]["services"][1]
    if (
        old["container_id"] != ident
        or value["worker_idle"]["state"] != "STOP_APPLIED"
        or any(worker.get(key) != old[key] for key in ("status", "running", "pid", "exit_code"))
    ):
        raise _fail()


def docker_worker(state: dict[str, Any]) -> dict[str, Any]:
    """Fixed projection only; reading a state never authorizes admission."""
    return {
        key: state.get(source)
        for key, source in (
            ("status", "Status"),
            ("running", "Running"),
            ("pid", "Pid"),
            ("exit_code", "ExitCode"),
        )
    }


def reprove_binding(raw: bytes | None, installed: OnDemandInstallation) -> None:
    """Same-lease current binding and STOP ACK, before any successor effect."""
    if raw is None:
        return
    from boca_socios import host_boca_binding_observe as binding

    value = decode(raw)
    binding._attest(value["observation_run_id"], pair._canonical(value["pair"]), installed)
    if installed.fingerprint() != value["binding_fingerprint"]:
        raise _fail()
    if value["worker_idle"]["state"] == "STOP_APPLIED":
        first, second = read_panel_status(installed), read_panel_status(installed)
        if (
            first != second
            or idle_evidence(value["pair"]["services"][1], first) != value["worker_idle"]
        ):
            raise _fail()


def snapshot(run_id: str) -> dict[str, object]:
    """Only verified current IDs, exact resource labels and bounded reads."""
    from boca_socios import host_boca_binding_observe as binding

    try:
        inventory = cleanup.capture_inventory()
        cleanup._validate_inventory(inventory)
        raw = pair.observe(run_id)
        installed = binding._read_host_binding()
        binding._attest(run_id, raw, installed)
        observed = json.loads(raw.removeprefix(pair._PREFIX))
        services = observed["services"]
        if (
            len(inventory.containers) != 2
            or {c.ident for c in inventory.containers} != {s["container_id"] for s in services}
            or {v.name for v in inventory.volumes} != set(observed["volumes"])
            or inventory.global_image_ids - {image.ident for image in inventory.images}
        ):
            raise _fail()
        for item in services:
            containers = [c for c in inventory.containers if c.ident == item["container_id"]]
            images = [i for i in inventory.images if i.ident == item["image_id"]]
            if (
                len(containers) != 1
                or containers[0].image_id != item["image_id"]
                or containers[0].running is not item["running"]
                or len(images) != 1
                or images[0].source != cleanup.BOCA_SOURCE
                or item["image_ref"] not in images[0].references
                or legacy._revision(images[0].ident) != installed.source_sha
            ):
                raise _fail()
        volumes = []
        for name, creator in _CREATORS:
            selected = [v for v in inventory.volumes if v.name == name]
            if (
                len(selected) != 1
                or legacy._creator(
                    selected[0].labels,
                    "com.docker.compose.volume",
                    name.removeprefix("boca-socios_"),
                )
                != creator
            ):
                raise _fail()
            volumes.append(
                {
                    "name": name,
                    "creator_attempt": creator,
                    "inode_sha256": legacy._identity(name),
                    "container_references": sum(name in c.volumes for c in inventory.containers),
                }
            )
        networks = [n for n in inventory.networks if n.name == legacy._EGRESS]
        if len(networks) != 1:
            raise _fail()
        network = networks[0]
        egress = {
            "name": network.name,
            "id": network.ident,
            "peer_ids": list(network.attached_ids),
            "creator_attempt": legacy._creator(
                network.labels, "com.docker.compose.network", "boca_browser_egress"
            ),
        }
        worker = services[1]
        status = read_panel_status(installed) if worker["status"] == "exited" else None
        return {
            "schema": 2,
            "state": "READ_ONLY",
            "scope": "CURRENT_PAIR",
            "observation_run_id": run_id,
            "source_sha": installed.source_sha,
            "installation_attempt": installed.installation_run_id,
            "pair": observed,
            "volumes": volumes,
            "egress": egress,
            "control_socket_directory_inode_sha256": legacy._identity("control_socket_directory"),
            "binding_fingerprint": installed.fingerprint(),
            "worker_idle": idle_evidence(worker, status),
            "observer_writes": 0,
            "foreign_resources_touched": 0,
            "successor_apply_authorized": False,
        }
    except Exception:
        raise _fail() from None


def observe(
    run_id: str, *, snapshot_reader: Callable[[str], dict[str, object]] = snapshot
) -> bytes:
    first, second = snapshot_reader(run_id), snapshot_reader(run_id)
    raw = PREFIX + _canonical(first) + b"\n"
    verify(raw, run_id)
    verify(PREFIX + _canonical(second) + b"\n", run_id)
    if first != second:
        raise _fail()
    return raw


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) != 2 or args[0] not in ("host", "verify"):
            raise _fail()
        raw = observe(args[1]) if args[0] == "host" else sys.stdin.buffer.read(LIMIT + 1)
        verify(raw, args[1])
    except Exception:
        print("BOCA_CURRENT_RETAINED_V2 state=NO_GO observer_writes=0")
        return 3
    sys.stdout.buffer.write(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
