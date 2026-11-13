"""R252 CODE_ONLY: compose one exact physical SUCCESS cleanup bridge.

All assembly is in-memory. This module does not acquire the protected Boca
lease, dispatch Docker, install containers, authorize the CLI, or accept a
technical-only 8443 health report as an owner's passkey login. The SUCCESS
executor exists exclusively inside the previously reviewed one-shot final
cleanup bridge and requires a fresh physical pair under the engine's lease.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cleanup_v2 as cleanup_v2
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_repeatable_journal as journal
from boca_socios import host_boca_retained_resources as retained
from boca_socios import host_boca_successor_physical_v2 as physical
from boca_socios import host_boca_upgrade_cleanup_runtime as cleanup_runtime
from boca_socios import host_boca_upgrade_postflight as postflight
from boca_socios import host_boca_upgrade_successor_runtime as successor
from boca_socios import host_on_demand_service as service
from boca_socios.host_boca_pair_stage import PairSources

if TYPE_CHECKING:
    from boca_socios.host_boca_pair_upgrade_cli import BoundSuccessorPreflight


class SuccessCleanupBridgeNoGo(ValueError):
    """Fixed-category refusal, never an original host error string."""


def _fail() -> SuccessCleanupBridgeNoGo:
    return SuccessCleanupBridgeNoGo("Boca successor SUCCESS cleanup assembly NO_GO")


@dataclass(frozen=True, slots=True)
class BoundSuccessCleanup:
    """Proof of object identity wiring only; not a deployment permission."""

    plan: transaction.PairCoordinates
    journal: journal.SuccessorPairJournal
    integrations: physical.PhysicalSuccessorIntegrations
    final_cleanup: successor.OneShotFinalCleanupBridge
    backend: successor.PostflightGatedSuccessorBackend

    @property
    def apply_authorized(self) -> Literal[False]:
        return False

    def verified_technical_completion(
        self,
        plan: transaction.PairCoordinates,
        lease: cleanup.BocaJobLease,
        expected: postflight.PostflightExpected,
        technical_raw: bytes,
    ) -> CompletedSuccessEvidence:
        """Consume the SAME official final cleanup, never promote BETA."""
        if plan is not self.plan or self.final_cleanup._delegate is not self.integrations:
            raise _fail()
        return verify_technical_completion(plan, lease, self.final_cleanup, expected, technical_raw)


@dataclass(frozen=True, slots=True)
class CompletedSuccessEvidence:
    """Cleanup SUCCESS + technical health, *not* physical owner acceptance.

    Technical bytes may be supplied by a protected capture but their durable
    O_EXCL/fsync/readback is a separate mandatory step. This object therefore
    cannot satisfy a terminal ACCEPTED gate or passkey/monitor acceptance.
    """

    plan: transaction.PairCoordinates
    cleanup_receipt: cleanup_runtime.DurableFinalCleanupReceipt
    technical_sha256: str
    technical_receipt: bytes

    @property
    def apply_authorized(self) -> Literal[False]:
        return False

    @property
    def terminal_accept_authorized(self) -> Literal[False]:
        return False

    @property
    def beta_deploy(self) -> Literal["NO_GO"]:
        return "NO_GO"


def verify_technical_completion(
    plan: transaction.PairCoordinates,
    lease: cleanup.BocaJobLease,
    final_cleanup: successor.OneShotFinalCleanupBridge,
    expected: postflight.PostflightExpected,
    technical_raw: bytes,
) -> CompletedSuccessEvidence:
    """Bind official one-shot V2 cleanup to separate versioned technical proof.

    The live one-shot finalizer enforces *identity* of plan and lease before
    returning its internal successful executor receipt. This verifier checks
    the canonical V2 and schema-2 postflight again. It never mutates anything
    or treats a technical snapshot as a Chrome passkey or owner monitor proof.
    """
    try:
        if (
            type(plan) is not transaction.PairCoordinates
            or type(lease) is not cleanup.BocaJobLease
            or type(final_cleanup) is not successor.OneShotFinalCleanupBridge
            or type(expected) is not postflight.PostflightExpected
            or expected.plan is not plan
            or type(technical_raw) is not bytes
            or not 0 < len(technical_raw) <= successor._MAX_RECEIPT
        ):
            raise _fail()
        plan.validate()
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        proof = final_cleanup.completed_final_cleanup(plan, lease)
        if (
            type(proof) is not cleanup_runtime.DurableFinalCleanupReceipt
            or proof.attempt_id != plan.attempt_id
            or proof.status != "ACCEPT"
            or proof.apply_authorized is not False
            or type(proof.raw) is not bytes
            or type(proof.sha256) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", proof.sha256)
            or hashlib.sha256(proof.raw).hexdigest() != proof.sha256
            or type(proof.intent_sha256) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", proof.intent_sha256)
            or expected.cleanup_receipt != proof.raw
        ):
            raise _fail()
        body = cleanup_v2.verify_cleanup_v2_receipt(proof.raw, plan.attempt_id)
        if body["outcome"] != "SUCCESS" or body["status"] != "ACCEPT":
            raise _fail()
        postflight.verify_technical_postflight(technical_raw, expected)
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        return CompletedSuccessEvidence(
            plan, proof, hashlib.sha256(technical_raw).hexdigest(), technical_raw
        )
    except Exception:
        raise _fail() from None


def prepare_success_cleanup(
    preflight: BoundSuccessorPreflight,
    durable: journal.SuccessorPairJournal,
) -> BoundSuccessCleanup:
    """Bind release+current pair+R188 pins to the original SUCCESS executor.

    This is the ONLY accepted production reader configuration for this future
    candidate. The journal is externally supplied so SUCCESS, FAILURE, stage
    and commit marker can eventually share one exact instance and lease.
    ``gate=None`` and the backend class interlock remain deliberately NO_GO.
    """
    from boca_socios.host_boca_pair_upgrade_cli import BoundSuccessorPreflight
    from boca_socios.host_boca_successor_integrations import BoundSuccessorInputs

    try:
        if (
            type(preflight) is not BoundSuccessorPreflight
            or type(preflight.inputs) is not BoundSuccessorInputs
            or type(durable) is not journal.SuccessorPairJournal
        ):
            raise _fail()
        inputs = preflight.inputs
        inputs.plan.validate()
        if (
            inputs.apply_authorized is not False
            or durable.release != inputs.release
            or durable.retained != inputs.custody.resources
            or type(durable.capture) is not physical.SuccessorCurrentPairCapture
        ):
            raise _fail()
        capture = durable.capture
        if (
            capture.historical_custody != inputs.custody
            or capture.current_pair_observation != inputs.original_pair_receipt
            or capture.retained_io is not None
            or capture.pair_reader is not pair.observe
            or capture.binding_reader is not service.read_installed_binding
            or capture.control_identity_reader is not retained._identity
        ):
            raise _fail()
        values = (preflight.base, preflight.overlay, preflight.seccomp)
        digests = (preflight.base_sha, preflight.overlay_sha, preflight.seccomp_sha)
        if any(
            hashlib.sha256(data).hexdigest() != digest
            for data, digest in zip(values, digests, strict=True)
        ):
            raise _fail()
        sources = PairSources(
            preflight.base,
            preflight.overlay,
            preflight.seccomp,
            original_compose_sha=preflight.base_sha,
            base_sha=preflight.base_sha,
            overlay_sha=preflight.overlay_sha,
            seccomp_sha=preflight.seccomp_sha,
        )
        sources.validate()
        integrations = physical.PhysicalSuccessorIntegrations(
            inputs.plan,
            inputs.release,
            inputs.custody,
            inputs.original_pair_receipt,
        )
        final = successor.OneShotFinalCleanupBridge(
            integrations,
            read_cleanup_coordinates=successor.ProductionFinalCleanupCoordinatesReader(),
            verify_lease=cleanup.verify_protected_boca_job_lease,
        )
        backend = successor.PostflightGatedSuccessorBackend(
            sources,
            inputs.retained,
            integrations=final,
            gate=None,
        )
        integrations.bind_backend(backend)
        if type(backend).requires_persistent_receipt is not False:
            raise _fail()
        return BoundSuccessCleanup(inputs.plan, durable, integrations, final, backend)
    except Exception:
        raise _fail() from None
