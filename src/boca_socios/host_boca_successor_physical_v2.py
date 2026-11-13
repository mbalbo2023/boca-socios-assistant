"""R248: physical Boca successor witnesses for a changing 2/3/4-CID pair.

R188 records original IPC/SITE/egress *creators*, not forever-current pair
source, attempt or CIDs. The separately authenticated V2 current-pair receipt
provides the old pair for this upgrade. This module makes no host effects at
construction, provides no CLI, and is deliberately not an APPLY authority.
All live readers run only when a reviewed protected caller holds one Boca lease.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from boca_socios import host_boca_binding_observe as binding
from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_pair_upgrade_reusable as reusable
from boca_socios import host_boca_repeatable_journal as journal
from boca_socios import host_boca_retained_resources as retained
from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios import host_boca_upgrade_same_lease as prior
from boca_socios import host_boca_upgrade_successor_runtime as successor
from boca_socios import host_on_demand_service as service
from boca_socios.host_boca_pair_stage import PairSources
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

_CID = re.compile(r"[a-f0-9]{64}\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")
_SHA = re.compile(r"[a-f0-9]{40}\Z")
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_PREPARED = frozenset({"NEW", "ATTESTED", "STAGED"})
_PARKED = frozenset({"PARKED"})
_THREE = frozenset({"WORKER"})
_FOUR = frozenset({"CONTROLLER", "ACCEPTED_COLD", "BOUND"})
_RETIRED = frozenset({"RETIRED"})
_RESTORED = frozenset({"RESTORED"})


class SuccessorPhysicalNoGo(ValueError):
    """A fixed redacted rejection with no raw host data or credentials."""


def _fail() -> SuccessorPhysicalNoGo:
    return SuccessorPhysicalNoGo("Boca successor physical evidence NO_GO")


def _historical_seed(custody: adapters.CustodyEvidence) -> None:
    """Validate actual R188 *history*, never relabel it as installed B/C."""
    if (
        type(custody) is not adapters.CustodyEvidence
        or type(custody.installed_source_sha) is not str
        or _SHA.fullmatch(custody.installed_source_sha) is None
        or type(custody.installation_attempt) is not str
        or _RUN.fullmatch(custody.installation_attempt) is None
        or type(custody.observation_run_id) is not str
        or _RUN.fullmatch(custody.observation_run_id) is None
        or type(custody.receipt_sha256) is not str
        or _HASH.fullmatch(custody.receipt_sha256) is None
        or type(custody.resources) is not adapters.ResourcePins
        or type(custody.control_directory_inode_sha256) is not str
        or _HASH.fullmatch(custody.control_directory_inode_sha256) is None
    ):
        raise _fail()
    custody.resources.validate()


def expected_transition_graph(
    plan: transaction.PairCoordinates,
    phase: str,
    *,
    worker_id: str | None = None,
    controller_id: str | None = None,
    previous_observation: bytes | None = None,
) -> adapters.GraphExpectation:
    """Only actor-recorded exact IDs; never discover candidates by Docker name.

    The previous observation is independently authenticated by the protected
    runner and verified again before this call. Without its exact image refs,
    graph validation cannot silently adopt R188's historical service names.
    """
    try:
        if (
            type(plan) is not transaction.PairCoordinates
            or type(phase) is not str
            or type(previous_observation) is not bytes
        ):
            raise _fail()
        plan.validate()
        observed = prior._decode_pair(previous_observation, plan.observation_run_id)
        old_controller, old_worker = prior._current_pair_matches(plan, observed, observed)
        old = (
            adapters.ExpectedService(
                plan.old_controller_id,
                "controller",
                plan.old_source_sha,
                plan.old_attempt_id,
                cast(str, old_controller["image_ref"]),
            ),
            adapters.ExpectedService(
                plan.old_worker_id,
                "browser-worker",
                plan.old_source_sha,
                plan.old_attempt_id,
                cast(str, old_worker["image_ref"]),
            ),
        )
        with_old = phase in _PREPARED | _PARKED | _THREE | _FOUR | _RESTORED
        with_worker = phase in _THREE | _FOUR | _RETIRED
        with_controller = phase in _FOUR | _RETIRED
        if (
            not with_old
            and not with_worker
            or (
                worker_id is not None
                and (type(worker_id) is not str or _CID.fullmatch(worker_id) is None)
            )
            or (
                controller_id is not None
                and (type(controller_id) is not str or _CID.fullmatch(controller_id) is None)
            )
            or (worker_id is None) != (not with_worker)
            or (controller_id is None) != (not with_controller)
        ):
            raise _fail()
        candidates: tuple[adapters.ExpectedService, ...] = ()
        if with_worker:
            assert worker_id is not None  # Guaranteed above; never a host input.
            candidates += (
                adapters.ExpectedService(
                    worker_id,
                    "browser-worker",
                    plan.new_source_sha,
                    plan.attempt_id,
                    plan.worker_ref,
                ),
            )
        if with_controller:
            assert controller_id is not None
            candidates += (
                adapters.ExpectedService(
                    controller_id,
                    "controller",
                    plan.new_source_sha,
                    plan.attempt_id,
                    plan.controller_ref,
                ),
            )
        graph = adapters.GraphExpectation((old if with_old else ()) + candidates)
        graph.validate()
        return graph
    except Exception:
        raise _fail() from None


@dataclass(slots=True)
class _TransitionBoundIO:
    """Enforce exact prior image IDs and single serving controller."""

    delegate: adapters.RetainedResourceIO
    graph: adapters.GraphExpectation
    plan: transaction.PairCoordinates

    def rootless_identity(self) -> tuple[int, int, str]:
        return self.delegate.rootless_identity()

    def inventory(self) -> cleanup.Inventory:
        current = self.delegate.inventory()
        if type(current) is not cleanup.Inventory:
            raise _fail()
        expected = {item.ident for item in self.graph.services}
        by_id = {item.ident: item for item in current.containers}
        controllers = [
            by_id[item.ident]
            for item in self.graph.services
            if item.role == "controller" and item.ident in by_id
        ]
        if (
            len(current.containers) != len(self.graph.services)
            or set(by_id) != expected
            or len(controllers) not in (1, 2)
            or sum(item.running for item in controllers) > 1
            or self.plan.old_controller_id in by_id
            and by_id[self.plan.old_controller_id].image_id != self.plan.old_controller_image_id
            or self.plan.old_worker_id in by_id
            and by_id[self.plan.old_worker_id].image_id != self.plan.old_worker_image_id
        ):
            raise _fail()
        if self.plan.old_controller_id not in by_id and not controllers[0].running:
            raise _fail()  # Retired new controller must be serving.
        if len(controllers) == 2 and (
            by_id[self.plan.old_controller_id].running
            or sum(item.running for item in controllers) != 1
        ):
            raise _fail()  # Parked old controller cannot continue serving.
        return current

    def identity(self, name: str) -> str:
        return self.delegate.identity(name)

    def worker_state(self, ident: str) -> object:
        return self.delegate.worker_state(ident)

    def mounts(self, ident: str) -> object:
        return self.delegate.mounts(ident)


def observe_transition_resources(
    plan: transaction.PairCoordinates,
    custody: adapters.CustodyEvidence,
    lease: cleanup.BocaJobLease,
    *,
    graph: adapters.GraphExpectation,
    retained_io: adapters.RetainedResourceIO,
) -> adapters.ResourcePins:
    """Recapture immutable R188 volumes and all 2/3/4 candidate CIDs twice."""
    try:
        _historical_seed(custody)
        if (
            type(plan) is not transaction.PairCoordinates
            or type(graph) is not adapters.GraphExpectation
        ):
            raise _fail()
        plan.validate()
        cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
        graph.validate()
        return adapters.observe_retained(
            custody.resources,
            graph,
            plan.attempt_id,
            lease,
            io=_TransitionBoundIO(retained_io, graph, plan),
        )
    except Exception:
        raise _fail() from None


@dataclass(frozen=True, slots=True)
class SuccessorCurrentPairCapture:
    """Fresh current-pair witness using historical pins only for resources.

    The two distinct artifacts must be authenticated by the runner BEFORE
    construction. Same-lease readers never treat R188's historical SHA or
    service CIDs as the installed pair's current SHA or current CIDs.
    """

    historical_custody: adapters.CustodyEvidence
    current_pair_observation: bytes
    retained_io: adapters.RetainedResourceIO | None = None
    pair_reader: Callable[[str], bytes] = pair.observe
    binding_reader: Callable[[cleanup.BocaJobLease], OnDemandInstallation] = (
        service.read_installed_binding
    )
    control_identity_reader: Callable[[str], str] = retained._identity

    def __call__(
        self, plan: transaction.PairCoordinates, lease: cleanup.BocaJobLease
    ) -> journal.FreshPairWitness:
        try:
            if type(plan) is not transaction.PairCoordinates or not callable(self.pair_reader):
                raise _fail()
            plan.validate()
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            _historical_seed(self.historical_custody)
            previous = prior._decode_pair(self.current_pair_observation, plan.observation_run_id)
            prior._current_pair_matches(plan, previous, previous)
            live = prior._decode_pair(self.pair_reader(plan.attempt_id), plan.attempt_id)
            controller, worker = prior._current_pair_matches(plan, live, previous)
            first_binding = self.binding_reader(lease)
            second_binding = self.binding_reader(lease)
            if first_binding != second_binding:
                raise _fail()
            binding._attest(plan.attempt_id, pair._canonical(live), first_binding)
            graph = expected_transition_graph(
                plan, "NEW", previous_observation=self.current_pair_observation
            )
            base_io = (
                self.retained_io
                if self.retained_io is not None
                else prior.ProductionRetainedResourceIO()
            )
            pins = observe_transition_resources(
                plan, self.historical_custody, lease, graph=graph, retained_io=base_io
            )
            before = self.control_identity_reader("control_socket_directory")
            after = self.control_identity_reader("control_socket_directory")
            if before != after or before != self.historical_custody.control_directory_inode_sha256:
                raise _fail()
            repeated = prior._decode_pair(self.pair_reader(plan.attempt_id), plan.attempt_id)
            prior._current_pair_matches(plan, repeated, previous)
            if prior._fixed_coordinates(repeated) != prior._fixed_coordinates(live):
                raise _fail()
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            witness = journal.FreshPairWitness(
                plan.observation_run_id,
                plan.old_attempt_id,
                plan.old_source_sha,
                plan.old_controller_id,
                plan.old_worker_id,
                plan.old_controller_image_id,
                plan.old_worker_image_id,
                pins,
                before,
            )
            witness.validate(plan, self.historical_custody.resources)
            return witness
        except Exception:
            raise _fail() from None


class PhysicalSuccessorIntegrations:
    """Read-side adapter to reused upgrade engine; no effectful cleanup route.

    The existing backend supplies phase and *only* the IDs it physically
    created and verified. Unacknowledged creation is an unknown resource and
    hard NO_GO, never permission to rediscover it via a Compose name.
    """

    def __init__(
        self,
        plan: transaction.PairCoordinates,
        release: adapters.ReleaseEvidence,
        custody: adapters.CustodyEvidence,
        previous_observation: bytes,
        *,
        retained_io: adapters.RetainedResourceIO | None = None,
        control_identity_reader: Callable[[str], str] = retained._identity,
    ) -> None:
        self.plan = plan
        self.release = release
        self.custody = custody
        self.previous_observation = previous_observation
        self.retained_io = retained_io
        self.control_identity_reader = control_identity_reader
        self.backend: successor.PostflightGatedSuccessorBackend | None = None

    def bind_backend(self, backend: successor.PostflightGatedSuccessorBackend) -> None:
        # SUCCESS finalization is delegated through ONE exact immutable
        # one-shot V2 bridge. It must wrap THIS physical read-side adapter;
        # an arbitrary foreign wrapper or extra backend is not admissible.
        wrapper = (
            backend.integrations
            if isinstance(backend, successor.PostflightGatedSuccessorBackend)
            else None
        )
        linked = wrapper is self or (
            type(wrapper) is successor.OneShotFinalCleanupBridge and wrapper._delegate is self
        )
        if (
            self.backend is not None
            or not isinstance(backend, successor.PostflightGatedSuccessorBackend)
            or not linked
        ):
            raise _fail()
        self.backend = backend

    def verify_release(
        self,
        plan: transaction.PairCoordinates,
        sources: PairSources,
        lease: cleanup.BocaJobLease,
    ) -> None:
        try:
            cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
            if (
                plan != self.plan
                or type(self.release) is not adapters.ReleaseEvidence
                or (
                    self.release.source_sha,
                    self.release.release_run_id,
                    self.release.controller_ref,
                    self.release.worker_ref,
                )
                != (plan.new_source_sha, plan.release_run_id, plan.controller_ref, plan.worker_ref)
                or type(sources) is not PairSources
            ):
                raise _fail()
            sources.validate()
        except Exception:
            raise _fail() from None

    def retained_resources(
        self, plan: transaction.PairCoordinates, lease: cleanup.BocaJobLease
    ) -> reusable.RetainedResourcePins:
        try:
            if plan != self.plan or self.backend is None:
                raise _fail()
            backend = self.backend
            graph = expected_transition_graph(
                plan,
                backend.state,
                # The R179 actor keeps historical candidate IDs in memory
                # after a *successful* physical restore. Only RESTORED may
                # leave those IDs out of the expected current graph; the
                # double census below still rejects surviving candidates.
                worker_id=None if backend.state == "RESTORED" else backend.worker_id,
                controller_id=None if backend.state == "RESTORED" else backend.controller_id,
                previous_observation=self.previous_observation,
            )
            io: adapters.RetainedResourceIO = (
                self.retained_io
                if self.retained_io is not None
                else prior.ProductionRetainedResourceIO()
            )
            pins = observe_transition_resources(
                plan, self.custody, lease, graph=graph, retained_io=io
            )
            before = self.control_identity_reader("control_socket_directory")
            after = self.control_identity_reader("control_socket_directory")
            if before != after or before != self.custody.control_directory_inode_sha256:
                raise _fail()
            return reusable.RetainedResourcePins(
                pins.ipc_creator_attempt,
                pins.ipc_inode_sha256,
                pins.site_creator_attempt,
                pins.site_inode_sha256,
                pins.egress_creator_attempt,
                pins.egress_id,
            )
        except Exception:
            raise _fail() from None

    def final_cleanup(self, plan: transaction.PairCoordinates, lease: cleanup.BocaJobLease) -> str:
        # R248 intentionally does not claim to implement V2 success/failure
        # cleanup. Never convert a textual success into an accepted receipt.
        raise _fail()
