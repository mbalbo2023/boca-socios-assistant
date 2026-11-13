"""R259 CODE_ONLY: bind reviewed Boca successor effects to ONE held lease.

This has no CLI or workflow dispatch and cannot certify owner passkey/BETA.
The historic R179 backend is never constructed. Before any STAGE/PARK,
the reviewed R255 source must capture genuine old-pair/volume/SITE_URL state.
Only the existing reusable actor may mutate the pair. Post-marker SUCCESS
requires its official cleanup V2 and an R257 durable technical-only terminal.
"""

from __future__ import annotations

import re
from typing import Literal

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_upgrade as upgrade
from boca_socios import host_boca_pair_upgrade_reusable as reusable
from boca_socios import host_boca_postflight_volume_attestor_v2 as volume
from boca_socios import host_boca_prepark_expected_v2 as prepark
from boca_socios import host_boca_repeatable_journal as journal
from boca_socios import host_boca_successor_assembly_v3 as assembly
from boca_socios import host_boca_technical_terminal_bridge_v3 as terminal
from boca_socios import host_boca_upgrade_postflight as postflight
from boca_socios import host_boca_upgrade_successor_runtime as successor

_HEX = re.compile(r"[0-9a-f]{64}\Z")


class GuardedSuccessorNoGo(ValueError):
    """Redacted fixed category, without private host/URL data."""


def _fail() -> GuardedSuccessorNoGo:
    return GuardedSuccessorNoGo("BOCA_GUARDED_SUCCESSOR_V4 NO_GO/INDETERMINATE")


class GuardedTechnicalSuccessorBackend:
    """Delegate only to the exact in-memory R253 backend under original lease.

    The engine reads this concrete class attribute. Construction is inert,
    and merely importing the class is not permission to promote the CLI.
    """

    requires_persistent_receipt = True

    def __init__(
        self,
        graph: assembly.InertSameLeaseAssembly,
        technical_terminal: terminal.OneShotTechnicalTerminalBridge,
        lease: cleanup.BocaJobLease,
    ) -> None:
        try:
            if (
                type(graph) is not assembly.InertSameLeaseAssembly
                or type(technical_terminal) is not terminal.OneShotTechnicalTerminalBridge
                or technical_terminal._actors is not graph
                or type(lease) is not cleanup.BocaJobLease
                or lease.attempt_id != graph.plan.attempt_id
                or type(graph.success.backend) is not successor.PostflightGatedSuccessorBackend
                or type(graph.success.backend).requires_persistent_receipt is not False
                or graph.success.backend.successor_postflight_gate is not None
            ):
                raise _fail()
            graph.__post_init__()
            cleanup.verify_protected_boca_job_lease(lease, graph.plan.attempt_id)
        except Exception:
            raise _fail() from None
        self.graph = graph
        self.terminal = technical_terminal
        self.lease = lease
        self.prepark_seed: prepark.PreParkExpectedSeed | None = None
        self._finalized = False

    @property
    def technical_accept_authorized(self) -> Literal[False]:
        # Technical terminal ≠ fresh owner passkey/monitor/BETA acceptance.
        return False

    def _check(self, plan: upgrade.PairCoordinates, lease: cleanup.BocaJobLease) -> None:
        try:
            if plan is not self.graph.plan or lease is not self.lease:
                raise _fail()
            self.graph.__post_init__()
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            self.graph.journal.attest_active_intent(plan, lease)
        except Exception:
            raise _fail() from None

    def attest(self, plan: upgrade.PairCoordinates, lease: cleanup.BocaJobLease) -> None:
        self._check(plan, lease)
        try:
            self.graph.success.backend.attest(plan, lease)
            seed = prepark.capture_prepark_expected_seed(self.graph.preflight.inputs, lease)
            if (
                type(seed) is not prepark.PreParkExpectedSeed
                or seed.inputs is not self.graph.preflight.inputs
                or seed.lease is not lease
                or seed.plan is not plan
                or type(seed.storage_before) is not postflight.PostflightStorage
                or type(seed.old_pair_witness) is not journal.FreshPairWitness
                or (
                    seed.site_url_state == "ATTESTED"
                    and (
                        type(seed.site_url_fingerprint) is not str
                        or _HEX.fullmatch(seed.site_url_fingerprint) is None
                    )
                )
                or (
                    seed.site_url_state == "NOT_CONFIGURED"
                    and seed.site_url_fingerprint is not None
                )
                or seed.site_url_state not in ("ATTESTED", "NOT_CONFIGURED")
            ):
                raise _fail()
            seed.storage_before.validate()
            seed.old_pair_witness.validate(plan, seed.inputs.custody.resources)
            self._check(plan, lease)
            self.prepark_seed = seed
        except Exception:
            raise _fail() from None

    def stage(self, plan: upgrade.PairCoordinates, lease: cleanup.BocaJobLease) -> None:
        self._check_effect(plan, lease)
        self.graph.success.backend.stage(plan, lease)

    def _check_effect(self, plan: upgrade.PairCoordinates, lease: cleanup.BocaJobLease) -> None:
        self._check(plan, lease)
        if (
            type(self.prepark_seed) is not prepark.PreParkExpectedSeed
            or self.prepark_seed.inputs is not self.graph.preflight.inputs
            or self.prepark_seed.lease is not lease
        ):
            raise _fail()

    def park(self, plan: upgrade.PairCoordinates, lease: cleanup.BocaJobLease) -> None:
        self._check_effect(plan, lease)
        self.graph.success.backend.park(plan, lease)

    def create_worker(self, plan: upgrade.PairCoordinates, lease: cleanup.BocaJobLease) -> str:
        self._check_effect(plan, lease)
        return self.graph.success.backend.create_worker(plan, lease)

    def create_controller(
        self, plan: upgrade.PairCoordinates, worker_id: str, lease: cleanup.BocaJobLease
    ) -> str:
        self._check_effect(plan, lease)
        return self.graph.success.backend.create_controller(plan, worker_id, lease)

    def accept(
        self,
        plan: upgrade.PairCoordinates,
        controller_id: str,
        worker_id: str,
        lease: cleanup.BocaJobLease,
    ) -> None:
        self._check_effect(plan, lease)
        self.graph.success.backend.accept(plan, controller_id, worker_id, lease)

    def replace_binding(
        self,
        plan: upgrade.PairCoordinates,
        controller_id: str,
        worker_id: str,
        lease: cleanup.BocaJobLease,
    ) -> None:
        self._check_effect(plan, lease)
        try:
            self.graph.success.backend.replace_binding(plan, controller_id, worker_id, lease)
            # Exact four-CID candidate is still reversible here. Read-only
            # double attestation of the fresh panel's saved/mirror URL must
            # precede the engine's irreversible commit marker.
            seed = self.prepark_seed
            if type(seed) is not prepark.PreParkExpectedSeed:
                raise _fail()
            prepark.attest_precommit_candidate_site_state(
                plan, controller_id, worker_id, lease, seed
            )
            self._check_effect(plan, lease)
        except Exception:
            raise _fail() from None

    def retire_old(
        self,
        plan: upgrade.PairCoordinates,
        controller_id: str,
        worker_id: str,
        lease: cleanup.BocaJobLease,
    ) -> None:
        self._check_effect(plan, lease)
        self.graph.success.backend.retire_old(plan, controller_id, worker_id, lease)

    def restore_old(self, plan: upgrade.PairCoordinates, lease: cleanup.BocaJobLease) -> bool:
        try:
            self._check_effect(plan, lease)
            return self.graph.success.backend.restore_old(plan, lease) is True
        except Exception:
            return False

    def finalize(
        self,
        plan: upgrade.PairCoordinates,
        *,
        commit_started: bool,
        controller_id: str | None,
        worker_id: str | None,
        lease: cleanup.BocaJobLease,
    ) -> str:
        # An interrupted V2 cleanup or O_EXCL write is never retryable.
        if self._finalized:
            return "INDETERMINATE"
        self._finalized = True
        try:
            self._check(plan, lease)
            # Explicitly use reusable actor's official finalizer; its R252
            # PostflightGated subclass has `gate=None` and cannot be mistaken
            # for a real owner login. A separate stricter technical receipt
            # follows ONLY the one-shot true V2 cleanup.
            status = reusable.ReusablePairUpgradeBackend.finalize(
                self.graph.success.backend,
                plan,
                commit_started=commit_started,
                controller_id=controller_id,
                worker_id=worker_id,
                lease=lease,
            )
            if status != "ACCEPT":
                return status if status in ("NO_GO", "INDETERMINATE") else "INDETERMINATE"
            if (
                commit_started is not True
                or type(controller_id) is not str
                or type(worker_id) is not str
                or type(self.prepark_seed) is not prepark.PreParkExpectedSeed
            ):
                return "INDETERMINATE"
            expected = self.prepark_seed.expected_after_cleanup(
                self.graph.success.final_cleanup, lease
            )
            if (
                type(expected) is not postflight.PostflightExpected
                or expected.plan is not plan
                or (expected.controller_id, expected.worker_id) != (controller_id, worker_id)
            ):
                raise _fail()
            attestor = volume.ProductionBocaVolumeAttestor(expected, lease)
            self.terminal.attest_technical_success(expected, attestor, lease)
            self._check(plan, lease)
            return "ACCEPT"
        except Exception:
            return "INDETERMINATE"
