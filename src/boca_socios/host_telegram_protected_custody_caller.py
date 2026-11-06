"""Code-only staged Telegram custody caller, inside one Boca protected lease.

Unlike the redacted four-GET diagnostic caller, this path retains the sealed
owner stage and can commit V2 custody **once** after four GETs. Its only network
transport is the one exact-ID ephemeral, read-only Docker helper; its only
durable effect is the existing nonce/custody adapter. No CLI, GitHub GO_B,
host backend, sender activation or human receipt is supplied by this module.

All injected host evidence MUST originate from a separate real protected
Cutover A / Telegram operation. Synthetic callbacks in tests are not authority.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from pathlib import Path

from boca_socios.host_boca_cleanup import BocaJobLease, verify_protected_boca_job_lease
from boca_socios.host_lifecycle_rootless_adapter import LifecycleDockerIO
from boca_socios.host_telegram_active_helper_topology import TelegramActiveHelperTopologyWitness
from boca_socios.host_telegram_egress_helper import (
    TelegramHelperPhaseProof,
    protected_ephemeral_get_session,
)
from boca_socios.host_telegram_postcutover import TelegramHostPins
from boca_socios.host_telegram_production_reader import TelegramProductionDockerIO
from boca_socios.telegram_bootstrap import RecipientReceipt
from boca_socios.telegram_pairing_cutover import (
    CutoverCoordinates,
    HostRecheckReceipt,
    OwnerPairingReceipt,
    ProtectedPairingReceipt,
    _coordinates_valid,
    _verify_owner_receipt,
)
from boca_socios.telegram_same_lease_stage import (
    execute_staged_pairing_under_lease,
    read_encrypted_telegram_stage,
)

HostPhaseAttestor = Callable[
    [str, TelegramHelperPhaseProof, CutoverCoordinates], HostRecheckReceipt
]


class TelegramProtectedCustodyNoGo(ValueError):
    """Only a static redacted reason crosses the workflow boundary."""


def _preflight(
    pins: TelegramHostPins,
    coords: CutoverCoordinates,
    *,
    lease: BocaJobLease,
    stage_directory: Path,
    owner_receipt: OwnerPairingReceipt,
    owner_receipt_key: bytes,
    recipient: RecipientReceipt,
    private_key: bytes,
    trusted_clock: Callable[[], int],
    phase_host_attestor: HostPhaseAttestor,
) -> None:
    """Fail before helper creation when stage/authority is already invalid."""
    try:
        pins.require()
        if (
            not _coordinates_valid(coords)
            or pins.attempt_id != coords.attempt_id
            or pins.source_sha != coords.target_sha
            or pins.controller_id != coords.controller_id
            or pins.controller_image != coords.image_digest
            or pins.owner_digest != coords.owner_digest
            or pins.recipient_fingerprint != coords.recipient_fingerprint
            or type(recipient) is not RecipientReceipt
            or recipient.fingerprint != coords.recipient_fingerprint
            or type(private_key) is not bytes
            or len(private_key) != 32
            or type(owner_receipt) is not OwnerPairingReceipt
            or type(owner_receipt_key) is not bytes
            or len(owner_receipt_key) != 32
            or not callable(trusted_clock)
            or not callable(phase_host_attestor)
        ):
            raise ValueError("coordinates")
        verify_protected_boca_job_lease(lease, pins.attempt_id)
        now = trusted_clock()
        stage = read_encrypted_telegram_stage(
            stage_directory, coordinates=coords, lease=lease, trusted_now=now
        )
        if (
            owner_receipt.coordinates != coords
            or not hmac.compare_digest(owner_receipt.envelope_sha256, stage.envelope_sha256)
            or type(owner_receipt.discovery_not_before) is not int
            or owner_receipt.discovery_not_before != stage.staged_at
            or stage.staged_at > owner_receipt.issued_at
            or now - stage.staged_at > 3600
        ):
            raise ValueError("owner stage")
        _verify_owner_receipt(coords, owner_receipt, owner_receipt_key, stage.envelope, now)
        verify_protected_boca_job_lease(lease, pins.attempt_id)
    except Exception:
        raise TelegramProtectedCustodyNoGo("telegram_custody_preflight_unverified") from None


def run_bound_telegram_staged_custody(
    pins: TelegramHostPins,
    coords: CutoverCoordinates,
    *,
    lease: BocaJobLease,
    stage_directory: Path,
    custody_directory: Path,
    owner_receipt: OwnerPairingReceipt,
    owner_receipt_key: bytes,
    recipient: RecipientReceipt,
    private_key: bytes,
    trusted_clock: Callable[[], int],
    phase_host_attestor: HostPhaseAttestor,
    reader: LifecycleDockerIO | None = None,
) -> ProtectedPairingReceipt:
    """Perform one staged pairing while the sole approved GET helper is open.

    Protected workflow ownership and physical GO_B are intentionally outside
    this library. A fake attestor or data path is never host verification.
    """
    _preflight(
        pins,
        coords,
        lease=lease,
        stage_directory=stage_directory,
        owner_receipt=owner_receipt,
        owner_receipt_key=owner_receipt_key,
        recipient=recipient,
        private_key=private_key,
        trusted_clock=trusted_clock,
        phase_host_attestor=phase_host_attestor,
    )
    probe = TelegramProductionDockerIO() if reader is None else reader
    try:
        with protected_ephemeral_get_session(
            pins, coords, lease=lease, reader=probe
        ) as private_get:

            def verified_host_phase(phase: str, checked: CutoverCoordinates) -> HostRecheckReceipt:
                if checked != coords:
                    raise TelegramProtectedCustodyNoGo("telegram_custody_coordinates_drift")
                helper_proof = private_get.attest_phase(phase)
                topology_proof = private_get.attest_topology(phase)
                if (
                    type(helper_proof) is not TelegramHelperPhaseProof
                    or helper_proof.attempt_id != pins.attempt_id
                    or helper_proof.source_sha != pins.source_sha
                    or helper_proof.phase != phase
                    or helper_proof.state != "HELPER_ATTESTED_READONLY_NO_GO"
                    or helper_proof.sender_state != "OFF"
                    or helper_proof.host_go is not False
                    or type(topology_proof) is not TelegramActiveHelperTopologyWitness
                    or topology_proof.attempt_id != pins.attempt_id
                    or topology_proof.source_sha != pins.source_sha
                    or topology_proof.phase != phase
                    or topology_proof.state != "ACTIVE_HELPER_STOPPED_TOPOLOGY_OBSERVED_NO_GO"
                    or topology_proof.sender_state != "OFF"
                    or topology_proof.host_go is not False
                    or topology_proof.custody_state != "UNVERIFIED"
                    or topology_proof.human_receipt != "UNVERIFIED"
                ):
                    raise TelegramProtectedCustodyNoGo("telegram_custody_phase_unverified")
                actual = phase_host_attestor(phase, helper_proof, checked)
                if type(actual) is not HostRecheckReceipt:
                    raise TelegramProtectedCustodyNoGo("telegram_custody_host_recheck_unverified")
                return actual

            result = execute_staged_pairing_under_lease(
                stage_directory=stage_directory,
                custody_directory=custody_directory,
                coordinates=coords,
                owner_receipt=owner_receipt,
                owner_receipt_key=owner_receipt_key,
                recipient=recipient,
                private_key=private_key,
                lease=lease,
                trusted_clock=trusted_clock,
                inspect_host=verified_host_phase,
                api_fetch=private_get,
            )
        if (
            type(result) is not ProtectedPairingReceipt
            or result.attempt_id != pins.attempt_id
            or result.source_sha != pins.source_sha
            or result.recipient_fingerprint != pins.recipient_fingerprint
            or result.state != "CUSTODY_COMMITTED_NO_SEND"
            or result.sender_state != "OFF"
            or result.human_notification_receipt != "UNVERIFIED"
        ):
            raise TelegramProtectedCustodyNoGo("telegram_custody_receipt_unverified")
        return result
    except Exception:
        # Failure after durable nonce/commit can be indeterminate: never
        # delete/retry the nonce or silently downgrade to read-only reads.
        raise TelegramProtectedCustodyNoGo("telegram_custody_protected_transaction_no_go") from None
