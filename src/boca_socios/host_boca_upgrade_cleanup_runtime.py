"""Unwired successor final-cleanup bridge: same-lease V2 and durable receipt.

This module MUST only be invoked by the future reviewed protected Boca pair
finalizer, after the active pair was verified. It does not acquire a lease,
change the existing backend interlock, or authorize an APPLY. The existing
Boca-only cleanup engine performs the only potential Docker operations; this
wrapper insists on its same-execution before/after inventories and R108 proof.

An exclusive, fsynced intent is written BEFORE the existing cleanup engine
can act. A failure after intent creation leaves the intent in place without a
successful receipt. Never retry that attempt or infer success from a Docker ACK.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cleanup_v2 as counted
from boca_socios.host_boca_pair_upgrade import PairCoordinates

INTENT_FILENAME = "boca-final-cleanup-v2.intent"
RECEIPT_FILENAME = "boca-final-cleanup-v2.receipt"
_CID = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_REQUIRED_VOLUMES = frozenset(
    {
        "boca-socios_boca_data",
        "boca-socios_boca_key",
        "boca-socios_boca_owner",
        "boca-socios_boca_site_config",
        "boca-socios_boca_browser_ipc",
    }
)
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600


class FinalCleanupNoGo(ValueError):
    """No cleanup outcome can authorize BETA from this unwired bridge."""

    state = "NO_GO"
    cleanup = "INDETERMINATE"


def _fail() -> FinalCleanupNoGo:
    return FinalCleanupNoGo("BOCA_FINAL_CLEANUP state=NO_GO cleanup=INDETERMINATE")


@dataclass(frozen=True, slots=True)
class DurableFinalCleanupReceipt:
    """Canonical counted V2 bytes, not a release or host-acceptance token."""

    attempt_id: str
    status: str
    raw: bytes
    sha256: str
    intent_sha256: str

    @property
    def apply_authorized(self) -> bool:
        return False


def _validated_pair(
    plan: PairCoordinates,
    controller_id: str,
    worker_id: str,
    controller_image_id: str,
    worker_image_id: str,
    historical_retained: cleanup.HistoricalRetainedImageProof,
) -> tuple[frozenset[str], frozenset[str]]:
    if type(plan) is not PairCoordinates:
        raise _fail()
    plan.validate()
    if (
        any(
            type(value) is not str or _CID.fullmatch(value) is None
            for value in (controller_id, worker_id)
        )
        or any(
            type(value) is not str or _IMAGE.fullmatch(value) is None
            for value in (controller_image_id, worker_image_id)
        )
        or controller_id == worker_id
        or controller_image_id == worker_image_id
        or {controller_id, worker_id} & {plan.old_controller_id, plan.old_worker_id}
        or {controller_image_id, worker_image_id}
        & {plan.old_controller_image_id, plan.old_worker_image_id}
        or type(historical_retained) is not cleanup.HistoricalRetainedImageProof
        or historical_retained
        != cleanup.HistoricalRetainedImageProof(
            cleanup.HISTORICAL_RETIRE_TARGET,
            cleanup.HISTORICAL_RETIRE_DIGEST,
            cleanup.HISTORICAL_RETIRE_REVISION,
        )
    ):
        raise _fail()
    return frozenset({controller_id, worker_id}), frozenset({controller_image_id, worker_image_id})


def _private_directory(path: Path) -> tuple[int, tuple[int, int]]:
    if not isinstance(path, Path) or not path.is_absolute() or not path.name:
        raise _fail()
    handle = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        metadata = os.fstat(handle)
        current = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != _PRIVATE_DIRECTORY_MODE
            or (metadata.st_dev, metadata.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise _fail()
        return handle, (metadata.st_dev, metadata.st_ino)
    except BaseException:
        os.close(handle)
        raise


def _directory_unchanged(handle: int, path: Path, identity: tuple[int, int]) -> None:
    opened = os.fstat(handle)
    current = os.stat(path, follow_symlinks=False)
    if (
        (opened.st_dev, opened.st_ino) != identity
        or (current.st_dev, current.st_ino) != identity
        or not stat.S_ISDIR(current.st_mode)
        or current.st_uid != os.geteuid()
        or stat.S_IMODE(current.st_mode) != _PRIVATE_DIRECTORY_MODE
    ):
        raise _fail()


def _write_once(parent: int, name: str, raw: bytes) -> None:
    handle = os.open(
        name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        _PRIVATE_FILE_MODE,
        dir_fd=parent,
    )
    try:
        os.fchmod(handle, _PRIVATE_FILE_MODE)
        offset = 0
        while offset < len(raw):
            step = os.write(handle, raw[offset:])
            if step <= 0:
                raise _fail()
            offset += step
        os.fsync(handle)
    finally:
        os.close(handle)
    os.fsync(parent)


def _read_private(parent: int, name: str, *, bound: int) -> bytes:
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    try:
        metadata = os.fstat(handle)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != _PRIVATE_FILE_MODE
            or metadata.st_nlink != 1
            or not 0 < metadata.st_size <= bound
        ):
            raise _fail()
        raw = os.read(handle, bound + 1)
        if len(raw) != metadata.st_size:
            raise _fail()
        return raw
    finally:
        os.close(handle)


def _require_absent(parent: int, name: str) -> None:
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise _fail()


def _require_protected_volumes(
    evidence: cleanup.ProtectedCleanupEvidence,
    protected_containers: frozenset[str],
    protected_images: frozenset[str],
    *,
    controller_id: str,
    worker_id: str,
    controller_image_id: str,
    worker_image_id: str,
) -> bytes:
    if type(evidence) is not cleanup.ProtectedCleanupEvidence:
        raise _fail()
    before_volumes = {item.name for item in evidence.before.volumes}
    after_volumes = {item.name for item in evidence.after.volumes}
    r108 = cleanup.HISTORICAL_RETIRE_TARGET
    if (
        not _REQUIRED_VOLUMES <= before_volumes
        or not _REQUIRED_VOLUMES <= after_volumes
        or evidence.receipt.retained_attested
        != (
            cleanup.HistoricalRetainedImageProof(
                r108,
                cleanup.HISTORICAL_RETIRE_DIGEST,
                cleanup.HISTORICAL_RETIRE_REVISION,
            ),
        )
        or r108 not in evidence.before.global_image_ids
        or r108 not in evidence.after.global_image_ids
    ):
        raise _fail()
    raw = counted.canonical_cleanup_v2_receipt(
        evidence.receipt,
        before=evidence.before,
        after=evidence.after,
        protected_containers=protected_containers,
        protected_images=protected_images,
    )
    parsed = counted.verify_cleanup_v2_receipt(
        raw, evidence.receipt.attempt_id, require_install_success=True
    )
    pair = parsed.get("protected_pair")
    if type(pair) is not dict:
        raise _fail()
    controller = pair.get("controller")
    worker = pair.get("worker")
    if (
        type(controller) is not dict
        or type(worker) is not dict
        or controller.get("id") != controller_id
        or worker.get("id") != worker_id
        or controller.get("image_id") != controller_image_id
        or worker.get("image_id") != worker_image_id
        or controller.get("running") is not True
        or worker.get("running") is not False
    ):
        raise _fail()
    return raw


def execute_durable_final_cleanup(
    plan: PairCoordinates,
    lease: cleanup.BocaJobLease,
    *,
    controller_id: str,
    worker_id: str,
    controller_image_id: str,
    worker_image_id: str,
    receipt_dir: Path,
    historical_retained: cleanup.HistoricalRetainedImageProof,
) -> DurableFinalCleanupReceipt:
    """One protected Boca cleanup call and a replay-resistant terminal proof.

    The caller's still-active lease is required before intent and after the
    cleanup. Every exception is NO_GO; a partial transaction is not retried.
    This function is NOT wired to a workflow or executable CLI.
    """
    try:
        protected_containers, protected_images = _validated_pair(
            plan,
            controller_id,
            worker_id,
            controller_image_id,
            worker_image_id,
            historical_retained,
        )
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        parent, identity = _private_directory(receipt_dir)
        try:
            _require_absent(parent, RECEIPT_FILENAME)
            _directory_unchanged(parent, receipt_dir, identity)
            intent = (
                json.dumps(
                    {
                        "attempt_id": plan.attempt_id,
                        "controller_id": controller_id,
                        "controller_image_id": controller_image_id,
                        "historical_image_id": cleanup.HISTORICAL_RETIRE_TARGET,
                        "release_run_id": plan.release_run_id,
                        "schema": 1,
                        "source_sha": plan.new_source_sha,
                        "worker_id": worker_id,
                        "worker_image_id": worker_image_id,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
                + "\n"
            ).encode("ascii")
            _write_once(parent, INTENT_FILENAME, intent)
            if _read_private(parent, INTENT_FILENAME, bound=2048) != intent:
                raise _fail()
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            _directory_unchanged(parent, receipt_dir, identity)
            evidence = cleanup.execute_protected_with_inventories(
                "SUCCESS",
                plan.attempt_id,
                preserve_images=protected_images,
                preserve_containers=protected_containers,
                retire_containers=frozenset(),
                lease=lease,
                historical_retained=historical_retained,
            )
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            _directory_unchanged(parent, receipt_dir, identity)
            raw = _require_protected_volumes(
                evidence,
                protected_containers,
                protected_images,
                controller_id=controller_id,
                worker_id=worker_id,
                controller_image_id=controller_image_id,
                worker_image_id=worker_image_id,
            )
            _write_once(parent, RECEIPT_FILENAME, raw)
            if _read_private(parent, RECEIPT_FILENAME, bound=counted.MAX_RECEIPT_BYTES) != raw:
                raise _fail()
            counted.verify_cleanup_v2_receipt(raw, plan.attempt_id)
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            _directory_unchanged(parent, receipt_dir, identity)
            return DurableFinalCleanupReceipt(
                plan.attempt_id,
                "ACCEPT",
                raw,
                hashlib.sha256(raw).hexdigest(),
                hashlib.sha256(intent).hexdigest(),
            )
        finally:
            os.close(parent)
    except Exception:
        raise _fail() from None
