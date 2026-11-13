"""R253 CODE_ONLY durable technical postflight; deliberately never a BETA gate.

This one-way adapter consumes ONLY the official completed SUCCESS cleanup and
R247 production read sources beneath the *original* BocaJobLease. It does not
acquire a lease, run Docker commands, start a browser, change a container,
authorize APPLY, or assert a passkey/monitor session. Its sole host-side write
is an immutable technical proof in Boca's dedicated private directory.

No deploy/CLI/backend entrypoint invokes this module in R253. The protected
caller still has to supply its independently reviewed volume/mount attestor;
an absent attestor is NO_GO, never substituted by a no-op in production.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from typing import Literal

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_postflight_sources_v2 as sources_v2
from boca_socios import host_boca_postflight_volume_attestor_v2 as volume_v2
from boca_socios import host_boca_success_bridge_v2 as bridge
from boca_socios import host_boca_upgrade_cleanup_runtime as cleanup_runtime
from boca_socios import host_boca_upgrade_postflight as postflight
from boca_socios import host_boca_upgrade_postflight_runtime as runtime
from boca_socios import host_boca_upgrade_successor_runtime as successor
from boca_socios import host_cutover_stage as stage
from boca_socios.host_boca_pair_upgrade import PairCoordinates

TECHNICAL_VERSION: Literal["BOCA_PAIR_POSTFLIGHT_TECHNICAL_V2"] = (
    "BOCA_PAIR_POSTFLIGHT_TECHNICAL_V2"
)


class DurableTechnicalPostflightNoGo(ValueError):
    """Constant-category refusal: never reveal a private path/host error."""


def _fail() -> DurableTechnicalPostflightNoGo:
    return DurableTechnicalPostflightNoGo("BOCA_DURABLE_TECHNICAL_POSTFLIGHT_V2 NO_GO")


@dataclass(frozen=True, slots=True)
class DurableTechnicalPostflightReceipt:
    """Same-lease O_EXCL readback, not a terminal owner ACCEPT decision."""

    attempt_id: str
    filename: str
    version: Literal["BOCA_PAIR_POSTFLIGHT_TECHNICAL_V2"]
    raw: bytes
    sha256: str
    inode_dev: int
    inode_ino: int
    completion: bridge.CompletedSuccessEvidence

    @property
    def apply_authorized(self) -> Literal[False]:
        return False

    @property
    def terminal_accept_authorized(self) -> Literal[False]:
        return False

    @property
    def beta_deploy(self) -> Literal["NO_GO"]:
        return "NO_GO"


class OneShotDurableTechnicalPostflightV2:
    """Persist official V2 health-only receipt once under one exact held lease.

    ``final_cleanup`` must already be the successfully completed original
    ``OneShotFinalCleanupBridge``. Its identity-bound accessor refuses a
    foreign plan or lease and returns the canonical on-disk SUCCESS receipt.
    ``volume_attestor`` is the caller's independently reviewed Boca-only
    rootless volume/mount proof, not a new mutable or mockable host backend.
    """

    def __init__(
        self,
        plan: PairCoordinates,
        expected: postflight.PostflightExpected,
        lease: cleanup.BocaJobLease,
        final_cleanup: successor.OneShotFinalCleanupBridge,
        *,
        volume_attestor: volume_v2.ProductionBocaVolumeAttestor | None,
    ) -> None:
        self._plan = plan
        self._expected = expected
        self._lease = lease
        self._final_cleanup = final_cleanup
        self._volume_attestor = volume_attestor
        self._started = False

    def persist(self) -> DurableTechnicalPostflightReceipt:
        """Read twice, verify, O_EXCL+fsync, attest inode/readback and lease.

        The one-way bit is set *before* contacting any external producer. An
        interrupted write or ambiguous exception leaves its attempt residue
        untouched and this instance cannot retry, overwrite or unlink it.
        """
        if self._started:
            raise _fail()
        self._started = True
        root_fd = -1
        try:
            plan = self._plan
            expected = self._expected
            lease = self._lease
            final = self._final_cleanup
            if (
                type(plan) is not PairCoordinates
                or type(expected) is not postflight.PostflightExpected
                or expected.plan is not plan
                or type(lease) is not cleanup.BocaJobLease
                or lease.attempt_id != plan.attempt_id
                or type(final) is not successor.OneShotFinalCleanupBridge
                or type(self._volume_attestor) is not volume_v2.ProductionBocaVolumeAttestor
                or self._volume_attestor.expected is not expected
                or self._volume_attestor.lease is not lease
            ):
                raise _fail()
            postflight._validate_expected(expected)
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            official = final.completed_final_cleanup(plan, lease)
            if (
                type(official) is not cleanup_runtime.DurableFinalCleanupReceipt
                or official.raw != expected.cleanup_receipt
                or official.apply_authorized is not False
                or official.status != "ACCEPT"
                or official.attempt_id != plan.attempt_id
                or official.sha256 != hashlib.sha256(official.raw).hexdigest()
            ):
                raise _fail()
            # Always bind to genuine R247 producers, NOT arbitrary callbacks
            # injected by the workflow to fabricate health, passkey or monitor.
            sources = sources_v2.build_protected_postflight_sources(
                expected,
                lease,
                official,
                receipt_directory=stage.ROOT,
                volume_attestor=self._volume_attestor,
            )
            if type(sources) is not runtime.PostflightReadSources:
                raise _fail()
            reader = runtime.ProductionPostflightSnapshotReader(
                expected,
                sources,
                verify_lease=cleanup.verify_protected_boca_job_lease,
                technical_only=True,
            )
            raw = postflight.capture_technical_postflight(
                expected,
                lease,
                read_snapshot=reader,
                verify_lease=cleanup.verify_protected_boca_job_lease,
            )
            completion = bridge.verify_technical_completion(plan, lease, final, expected, raw)
            if completion.cleanup_receipt is not official or completion.technical_receipt != raw:
                raise _fail()
            checksum = hashlib.sha256(raw).hexdigest()
            filename = f".boca-pair-upgrade-{plan.attempt_id}.technical-postflight-v2"
            if (
                stage.ATTEMPT.fullmatch(plan.attempt_id) is None
                or len(raw) > postflight._BOUND
                or checksum != completion.technical_sha256
            ):
                raise _fail()
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            root_fd = stage._root_fd()
            original_dir = stage._checked_dir(root_fd)
            # stage.ROOT is the fixed Boca-only path; never from workflow input.
            _same_live_directory(root_fd, original_dir)
            stage._create_exclusive(root_fd, filename, raw)
            saved, inode = stage._read_file(root_fd, filename, checksum, limit=postflight._BOUND)
            if saved != raw:
                raise _fail()
            postflight.verify_technical_postflight(saved, expected)
            _same_live_directory(root_fd, original_dir)
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            # The named receipt must still be the exact inode just opened,
            # not a later same-name replacement under the trusted directory.
            named_receipt = os.stat(filename, dir_fd=root_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(named_receipt.st_mode)
                or (named_receipt.st_dev, named_receipt.st_ino, named_receipt.st_mode)
                != (inode.st_dev, inode.st_ino, inode.st_mode)
                or named_receipt.st_nlink != 1
                or named_receipt.st_size != len(saved)
            ):
                raise _fail()
            return DurableTechnicalPostflightReceipt(
                plan.attempt_id,
                filename,
                TECHNICAL_VERSION,
                saved,
                checksum,
                inode.st_dev,
                inode.st_ino,
                completion,
            )
        except Exception:
            raise _fail() from None
        finally:
            if root_fd >= 0:
                os.close(root_fd)


def _same_live_directory(fd: int, before: os.stat_result) -> None:
    """Refuse a replaced named Boca root even if the original FD remains open."""
    opened = stage._checked_dir(fd)
    named = os.stat(stage.ROOT, follow_symlinks=False)
    if (
        not stat.S_ISDIR(named.st_mode)
        or (opened.st_dev, opened.st_ino, opened.st_uid, opened.st_gid, opened.st_mode)
        != (before.st_dev, before.st_ino, before.st_uid, before.st_gid, before.st_mode)
        or (named.st_dev, named.st_ino, named.st_uid, named.st_gid, named.st_mode)
        != (before.st_dev, before.st_ino, before.st_uid, before.st_gid, before.st_mode)
    ):
        raise _fail()
