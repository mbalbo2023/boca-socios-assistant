"""Read-only, active-helper-aware Boca Telegram topology witness (ADR0178).

The existing stopped-release observer legitimately expects an EMPTY Telegram
egress network. During a protected, exactly-one ephemeral GET helper session,
that one freshly attested container is the only allowed extra Docker object.
This module validates the *actual* live graph before projecting away that
exact helper for the existing stopped-release observer. Projection must never
hide competing pollers, unknown containers, unauthorized mounts or sender.

This is only a diagnostic. No WebAuthn, schema, stage, recipient custody,
provider result or GO_B authority can be inferred from Docker inventory.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from boca_socios.host_boca_cleanup import (
    BocaJobLease,
    Inventory,
    verify_protected_boca_job_lease,
)
from boca_socios.host_lifecycle_rootless_adapter import LifecycleDockerIO
from boca_socios.host_telegram_postcutover import (
    TelegramHostPins,
    TelegramTopologyWitness,
    observe_telegram_host,
)
from boca_socios.integration.engine_socket import EngineReceipt
from boca_socios.telegram_pairing_cutover import CutoverCoordinates, _coordinates_valid

_EGRESS = "boca-socios_boca_telegram_egress"


class TelegramActiveTopologyNoGo(ValueError):
    """No raw Docker state, secrets or foreign metadata in this error."""


@dataclass(frozen=True, slots=True)
class TelegramActiveHelperTopologyWitness:
    """Non-authorizing topology proof; helper ID deliberately not published."""

    attempt_id: str
    source_sha: str
    phase: str
    state: Literal["ACTIVE_HELPER_STOPPED_TOPOLOGY_OBSERVED_NO_GO"] = (
        "ACTIVE_HELPER_STOPPED_TOPOLOGY_OBSERVED_NO_GO"
    )
    sender_state: Literal["OFF"] = "OFF"
    host_go: Literal[False] = False
    custody_state: Literal["UNVERIFIED"] = "UNVERIFIED"
    human_receipt: Literal["UNVERIFIED"] = "UNVERIFIED"


class _ScopedInactiveProjection:
    """Snapshot of all Boca resources with ONE previously proven helper removed.

    The projection is never returned to the caller as physical evidence: only
    the stopped-release observer can read it; that observer still inspects
    original live Docker fields through the same rootless reader.
    """

    def __init__(self, reader: LifecycleDockerIO, inventory: Inventory) -> None:
        self._reader = reader
        self._inventory = inventory

    @property
    def uid(self) -> int:
        return self._reader.uid

    @property
    def gid(self) -> int:
        return self._reader.gid

    def inventory(self) -> Inventory:
        return self._inventory

    def field(self, kind: str, ident: str, field: str) -> object:
        return self._reader.field(kind, ident, field)

    def engine_request(self, controller_id: str, operation: str) -> EngineReceipt:
        raise TelegramActiveTopologyNoGo("telegram_active_topology_readonly_only")

    def worker_action(self, worker_id: str, operation: str) -> None:
        raise TelegramActiveTopologyNoGo("telegram_active_topology_readonly_only")


def _project_only_attested_helper(
    original: Inventory, pins: TelegramHostPins, helper_id: str
) -> Inventory:
    expected = {pins.controller_id, pins.worker_id, helper_id}
    if pins.sender_expected_state == "stopped":
        expected.add(pins.sender_id)
    actual = {item.ident for item in original.containers}
    networks = {item.name: item for item in original.networks}
    if (
        len(original.containers) != len(expected)
        or actual != expected
        or helper_id in {pins.controller_id, pins.worker_id, pins.sender_id}
        or len(networks) != len(original.networks)
        or set(networks) != {"boca-socios_boca_private", _EGRESS}
        or networks[_EGRESS].attached_ids != (helper_id,)
    ):
        raise TelegramActiveTopologyNoGo("telegram_active_topology_competing_object_unverified")
    projected = replace(
        original,
        containers=tuple(item for item in original.containers if item.ident != helper_id),
        networks=tuple(
            replace(network, attached_ids=()) if network.name == _EGRESS else network
            for network in original.networks
        ),
    )
    if len(projected.containers) != len(expected) - 1:
        raise TelegramActiveTopologyNoGo("telegram_active_topology_projection_unverified")
    return projected


def observe_active_helper_topology(
    pins: TelegramHostPins,
    coordinates: CutoverCoordinates,
    *,
    phase: str,
    lease: BocaJobLease,
    reader: LifecycleDockerIO,
    helper_id: str,
) -> TelegramActiveHelperTopologyWitness:
    """Observe stopped Boca release *while* its one attested GET helper runs.

    The protected helper session calls its exact-ID helper inspection before
    entering this function. Both caller and this observer recheck the held
    lease, then compare actual rootless inventory before and after inspection.
    Any uncertainty is NO_GO; no side effect is performed here.
    """
    try:
        pins.require()
        if (
            not _coordinates_valid(coordinates)
            or coordinates.attempt_id != pins.attempt_id
            or coordinates.target_sha != pins.source_sha
            or coordinates.controller_id != pins.controller_id
            or coordinates.image_digest != pins.controller_image
            or reader.uid != 10001
            or reader.gid != 10001
            or phase
            not in {
                "BEFORE_API",
                "BEFORE_getMe",
                "BEFORE_getWebhookInfo",
                "BEFORE_getUpdates",
                "BEFORE_getChat",
                "AFTER_READS",
                "BEFORE_COMMIT",
                "AFTER_COMMIT",
            }
        ):
            raise ValueError("input")
        verify_protected_boca_job_lease(lease, pins.attempt_id)
        # Do not trust the caller merely because it supplied a 64-hex ID.
        # This direct function entry must independently validate the same
        # UID10001/helper image/mount/env/egress boundary as the GET helper.
        from boca_socios.host_telegram_egress_helper import _helper_attested

        _helper_attested(
            reader,
            helper_id,
            "boca-socios-telegram-readonly-" + pins.attempt_id,
            pins,
            coordinates,
        )
        before = reader.inventory()
        projected = _project_only_attested_helper(before, pins, helper_id)
        stopped = observe_telegram_host(
            pins, lease=lease, io=_ScopedInactiveProjection(reader, projected)
        )
        if type(stopped) is not TelegramTopologyWitness or stopped.authorized is not False:
            raise ValueError("inactive topology")
        after = reader.inventory()
        # The live graph must not mutate across the stopped-release field
        # inspections. Disk/inode availability is not a resource identity.
        if (
            before.containers != after.containers
            or before.images != after.images
            or before.networks != after.networks
            or before.volumes != after.volumes
        ):
            raise ValueError("inventory raced")
        verify_protected_boca_job_lease(lease, pins.attempt_id)
    except Exception:
        raise TelegramActiveTopologyNoGo("telegram_active_topology_unverified") from None
    return TelegramActiveHelperTopologyWitness(pins.attempt_id, pins.source_sha, phase)
