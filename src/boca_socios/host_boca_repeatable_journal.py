"""Durable Boca successor evidence/intent/commit/terminal under one lease.

CODE_ONLY, never an authorization. O_EXCL residue consumes an attempt.
Trust boundaries and original full rationale: ADR0276 and ADR0259.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_pair_upgrade_backend as historical
from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios import host_cutover_stage as stage

_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_VERSION = "boca-successor-pair-intent-evidence-v1"
_PREFIX = ".boca-pair-upgrade-"
_MAX_EVIDENCE = 4096


class SuccessorJournalNoGo(ValueError):
    """Fixed refusal; no untrusted host exception, filename or member data."""


def _fail() -> SuccessorJournalNoGo:
    return SuccessorJournalNoGo("Boca successor evidence or same-lease witness unverified")


@dataclass(frozen=True, slots=True)
class FreshPairWitness:
    """Host-read CID, binding, retained graph and inode; never runner-form data."""

    observation_run_id: str
    old_attempt_id: str
    old_source_sha: str
    controller_id: str
    worker_id: str
    controller_image_id: str
    worker_image_id: str
    retained: adapters.ResourcePins
    control_inode_sha256: str

    def validate(self, plan: transaction.PairCoordinates, pins: adapters.ResourcePins) -> None:
        if (
            any(
                type(value) is not str or pattern.fullmatch(value) is None
                for pattern, values in (
                    (_RUN, (self.observation_run_id, self.old_attempt_id)),
                    (_SHA, (self.old_source_sha,)),
                    (_HEX, (self.controller_id, self.worker_id, self.control_inode_sha256)),
                    (_IMAGE, (self.controller_image_id, self.worker_image_id)),
                )
                for value in values
            )
            or (
                self.observation_run_id,
                self.old_attempt_id,
                self.old_source_sha,
                self.controller_id,
                self.worker_id,
                self.controller_image_id,
                self.worker_image_id,
            )
            != (
                plan.observation_run_id,
                plan.old_attempt_id,
                plan.old_source_sha,
                plan.old_controller_id,
                plan.old_worker_id,
                plan.old_controller_image_id,
                plan.old_worker_image_id,
            )
            or type(self.retained) is not adapters.ResourcePins
            or self.retained != pins
        ):
            raise _fail()
        self.retained.validate()


SameLeaseCapture = Callable[[transaction.PairCoordinates, cleanup.BocaJobLease], FreshPairWitness]


class SuccessorPairJournal(historical.PairUpgradeJournal):
    """Immutable witness/intent journal; `capture` is a real host read-side gate."""

    def __init__(
        self,
        release: adapters.ReleaseEvidence,
        retained: adapters.ResourcePins,
        capture: SameLeaseCapture,
    ) -> None:
        super().__init__()
        self.release = release
        self.retained = retained
        self.capture = capture

    def _verified_witness(
        self, plan: transaction.PairCoordinates, lease: cleanup.BocaJobLease
    ) -> FreshPairWitness:
        try:
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            plan.validate()
            if (
                type(self.release) is not adapters.ReleaseEvidence
                or type(self.retained) is not adapters.ResourcePins
                or not callable(self.capture)
            ):
                raise _fail()
            self.retained.validate()
            if (
                self.release.source_sha,
                self.release.release_run_id,
                self.release.controller_ref,
                self.release.worker_ref,
            ) != (
                plan.new_source_sha,
                plan.release_run_id,
                plan.controller_ref,
                plan.worker_ref,
            ) or any(
                type(value) is not str or _HEX.fullmatch(value) is None
                for value in (
                    self.release.controller_manifest_sha256,
                    self.release.paired_manifest_sha256,
                )
            ):
                raise _fail()
            first, second = self.capture(plan, lease), self.capture(plan, lease)
            if type(first) is not FreshPairWitness or type(second) is not FreshPairWitness:
                raise _fail()
            first.validate(plan, self.retained)
            second.validate(plan, self.retained)
            if first != second:
                raise _fail()
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            return first
        except Exception:
            raise _fail() from None

    def attest_active_intent(
        self, plan: transaction.PairCoordinates, lease: cleanup.BocaJobLease
    ) -> None:
        """Reopen same-lease intent and witness evidence before terminal effects."""
        try:
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            if (
                type(plan) is not transaction.PairCoordinates
                or self._lease is not lease
                or type(self._intent) is not bytes
                or not 0 < len(self._intent) <= 1024
            ):
                raise _fail()
            plan.validate()
            intent = json.loads(self._intent)
            if (
                type(intent) is not dict
                or intent.keys()
                != {
                    "attempt",
                    "evidence_sha256",
                    "old_controller",
                    "old_worker",
                    "old_source",
                    "new_source",
                    "release",
                }
                or intent["attempt"] != plan.attempt_id
                or intent["old_controller"] != plan.old_controller_id
                or intent["old_worker"] != plan.old_worker_id
                or intent["old_source"] != plan.old_source_sha
                or intent["new_source"] != plan.new_source_sha
                or intent["release"] != plan.release_run_id
                or type(intent["evidence_sha256"]) is not str
                or _HEX.fullmatch(intent["evidence_sha256"]) is None
            ):
                raise _fail()
            root = stage._root_fd()
            try:
                prefix = f"{_PREFIX}{plan.attempt_id}."
                actual, _ = stage._read_file(
                    root,
                    prefix + "intent",
                    hashlib.sha256(self._intent).hexdigest(),
                    limit=1024,
                )
                evidence, _ = stage._read_file(
                    root,
                    prefix + "evidence",
                    intent["evidence_sha256"],
                    limit=_MAX_EVIDENCE,
                )
                if actual != self._intent or not evidence:
                    raise _fail()
            finally:
                os.close(root)
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        except Exception:
            raise _fail() from None

    def intent(self, plan: transaction.PairCoordinates, lease: cleanup.BocaJobLease) -> None:
        """Create evidence *before* original intent; neither file can replay."""
        witness = self._verified_witness(plan, lease)
        payload = json.dumps(
            {
                "version": _VERSION,
                "plan": asdict(plan),
                "release": asdict(self.release),
                "witness": asdict(witness),
            },
            sort_keys=True,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        if not 0 < len(payload) <= _MAX_EVIDENCE:
            raise _fail()
        digest = hashlib.sha256(payload).hexdigest()
        statement = json.dumps(
            {
                "attempt": plan.attempt_id,
                "evidence_sha256": digest,
                "old_controller": plan.old_controller_id,
                "old_worker": plan.old_worker_id,
                "old_source": plan.old_source_sha,
                "new_source": plan.new_source_sha,
                "release": plan.release_run_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        if len(statement) > 1024:
            raise _fail()
        # O_EXCL + readback: failures preserve attempt-specific residue.
        fd = stage._root_fd()
        try:
            name = f"{_PREFIX}{plan.attempt_id}.evidence"
            stage._create_exclusive(fd, name, payload)
            readback, _ = stage._read_file(fd, name, digest, limit=_MAX_EVIDENCE)
            if readback != payload:
                raise _fail()
        finally:
            os.close(fd)
        self._lease = lease
        self._intent = statement
        self._write(plan, "intent", statement)

    def terminal(
        self,
        plan: transaction.PairCoordinates,
        receipt: transaction.PairUpgradeReceipt,
        lease: cleanup.BocaJobLease,
    ) -> None:
        """Persist once, then prove the exact terminal inode and bytes before returning."""
        from boca_socios.host_boca_pair_upgrade_cli import encode_upgrade

        try:
            if self._lease is not lease or self._intent is None:
                raise _fail()
            raw = encode_upgrade(receipt)
            self._write(plan, "terminal", raw)
            root = stage._root_fd()
            try:
                readback, _ = stage._read_file(
                    root,
                    f"{_PREFIX}{plan.attempt_id}.terminal",
                    hashlib.sha256(raw).hexdigest(),
                    limit=1024,
                )
                if readback != raw:
                    raise _fail()
            finally:
                os.close(root)
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        except Exception:
            raise _fail() from None
