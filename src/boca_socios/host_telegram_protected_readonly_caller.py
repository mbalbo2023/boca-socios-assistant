"""Bind a Boca helper's verified phases to the four-GET owner-stage contract.

This is a library-only candidate, NOT a GitHub Environment gate or host CLI.
The future protected Actions backend must prove exact GO_B, Cutover A ACK,
release provenance and real rootless topology *before* invoking it. Its
``phase_host_attestor`` must inspect actual stopped Boca services under the
held lock; fabricated claims in offline tests are never physical authority.

No sender or custody path is exposed here. Four GETs only return a proof that
explicitly says UNCOMMITTED / OFF / NOT_AUTHORIZED / human UNVERIFIED.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from boca_socios.host_boca_cleanup import BocaJobLease
from boca_socios.host_lifecycle_rootless_adapter import LifecycleDockerIO
from boca_socios.host_telegram_active_helper_topology import TelegramActiveHelperTopologyWitness
from boca_socios.host_telegram_egress_helper import (
    ProtectedEphemeralGet,
    TelegramHelperPhaseProof,
    protected_ephemeral_get_session,
)
from boca_socios.host_telegram_postcutover import TelegramHostPins
from boca_socios.host_telegram_production_reader import TelegramProductionDockerIO
from boca_socios.telegram_bootstrap import RecipientReceipt
from boca_socios.telegram_host_readonly_session import (
    TelegramFourGetProof,
    four_gets_under_existing_lease,
)
from boca_socios.telegram_pairing_cutover import CutoverCoordinates, HostRecheckReceipt

HostPhaseAttestor = Callable[
    [str, TelegramHelperPhaseProof, CutoverCoordinates], HostRecheckReceipt
]


class TelegramProtectedReadOnlyNoGo(ValueError):
    """Static failure reason, never disclose helper IDs, token or chat IDs."""


def run_bound_telegram_four_gets(
    pins: TelegramHostPins,
    coordinates: CutoverCoordinates,
    *,
    lease: BocaJobLease,
    recipient: RecipientReceipt,
    private_key: bytes,
    trusted_clock: Callable[[], int],
    phase_host_attestor: HostPhaseAttestor,
    reader: LifecycleDockerIO | None = None,
) -> TelegramFourGetProof:
    """Wire exact-ID helper phase checks to the owner-stage read session.

    The host phase attestor is deliberately external: a future protected
    workflow needs a *real* active-helper-aware topology check, not a fake
    JSON claim. Even SUCCESS of this function cannot commit custody or send.
    """
    if not callable(phase_host_attestor) or not callable(trusted_clock):
        raise TelegramProtectedReadOnlyNoGo("telegram_protected_phase_backend_unverified")
    probe = TelegramProductionDockerIO() if reader is None else reader
    active: list[ProtectedEphemeralGet] = []

    @contextmanager
    def one_helper() -> Iterator[ProtectedEphemeralGet]:
        with protected_ephemeral_get_session(
            pins, coordinates, lease=lease, reader=probe
        ) as private_get:
            active.append(private_get)
            try:
                yield private_get
            finally:
                active.clear()

    def verified_host_phase(phase: str, checked: CutoverCoordinates) -> HostRecheckReceipt:
        try:
            if len(active) != 1 or checked != coordinates:
                raise ValueError("caller missing its helper")
            proof = active[0].attest_phase(phase)
            if (
                type(proof) is not TelegramHelperPhaseProof
                or proof.attempt_id != pins.attempt_id
                or proof.source_sha != pins.source_sha
                or proof.phase != phase
                or proof.state != "HELPER_ATTESTED_READONLY_NO_GO"
                or proof.sender_state != "OFF"
                or proof.host_go is not False
            ):
                raise ValueError("helper proof mismatch")
            # The legacy stopped-release observer expects Telegram egress
            # empty. During these GETs the exact approved ephemeral helper
            # occupies it, so independently observe the stopped release with
            # that ONE helper excluded only after its live attestation.
            topology = active[0].attest_topology(phase)
            if (
                type(topology) is not TelegramActiveHelperTopologyWitness
                or topology.attempt_id != pins.attempt_id
                or topology.source_sha != pins.source_sha
                or topology.phase != phase
                or topology.state != "ACTIVE_HELPER_STOPPED_TOPOLOGY_OBSERVED_NO_GO"
                or topology.sender_state != "OFF"
                or topology.host_go is not False
                or topology.custody_state != "UNVERIFIED"
                or topology.human_receipt != "UNVERIFIED"
            ):
                raise ValueError("stopped Boca release with helper unverified")
            actual = phase_host_attestor(phase, proof, checked)
            if type(actual) is not HostRecheckReceipt:
                raise ValueError("missing physical topology receipt")
            return actual
        except Exception:
            raise TelegramProtectedReadOnlyNoGo(
                "telegram_protected_host_phase_unverified"
            ) from None

    try:
        result = four_gets_under_existing_lease(
            pins,
            coordinates,
            lease=lease,
            recipient=recipient,
            private_key=private_key,
            session_factory=one_helper,
            recheck_host=verified_host_phase,
            trusted_clock=trusted_clock,
            io=probe,
        )
    except Exception:
        raise TelegramProtectedReadOnlyNoGo("telegram_protected_four_gets_no_go") from None
    if (
        type(result) is not TelegramFourGetProof
        or result.attempt_id != pins.attempt_id
        or result.source_sha != pins.source_sha
        or result.sender_state != "OFF"
        or result.custody_state != "UNCOMMITTED"
        or result.human_receipt != "UNVERIFIED"
        or result.host_go is not False
        or result.methods != 4
    ):
        raise TelegramProtectedReadOnlyNoGo("telegram_protected_readonly_receipt_unverified")
    return result
