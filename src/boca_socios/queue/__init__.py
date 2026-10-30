"""Deterministic, offline queue simulation; never a live Queue-it adapter."""

from boca_socios.queue.simulator import (
    OfflineQueueSimulator,
    QueueSnapshot,
    SimulatorConfig,
)
from boca_socios.queue.state_machine import (
    IdentityPolicy,
    InvalidStateTransition,
    PrequeuePolicy,
    QueueState,
    check_transition,
)

__all__ = [
    "IdentityPolicy",
    "InvalidStateTransition",
    "OfflineQueueSimulator",
    "PrequeuePolicy",
    "QueueSnapshot",
    "QueueState",
    "SimulatorConfig",
    "check_transition",
]
