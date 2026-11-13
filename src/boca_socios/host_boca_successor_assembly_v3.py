"""R253 inert exact-one-journal Boca successor assembly, not APPLY authority.

Bind the independently reviewed R252 stage, SUCCESS and FAILURE adapters to
one immutable plan and one durable journal. Construction does not acquire a
lease or invoke Docker. The engine's class-level interlock, missing physical
postflight gate, and absent CLI execution route remain untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_observe as pair
from boca_socios import host_boca_pair_upgrade as transaction
from boca_socios import host_boca_pair_upgrade_cli as cli
from boca_socios import host_boca_repeatable_journal as journal
from boca_socios import host_boca_retained_resources as retained
from boca_socios import host_boca_success_bridge_v2 as success_bridge
from boca_socios import host_boca_successor_integrations as integration
from boca_socios import host_boca_successor_physical_v2 as physical
from boca_socios import host_boca_upgrade_same_lease as same_lease
from boca_socios import host_boca_upgrade_successor_runtime as successor
from boca_socios import host_on_demand_service as service


class SuccessorAssemblyNoGo(ValueError):
    """Fixed, redacted refusal before a host effect or a protected lease."""


def _fail() -> SuccessorAssemblyNoGo:
    return SuccessorAssemblyNoGo("Boca R253 inert successor assembly NO_GO")


@dataclass(frozen=True, slots=True)
class InertSameLeaseAssembly:
    """Exact identity graph; deliberately has no executor or GO capability."""

    plan: transaction.PairCoordinates
    preflight: cli.BoundSuccessorPreflight
    journal: journal.SuccessorPairJournal
    stage: integration.CurrentBaseOnlyStageCustody
    success: success_bridge.BoundSuccessCleanup
    failure: integration.OneShotFailureTerminalSink

    def __post_init__(self) -> None:
        try:
            inputs = self.preflight.inputs
            capture = self.journal.capture
            actors = self.success.integrations
            if (
                type(self.plan) is not transaction.PairCoordinates
                or type(self.preflight) is not cli.BoundSuccessorPreflight
                or type(self.journal) is not journal.SuccessorPairJournal
                or type(self.stage) is not integration.CurrentBaseOnlyStageCustody
                or type(self.success) is not success_bridge.BoundSuccessCleanup
                or type(self.failure) is not integration.OneShotFailureTerminalSink
                or type(self.success.backend) is not successor.PostflightGatedSuccessorBackend
                or self.preflight.apply_authorized is not False
                or self.success.apply_authorized is not False
                or self.plan is not self.preflight.inputs.plan
                or self.journal.release is not inputs.release
                or self.journal.retained is not inputs.custody.resources
                or type(capture) is not physical.SuccessorCurrentPairCapture
                or capture.historical_custody is not inputs.custody
                or capture.current_pair_observation is not inputs.original_pair_receipt
                or capture.retained_io is not None
                or capture.pair_reader is not pair.observe
                or capture.binding_reader is not service.read_installed_binding
                or capture.control_identity_reader is not retained._identity
                or self.stage.preflight is not self.preflight
                or self.stage.journal is not self.journal
                or self.success.journal is not self.journal
                or self.success.plan is not self.plan
                or self.failure.journal is not self.journal
                or self.failure.plan is not self.plan
                or type(self.failure.retained_io) is not same_lease.ProductionRetainedResourceIO
                or self.success.backend.integrations is not self.success.final_cleanup
                or self.success.final_cleanup._delegate is not self.success.integrations
                or type(self.success.final_cleanup._read_coordinates)
                is not successor.ProductionFinalCleanupCoordinatesReader
                or self.success.final_cleanup._verify_lease
                is not cleanup.verify_protected_boca_job_lease
                or self.success.integrations.backend is not self.success.backend
                or type(actors) is not physical.PhysicalSuccessorIntegrations
                or actors.plan is not self.plan
                or actors.release is not inputs.release
                or actors.custody is not inputs.custody
                or actors.previous_observation is not inputs.original_pair_receipt
                or actors.retained_io is not None
                or actors.control_identity_reader is not retained._identity
                or self.success.backend.retained is not inputs.retained
                or self.success.backend.successor_postflight_gate is not None
                or type(self.success.backend).requires_persistent_receipt is not False
                or self.success.backend.sources != self.stage.sources()
            ):
                raise _fail()
            self.plan.validate()
        except Exception:
            raise _fail() from None

    @property
    def apply_authorized(self) -> Literal[False]:
        return False

    @property
    def terminal_accept_authorized(self) -> Literal[False]:
        return False


def prepare_inert_same_lease(preflight: cli.BoundSuccessorPreflight) -> InertSameLeaseAssembly:
    """Assemble exact actors from *already authenticated* runner provenance.

    The input object's type and digests are integrity checks, not independent
    GitHub authentication. Only a future protected runner may provide one.
    This function itself never acquires a lease or performs a Docker action.
    """
    try:
        if (
            type(preflight) is not cli.BoundSuccessorPreflight
            or preflight.apply_authorized is not False
        ):
            raise _fail()
        bound = preflight.inputs
        bound.plan.validate()
        capture = physical.SuccessorCurrentPairCapture(
            current_pair_observation=bound.original_pair_receipt,
            historical_custody=bound.custody,
        )
        durable = journal.SuccessorPairJournal(bound.release, bound.custody.resources, capture)
        custody = integration.CurrentBaseOnlyStageCustody(preflight, durable)
        successful = success_bridge.prepare_success_cleanup(preflight, durable)
        failed = integration.OneShotFailureTerminalSink(
            bound.plan,
            durable,
            retained_io=same_lease.ProductionRetainedResourceIO(),
        )
        return InertSameLeaseAssembly(bound.plan, preflight, durable, custody, successful, failed)
    except Exception:
        raise _fail() from None
