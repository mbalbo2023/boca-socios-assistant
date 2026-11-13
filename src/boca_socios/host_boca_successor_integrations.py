"""Bound, fail-closed Boca successor inputs for one future protected host lease.

The ONLY trusted provenance is the reviewed GitHub runner: it must first
authenticate the live current-pair V2 envelope, previous dual release, R188
historical custody and the target dual release. This host-side validator
rechecks canonical *integrity and coordinates*, never invents a GitHub
signature or elevates an Actions Step Summary into a physical witness.

The R186 migration remains excluded. A syntactically valid bundle is not
permission to mutate Docker. R248 now binds the changing 2/3/4-CID graph
while preserving historical R188 resource creators. The effectful successor
stays NO_GO until FAILURE cleanup, durable postflight, bundle space and
owner/passkey acceptance are connected and independently reviewed.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cleanup_v2 as counted
from boca_socios import host_boca_current_pair_v2 as current
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_pair_upgrade_reusable as reusable
from boca_socios import host_boca_repeatable_journal as journal
from boca_socios import host_boca_successor_physical_v2 as physical
from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios import host_boca_upgrade_failure_cleanup_v2 as failure_cleanup
from boca_socios import host_boca_upgrade_observation_bridge as observation
from boca_socios import host_boca_upgrade_release_bridge as release_bridge
from boca_socios import host_boca_upgrade_same_lease as same_lease
from boca_socios import host_boca_upgrade_successor_runtime as successor_runtime
from boca_socios import host_cutover_stage as stage
from boca_socios.host_boca_pair_stage import PairSources
from boca_socios.host_boca_pair_upgrade_plan import CandidateRelease

if TYPE_CHECKING:
    from boca_socios.host_boca_pair_upgrade_cli import BoundSuccessorPreflight

_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_SHA = re.compile(r"[a-f0-9]{40}\Z")


class SuccessorIntegrationNoGo(ValueError):
    """Redacted, terminal refusal before any host transaction effect."""


def _fail() -> SuccessorIntegrationNoGo:
    return SuccessorIntegrationNoGo("Boca successor authentic same-lease integration NO_GO")


@dataclass(frozen=True, slots=True)
class BoundSuccessorInputs:
    """Coordinates bound to runner-provided proofs, not Docker authority."""

    plan: transaction.PairCoordinates
    release: adapters.ReleaseEvidence
    custody: adapters.CustodyEvidence
    retained: reusable.RetainedResourcePins
    original_pair_receipt: bytes
    current_pair_proof: bytes

    @property
    def apply_authorized(self) -> Literal[False]:
        return False


@dataclass(frozen=True, slots=True)
class CurrentBaseOnlyStageCustody:
    """Read actual unchanged root Compose twice in the journal's SAME lease.

    This intentionally supports only the current no-base-Compose-change
    upgrade. A future changed-base upgrade requires a separately authenticated
    historical source digest, not the old R186 singleton constant.
    No Docker effect, lease acquisition or journal write during assembly.
    """

    preflight: BoundSuccessorPreflight
    journal: journal.SuccessorPairJournal

    def __post_init__(self) -> None:
        from boca_socios.host_boca_pair_upgrade_cli import BoundSuccessorPreflight

        if (
            type(self.preflight) is not BoundSuccessorPreflight
            or self.preflight.apply_authorized is not False
            or type(self.journal) is not journal.SuccessorPairJournal
        ):
            raise _fail()
        self.preflight.inputs.plan.validate()
        self.sources().validate()

    def sources(self) -> PairSources:
        """Freeze target bytes; original digest becomes a strict equality gate.

        Only `intent` can attest that the physical old root actually has this
        SHA. Mere construction does NOT prove the old Compose identity.
        """
        try:
            proof = self.preflight
            sources = PairSources(
                proof.base,
                proof.overlay,
                proof.seccomp,
                original_compose_sha=proof.base_sha,
                base_sha=proof.base_sha,
                overlay_sha=proof.overlay_sha,
                seccomp_sha=proof.seccomp_sha,
            )
            sources.validate()
            return sources
        except Exception:
            raise _fail() from None

    def intent(self, plan: transaction.PairCoordinates, lease: cleanup.BocaJobLease) -> None:
        """Attest exact physical Compose before O_EXCL journal intent.

        The existing stage.prepare rechecks the same unchanged root inode
        both before and after its own attempt-scoped stage write.
        """
        try:
            if type(plan) is not transaction.PairCoordinates or plan != self.preflight.inputs.plan:
                raise _fail()
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            sources = self.sources()
            root = stage._root_fd()
            try:
                first, first_inode = stage._read_file(
                    root,
                    "compose.beta.yaml",
                    sources.original_compose_sha,
                    limit=stage.MAX_FILE,
                    historical_compose=True,
                )
                second, second_inode = stage._read_file(
                    root,
                    "compose.beta.yaml",
                    sources.original_compose_sha,
                    limit=stage.MAX_FILE,
                    historical_compose=True,
                )
                if (
                    first != sources.base
                    or second != sources.base
                    or not stage._same_inode(first_inode, second_inode)
                ):
                    raise _fail()
            finally:
                os.close(root)
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            self.journal.intent(plan, lease)
        except Exception:
            raise _fail() from None


class OneShotFailureTerminalSink:
    """Compose official FAILURE V2 and the original journal terminal once.

    This is an inert, unwired future terminal callback. It does not acquire a
    lease, dispatch Docker, retry an effect or grant an installed-pair GO.
    A failed precommit attempt may clean exact Boca resources only through
    the existing durable V2 executor. After a possible commit, never restore
    or perform FAILURE cleanup; retain the original uncertainty.
    """

    def __init__(
        self,
        plan: transaction.PairCoordinates,
        durable: journal.SuccessorPairJournal,
        *,
        retained_io: adapters.RetainedResourceIO | None = None,
    ) -> None:
        if (
            type(plan) is not transaction.PairCoordinates
            or type(durable) is not journal.SuccessorPairJournal
            or (
                retained_io is not None
                and type(retained_io) is not same_lease.ProductionRetainedResourceIO
            )
        ):
            raise _fail()
        plan.validate()
        self.plan = plan
        self.journal = durable
        self.retained_io = retained_io
        self._started = False

    def __call__(
        self,
        plan: transaction.PairCoordinates,
        receipt: transaction.PairUpgradeReceipt,
        lease: cleanup.BocaJobLease,
    ) -> None:
        if self._started:
            raise _fail()
        # One-way boundary before a callback may write O_EXCL intent or delete
        # an exact Boca resource. Even an uncertain exception cannot retry.
        self._started = True
        try:
            if (
                type(plan) is not transaction.PairCoordinates
                or plan != self.plan
                or type(receipt) is not transaction.PairUpgradeReceipt
                or receipt.attempt_id != plan.attempt_id
                or type(receipt.commit_started) is not bool
                or type(receipt.old_restored) is not bool
                or receipt.state not in ("ACCEPTED", "RECOVERED", "NO_GO")
                or receipt.cleanup not in ("ACCEPT", "NO_GO", "INDETERMINATE")
            ):
                raise _fail()
            plan.validate()
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            # No physical cleanup may precede this exact journal's durable
            # same-lease intent and witness evidence. A stray journal object
            # must not be able to consume a new terminal attempt.
            self.journal.attest_active_intent(plan, lease)
            if receipt.commit_started:
                if (
                    receipt.old_restored
                    # The current bridge has no completed SUCCESS V2 receipt
                    # nor independent owner/monitor postflight source. Never
                    # persist ACCEPTED from only the engine's textual result.
                    or receipt.state == "ACCEPTED"
                    or receipt.state == "RECOVERED"
                ):
                    raise _fail()
                # Post-marker uncertainty cannot authorize any rollback,
                # FAILURE cleanup or a second cleanup after SUCCESS intent.
                self.journal.terminal(plan, receipt, lease)
                return
            if receipt.state == "RECOVERED":
                if not receipt.old_restored or receipt.cleanup != "ACCEPT":
                    raise _fail()
            elif receipt.state != "NO_GO" or receipt.cleanup == "ACCEPT":
                raise _fail()
            if receipt.old_restored and self.retained_io is None:
                raise _fail()
            proof = failure_cleanup.execute_durable_failure_cleanup(
                plan,
                lease,
                restored=receipt.old_restored,
                receipt_dir=stage.ROOT,
                historical_retained=failure_cleanup._EXPECTED_R108,
                retained_io=self.retained_io if receipt.old_restored else None,
            )
            if (
                type(proof) is not failure_cleanup.DurableFailureCleanupReceipt
                or proof.attempt_id != plan.attempt_id
                or proof.state != "NO_GO"
                or proof.apply_authorized is not False
                or proof.cleanup_status not in ("ACCEPT", "NO_GO", "INDETERMINATE")
                or type(proof.raw) is not bytes
                or type(proof.sha256) is not str
                or type(proof.intent_sha256) is not str
                or hashlib.sha256(proof.raw).hexdigest() != proof.sha256
                or not re.fullmatch(r"[0-9a-f]{64}", proof.sha256)
                or not re.fullmatch(r"[0-9a-f]{64}", proof.intent_sha256)
            ):
                raise _fail()
            body = counted.verify_cleanup_v2_receipt(
                proof.raw, plan.attempt_id, require_install_success=False
            )
            if body["outcome"] != "FAILURE" or body["status"] != proof.cleanup_status:
                raise _fail()
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            # FAILURE cleanup ACCEPT does not install the new release. Keep
            # the engine's original NO_GO or legitimate RECOVERED receipt.
            self.journal.terminal(plan, receipt, lease)
        except Exception:
            raise _fail() from None


def verify_runner_bound_host_inputs(
    *,
    attempt_id: str,
    source_sha: str,
    controller_ref: str,
    worker_ref: str,
    release_run_id: str,
    observation_run_id: str,
    release_proof: bytes,
    controller_manifest: bytes,
    paired_manifest: bytes,
    observation_proof: bytes,
    observation_receipt: bytes,
    retained_receipt: bytes,
    current_pair_v2: bytes,
) -> BoundSuccessorInputs:
    """Validate physical coordinates after runner-authenticated GH transport.

    No arguments here may come from an unverified host/form payload. A V2
    checksum is only internal integrity; authenticating its GitHub origin
    remains the protected runner's responsibility. Historical R188 source and
    attempt deliberately differ from the current installed pair on B -> C.
    """
    try:
        if (
            any(
                type(value) is not str or _RUN.fullmatch(value) is None
                for value in (attempt_id, release_run_id, observation_run_id)
            )
            or type(source_sha) is not str
            or _SHA.fullmatch(source_sha) is None
            or not all(
                type(data) is bytes
                for data in (
                    release_proof,
                    controller_manifest,
                    paired_manifest,
                    observation_proof,
                    observation_receipt,
                    retained_receipt,
                    current_pair_v2,
                )
            )
        ):
            raise _fail()
        candidate = CandidateRelease(source_sha, release_run_id, controller_ref, worker_ref)
        release_bridge.verify_bundled_release(
            release_proof, controller_manifest, paired_manifest, candidate
        )
        pair_data = observation.verify_bundled_observation(
            observation_proof,
            observation_receipt,
            source_sha,
            observation_run_id,
            attempt_id,
            release_run_id,
        )
        v2 = current.verify_current_pair_v2(current_pair_v2)
        history = v2["historical_resource_custody"]
        if type(history) is not dict:
            raise _fail()
        historical_run = history["original_observation_run"]
        if type(historical_run) is not str or _RUN.fullmatch(historical_run) is None:
            raise _fail()
        custody = adapters.parse_custody_integrity(
            retained_receipt, observation_run_id=historical_run
        )
        if (
            current._history(custody) != history
            or hashlib.sha256(retained_receipt).hexdigest() != history["historical_receipt_sha256"]
        ):
            raise _fail()
        for key, expected in (
            ("target_main_sha", source_sha),
            ("target_release_run", release_run_id),
            ("apply_attempt", attempt_id),
            ("observation_run", observation_run_id),
            ("previous_pair_source_sha", pair_data["old_source_sha"]),
            ("previous_pair_attempt", pair_data["old_attempt_id"]),
            ("previous_controller_id", pair_data["controller_id"]),
            ("previous_worker_id", pair_data["worker_id"]),
            ("previous_controller_image_id", pair_data["controller_image_id"]),
            ("previous_worker_image_id", pair_data["worker_image_id"]),
            ("previous_controller_ref", pair_data["controller_ref"]),
            ("previous_worker_ref", pair_data["worker_ref"]),
            ("observed_pair_sha256", hashlib.sha256(observation_receipt).hexdigest()),
            ("observation_proof_sha256", hashlib.sha256(observation_proof).hexdigest()),
        ):
            if v2[key] != expected:
                raise _fail()
        plan = transaction.PairCoordinates(
            attempt_id=attempt_id,
            observation_run_id=observation_run_id,
            old_attempt_id=cast(str, pair_data["old_attempt_id"]),
            old_source_sha=cast(str, pair_data["old_source_sha"]),
            old_controller_id=cast(str, pair_data["controller_id"]),
            old_worker_id=cast(str, pair_data["worker_id"]),
            old_controller_image_id=cast(str, pair_data["controller_image_id"]),
            old_worker_image_id=cast(str, pair_data["worker_image_id"]),
            new_source_sha=source_sha,
            release_run_id=release_run_id,
            controller_ref=controller_ref,
            worker_ref=worker_ref,
        )
        plan.validate()
        pins = custody.resources
        pins.validate()
        retained = reusable.RetainedResourcePins(
            ipc_creator_attempt=pins.ipc_creator_attempt,
            ipc_inode_sha256=pins.ipc_inode_sha256,
            site_creator_attempt=pins.site_creator_attempt,
            site_inode_sha256=pins.site_inode_sha256,
            egress_creator_attempt=pins.egress_creator_attempt,
            egress_id=pins.egress_id,
        )
        retained.validate()
        release = adapters.ReleaseEvidence(
            source_sha=source_sha,
            release_run_id=release_run_id,
            controller_ref=controller_ref,
            worker_ref=worker_ref,
            controller_manifest_sha256=hashlib.sha256(controller_manifest).hexdigest(),
            paired_manifest_sha256=hashlib.sha256(paired_manifest).hexdigest(),
        )
        return BoundSuccessorInputs(
            plan, release, custody, retained, observation_receipt, current_pair_v2
        )
    except Exception:
        raise _fail() from None


@dataclass(frozen=True, slots=True)
class PreparedSuccessorTransaction:
    """Reuse the ONLY one-lease engine and its journal; still ineligible.

    Explicitly retain two independent interlocks: the backend class guard
    and this entrypoint's guard. A future reviewed activation must change
    both after completing all failure/postflight source dependencies.
    """

    plan: transaction.PairCoordinates
    backend: successor_runtime.PostflightGatedSuccessorBackend
    journal: journal.SuccessorPairJournal

    def execute(self) -> transaction.PairUpgradeReceipt:
        if type(self.backend).requires_persistent_receipt is not False:
            raise _fail()
        return transaction.run_pair_upgrade(
            self.plan,
            backend=self.backend,
            terminal_preflight=self.journal.intent,
            commit_marker=self.journal.commit,
            terminal_sink=self.journal.terminal,
        )


def prepare_effectful_successor(
    inputs: BoundSuccessorInputs,
    *,
    sources: PairSources | None = None,
) -> PreparedSuccessorTransaction:
    """Assemble exact Boca actors and read-side dynamic graph, still NO_GO.

    The existing journal implements exclusive durable intent/evidence,
    commit and terminal receipts under `run_pair_upgrade`'s sole lease. The
    current B->C witness uses original R188 *resource* pins separately from
    the authenticated current pair, and rechecks all 2/3/4 exact CIDs.
    FAILURE cleanup and the full physical owner/postflight remain unwired;
    the actor stays type-interlocked. No Docker read/write during assembly.
    """
    try:
        if type(inputs) is not BoundSuccessorInputs or type(sources) is not PairSources:
            raise _fail()
        sources.validate()
        capture = physical.SuccessorCurrentPairCapture(
            current_pair_observation=inputs.original_pair_receipt,
            historical_custody=inputs.custody,
        )
        durable = journal.SuccessorPairJournal(
            release=inputs.release,
            retained=inputs.custody.resources,
            capture=capture,
        )
        integrations = physical.PhysicalSuccessorIntegrations(
            inputs.plan,
            inputs.release,
            inputs.custody,
            inputs.original_pair_receipt,
        )
        backend = successor_runtime.PostflightGatedSuccessorBackend(
            sources,
            inputs.retained,
            integrations=integrations,
            gate=None,
        )
        integrations.bind_backend(backend)
        if type(backend).requires_persistent_receipt is not False:
            raise _fail()
        return PreparedSuccessorTransaction(inputs.plan, backend, durable)
    except Exception:
        raise _fail() from None
