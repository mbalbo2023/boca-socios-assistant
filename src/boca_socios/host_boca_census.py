"""Read-only, Boca-rootless topology census; informational, never Cutover GO.

The host collector reuses cleanup's strictly bounded Docker list/field readers,
but *not* its broad full inventory: an unrelated OCI image can spoof a Boca
source label. Global ID/name-only checks reject foreign containers, networks,
and volumes before any per-container inspect, and no image is inspected or
listed. Two independent reads must agree. No lease is acquired (which would
create a lock file), and the redacted receipt never grants Cutover permission.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from boca_socios import host_boca_cleanup as cleanup

_RUN_ID = re.compile(r"[1-9][0-9]{0,19}\Z")
_PREFIX = b"BOCA_CURRENT_CENSUS "
_NO_GO = b"BOCA_CURRENT_CENSUS state=NO_GO reason=UNVERIFIED observer_writes=0\n"
_MAX_RECEIPT_BYTES = 512
_COUNT_CATEGORIES = frozenset(("0", "1", "2_PLUS"))
_LEGACY_CATEGORIES = frozenset(("ABSENT", "APPEARS_RUNNING", "APPEARS_STOPPED"))
_RECEIPT_FIELDS = frozenset(
    {
        "schema",
        "state",
        "observation_run_id",
        "total",
        "controllers",
        "workers",
        "other_boca",
        "legacy_shape",
        "observer_writes",
        "foreign_resources_touched",
        "cutover_authorized",
    }
)


class CensusNoGo(ValueError):
    """No authenticated, stable Boca-only snapshot exists for this observation."""


@dataclass(frozen=True)
class CensusContainer:
    ident: str
    name: str
    running: bool
    labels: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class CensusSnapshot:
    containers: tuple[CensusContainer, ...]
    network_ids: frozenset[str]
    volume_names: frozenset[str]
    docker_root_identity: tuple[int, int]


def capture_container_census() -> CensusSnapshot:
    """ONLY Boca container fields, following global foreign ID-only guards.

    `cleanup.capture_inventory` is deliberately not called: it examines
    image OCI labels and can inspect a foreign image spoofing Boca provenance.
    This narrower path invokes no Docker image command, effectful filesystem
    operation, lease, container mutation, or Docker context beyond UID10001 rootless.
    """
    # UID and pinned socket alone cannot prove rootless daemon custody. This
    # existing READ_ONLY attestor first checks Docker info rootless/cgroup-v2/
    # systemd and follows only the UID10001-owned DockerRootDir with nofollow
    # read-only directory fds and device/inode verification. Always run it
    # BEFORE the first container/network/volume listing, on *each* snapshot.
    _, _, docker_device, docker_inode = cleanup._rootless_docker_disk_inodes()
    project_filter = f"label=com.docker.compose.project={cleanup.BOCA_PROJECT}"
    global_containers = set(cleanup._ids("ps", "-a", "-q", "--no-trunc"))
    boca_containers = set(cleanup._ids("ps", "-a", "-q", "--no-trunc", "--filter", project_filter))
    if global_containers != boca_containers:
        raise CensusNoGo("foreign container in dedicated rootless daemon")

    global_networks = set(cleanup._ids("network", "ls", "-q", "--no-trunc"))
    builtin_networks = set(
        cleanup._ids("network", "ls", "-q", "--no-trunc", "--filter", "type=builtin")
    )
    boca_networks = set(
        cleanup._ids("network", "ls", "-q", "--no-trunc", "--filter", project_filter)
    )
    if global_networks - builtin_networks != boca_networks:
        raise CensusNoGo("foreign network in dedicated rootless daemon")

    global_volumes = set(cleanup._names("volume", "ls", "-q"))
    boca_volumes = set(cleanup._names("volume", "ls", "-q", "--filter", project_filter))
    if global_volumes != boca_volumes:
        raise CensusNoGo("foreign volume in dedicated rootless daemon")

    # Resource listings above are ID/name-only. Only now may exact container
    # IDs from the proven Boca label-filtered set be inspected, and only four
    # reviewed fields (no Config.Env, Image, Mounts, network config or volumes).
    containers: list[CensusContainer] = []
    for ident in sorted(boca_containers):
        if cleanup._inspect_field("container", ident, "Id") != ident:
            raise CensusNoGo("Boca container ID drift")
        name = cleanup._inspect_field("container", ident, "Name")
        running = cleanup._inspect_field("container", ident, "State.Running")
        labels = cleanup._docker_labels(cleanup._inspect_field("container", ident, "Config.Labels"))
        proven = cleanup._labels(labels)
        if (
            not isinstance(name, str)
            or not cleanup.DOCKER_NAME.fullmatch(name.removeprefix("/"))
            or not name.startswith("/boca-socios-")
            or type(running) is not bool
            or proven.get("com.docker.compose.project") != cleanup.BOCA_PROJECT
            or not proven.get("com.docker.compose.service")
        ):
            raise CensusNoGo("Boca container identity or status unverified")
        containers.append(CensusContainer(ident, name, running, labels))
    if len({c.name for c in containers}) != len(containers):
        raise CensusNoGo("duplicate Boca container name")
    return CensusSnapshot(
        tuple(containers),
        frozenset(global_networks),
        frozenset(global_volumes),
        (docker_device, docker_inode),
    )


def _valid_run_id(run_id: str) -> bool:
    return isinstance(run_id, str) and _RUN_ID.fullmatch(run_id) is not None


def _category(count: int) -> str:
    return "0" if count == 0 else "1" if count == 1 else "2_PLUS"


def _topology(inventory: CensusSnapshot) -> tuple[object, ...]:
    if not isinstance(inventory, CensusSnapshot):
        raise CensusNoGo("census type unverified")
    if (
        len(inventory.containers) + len(inventory.network_ids) + len(inventory.volume_names)
        > cleanup.MAX_OBJECTS
        or len({c.ident for c in inventory.containers}) != len(inventory.containers)
        or not isinstance(inventory.docker_root_identity, tuple)
        or len(inventory.docker_root_identity) != 2
        or any(type(value) is not int or value < 0 for value in inventory.docker_root_identity)
    ):
        raise CensusNoGo("census object count unverified")
    for container in inventory.containers:
        if (
            not isinstance(container, CensusContainer)
            or not cleanup.HEX_ID.fullmatch(container.ident)
            or not cleanup.DOCKER_NAME.fullmatch(container.name.removeprefix("/"))
            or type(container.running) is not bool
        ):
            raise CensusNoGo("container census field unverified")
        cleanup._labels(container.labels)
    # Image IDs/OCI labels and changing free storage capacities are outside
    # this informational container census. The verified Docker storage's
    # device/inode MUST remain stable across both reads; Cutover re-attests all
    # remaining state independently.
    return (
        inventory.containers,
        inventory.network_ids,
        inventory.volume_names,
        inventory.docker_root_identity,
    )


def _classify(inventory: CensusSnapshot, run_id: str) -> dict[str, object]:
    controllers = 0
    workers = 0
    others = 0
    legacy_shape = "ABSENT"
    for container in inventory.containers:
        labels = dict(container.labels)
        if labels.get(
            "com.docker.compose.project"
        ) != cleanup.BOCA_PROJECT or not container.name.startswith("/boca-socios-"):
            raise CensusNoGo("container Boca identity unverified")
        service = labels.get("com.docker.compose.service")
        if service == "controller":
            controllers += 1
        elif service == "browser-worker":
            workers += 1
        else:
            others += 1
        if (
            service == "controller"
            and container.name == "/boca-socios-controller-1"
            and "boca.socios.browser-ipc-attempt" not in labels
        ):
            # Name+Compose labels do NOT prove historical digest, health, or
            # controller authenticity; this is a shape indicator only.
            legacy_shape = "APPEARS_RUNNING" if container.running else "APPEARS_STOPPED"
    return {
        "schema": 1,
        "state": "READY",
        "observation_run_id": run_id,
        "total": _category(len(inventory.containers)),
        "controllers": _category(controllers),
        "workers": _category(workers),
        "other_boca": _category(others),
        "legacy_shape": legacy_shape,
        "observer_writes": 0,
        "foreign_resources_touched": 0,
        "cutover_authorized": False,
    }


def _canonical(payload: dict[str, object]) -> bytes:
    return (
        _PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
    )


def observe(
    run_id: str,
    *,
    inventory_reader: Callable[[], CensusSnapshot] | None = None,
    effective_uid: int | None = None,
    effective_gid: int | None = None,
) -> bytes:
    """Take exactly two Boca-only read-only snapshots, no retries or leases."""
    if not _valid_run_id(run_id):
        raise CensusNoGo("invalid observation identity")
    uid = os.geteuid() if effective_uid is None else effective_uid
    gid = os.getegid() if effective_gid is None else effective_gid
    if uid != cleanup.EXPECTED_UID or gid != cleanup.EXPECTED_GID:
        raise CensusNoGo("wrong rootless identity")
    reader = capture_container_census if inventory_reader is None else inventory_reader
    first = reader()
    first_topology = _topology(first)
    second = reader()
    if first_topology != _topology(second):
        raise CensusNoGo("unstable Boca topology between reads")
    receipt = _canonical(_classify(second, run_id))
    if len(receipt) > _MAX_RECEIPT_BYTES:
        raise CensusNoGo("receipt outside bound")
    return receipt


def verify(receipt: bytes, run_id: str) -> bytes:
    """Runner-side strict, canonical whitelist verification of host output."""
    if (
        not _valid_run_id(run_id)
        or not isinstance(receipt, bytes)
        or not receipt.startswith(_PREFIX)
        or len(receipt) > _MAX_RECEIPT_BYTES
        or receipt.count(b"\n") != 1
        or not receipt.endswith(b"\n")
    ):
        raise CensusNoGo("host receipt boundary invalid")

    def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise CensusNoGo("duplicate receipt property")
            value[key] = item
        return value

    try:
        payload = json.loads(receipt[len(_PREFIX) :], object_pairs_hook=_pairs)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise CensusNoGo("receipt JSON unverified") from exc
    if not isinstance(payload, dict) or payload.keys() != _RECEIPT_FIELDS:
        raise CensusNoGo("unallowlisted receipt fields")
    if (
        type(payload["schema"]) is not int
        or payload["schema"] != 1
        or payload["state"] != "READY"
        or payload["observation_run_id"] != run_id
        or type(payload["observer_writes"]) is not int
        or payload["observer_writes"] != 0
        or type(payload["foreign_resources_touched"]) is not int
        or payload["foreign_resources_touched"] != 0
        or payload["cutover_authorized"] is not False
        or type(payload["legacy_shape"]) is not str
        or payload["legacy_shape"] not in _LEGACY_CATEGORIES
        or any(
            type(payload[key]) is not str or payload[key] not in _COUNT_CATEGORIES
            for key in ("total", "controllers", "workers", "other_boca")
        )
    ):
        raise CensusNoGo("receipt values unverified")
    count_min = {"0": 0, "1": 1, "2_PLUS": 2}
    minimum = sum(count_min[payload[key]] for key in ("controllers", "workers", "other_boca"))
    total = payload["total"]
    if (
        (total == "0" and minimum != 0)
        or (total == "1" and minimum != 1)
        or (total == "2_PLUS" and minimum < 2)
        or (payload["legacy_shape"] != "ABSENT" and payload["controllers"] == "0")
        or _canonical(payload) != receipt
    ):
        raise CensusNoGo("receipt cardinality or canonical form unverified")
    return receipt


def main(argv: Sequence[str]) -> int:
    """No unredacted diagnostics, including on uncaught Docker/probe failures."""
    try:
        if len(argv) != 2 or argv[0] not in ("host", "verify"):
            raise CensusNoGo("invalid census mode")
        if argv[0] == "host":
            receipt = observe(argv[1])
        else:
            receipt = verify(sys.stdin.buffer.read(_MAX_RECEIPT_BYTES + 1), argv[1])
        sys.stdout.buffer.write(receipt)
        return 0
    except Exception:
        # Never surface Docker errors, image IDs, paths, labels or user data.
        print(_NO_GO.decode("ascii"), end="")
        return 3


if __name__ == "__main__":  # pragma: no cover - zip entrypoint calls main()
    raise SystemExit(main(sys.argv[1:]))
