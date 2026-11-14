"""Unwired, durable FAILURE cleanup for a failed successor Boca pair attempt.

This is *not* the SUCCESS-only finalizer, not a deployment entrypoint, and
never changes the successor transaction interlock. A prior compensation is
required before mutating a positively restored old pair; other failure states
are inventoried only. Every physical operation remains Boca-rootless, exact
identity and same lease. A failed installation is always NO_GO.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from boca_socios import host_boca_binding_observe as binding
from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cleanup_v2 as counted
from boca_socios import host_boca_current_retained as current_resources
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios import host_cutover_stage as stage
from boca_socios import host_on_demand_service as service
from boca_socios.host_boca_pair_upgrade import PairCoordinates
from boca_socios.host_boca_repeatable_journal import FreshPairWitness
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

INTENT_SUFFIX = ".failure-cleanup-v2.intent"
RECEIPT_SUFFIX = ".failure-cleanup-v2.receipt"
_JOURNAL_PREFIX = ".boca-pair-upgrade-"
_JOURNAL_VERSION = "boca-successor-pair-intent-evidence-v1"
_EXPECTED_R108 = cleanup.HistoricalRetainedImageProof(
    cleanup.HISTORICAL_RETIRE_TARGET,
    cleanup.HISTORICAL_RETIRE_DIGEST,
    cleanup.HISTORICAL_RETIRE_REVISION,
)
_CONTROL_MOUNTS = frozenset(
    {
        "boca-socios_boca_data",
        "boca-socios_boca_key",
        "boca-socios_boca_owner",
        "boca-socios_boca_site_config",
        "boca-socios_boca_browser_ipc",
    }
)
_WORKER_MOUNTS = frozenset({"boca-socios_boca_site_config", "boca-socios_boca_browser_ipc"})
_PRIVATE_NETWORK = "boca-socios_boca_private"
_EGRESS_NETWORK = "boca-socios_boca_browser_egress"
_IPC_VOLUME = "boca-socios_boca_browser_ipc"
_SITE_VOLUME = "boca-socios_boca_site_config"
_ROOTLESS_IDENTITY = (10001, 10001, "/home/boca-deploy/.local/share/docker")
_HASH64 = re.compile(r"[0-9a-f]{64}\Z")


class FailureCleanupNoGo(ValueError):
    """Stable refusal without Docker output, secret data or host paths."""

    state = "NO_GO"
    cleanup = "INDETERMINATE"


def _fail() -> FailureCleanupNoGo:
    return FailureCleanupNoGo("BOCA_FAILURE_CLEANUP state=NO_GO cleanup=INDETERMINATE")


def failure_cleanup_filenames(attempt_id: str) -> tuple[str, str]:
    """Per-attempt journal siblings; a prior failure cannot block another run."""
    if type(attempt_id) is not str or cleanup.ATTEMPT_ID.fullmatch(attempt_id) is None:
        raise _fail()
    stem = f"{_JOURNAL_PREFIX}{attempt_id}"
    return stem + INTENT_SUFFIX, stem + RECEIPT_SUFFIX


@dataclass(frozen=True, slots=True)
class DurableFailureCleanupReceipt:
    """A FAILURE cleanup receipt is never an installation authority."""

    attempt_id: str
    cleanup_status: str
    raw: bytes
    sha256: str
    intent_sha256: str
    state: str = "NO_GO"

    @property
    def apply_authorized(self) -> bool:
        return False


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for name, item in pairs:
        if name in value:
            raise _fail()
        value[name] = item
    return value


def _parse_canonical(raw: bytes) -> dict[str, object]:
    try:
        parsed = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_object)
        if type(parsed) is not dict or _canonical(parsed) != raw:
            raise _fail()
        return parsed
    except (UnicodeError, TypeError, ValueError, OverflowError) as exc:
        raise _fail() from exc


def _canonical(value: dict[str, object]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def _verify_original_journal(plan: PairCoordinates, root: int) -> tuple[str, adapters.ResourcePins]:
    """Authenticate exact attempt coordinates from prior immutable journal.

    Journal provenance originates in the separately authenticated successor
    writer. This reader refuses the legacy no-evidence journal and never
    treats a newly assembled JSON object as a release authorization.
    """
    name = f"{_JOURNAL_PREFIX}{plan.attempt_id}"
    prior, _ = stage._read_file(root, f"{name}.intent", None, limit=1024)
    evidence, _ = stage._read_file(root, f"{name}.evidence", None, limit=4096)
    linked = _parse_canonical(prior)
    origin = _parse_canonical(evidence)
    expected_intent = {
        "attempt": plan.attempt_id,
        "evidence_sha256": hashlib.sha256(evidence).hexdigest(),
        "old_controller": plan.old_controller_id,
        "old_worker": plan.old_worker_id,
        "old_source": plan.old_source_sha,
        "new_source": plan.new_source_sha,
        "release": plan.release_run_id,
    }
    release = origin.get("release")
    witness = origin.get("witness")
    if (
        linked != expected_intent
        or set(origin) != {"version", "plan", "release", "witness"}
        or origin["version"] != _JOURNAL_VERSION
        or origin["plan"] != asdict(plan)
        or type(release) is not dict
        or set(release)
        != {
            "source_sha",
            "release_run_id",
            "controller_ref",
            "worker_ref",
            "controller_manifest_sha256",
            "paired_manifest_sha256",
        }
        or any(
            type(release[name]) is not str or _HASH64.fullmatch(release[name]) is None
            for name in ("controller_manifest_sha256", "paired_manifest_sha256")
        )
        or any(
            release.get(name) != value
            for name, value in (
                ("source_sha", plan.new_source_sha),
                ("release_run_id", plan.release_run_id),
                ("controller_ref", plan.controller_ref),
                ("worker_ref", plan.worker_ref),
            )
        )
        or type(witness) is not dict
        or set(witness)
        != {
            "observation_run_id",
            "old_attempt_id",
            "old_source_sha",
            "controller_id",
            "worker_id",
            "controller_image_id",
            "worker_image_id",
            "control_inode_sha256",
            "retained",
        }
        or any(
            witness.get(name) != value
            for name, value in (
                ("observation_run_id", plan.observation_run_id),
                ("old_attempt_id", plan.old_attempt_id),
                ("old_source_sha", plan.old_source_sha),
                ("controller_id", plan.old_controller_id),
                ("worker_id", plan.old_worker_id),
                ("controller_image_id", plan.old_controller_image_id),
                ("worker_image_id", plan.old_worker_image_id),
            )
        )
    ):
        raise _fail()
    raw_retained = witness["retained"]
    if type(raw_retained) is not dict:
        raise _fail()
    retained = adapters.ResourcePins(**raw_retained)
    retained.validate()
    FreshPairWitness(
        witness["observation_run_id"],
        witness["old_attempt_id"],
        witness["old_source_sha"],
        witness["controller_id"],
        witness["worker_id"],
        witness["controller_image_id"],
        witness["worker_image_id"],
        retained,
        witness["control_inode_sha256"],
    ).validate(plan, retained)
    return hashlib.sha256(prior).hexdigest(), retained


def _require_absent(root: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=root, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise _fail()


def _directory_unchanged(root: int, location: Path, identity: tuple[int, int]) -> None:
    first = os.fstat(root)
    last = os.stat(location, follow_symlinks=False)
    if (
        (first.st_dev, first.st_ino) != identity
        or (last.st_dev, last.st_ino) != identity
        or not stat.S_ISDIR(last.st_mode)
        or last.st_uid != os.geteuid()
        or last.st_gid != os.getegid()
        or stat.S_IMODE(last.st_mode) != 0o700
    ):
        raise _fail()


def _probe_r108(lease: cleanup.BocaJobLease, plan: PairCoordinates) -> cleanup.Inventory:
    cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
    snapshot = cleanup.capture_inventory()
    counted._snapshot_is_boca_only(snapshot)
    if cleanup.attest_historical_retained_image(snapshot) != _EXPECTED_R108:
        raise _fail()
    cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
    return snapshot


def _unrestored_failure_receipt(
    plan: PairCoordinates, lease: cleanup.BocaJobLease
) -> tuple[bytes, str]:
    first = _probe_r108(lease, plan)
    second = _probe_r108(lease, plan)
    result = cleanup.CleanupReceipt(
        "FAILURE",
        plan.attempt_id,
        "NO_GO",
        first.disk,
        second.disk,
        (),
        ("restoration-not-proven",),
        (),
        (_EXPECTED_R108,),
    )
    raw = counted.canonical_cleanup_v2_receipt(
        result,
        before=first,
        after=second,
        protected_containers=frozenset(),
        protected_images=frozenset(),
    )
    counted.verify_cleanup_v2_receipt(raw, plan.attempt_id, require_install_success=False)
    return raw, "NO_GO"


def _restored_snapshot(
    plan: PairCoordinates,
    lease: cleanup.BocaJobLease,
    pins: adapters.ResourcePins,
    retained_io: adapters.RetainedResourceIO,
    *,
    current_retained: bytes | None = None,
) -> cleanup.Inventory:
    """Check the restored pair and immutable owner volumes before each effect."""
    snapshot = _probe_r108(lease, plan)
    installed = service.read_installed_binding(lease)
    images = {item.ident: item for item in snapshot.images}
    containers = {item.ident: item for item in snapshot.containers}
    if (
        type(installed) is not OnDemandInstallation
        or retained_io.rootless_identity() != _ROOTLESS_IDENTITY
        or (
            installed.installation_run_id,
            installed.source_sha,
            installed.controller_id,
            installed.worker_id,
            installed.database_path,
        )
        != (
            plan.old_attempt_id,
            plan.old_source_sha,
            plan.old_controller_id,
            plan.old_worker_id,
            binding.CANONICAL_DATABASE,
        )
        or not _CONTROL_MOUNTS <= {item.name for item in snapshot.volumes}
        or len(containers) != len(snapshot.containers)
    ):
        raise _fail()
    installed.pair.require()
    current_resources.reprove_binding(current_retained, installed)
    for role, cid, image_id, image_ref, running, mounts, config_hash in (
        (
            "controller",
            plan.old_controller_id,
            plan.old_controller_image_id,
            installed.controller_image,
            True,
            _CONTROL_MOUNTS,
            installed.pair.controller_config_hash,
        ),
        (
            "browser-worker",
            plan.old_worker_id,
            plan.old_worker_image_id,
            installed.worker_image,
            False,
            _WORKER_MOUNTS,
            installed.pair.worker_config_hash,
        ),
    ):
        container = containers.get(cid)
        image = images.get(image_id)
        if (
            container is None
            or image is None
            or container.image_id != image_id
            or container.running is not running
            or frozenset(container.volumes) != mounts
            or image.source != cleanup.BOCA_SOURCE
            or image_ref not in image.references
            or dict(container.labels).get("com.docker.compose.project") != cleanup.BOCA_PROJECT
            or dict(container.labels).get("com.docker.compose.service") != role
            or dict(container.labels).get("boca.socios.browser-ipc-attempt") != plan.old_attempt_id
            or dict(container.labels).get("org.opencontainers.image.revision")
            != plan.old_source_sha
            or dict(container.labels).get("com.docker.compose.config-hash") != config_hash
            or (role == "controller" and container.networks != (_PRIVATE_NETWORK,))
            or (role == "browser-worker" and container.networks not in ((), (_EGRESS_NETWORK,)))
            or pair._safe_mounts(
                retained_io.mounts(cid),
                service=role,
                valid_volumes=_CONTROL_MOUNTS,
                historical=False,
            )
            != sorted(mounts)
        ):
            raise _fail()
        if role == "browser-worker":
            state = retained_io.worker_state(cid)
            if not isinstance(state, dict):
                raise _fail()
            current_resources.require_worker(
                current_resources.docker_worker(state), cid, current_retained
            )
    by_network = {item.name: item for item in snapshot.networks}
    private = by_network.get(_PRIVATE_NETWORK)
    egress = by_network.get(_EGRESS_NETWORK)
    if (
        private is None
        or egress is None
        or egress.ident != pins.egress_id
        or private.attached_ids != (plan.old_controller_id,)
        or egress.attached_ids
        or cleanup._labels(private.labels).get("com.docker.compose.project") != cleanup.BOCA_PROJECT
        or cleanup._labels(egress.labels)
        != {
            "com.docker.compose.project": cleanup.BOCA_PROJECT,
            "com.docker.compose.network": "boca_browser_egress",
            "boca.socios.browser-ipc-attempt": pins.egress_creator_attempt,
        }
    ):
        raise _fail()
    by_volume = {item.name: item for item in snapshot.volumes}
    for name, role, attempt, inode in (
        (_IPC_VOLUME, "boca_browser_ipc", pins.ipc_creator_attempt, pins.ipc_inode_sha256),
        (_SITE_VOLUME, "boca_site_config", pins.site_creator_attempt, pins.site_inode_sha256),
    ):
        found = by_volume.get(name)
        if (
            found is None
            or cleanup._labels(found.labels)
            != {
                "com.docker.compose.project": cleanup.BOCA_PROJECT,
                "com.docker.compose.volume": role,
                "boca.socios.browser-ipc-attempt": attempt,
            }
            or retained_io.identity(name) != inode
        ):
            raise _fail()
    for cid, container in containers.items():
        if cid in (plan.old_controller_id, plan.old_worker_id):
            continue
        labels = dict(container.labels)
        image = images.get(container.image_id)
        candidate_role = labels.get("com.docker.compose.service")
        expected_ref = plan.controller_ref if candidate_role == "controller" else plan.worker_ref
        if (
            container.running
            or labels.get("com.docker.compose.project") != cleanup.BOCA_PROJECT
            or labels.get("boca.socios.browser-ipc-attempt") != plan.attempt_id
            or labels.get("org.opencontainers.image.revision") != plan.new_source_sha
            or candidate_role not in ("controller", "browser-worker")
            or _HASH64.fullmatch(labels.get("com.docker.compose.config-hash", "")) is None
            or image is None
            or image.source != cleanup.BOCA_SOURCE
            or image.references != (expected_ref,)
        ):
            raise _fail()
    cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
    return snapshot


def _allowed_failure_targets(
    plan: PairCoordinates, initial: cleanup.Inventory
) -> tuple[frozenset[cleanup.Target], frozenset[str], frozenset[str]]:
    """Freeze exact attempt-only deletion candidates, preserving every unknown."""
    old = frozenset({plan.old_controller_id, plan.old_worker_id})
    candidates = frozenset(item.ident for item in initial.containers if item.ident not in old)
    candidate_images = frozenset(
        image.ident
        for image in initial.images
        if image.source == cleanup.BOCA_SOURCE
        and image.references in ((plan.controller_ref,), (plan.worker_ref,))
        and image.ident not in {plan.old_controller_image_id, plan.old_worker_image_id}
    )
    allowed: set[cleanup.Target] = {
        *(cleanup.Target("container", ident) for ident in candidates),
        *(cleanup.Target("image", ident) for ident in candidate_images),
    }
    for volume in initial.volumes:
        labels = dict(volume.labels)
        if (
            volume.name not in cleanup.PROTECTED_VOLUMES
            and volume.name.startswith("boca-socios_")
            and labels.get("com.docker.compose.project") == cleanup.BOCA_PROJECT
            and cleanup._attempt_owner(labels, plan.attempt_id)
        ):
            allowed.add(cleanup.Target("volume", volume.name))
    for network in initial.networks:
        labels = dict(network.labels)
        if (
            network.name.startswith("boca-socios_")
            and labels.get("com.docker.compose.project") == cleanup.BOCA_PROJECT
            and cleanup._attempt_owner(labels, plan.attempt_id)
            and set(network.attached_ids) <= candidates
        ):
            allowed.add(cleanup.Target("network", network.ident))
    if len(allowed) > cleanup.MAX_DELETIONS:
        raise _fail()
    preserve_images = frozenset(
        image.ident for image in initial.images if image.ident not in candidate_images
    )
    return frozenset(allowed), candidates, preserve_images


def _restored_failure_receipt(
    plan: PairCoordinates,
    lease: cleanup.BocaJobLease,
    *,
    verify_journal: Any,
    retained_pins: adapters.ResourcePins,
    retained_io: adapters.RetainedResourceIO,
    current_retained: bytes | None = None,
) -> tuple[bytes, str]:
    initial = _restored_snapshot(
        plan, lease, retained_pins, retained_io, current_retained=current_retained
    )
    second = _restored_snapshot(
        plan, lease, retained_pins, retained_io, current_retained=current_retained
    )
    if initial != second:
        raise _fail()
    allow, retire_containers, preserve_images = _allowed_failure_targets(plan, initial)
    old = frozenset({plan.old_controller_id, plan.old_worker_id})
    frozen_images = {item.ident: item for item in initial.images}
    frozen_volumes = {item.name: item for item in initial.volumes}
    frozen_networks = {item.ident: item for item in initial.networks}
    first: cleanup.Inventory | None = None
    last: cleanup.Inventory | None = None

    def protected_probe() -> cleanup.Inventory:
        nonlocal first, last
        verify_journal()
        snapshot = _restored_snapshot(
            plan, lease, retained_pins, retained_io, current_retained=current_retained
        )
        if first is None:
            first = snapshot
        last = snapshot
        return snapshot

    def protected_delete(target: cleanup.Target) -> None:
        if target not in allow:
            raise cleanup.CleanupError("Boca FAILURE resource outside exact attempt allowlist")
        verify_journal()
        snapshot = _restored_snapshot(
            plan, lease, retained_pins, retained_io, current_retained=current_retained
        )
        ids = {
            "container": {c.ident for c in snapshot.containers},
            "image": {i.ident for i in snapshot.images},
            "network": {n.ident for n in snapshot.networks},
            "volume": {v.name for v in snapshot.volumes},
        }
        if target.ident not in ids[target.kind]:
            raise cleanup.CleanupError("Boca FAILURE target changed before exact deletion")
        if target.kind == "container":
            container = next(c for c in snapshot.containers if c.ident == target.ident)
            if container.running or target.ident not in retire_containers:
                raise cleanup.CleanupError("Boca FAILURE live or non-attempt container retained")
        if target.kind == "image":
            current_image = next(
                (item for item in snapshot.images if item.ident == target.ident), None
            )
            if (
                target.ident in preserve_images
                or current_image is None
                or current_image != frozen_images.get(target.ident)
                or current_image.source != cleanup.BOCA_SOURCE
                or current_image.references not in ((plan.controller_ref,), (plan.worker_ref,))
                or any(container.image_id == target.ident for container in snapshot.containers)
            ):
                raise cleanup.CleanupError("Boca FAILURE image identity or references changed")
        if target.kind == "volume":
            current_volume = next(
                (item for item in snapshot.volumes if item.name == target.ident), None
            )
            if (
                target.ident in cleanup.PROTECTED_VOLUMES
                or current_volume is None
                or current_volume != frozen_volumes.get(target.ident)
                or cleanup._labels(current_volume.labels).get("com.docker.compose.project")
                != cleanup.BOCA_PROJECT
                or not cleanup._attempt_owner(
                    cleanup._labels(current_volume.labels), plan.attempt_id
                )
                or any(target.ident in container.volumes for container in snapshot.containers)
            ):
                raise cleanup.CleanupError("Boca FAILURE volume ownership changed")
        if target.kind == "network":
            current_network = next(
                (item for item in snapshot.networks if item.ident == target.ident), None
            )
            if (
                current_network is None
                or current_network != frozen_networks.get(target.ident)
                or cleanup._labels(current_network.labels).get("com.docker.compose.project")
                != cleanup.BOCA_PROJECT
                or not cleanup._attempt_owner(
                    cleanup._labels(current_network.labels), plan.attempt_id
                )
                or current_network.attached_ids
            ):
                raise cleanup.CleanupError("Boca FAILURE network ownership changed")
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        cleanup.delete_exact(target)

    result = cleanup.execute(
        "FAILURE",
        plan.attempt_id,
        preserve_images=preserve_images,
        preserve_containers=old,
        retire_containers=retire_containers,
        probe=protected_probe,
        delete_exact=protected_delete,
    )
    if first is None or last is None or result.before != first.disk or result.after != last.disk:
        raise _fail()
    result = replace(result, retained_attested=(_EXPECTED_R108,))
    raw = counted.canonical_cleanup_v2_receipt(
        result,
        before=first,
        after=last,
        protected_containers=old,
        protected_images=frozenset({plan.old_controller_image_id, plan.old_worker_image_id}),
    )
    counted.verify_cleanup_v2_receipt(raw, plan.attempt_id, require_install_success=False)
    return raw, result.status


def execute_durable_failure_cleanup(
    plan: PairCoordinates,
    lease: cleanup.BocaJobLease,
    *,
    restored: bool,
    receipt_dir: Path,
    historical_retained: cleanup.HistoricalRetainedImageProof,
    retained_io: adapters.RetainedResourceIO | None = None,
    current_retained: bytes | None = None,
) -> DurableFailureCleanupReceipt:
    """One immutable failure receipt, never a retry or accepted deployment.

    This function has no CLI/workflow binding. An interrupted write leaves
    the intent in place; the caller must retain NO_GO and inspect anew.
    """
    root: int | None = None
    try:
        if (
            type(plan) is not PairCoordinates
            or type(restored) is not bool
            or not isinstance(receipt_dir, Path)
            or receipt_dir != stage.ROOT
            or type(historical_retained) is not cleanup.HistoricalRetainedImageProof
            or historical_retained != _EXPECTED_R108
            or (restored and retained_io is None)
        ):
            raise _fail()
        plan.validate()
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        root = stage._root_fd()
        directory = os.fstat(root)
        identity = (directory.st_dev, directory.st_ino)
        intent_name, receipt_name = failure_cleanup_filenames(plan.attempt_id)
        _require_absent(root, intent_name)
        _require_absent(root, receipt_name)
        _require_absent(root, f"{_JOURNAL_PREFIX}{plan.attempt_id}.terminal")
        if restored:
            _require_absent(root, f"{_JOURNAL_PREFIX}{plan.attempt_id}.commit")
        previous_sha, retained_pins = _verify_original_journal(plan, root)
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        intent = _canonical(
            {
                "attempt_id": plan.attempt_id,
                "journal_intent_sha256": previous_sha,
                "restored_claim": restored,
                "schema": 1,
                "source_sha": plan.new_source_sha,
            }
        )
        stage._create_exclusive(root, intent_name, intent)
        if (
            stage._read_file(root, intent_name, hashlib.sha256(intent).hexdigest(), limit=1024)[0]
            != intent
        ):
            raise _fail()
        _directory_unchanged(root, receipt_dir, identity)
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)

        def verify_journal() -> None:
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            _directory_unchanged(root, receipt_dir, identity)
            if _verify_original_journal(plan, root) != (previous_sha, retained_pins):
                raise _fail()
            if restored:
                _require_absent(root, f"{_JOURNAL_PREFIX}{plan.attempt_id}.commit")

        if restored:
            if retained_io is None:
                raise _fail()
            raw, status = _restored_failure_receipt(
                plan,
                lease,
                verify_journal=verify_journal,
                retained_pins=retained_pins,
                retained_io=retained_io,
                current_retained=current_retained,
            )
        else:
            raw, status = _unrestored_failure_receipt(plan, lease)
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        _directory_unchanged(root, receipt_dir, identity)
        stage._create_exclusive(root, receipt_name, raw)
        if (
            stage._read_file(
                root,
                receipt_name,
                hashlib.sha256(raw).hexdigest(),
                limit=counted.MAX_RECEIPT_BYTES,
            )[0]
            != raw
        ):
            raise _fail()
        if _verify_original_journal(plan, root) != (previous_sha, retained_pins):
            raise _fail()
        counted.verify_cleanup_v2_receipt(raw, plan.attempt_id, require_install_success=False)
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        _directory_unchanged(root, receipt_dir, identity)
        return DurableFailureCleanupReceipt(
            plan.attempt_id,
            status,
            raw,
            hashlib.sha256(raw).hexdigest(),
            hashlib.sha256(intent).hexdigest(),
        )
    except Exception:
        raise _fail() from None
    finally:
        if root is not None:
            os.close(root)
