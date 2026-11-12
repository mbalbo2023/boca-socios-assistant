"""Canonical, offline-verifiable Boca-only cleanup V2 evidence.

This module has no Docker, filesystem, SSH, or deletion entrypoint. A future
protected job supplies the first and last inventories obtained under its
already-held Boca lease; an offline runner independently verifies the JSON.
"""

from __future__ import annotations

import json
import re
from typing import TypeVar

from boca_socios import host_boca_cleanup as cleanup

MAX_RECEIPT_BYTES = 8192
COUNTED_V2_SCOPE = "boca-postdeploy-counted-v2"
_KEYS = frozenset(
    {
        "version",
        "scope",
        "outcome",
        "attempt_id",
        "status",
        "before",
        "after",
        "before_counts",
        "after_counts",
        "removed",
        "retained_uncertain",
        "known_residue",
        "retained_attested",
        "protected_pair",
    }
)
_DISK_KEYS = frozenset(
    {
        "stage_bytes_free",
        "stage_inodes_free",
        "docker_bytes_free",
        "docker_inodes_free",
        "stage_device",
        "stage_inode",
        "docker_device",
        "docker_inode",
    }
)
_COUNT_KEYS = frozenset({"containers", "images", "networks", "volumes", "global_images"})
_HISTORICAL_ENTRY = {
    "kind": "image",
    "id": cleanup.HISTORICAL_RETIRE_TARGET,
    "classification": "KNOWN_HISTORICAL_QUARANTINE",
    "release_run": "41559973013",
    "manifest_artifact": "13196392925",
    "digest": cleanup.HISTORICAL_RETIRE_DIGEST,
    "revision": cleanup.HISTORICAL_RETIRE_REVISION,
}


_T = TypeVar("_T")


def _by_id(items: tuple[_T, ...], attr: str) -> dict[str, _T]:  # noqa: UP047
    # Protected host memfd bootstrap still runs Python 3.10.
    return {str(getattr(item, attr)): item for item in items}


def _identities(snapshot: cleanup.Inventory) -> dict[str, dict[str, object]]:
    return {
        "container": _by_id(snapshot.containers, "ident"),
        "image": _by_id(snapshot.images, "ident"),
        "network": _by_id(snapshot.networks, "ident"),
        "volume": _by_id(snapshot.volumes, "name"),
    }


def _snapshot_is_boca_only(snapshot: cleanup.Inventory) -> None:
    """The host inventory must be complete; foreign identities never get printed."""
    cleanup._validate_inventory(snapshot)
    if snapshot.global_image_ids != {image.ident for image in snapshot.images}:
        raise cleanup.CleanupError("cleanup V2 image census includes an unproven resource")
    containers = {item.ident for item in snapshot.containers}
    images = {item.ident for item in snapshot.images}
    networks = {item.name for item in snapshot.networks}
    volumes = {item.name for item in snapshot.volumes}
    for container in snapshot.containers:
        if (
            dict(container.labels).get("com.docker.compose.project") != cleanup.BOCA_PROJECT
            or not container.name.removeprefix("/").startswith("boca-socios-")
            or container.image_id not in images
            or not set(container.volumes) <= volumes
            or not set(container.networks) <= networks
        ):
            raise cleanup.CleanupError("cleanup V2 foreign or incomplete container graph")
    for network in snapshot.networks:
        if (
            dict(network.labels).get("com.docker.compose.project") != cleanup.BOCA_PROJECT
            or not network.name.startswith("boca-socios_")
            or not set(network.attached_ids) <= containers
        ):
            raise cleanup.CleanupError("cleanup V2 unproven Boca network graph")
    for volume in snapshot.volumes:
        if dict(volume.labels).get(
            "com.docker.compose.project"
        ) != cleanup.BOCA_PROJECT or not volume.name.startswith("boca-socios_"):
            raise cleanup.CleanupError("cleanup V2 unproven Boca volume graph")


def _verify_historical_quarantine(
    receipt: cleanup.CleanupReceipt, before: cleanup.Inventory, after: cleanup.Inventory
) -> None:
    ident = cleanup.HISTORICAL_RETIRE_TARGET
    expected = (
        cleanup.HistoricalRetainedImageProof(
            ident, cleanup.HISTORICAL_RETIRE_DIGEST, cleanup.HISTORICAL_RETIRE_REVISION
        ),
    )
    present = ident in before.global_image_ids or ident in after.global_image_ids
    if present != bool(receipt.retained_attested):
        raise cleanup.CleanupError("cleanup V2 historical quarantine proof absent or unexpected")
    if not present:
        return
    if receipt.retained_attested != expected:
        raise cleanup.CleanupError("cleanup V2 historical quarantine provenance invalid")
    for snapshot in (before, after):
        candidates = [item for item in snapshot.images if item.ident == ident]
        if (
            len(candidates) != 1
            or candidates[0].source is not None
            or candidates[0].historical_legacy_attested
            or candidates[0].references != ("ghcr.io/mbalbo2023/boca-socios-assistant:unverified",)
            or any(item.image_id == ident for item in snapshot.containers)
        ):
            raise cleanup.CleanupError("cleanup V2 historical forensic image changed or referenced")


def _verify_positive_deltas(
    receipt: cleanup.CleanupReceipt,
    before: cleanup.Inventory,
    after: cleanup.Inventory,
    protected_containers: frozenset[str],
    protected_images: frozenset[str],
) -> None:
    if (
        type(receipt) is not cleanup.CleanupReceipt
        or type(protected_containers) is not frozenset
        or type(protected_images) is not frozenset
        or receipt.before != before.disk
        or receipt.after != after.disk
        or cleanup._storage_topology_changed(before.disk, after.disk)
    ):
        raise cleanup.CleanupError("cleanup V2 inventory does not match bounded physical receipt")
    old = _identities(before)
    new = _identities(after)
    if (
        not protected_containers <= old["container"].keys()
        or not protected_containers <= new["container"].keys()
        or not protected_images <= old["image"].keys()
        or not protected_images <= new["image"].keys()
    ):
        raise cleanup.CleanupError("cleanup V2 protected controller, worker or image absent")
    removed = {(target.kind, target.ident) for target in receipt.removed}
    retired_containers = {ident for kind, ident in removed if kind == "container"}
    if len(removed) != len(receipt.removed):
        raise cleanup.CleanupError("cleanup V2 duplicate exact deletion")
    for kind in ("container", "image", "network", "volume"):
        lost = old[kind].keys() - new[kind].keys()
        gained = new[kind].keys() - old[kind].keys()
        if gained or {(kind, ident) for ident in lost} != {
            (item_kind, ident) for item_kind, ident in removed if item_kind == kind
        }:
            raise cleanup.CleanupError("cleanup V2 exact removal ID or count mismatch")
        if any(
            old[kind][ident] != new[kind][ident] for ident in old[kind].keys() & new[kind].keys()
        ):
            raise cleanup.CleanupError("cleanup V2 preserved Docker resource drifted")
    removed_image_ids = {ident for kind, ident in removed if kind == "image"}
    if before.global_image_ids - after.global_image_ids != removed_image_ids:
        raise cleanup.CleanupError("cleanup V2 global image census drifted")
    for target in receipt.removed:
        source = old[target.kind][target.ident]
        if target.kind == "container":
            container = source
            if (
                not isinstance(container, cleanup.Container)
                or container.running
                or not cleanup._attempt_owner(dict(container.labels), receipt.attempt_id)
            ):
                raise cleanup.CleanupError("cleanup V2 container deletion unproven")
        elif target.kind == "image":
            image = source
            if (
                not isinstance(image, cleanup.Image)
                or not cleanup._known_boca_image(image)
                or target.ident in protected_images
                or target.ident == cleanup.HISTORICAL_RETIRE_TARGET
                or any(
                    container.image_id == target.ident and container.ident not in retired_containers
                    for container in before.containers
                )
            ):
                raise cleanup.CleanupError("cleanup V2 image deletion lacks positive provenance")
        elif target.kind == "network":
            network = source
            if (
                not isinstance(network, cleanup.Network)
                or not set(network.attached_ids) <= retired_containers
                or not cleanup._attempt_owner(dict(network.labels), receipt.attempt_id)
                or any(
                    network.name in item.networks and item.ident not in retired_containers
                    for item in before.containers
                )
            ):
                raise cleanup.CleanupError("cleanup V2 network deletion unproven")
        elif target.kind == "volume":
            volume = source
            if (
                not isinstance(volume, cleanup.Volume)
                or volume.name in cleanup.PROTECTED_VOLUMES
                or not cleanup._attempt_owner(dict(volume.labels), receipt.attempt_id)
                or any(
                    volume.name in item.volumes and item.ident not in retired_containers
                    for item in before.containers
                )
            ):
                raise cleanup.CleanupError("cleanup V2 volume deletion unproven")
        else:
            raise cleanup.CleanupError("cleanup V2 unknown deletion kind")
    if receipt.known_residue and receipt.status == "ACCEPT":
        raise cleanup.CleanupError("cleanup V2 known residue blocks acceptance")
    for target in receipt.known_residue:
        if target.kind not in new or target.ident not in new[target.kind]:
            raise cleanup.CleanupError("cleanup V2 known residue not found in final inventory")
    _verify_historical_quarantine(receipt, before, after)
    if receipt.status == "ACCEPT":
        final = cleanup.plan(
            after,
            receipt.attempt_id,
            preserve_images=protected_images
            | frozenset(proof.ident for proof in receipt.retained_attested),
            preserve_containers=protected_containers,
            retire_containers=frozenset(),
        )
        if final.targets or final.uncertain:
            raise cleanup.CleanupError("cleanup V2 unretired Boca residue prevents acceptance")


def _counts(snapshot: cleanup.Inventory) -> dict[str, int]:
    return {
        "containers": len(snapshot.containers),
        "images": len(snapshot.images),
        "networks": len(snapshot.networks),
        "volumes": len(snapshot.volumes),
        "global_images": len(snapshot.global_image_ids),
    }


def _protected_pair(
    receipt: cleanup.CleanupReceipt,
    after: cleanup.Inventory,
    protected_containers: frozenset[str],
    protected_images: frozenset[str],
) -> dict[str, dict[str, str | bool]] | None:
    """Positive final pair identity, never guessed from two container counts."""
    if receipt.outcome != "SUCCESS" or receipt.status != "ACCEPT":
        return None  # Failed installs may have zero resources; never release-ACCEPT.
    roles: dict[str, dict[str, str | bool]] = {}
    for role, service in (("controller", "controller"), ("worker", "browser-worker")):
        matches = [
            container
            for container in after.containers
            if dict(container.labels).get("com.docker.compose.service") == service
        ]
        if len(matches) != 1:
            raise cleanup.CleanupError("cleanup V2 protected controller/worker role ambiguous")
        container = matches[0]
        if (
            container.ident not in protected_containers
            or container.image_id not in protected_images
            or role == "controller"
            and not container.running
        ):
            raise cleanup.CleanupError("cleanup V2 exact active pair is not protected")
        roles[role] = {
            "id": container.ident,
            "image_id": container.image_id,
            "running": container.running,
        }
    allowed_containers = frozenset(
        {
            str(roles["controller"]["id"]),
            str(roles["worker"]["id"]),
        }
    )
    allowed_images = frozenset(
        {
            str(roles["controller"]["image_id"]),
            str(roles["worker"]["image_id"]),
        }
    )
    if (
        roles["controller"]["id"] == roles["worker"]["id"]
        or roles["controller"]["image_id"] == roles["worker"]["image_id"]
        or protected_containers != allowed_containers
        or not allowed_images <= protected_images
        or protected_images - allowed_images
        not in (frozenset(), frozenset({cleanup.HISTORICAL_RETIRE_TARGET}))
        or cleanup.HISTORICAL_RETIRE_TARGET in protected_images
        and not receipt.retained_attested
    ):
        raise cleanup.CleanupError("cleanup V2 exact dual pair identities are not distinct")
    return roles


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for key, value in pairs:
        if key in fields:
            raise cleanup.CleanupError("cleanup V2 duplicate JSON fields")
        fields[key] = value
    return fields


def _strict_nonnegative_integer_fields(value: object, keys: frozenset[str]) -> dict[str, int]:
    if (
        type(value) is not dict
        or set(value) != keys
        or any(type(item) is not int or item < 0 for item in value.values())
    ):
        raise cleanup.CleanupError("cleanup V2 physical counter schema invalid")
    return value


def _resources(value: object) -> list[tuple[str, str]]:
    if type(value) is not list or len(value) > cleanup.MAX_DELETIONS:
        raise cleanup.CleanupError("cleanup V2 resource set unbounded")
    result: list[tuple[str, str]] = []
    for item in value:
        if type(item) is not dict or set(item) != {"kind", "id"}:
            raise cleanup.CleanupError("cleanup V2 exact resource tuple malformed")
        kind, ident = item["kind"], item["id"]
        if type(kind) is not str or type(ident) is not str:
            raise cleanup.CleanupError("cleanup V2 exact resource type malformed")
        if kind in ("container", "network"):
            authorized = re.fullmatch(r"[0-9a-f]{64}", ident) is not None
        elif kind == "image":
            authorized = re.fullmatch(r"sha256:[0-9a-f]{64}", ident) is not None
        elif kind == "volume":
            authorized = (
                re.fullmatch(r"boca-socios_[A-Za-z0-9_.-]{1,110}", ident) is not None
                and ident not in cleanup.PROTECTED_VOLUMES
            )
        else:
            authorized = False
        if (
            not authorized
            or (kind, ident) in result
            or (kind == "image" and ident == cleanup.HISTORICAL_RETIRE_TARGET)
        ):
            raise cleanup.CleanupError("cleanup V2 resource identity unproven")
        result.append((kind, ident))
    return result


def canonical_cleanup_v2_receipt(
    receipt: cleanup.CleanupReceipt,
    *,
    before: cleanup.Inventory,
    after: cleanup.Inventory,
    protected_containers: frozenset[str],
    protected_images: frozenset[str],
) -> bytes:
    """Bind the existing verified cleanup result to exact resource counts."""
    _snapshot_is_boca_only(before)
    _snapshot_is_boca_only(after)
    _verify_positive_deltas(receipt, before, after, protected_containers, protected_images)
    body = json.loads(receipt.redacted_json())
    body["version"] = 2
    body["scope"] = COUNTED_V2_SCOPE
    body.setdefault("retained_attested", [])
    body["before_counts"] = _counts(before)
    body["after_counts"] = _counts(after)
    body["protected_pair"] = _protected_pair(receipt, after, protected_containers, protected_images)
    result = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")
    if not 0 < len(result) <= MAX_RECEIPT_BYTES:
        raise cleanup.CleanupError("cleanup V2 public receipt exceeds bounded size")
    return result


def verify_cleanup_v2_receipt(
    raw: bytes, expected_attempt_id: str, *, require_install_success: bool = True
) -> dict[str, object]:
    """Independently reject malformed/ambiguous postflight evidence.

    This validates a host-produced receipt, not Docker ownership by itself:
    the emitting job must run the positive inventory/lease checks first.
    """
    if (
        type(raw) is not bytes
        or not 0 < len(raw) <= MAX_RECEIPT_BYTES
        or type(expected_attempt_id) is not str
        or not cleanup.ATTEMPT_ID.fullmatch(expected_attempt_id)
        or type(require_install_success) is not bool
    ):
        raise cleanup.CleanupError("cleanup V2 bounded attempt or receipt invalid")
    try:
        body = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_fields)
        canonical = json.dumps(
            body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("ascii")
    except (ValueError, UnicodeError, TypeError, OverflowError) as exc:
        raise cleanup.CleanupError("cleanup V2 JSON malformed") from exc
    if type(body) is not dict or set(body) != _KEYS or canonical != raw:
        raise cleanup.CleanupError("cleanup V2 JSON schema or canonical bytes invalid")
    if type(body["version"]) is not int or body["version"] != 2:
        raise cleanup.CleanupError("cleanup V2 schema unsupported")
    if (
        body["scope"] != COUNTED_V2_SCOPE
        or body["attempt_id"] != expected_attempt_id
        or body["outcome"] not in ("SUCCESS", "FAILURE")
        or body["status"] not in ("ACCEPT", "NO_GO", "INDETERMINATE")
    ):
        raise cleanup.CleanupError("cleanup V2 attempt does not match")
    before = _strict_nonnegative_integer_fields(body["before"], _DISK_KEYS)
    after = _strict_nonnegative_integer_fields(body["after"], _DISK_KEYS)
    if any(
        before[key] != after[key]
        for key in ("stage_device", "stage_inode", "docker_device", "docker_inode")
    ):
        raise cleanup.CleanupError("cleanup V2 storage identity drifted")
    before_counts = _strict_nonnegative_integer_fields(body["before_counts"], _COUNT_KEYS)
    after_counts = _strict_nonnegative_integer_fields(body["after_counts"], _COUNT_KEYS)
    if (
        any(item > cleanup.MAX_OBJECTS for item in before_counts.values())
        or any(item > cleanup.MAX_OBJECTS for item in after_counts.values())
        or sum(before_counts[key] for key in ("containers", "images", "networks", "volumes"))
        > cleanup.MAX_OBJECTS
        or sum(after_counts[key] for key in ("containers", "images", "networks", "volumes"))
        > cleanup.MAX_OBJECTS
        or before_counts["global_images"] != before_counts["images"]
        or after_counts["global_images"] != after_counts["images"]
    ):
        raise cleanup.CleanupError("cleanup V2 image census/count bounds untrusted")
    removed = _resources(body["removed"])
    _resources(body["known_residue"])
    count_kinds = {
        "containers": "container",
        "images": "image",
        "networks": "network",
        "volumes": "volume",
        "global_images": "image",
    }
    for key, kind in count_kinds.items():
        if before_counts[key] - after_counts[key] != sum(
            item_kind == kind for item_kind, _ident in removed
        ):
            raise cleanup.CleanupError("cleanup V2 exact removed ID count disagrees with census")
    uncertain = body["retained_uncertain"]
    if (
        type(uncertain) is not list
        or len(uncertain) > cleanup.MAX_OBJECTS
        or any(
            type(reason) is not str or re.fullmatch(r"[A-Za-z0-9:_.-]{1,220}", reason) is None
            for reason in uncertain
        )
    ):
        raise cleanup.CleanupError("cleanup V2 untrusted uncertainty category")
    if body["retained_attested"] not in ([], [_HISTORICAL_ENTRY]):
        raise cleanup.CleanupError("cleanup V2 R108 quarantine proof mismatched")
    if body["retained_attested"] and (not before_counts["images"] or not after_counts["images"]):
        raise cleanup.CleanupError("cleanup V2 quarantined image absent from count inventory")
    pair = body["protected_pair"]
    if body["outcome"] == "SUCCESS" and body["status"] == "ACCEPT":
        if type(pair) is not dict or set(pair) != {"controller", "worker"}:
            raise cleanup.CleanupError("cleanup V2 accepted pair evidence absent")
        identities: list[tuple[str, str]] = []
        for role in ("controller", "worker"):
            item = pair[role]
            if type(item) is not dict or set(item) != {"id", "image_id", "running"}:
                raise cleanup.CleanupError("cleanup V2 accepted pair identity malformed")
            ident, image_id, running = item["id"], item["image_id"], item["running"]
            if (
                type(ident) is not str
                or re.fullmatch(r"[0-9a-f]{64}", ident) is None
                or type(image_id) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
                or type(running) is not bool
                or role == "controller"
                and running is not True
                or ("container", ident) in removed
                or ("image", image_id) in removed
            ):
                raise cleanup.CleanupError("cleanup V2 accepted pair identity unproven")
            identities.append((ident, image_id))
        if (
            len({ident for ident, _image_id in identities}) != 2
            or len({image_id for _ident, image_id in identities}) != 2
            or before_counts["containers"] < 2
            or after_counts["containers"] < 2
            or before_counts["images"] < 2
            or after_counts["images"] < 2
        ):
            raise cleanup.CleanupError("cleanup V2 accepted dual pair counts or IDs absent")
    elif pair is not None:
        raise cleanup.CleanupError("cleanup V2 non-accepted install cannot claim active pair")
    if body["status"] == "ACCEPT" and (uncertain or body["known_residue"]):
        raise cleanup.CleanupError("cleanup V2 unknown or known residue blocks acceptance")
    if require_install_success and (body["outcome"] != "SUCCESS" or body["status"] != "ACCEPT"):
        raise cleanup.CleanupError("cleanup V2 installation not accepted")
    return body
