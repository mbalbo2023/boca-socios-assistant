"""Double-attested, READ_ONLY installed Boca controller/browser-worker pair.

This observer is deliberately **not** a Cutover PREPARE or deployment gate.
It reads only two already-proven Boca container IDs after the existing rootless
UID10001 global-census guard; never scans image IDs, reads Config.Env, opens
secrets, acquires host leases, touches foreign Docker, or changes host state.
The receipt is an observation, never a claim that either service is healthy.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable, Sequence

from boca_socios import host_boca_census as census
from boca_socios import host_boca_cleanup as cleanup
from boca_socios.host_cutover_inventory_observe import ProductionCutoverInventoryIO

_PREFIX = b"BOCA_INSTALLED_PAIR "
_NO_GO = b"BOCA_INSTALLED_PAIR state=NO_GO reason=UNVERIFIED observer_writes=0\n"
_MAX_RECEIPT_BYTES = 4_096
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CONTROLLER_IMAGE = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_WORKER_IMAGE = re.compile(
    r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z"
)
_SERVICES = ("controller", "browser-worker")
_NAMES = {
    "controller": "/boca-socios-controller-1",
    "browser-worker": "/boca-socios-browser-worker-1",
}
_IMAGE_RULES = {"controller": _CONTROLLER_IMAGE, "browser-worker": _WORKER_IMAGE}
_NETWORKS = {
    "controller": "boca-socios_boca_private",
    "browser-worker": "boca-socios_boca_browser_egress",
}
# The physically installed V3 source/attempt predate R170 SITE_URL and R171
# worker egress. Its worker was created under Docker `--network none`.
_HISTORICAL_SOURCE = "03df9a14bdd78cf768386a865876fed9d5656911"
_HISTORICAL_ATTEMPT = "42806447101"
_HISTORICAL_WORKER_NETWORK = "none"
_BASE_MOUNTS = {
    "controller": frozenset(
        {
            ("boca-socios_boca_data", "/data", True),
            ("boca-socios_boca_key", "/run/secrets", False),
            ("boca-socios_boca_owner", "/run/owner", False),
            ("boca-socios_boca_browser_ipc", "/run/boca-browser-ipc", False),
        }
    ),
    "browser-worker": frozenset({("boca-socios_boca_browser_ipc", "/run/boca-browser-ipc", True)}),
}
_SITE_MOUNTS = {
    "controller": ("boca-socios_boca_site_config", "/run/boca-site-config", True),
    "browser-worker": ("boca-socios_boca_site_config", "/run/boca-site-config", False),
}
_VOLUMES = frozenset(
    {
        "boca-socios_boca_data",
        "boca-socios_boca_key",
        "boca-socios_boca_owner",
        "boca-socios_boca_telegram",
        "boca-socios_boca_browser_ipc",
        "boca-socios_boca_site_config",
    }
)
_CONTROLLER_PORT = {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
_CONTROL_BIND_SOURCE = "/home/boca-deploy/.boca-on-demand/socket"
_CONTROL_BIND_TARGET = "/run/boca-bot-control"
_HEALTH = frozenset({"healthy", "unhealthy", "starting", "none"})
_FIELDS = (
    "Image",
    "Config.Image",
    "State.Health.Status",
    "State.Status",
    "State.Pid",
    "State.ExitCode",
    "HostConfig.PortBindings",
    "NetworkSettings.Networks",
    "Mounts",
)
_PUBLIC_FIELDS = frozenset(
    {
        "schema",
        "state",
        "observation_run_id",
        "source_sha",
        "attempt_id",
        "services",
        "volumes",
        "ipc_volume",
        "observer_writes",
        "foreign_resources_touched",
        "cutover_authorized",
    }
)
_SERVICE_FIELDS = frozenset(
    {
        "service",
        "container_id",
        "running",
        "status",
        "pid",
        "exit_code",
        "health",
        "image_id",
        "image_ref",
        "config_hash",
        "network_name",
        "network_id",
        "volumes",
        "port_8443",
    }
)


class PairNoGo(ValueError):
    """The live dual-service Boca pair could not be uniquely attested."""


def _is_run(value: object) -> bool:
    return isinstance(value, str) and _RUN.fullmatch(value) is not None


def _fields_from_proven_boca(ident: str, field: str) -> object:
    """Only exact allowlisted public coordinates of an already-proven Boca ID."""
    if not _HEX.fullmatch(ident) or field not in _FIELDS:
        raise PairNoGo("unapproved Boca field")
    if field == "State.Health.Status":
        # An intentionally unstarted CREATED worker has no State.Health
        # object yet. Docker's unguarded Go template would fail *before*
        # the pair verifier can represent that state as `health=none`.
        # This exact nullable projection is already used by the separate
        # Boca worker inspector and never fetches other Docker fields.
        try:
            return json.loads(
                cleanup._docker(
                    "inspect",
                    "--format",
                    "{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}}",
                    ident,
                )
            )
        except (ValueError, TypeError):
            raise PairNoGo("Docker health unverified") from None
    if field in ("Image", "NetworkSettings.Networks", "Mounts"):
        return cleanup._inspect_field("container", ident, field)
    if field in ("State.Status", "State.Pid", "State.ExitCode"):
        # New READ_ONLY observer projection; don't expand the authenticated
        # historical Cutover ZIP's fixed field reader (its SHA must not drift).
        try:
            return json.loads(
                cleanup._docker("inspect", "--format", "{{json ." + field + "}}", ident)
            )
        except (ValueError, TypeError) as exc:
            raise PairNoGo("Boca process state field unavailable") from exc
    return ProductionCutoverInventoryIO().field("container", ident, field)


def _safe_mounts(
    raw: object, *, service: str, valid_volumes: frozenset[str], historical: bool
) -> list[str]:
    if not isinstance(raw, list) or len(raw) > cleanup.MAX_OBJECTS:
        raise PairNoGo("unverified service mounts")
    chosen: list[str] = []
    projections: set[tuple[str, str, bool]] = set()
    binds = 0
    for mount in raw:
        if not isinstance(mount, dict):
            raise PairNoGo("unverified mount entry")
        kind = mount.get("Type")
        if kind == "bind":
            # Verify the *exact* separately reviewed Boca on-demand socket
            # bind; never print the host source or path in the receipt.
            binds += 1
            if (
                service != "controller"
                or binds != 1
                or mount.get("Source") != _CONTROL_BIND_SOURCE
                or mount.get("Destination") != _CONTROL_BIND_TARGET
                or mount.get("RW") is not False
                or mount.get("Propagation") != "rprivate"
            ):
                raise PairNoGo("controller bind outside Boca control boundary")
            continue
        name = mount.get("Name")
        if kind != "volume" or not isinstance(name, str) or name not in valid_volumes:
            raise PairNoGo("volume not Boca-owned")
        destination = mount.get("Destination")
        rw = mount.get("RW")
        if name in chosen or not isinstance(destination, str) or type(rw) is not bool:
            raise PairNoGo("duplicated service mount")
        chosen.append(name)
        projections.add((name, destination, rw))
    expected = _BASE_MOUNTS[service]
    if not historical:
        expected = expected | {_SITE_MOUNTS[service]}
    if projections != expected or binds != (1 if service == "controller" else 0):
        raise PairNoGo("installed Boca mount profile unverified")
    return sorted(chosen)


def _safe_network(
    raw: object, *, service: str, known_ids: frozenset[str], historical: bool
) -> tuple[str, str]:
    if historical and service == "browser-worker":
        if not isinstance(raw, dict) or not set(raw) <= {_HISTORICAL_WORKER_NETWORK}:
            raise PairNoGo("historical worker gained IP network")
        if not raw:
            return _HISTORICAL_WORKER_NETWORK, "UNATTACHED"
        item = raw[_HISTORICAL_WORKER_NETWORK]
        if (
            not isinstance(item, dict)
            or item.get("IPAddress") not in (None, "")
            or item.get("GlobalIPv6Address") not in (None, "")
        ):
            raise PairNoGo("historical worker received IP address")
        ident = item.get("NetworkID")
        if ident in (None, ""):
            return _HISTORICAL_WORKER_NETWORK, "UNATTACHED"
        if not isinstance(ident, str) or not _HEX.fullmatch(ident) or ident not in known_ids:
            raise PairNoGo("historical worker network identity unverified")
        return _HISTORICAL_WORKER_NETWORK, ident
    expected = _NETWORKS[service]
    if not isinstance(raw, dict) or set(raw) != {expected}:
        raise PairNoGo("service network isolation unverified")
    item = raw[expected]
    if not isinstance(item, dict):
        raise PairNoGo("service network attachment unverified")
    ident = item.get("NetworkID")
    # Docker may omit NetworkID for an intentionally stopped worker. This
    # remains explicitly UNKNOWN, not a claim of live network attachment.
    if ident in (None, "") and service == "browser-worker":
        return expected, "UNATTACHED"
    if not isinstance(ident, str) or not _HEX.fullmatch(ident) or ident not in known_ids:
        raise PairNoGo("service network ID outside Boca census")
    return expected, ident


def _valid_state(running: object, status: object, pid: object, exit_code: object) -> bool:
    """Report Created and Exited separately; never infer an alive worker from health."""
    return bool(
        type(running) is bool
        and status in ("created", "running", "exited")
        and type(pid) is int
        and 0 <= pid <= 2_147_483_647
        and type(exit_code) is int
        and -1 <= exit_code <= 255
        and (
            (status == "running" and running and pid > 0)
            or (status in ("created", "exited") and not running and pid == 0)
        )
        and (status != "created" or exit_code == 0)
    )


def _snapshot(
    inventory_reader: Callable[[], census.CensusSnapshot],
    field_reader: Callable[[str, str], object],
    label_reader: Callable[[str, str], str | None],
) -> dict[str, object]:
    inventory = inventory_reader()  # rootless attestation/global foreign checks FIRST
    census._topology(inventory)  # reuse the strict census dataclass/ID validators
    if (
        len(inventory.containers) != 2
        or not inventory.volume_names <= _VOLUMES
        or not isinstance(inventory.network_ids, frozenset)
    ):
        raise PairNoGo("installed Boca pair or volumes unverified")
    by_service = {}
    sources = set()
    attempts = set()
    for container in inventory.containers:
        labels = cleanup._labels(container.labels)
        service = labels.get("com.docker.compose.service")
        if (
            service not in _SERVICES
            or service in by_service
            or container.name != _NAMES[service]
            or labels.get("com.docker.compose.project") != cleanup.BOCA_PROJECT
            or not _SHA.fullmatch(labels.get("org.opencontainers.image.revision", ""))
            or not _HEX.fullmatch(labels.get("com.docker.compose.config-hash", ""))
            or not _is_run(labels.get("boca.socios.browser-ipc-attempt"))
        ):
            raise PairNoGo("Boca service labels unverified")
        source = labels["org.opencontainers.image.revision"]
        attempt = labels["boca.socios.browser-ipc-attempt"]
        if source == _HISTORICAL_SOURCE and attempt != _HISTORICAL_ATTEMPT:
            raise PairNoGo("historical V3 source and attempt differ")
        historical = source == _HISTORICAL_SOURCE
        sources.add(source)
        attempts.add(attempt)
        fields = {key: field_reader(container.ident, key) for key in _FIELDS}
        image_id = fields["Image"]
        ref = fields["Config.Image"]
        if (
            not isinstance(image_id, str)
            or not _IMAGE_ID.fullmatch(image_id)
            or not isinstance(ref, str)
            or not _IMAGE_RULES[service].fullmatch(ref)
            or label_reader(image_id, "org.opencontainers.image.source") != cleanup.BOCA_SOURCE
            or label_reader(image_id, "org.opencontainers.image.revision") != source
        ):
            raise PairNoGo("OCI image provenance unverified")
        health = fields["State.Health.Status"]
        if health is None:
            health = "none"
        if not isinstance(health, str) or health not in _HEALTH:
            raise PairNoGo("Docker health unverified")
        binding = fields["HostConfig.PortBindings"]
        if binding != _CONTROLLER_PORT if service == "controller" else binding not in ({}, None):
            raise PairNoGo("Boca-only panel host binding unverified")
        status = fields["State.Status"]
        pid = fields["State.Pid"]
        exit_code = fields["State.ExitCode"]
        if not _valid_state(container.running, status, pid, exit_code):
            raise PairNoGo("Boca service process state unverified")
        network_name, network_id = _safe_network(
            fields["NetworkSettings.Networks"],
            service=service,
            known_ids=inventory.network_ids,
            historical=historical,
        )
        volumes = _safe_mounts(
            fields["Mounts"],
            service=service,
            valid_volumes=inventory.volume_names,
            historical=historical,
        )
        if service == "browser-worker" and any(
            name in volumes
            for name in (
                "boca-socios_boca_data",
                "boca-socios_boca_key",
                "boca-socios_boca_owner",
                "boca-socios_boca_telegram",
            )
        ):
            raise PairNoGo("browser has member data or owner credential volume")
        by_service[service] = {
            "service": service,
            "container_id": container.ident,
            "running": container.running,
            "status": status,
            "pid": pid,
            "exit_code": exit_code,
            "health": health,
            "image_id": image_id,
            "image_ref": ref,
            "config_hash": labels["com.docker.compose.config-hash"],
            "network_name": network_name,
            "network_id": network_id,
            "volumes": volumes,
            "port_8443": "LOOPBACK" if service == "controller" else "NONE",
        }
    if set(by_service) != set(_SERVICES) or len(sources) != 1 or len(attempts) != 1:
        raise PairNoGo("pair provenance ambiguous")
    controller_network_id = by_service["controller"]["network_id"]
    worker_network_id = by_service["browser-worker"]["network_id"]
    if (
        isinstance(controller_network_id, str)
        and isinstance(worker_network_id, str)
        and controller_network_id == worker_network_id
    ):
        raise PairNoGo("Boca controller/worker isolation networks identical")
    c_vols = by_service["controller"]["volumes"]
    w_vols = by_service["browser-worker"]["volumes"]
    if not isinstance(c_vols, list) or not isinstance(w_vols, list):
        raise PairNoGo("Boca pair volumes malformed")
    ipc = "boca-socios_boca_browser_ipc"
    ipc_scope = (
        "BOTH"
        if ipc in c_vols and ipc in w_vols
        else "CONTROLLER_ONLY"
        if ipc in c_vols
        else "WORKER_ONLY"
        if ipc in w_vols
        else "ABSENT"
    )
    return {
        "schema": 1,
        "state": "OBSERVED",
        "source_sha": sources.pop(),
        "attempt_id": attempts.pop(),
        "services": [by_service[service] for service in _SERVICES],
        "volumes": sorted(inventory.volume_names),
        "ipc_volume": ipc_scope,
        # Never pass inode/device metadata to a public receipt, but the
        # host-level equality test includes this storage identity below.
        "_storage_identity": inventory.docker_root_identity,
    }


def _canonical(payload: dict[str, object]) -> bytes:
    return (
        _PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
    )


def observe(
    run_id: str,
    *,
    inventory_reader: Callable[[], census.CensusSnapshot] | None = None,
    container_field_reader: Callable[[str, str], object] | None = None,
    image_label_reader: Callable[[str, str], str | None] | None = None,
    effective_uid: int | None = None,
    effective_gid: int | None = None,
) -> bytes:
    """Two independent complete reads; reject any inventory or field drift."""
    if not _is_run(run_id):
        raise PairNoGo("observation run ID unverified")
    uid = os.geteuid() if effective_uid is None else effective_uid
    gid = os.getegid() if effective_gid is None else effective_gid
    if uid != cleanup.EXPECTED_UID or gid != cleanup.EXPECTED_GID:
        raise PairNoGo("dedicated rootless user identity unverified")
    reader = census.capture_container_census if inventory_reader is None else inventory_reader
    field_reader = (
        _fields_from_proven_boca if container_field_reader is None else container_field_reader
    )
    label_reader = (
        cleanup._inspect_image_public_oci_label
        if image_label_reader is None
        else image_label_reader
    )
    first = _snapshot(reader, field_reader, label_reader)
    second = _snapshot(reader, field_reader, label_reader)
    if first != second:
        raise PairNoGo("installed Boca pair changed between reads")
    second.pop("_storage_identity")
    second.update(
        {
            "observation_run_id": run_id,
            "observer_writes": 0,
            "foreign_resources_touched": 0,
            "cutover_authorized": False,
        }
    )
    result = _canonical(second)
    if len(result) > _MAX_RECEIPT_BYTES:
        raise PairNoGo("installed pair receipt too long")
    verify(result, run_id)
    return result


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, item in pairs:
        if key in result:
            raise PairNoGo("duplicate receipt fields")
        result[key] = item
    return result


def verify(receipt: bytes, run_id: str) -> bytes:
    """Runner-side exact public receipt schema; never interpret as Cutover GO."""
    if (
        not _is_run(run_id)
        or not isinstance(receipt, bytes)
        or len(receipt) > _MAX_RECEIPT_BYTES
        or not receipt.startswith(_PREFIX)
        or not receipt.endswith(b"\n")
        or receipt.count(b"\n") != 1
    ):
        raise PairNoGo("unbounded or unbound pair receipt")
    try:
        value = json.loads(receipt[len(_PREFIX) :], object_pairs_hook=_unique)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise PairNoGo("bad pair receipt JSON") from exc
    if not isinstance(value, dict) or value.keys() != _PUBLIC_FIELDS:
        raise PairNoGo("unallowlisted receipt keys")
    if (
        type(value["schema"]) is not int
        or value["schema"] != 1
        or value["state"] != "OBSERVED"
        or value["observation_run_id"] != run_id
        or not isinstance(value["source_sha"], str)
        or not _SHA.fullmatch(value["source_sha"])
        or not _is_run(value["attempt_id"])
        or type(value["observer_writes"]) is not int
        or value["observer_writes"] != 0
        or type(value["foreign_resources_touched"]) is not int
        or value["foreign_resources_touched"] != 0
        or value["cutover_authorized"] is not False
        or not isinstance(value["volumes"], list)
        or len(value["volumes"]) > len(_VOLUMES)
        or any(type(v) is not str or v not in _VOLUMES for v in value["volumes"])
        or sorted(set(value["volumes"])) != value["volumes"]
        or value["ipc_volume"] not in ("BOTH", "CONTROLLER_ONLY", "WORKER_ONLY", "ABSENT")
        or not isinstance(value["services"], list)
        or len(value["services"]) != 2
        or (value["source_sha"] == _HISTORICAL_SOURCE)
        != (value["attempt_id"] == _HISTORICAL_ATTEMPT)
    ):
        raise PairNoGo("invalid pair receipt values")
    historical = value["source_sha"] == _HISTORICAL_SOURCE
    for service, item in zip(_SERVICES, value["services"], strict=True):
        if not isinstance(item, dict) or item.keys() != _SERVICE_FIELDS:
            raise PairNoGo("unexpected pair service fields")
        if (
            item["service"] != service
            or not isinstance(item["container_id"], str)
            or not _HEX.fullmatch(item["container_id"])
            or not _valid_state(item["running"], item["status"], item["pid"], item["exit_code"])
            or item["health"] not in _HEALTH
            or not isinstance(item["image_id"], str)
            or not _IMAGE_ID.fullmatch(item["image_id"])
            or not isinstance(item["image_ref"], str)
            or not _IMAGE_RULES[service].fullmatch(item["image_ref"])
            or not isinstance(item["config_hash"], str)
            or not _HEX.fullmatch(item["config_hash"])
            or item["network_name"]
            != (
                _HISTORICAL_WORKER_NETWORK
                if historical and service == "browser-worker"
                else _NETWORKS[service]
            )
            or not isinstance(item["network_id"], str)
            or (item["network_id"] != "UNATTACHED" and not _HEX.fullmatch(item["network_id"]))
            or (item["network_id"] == "UNATTACHED" and service != "browser-worker")
            or not isinstance(item["volumes"], list)
            or any(v not in value["volumes"] for v in item["volumes"])
            or sorted(set(item["volumes"])) != item["volumes"]
            or item["port_8443"] != ("LOOPBACK" if service == "controller" else "NONE")
        ):
            raise PairNoGo("invalid service provenance or host binding")
    controller_vols = value["services"][0]["volumes"]
    worker_vols = value["services"][1]["volumes"]
    controller_expected = _BASE_MOUNTS["controller"]
    worker_expected = _BASE_MOUNTS["browser-worker"]
    if not historical:
        controller_expected = controller_expected | {_SITE_MOUNTS["controller"]}
        worker_expected = worker_expected | {_SITE_MOUNTS["browser-worker"]}
    ipc = "boca-socios_boca_browser_ipc"
    expected_ipc = (
        "BOTH"
        if ipc in controller_vols and ipc in worker_vols
        else "CONTROLLER_ONLY"
        if ipc in controller_vols
        else "WORKER_ONLY"
        if ipc in worker_vols
        else "ABSENT"
    )
    if (
        value["services"][0]["container_id"] == value["services"][1]["container_id"]
        or {item[0] for item in controller_expected} != set(controller_vols)
        or {item[0] for item in worker_expected} != set(worker_vols)
        or (value["services"][0]["network_id"] == value["services"][1]["network_id"])
        or value["ipc_volume"] != expected_ipc
        or any(
            v in worker_vols
            for v in (
                "boca-socios_boca_data",
                "boca-socios_boca_key",
                "boca-socios_boca_owner",
                "boca-socios_boca_telegram",
            )
        )
        or _canonical(value) != receipt
    ):
        raise PairNoGo("pair receipt identity or canonical encoding invalid")
    return receipt


def main(argv: Sequence[str]) -> int:
    """Never surface raw Docker/SSH/label/exception data across boundary."""
    try:
        if len(argv) != 2 or argv[0] not in ("host", "verify"):
            raise PairNoGo("unknown pair observer mode")
        result = (
            observe(argv[1])
            if argv[0] == "host"
            else verify(sys.stdin.buffer.read(_MAX_RECEIPT_BYTES + 1), argv[1])
        )
        sys.stdout.buffer.write(result)
        return 0
    except Exception:
        sys.stdout.buffer.write(_NO_GO)
        return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
