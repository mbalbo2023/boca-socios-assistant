"""R178 inert upgrade plan for an already-installed Boca controller/worker pair.

This module does NOT execute or authorize Cutover. Its only input about the
installed host is the canonical R177 READ_ONLY pair receipt. Exact historical
container IDs and new immutable image refs are retained as *coordinates for
future validation*, never treated as permission for Docker or systemd writes.

The future effectful executor must separately authenticate the GitHub Actions
run, source/release manifests, protected Environment, rootless lease, current
same-lease physical snapshot, worker PID0, SQLite inode and control socket
binding. Until then `apply_authorized` is unconditionally false.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from boca_socios import host_boca_pair_observe as observer

_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CONTROLLER = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_WORKER = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z")
_HISTORICAL_SOURCE = "03df9a14bdd78cf768386a865876fed9d5656911"
_HISTORICAL_ATTEMPT = "42806447101"
_PREFIX = b"BOCA_DUAL_UPGRADE_PLAN "
_BOUND = 4_096
_REQUIRED_CONTROLLER_VOLUMES = frozenset(
    {
        "boca-socios_boca_data",
        "boca-socios_boca_key",
        "boca-socios_boca_owner",
        "boca-socios_boca_browser_ipc",
    }
)
_PUBLIC_FIELDS = frozenset(
    {
        "schema",
        "state",
        "planning_attempt_id",
        "observed_run_id",
        "old_attempt_id",
        "old_source_sha",
        "old_controller_id",
        "old_worker_id",
        "old_controller_image_id",
        "old_worker_image_id",
        "old_worker_status",
        "old_worker_exit_code",
        "old_worker_network",
        "new_source_sha",
        "new_release_run_id",
        "new_controller_image_ref",
        "new_worker_image_ref",
        "controller_healthy",
        "worker_stopped",
        "worker_pid0",
        "ipc_shared",
        "ipc_socket_handshake",
        "port_8443",
        "panel_live_http",
        "target_egress_bridge",
        "preserve_volumes",
        "host_binding",
        "database_inode",
        "release_provenance",
        "candidate_cids",
        "observer_writes",
        "docker_writes",
        "apply_authorized",
    }
)


class UpgradeNoGo(ValueError):
    """Insufficient verified coordinates even for a non-effectful upgrade plan."""


def _run(value: object) -> bool:
    return isinstance(value, str) and _RUN.fullmatch(value) is not None


def _sha(value: object) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


@dataclass(frozen=True)
class CandidateRelease:
    """Syntax-checked candidate, NOT proof of a GitHub-authenticated release."""

    source_sha: str
    release_run_id: str
    controller_image_ref: str
    worker_image_ref: str

    def validate(self) -> None:
        if (
            not _sha(self.source_sha)
            or not _run(self.release_run_id)
            or not isinstance(self.controller_image_ref, str)
            or not _CONTROLLER.fullmatch(self.controller_image_ref)
            or not isinstance(self.worker_image_ref, str)
            or not _WORKER.fullmatch(self.worker_image_ref)
        ):
            raise UpgradeNoGo("target dual release coordinates unverified")


def _canonical(payload: dict[str, object]) -> bytes:
    return (
        _PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
    )


def _secure_pair(raw: bytes, run_id: str) -> dict[str, object]:
    observer.verify(raw, run_id)
    payload = json.loads(raw.removeprefix(b"BOCA_INSTALLED_PAIR "))
    if not isinstance(payload, dict):
        raise UpgradeNoGo("installed pair receipt was not a JSON object")
    services = payload["services"]
    if not isinstance(services, list) or len(services) != 2:
        raise UpgradeNoGo("installed pair services missing")
    controller = services[0]
    worker = services[1]
    if not isinstance(controller, dict) or not isinstance(worker, dict):
        raise UpgradeNoGo("installed pair service types invalid")
    if (
        controller["running"] is not True
        or controller["status"] != "running"
        or type(controller["pid"]) is not int
        or controller["pid"] <= 0
        or controller["health"] != "healthy"
        or worker["running"] is not False
        or worker["status"] not in ("created", "exited")
        or worker["pid"] != 0
        or (
            worker["status"] == "exited"
            and (type(worker["exit_code"]) is not int or worker["exit_code"] < 0)
        )
        or payload["ipc_volume"] != "BOTH"
        or controller["port_8443"] != "LOOPBACK"
        or worker["port_8443"] != "NONE"
        or (
            worker["network_id"] == "UNATTACHED"
            and (
                payload["source_sha"] != _HISTORICAL_SOURCE
                or payload["attempt_id"] != _HISTORICAL_ATTEMPT
                or worker["network_name"] != "none"
                or worker["status"] != "exited"
                or worker["exit_code"] != 1
            )
        )
        or controller["network_id"] == worker["network_id"]
        or not _REQUIRED_CONTROLLER_VOLUMES.issubset(controller["volumes"])
        or "boca-socios_boca_browser_ipc" not in worker["volumes"]
        or any(
            value in worker["volumes"]
            for value in (
                "boca-socios_boca_data",
                "boca-socios_boca_key",
                "boca-socios_boca_owner",
            )
        )
    ):
        raise UpgradeNoGo("installed pair not idle, healthy or storage-isolated")
    return payload


def prepare(
    pair_receipt: bytes,
    *,
    observation_run_id: str,
    attempt_id: str,
    release: CandidateRelease,
) -> bytes:
    """Prepare an informational source/target mapping, with NO host effects."""
    if (
        not _run(observation_run_id)
        or not _run(attempt_id)
        or not isinstance(release, CandidateRelease)
    ):
        raise UpgradeNoGo("upgrade plan input identities invalid")
    release.validate()
    observed = _secure_pair(pair_receipt, observation_run_id)
    old_source = observed["source_sha"]
    old_attempt = observed["attempt_id"]
    if (
        release.source_sha == old_source
        or attempt_id in (observation_run_id, old_attempt, release.release_run_id)
        or release.release_run_id == old_attempt
    ):
        raise UpgradeNoGo("same-source upgrade or replay forbidden")
    services = observed["services"]
    if not isinstance(services, list) or len(services) != 2:
        raise UpgradeNoGo("installed services shape changed after verification")
    controller = services[0]
    worker = services[1]
    if not isinstance(controller, dict) or not isinstance(worker, dict):
        raise UpgradeNoGo("installed service coordinates malformed")
    result: dict[str, object] = {
        "schema": 1,
        "state": "CODE_ONLY_HOST_PROOF_PENDING",
        "planning_attempt_id": attempt_id,
        "observed_run_id": observation_run_id,
        "old_attempt_id": old_attempt,
        "old_source_sha": old_source,
        "old_controller_id": controller["container_id"],
        "old_worker_id": worker["container_id"],
        "old_controller_image_id": controller["image_id"],
        "old_worker_image_id": worker["image_id"],
        "old_worker_status": worker["status"],
        "old_worker_exit_code": worker["exit_code"],
        "old_worker_network": "NONE" if worker["network_name"] == "none" else "EGRESS",
        "new_source_sha": release.source_sha,
        "new_release_run_id": release.release_run_id,
        "new_controller_image_ref": release.controller_image_ref,
        "new_worker_image_ref": release.worker_image_ref,
        "controller_healthy": True,
        "worker_stopped": True,
        "worker_pid0": "OBSERVED_HISTORICAL",
        "ipc_shared": True,
        "ipc_socket_handshake": "UNVERIFIED",
        "port_8443": "LOOPBACK_ONLY",
        "panel_live_http": "UNVERIFIED",
        "target_egress_bridge": "UNVERIFIED",
        "preserve_volumes": observed["volumes"],
        "host_binding": "UNVERIFIED",
        "database_inode": "UNVERIFIED",
        "release_provenance": "RUNNER_VERIFICATION_REQUIRED",
        "candidate_cids": "UNCREATED",
        "observer_writes": 0,
        "docker_writes": 0,
        "apply_authorized": False,
    }
    receipt = _canonical(result)
    verify(receipt, attempt_id)
    return receipt


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, item in pairs:
        if key in output:
            raise UpgradeNoGo("duplicate upgrade plan property")
        output[key] = item
    return output


def verify(receipt: bytes, attempt_id: str) -> bytes:
    """Strict inert plan receipt. Never turns a plan into an APPLY token."""
    if (
        not _run(attempt_id)
        or not isinstance(receipt, bytes)
        or len(receipt) > _BOUND
        or not receipt.startswith(_PREFIX)
        or not receipt.endswith(b"\n")
        or receipt.count(b"\n") != 1
    ):
        raise UpgradeNoGo("plan receipt boundary invalid")
    try:
        value = json.loads(receipt[len(_PREFIX) :], object_pairs_hook=_unique)
    except (TypeError, ValueError, UnicodeError) as exc:
        raise UpgradeNoGo("invalid plan JSON") from exc
    if not isinstance(value, dict) or value.keys() != _PUBLIC_FIELDS:
        raise UpgradeNoGo("invalid plan receipt properties")
    if (
        type(value["schema"]) is not int
        or value["schema"] != 1
        or value["state"] != "CODE_ONLY_HOST_PROOF_PENDING"
        or value["planning_attempt_id"] != attempt_id
        or not _run(value["observed_run_id"])
        or not _run(value["old_attempt_id"])
        or not _sha(value["old_source_sha"])
        or not _sha(value["new_source_sha"])
        or value["new_source_sha"] == value["old_source_sha"]
        or not _run(value["new_release_run_id"])
        or not isinstance(value["new_controller_image_ref"], str)
        or not _CONTROLLER.fullmatch(value["new_controller_image_ref"])
        or not isinstance(value["new_worker_image_ref"], str)
        or not _WORKER.fullmatch(value["new_worker_image_ref"])
        or value["controller_healthy"] is not True
        or value["worker_stopped"] is not True
        or value["worker_pid0"] != "OBSERVED_HISTORICAL"
        or value["ipc_shared"] is not True
        or value["ipc_socket_handshake"] != "UNVERIFIED"
        or value["port_8443"] != "LOOPBACK_ONLY"
        or value["panel_live_http"] != "UNVERIFIED"
        or value["target_egress_bridge"] != "UNVERIFIED"
        or value["host_binding"] != "UNVERIFIED"
        or value["database_inode"] != "UNVERIFIED"
        or value["release_provenance"] != "RUNNER_VERIFICATION_REQUIRED"
        or value["candidate_cids"] != "UNCREATED"
        or type(value["observer_writes"]) is not int
        or value["observer_writes"] != 0
        or type(value["docker_writes"]) is not int
        or value["docker_writes"] != 0
        or value["apply_authorized"] is not False
        or not isinstance(value["preserve_volumes"], list)
        or len(value["preserve_volumes"]) > 6
        or any(not isinstance(item, str) for item in value["preserve_volumes"])
        or sorted(set(value["preserve_volumes"])) != value["preserve_volumes"]
        or not _REQUIRED_CONTROLLER_VOLUMES.issubset(value["preserve_volumes"])
    ):
        raise UpgradeNoGo("plan receipt is not inert, complete and bounded")
    old_ids = (value["old_controller_id"], value["old_worker_id"])
    image_ids = (value["old_controller_image_id"], value["old_worker_image_id"])
    old_status = value["old_worker_status"]
    old_exit = value["old_worker_exit_code"]
    old_network = value["old_worker_network"]
    if (
        any(not isinstance(item, str) or not _HASH.fullmatch(item) for item in old_ids)
        or len(set(old_ids)) != 2
        or any(not isinstance(item, str) or not _IMAGE_ID.fullmatch(item) for item in image_ids)
        or old_status not in ("created", "exited")
        or type(old_exit) is not int
        or not -1 <= old_exit <= 255
        or (old_status == "created" and old_exit != 0)
        or old_network not in ("NONE", "EGRESS")
        or (old_network == "NONE" and (old_status != "exited" or old_exit != 1))
        or attempt_id
        in (value["observed_run_id"], value["old_attempt_id"], value["new_release_run_id"])
        or _canonical(value) != receipt
    ):
        raise UpgradeNoGo("plan exact IDs or canonical binding invalid")
    return receipt
