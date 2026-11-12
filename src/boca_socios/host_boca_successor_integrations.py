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
import re
from dataclasses import dataclass
from typing import Literal, cast

from boca_socios import host_boca_current_pair_v2 as current
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_pair_upgrade_reusable as reusable
from boca_socios import host_boca_repeatable_journal as journal
from boca_socios import host_boca_successor_physical_v2 as physical
from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios import host_boca_upgrade_observation_bridge as observation
from boca_socios import host_boca_upgrade_release_bridge as release_bridge
from boca_socios import host_boca_upgrade_successor_runtime as successor_runtime
from boca_socios.host_boca_pair_stage import PairSources
from boca_socios.host_boca_pair_upgrade_plan import CandidateRelease

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
