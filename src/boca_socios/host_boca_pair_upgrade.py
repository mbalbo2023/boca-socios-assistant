"""R179 transaction ordering for Boca's *already installed* dual container pair.

This is an injectable orchestration contract, NOT a standalone host entrypoint.
In particular, syntax-checked coordinates and R178's inert plan are never an
authorization. The protected runner must first authenticate its exact release,
CI/owner/environment and persistent journal; the host adapter must prove the
current exact CIDs, binding, rootless lease, SQLite inode and target provenance.

All effects are delegated to a narrow actor whose methods verify one lease.
The precommit recovery boundary covers BOTH old CIDs and their systemd binding;
after a durable commit marker has even been *attempted*, old CIDs are never
reactivated automatically, including on an uncertain fsync or interrupted SSH.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from boca_socios.host_boca_cleanup import BocaJobLease, protected_boca_job_lease
from boca_socios.host_boca_pair_upgrade_plan import verify as verify_inert_plan

_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CONTROLLER = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_WORKER = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z")
PairPhase = Literal[
    "NONE",
    "ATTEST",
    "STAGE",
    "PARK",
    "CREATE_WORKER",
    "CREATE_CONTROLLER",
    "ACCEPT",
    "REPLACE_BINDING",
    "COMMIT_MARKER",
    "RETIRE_OLD",
    "FINALIZE",
]
_CLEANUP = frozenset({"ACCEPT", "NO_GO", "INDETERMINATE"})


class PairUpgradeError(ValueError):
    """The Boca pair or its state cannot be upgraded with positive evidence."""


@dataclass(frozen=True)
class PairCoordinates:
    """Immutable identity coordinates; NOT permission or a current-host proof."""

    attempt_id: str
    observation_run_id: str
    old_attempt_id: str
    old_source_sha: str
    old_controller_id: str
    old_worker_id: str
    old_controller_image_id: str
    old_worker_image_id: str
    new_source_sha: str
    release_run_id: str
    controller_ref: str
    worker_ref: str

    @classmethod
    def from_inert_plan(cls, raw: bytes, attempt_id: str) -> PairCoordinates:
        """Verify R178's canonical NO_GO plan, never reinterpret it as a GO."""
        verify_inert_plan(raw, attempt_id)
        data = json.loads(raw.removeprefix(b"BOCA_DUAL_UPGRADE_PLAN "))
        return cls(
            attempt_id=attempt_id,
            observation_run_id=data["observed_run_id"],
            old_attempt_id=data["old_attempt_id"],
            old_source_sha=data["old_source_sha"],
            old_controller_id=data["old_controller_id"],
            old_worker_id=data["old_worker_id"],
            old_controller_image_id=data["old_controller_image_id"],
            old_worker_image_id=data["old_worker_image_id"],
            new_source_sha=data["new_source_sha"],
            release_run_id=data["new_release_run_id"],
            controller_ref=data["new_controller_image_ref"],
            worker_ref=data["new_worker_image_ref"],
        )

    def validate(self) -> None:
        if (
            any(
                type(value) is not str or _RUN.fullmatch(value) is None
                for value in (
                    self.attempt_id,
                    self.observation_run_id,
                    self.old_attempt_id,
                    self.release_run_id,
                )
            )
            or len(
                {
                    self.attempt_id,
                    self.observation_run_id,
                    self.old_attempt_id,
                    self.release_run_id,
                }
            )
            != 4
            or any(
                type(value) is not str or _SHA.fullmatch(value) is None
                for value in (self.old_source_sha, self.new_source_sha)
            )
            or self.old_source_sha == self.new_source_sha
            or any(
                type(value) is not str or _HEX.fullmatch(value) is None
                for value in (self.old_controller_id, self.old_worker_id)
            )
            or self.old_controller_id == self.old_worker_id
            or any(
                type(value) is not str or _IMAGE_ID.fullmatch(value) is None
                for value in (self.old_controller_image_id, self.old_worker_image_id)
            )
            or type(self.controller_ref) is not str
            or _CONTROLLER.fullmatch(self.controller_ref) is None
            or type(self.worker_ref) is not str
            or _WORKER.fullmatch(self.worker_ref) is None
        ):
            raise PairUpgradeError("Boca dual upgrade identities untrusted")


@dataclass(frozen=True)
class PairUpgradeReceipt:
    attempt_id: str
    state: Literal["ACCEPTED", "RECOVERED", "NO_GO"]
    cleanup: Literal["ACCEPT", "NO_GO", "INDETERMINATE"]
    old_restored: bool
    commit_started: bool
    controller_id: str | None
    worker_id: str | None
    failed_phase: PairPhase

    @property
    def accepted(self) -> bool:
        return self.state == "ACCEPTED" and self.cleanup == "ACCEPT" and self.commit_started


class PairUpgradeBackend(Protocol):
    """Each operation must attest Boca-only ownership and this same rootless lease.

    `attest` is strictly read-only and rejects unverified SQLite inode,
    rootless systemd, foreign Docker resources, active worker and stale CIDs.
    `stage` must verify dual release integrity before any mutation. `park`
    quiesces old socket and parks both exact CIDs, without deleting either.
    `restore_old` is independently idempotent and verifies old health+bindings.
    `retire_old` only deletes the two original exact CIDs after commit marker.
    `finalize` must perform same-lease selective reconciliation even on failure.
    """

    requires_persistent_receipt: bool

    def attest(self, plan: PairCoordinates, lease: BocaJobLease) -> None: ...

    def stage(self, plan: PairCoordinates, lease: BocaJobLease) -> None: ...

    def park(self, plan: PairCoordinates, lease: BocaJobLease) -> None: ...

    def create_worker(self, plan: PairCoordinates, lease: BocaJobLease) -> str: ...

    def create_controller(
        self, plan: PairCoordinates, worker_id: str, lease: BocaJobLease
    ) -> str: ...

    def accept(
        self, plan: PairCoordinates, controller_id: str, worker_id: str, lease: BocaJobLease
    ) -> None: ...

    def replace_binding(
        self, plan: PairCoordinates, controller_id: str, worker_id: str, lease: BocaJobLease
    ) -> None: ...

    def retire_old(
        self, plan: PairCoordinates, controller_id: str, worker_id: str, lease: BocaJobLease
    ) -> None: ...

    def restore_old(self, plan: PairCoordinates, lease: BocaJobLease) -> bool: ...

    def finalize(
        self,
        plan: PairCoordinates,
        *,
        commit_started: bool,
        controller_id: str | None,
        worker_id: str | None,
        lease: BocaJobLease,
    ) -> str: ...


TerminalPreflight = Callable[[PairCoordinates, BocaJobLease], None]
CommitMarker = Callable[[PairCoordinates, BocaJobLease], None]
TerminalSink = Callable[[PairCoordinates, PairUpgradeReceipt, BocaJobLease], None]
BackendFactory = Callable[[PairCoordinates, BocaJobLease], PairUpgradeBackend]


def run_pair_upgrade(
    plan: PairCoordinates,
    *,
    backend: PairUpgradeBackend | None = None,
    backend_factory: BackendFactory | None = None,
    terminal_preflight: TerminalPreflight | None = None,
    commit_marker: CommitMarker | None = None,
    terminal_sink: TerminalSink | None = None,
) -> PairUpgradeReceipt:
    """Sequence an exact-pair upgrade with one lease and durable boundaries.

    This function alone can never authenticate runner provenance or provide
    permission; production host adapter plus preflight/marker/terminal sink are
    mandatory. A backend factory is invoked under the held lease only AFTER
    durable intent, so its potential host effects cannot precede the record.
    Unverified finalization fails closed. Post-marker rollback is forbidden
    even if marker fsync failed with an indeterminate outcome.
    """
    if type(plan) is not PairCoordinates:
        raise PairUpgradeError("Boca pair upgrade coordinates missing")
    plan.validate()
    if (
        (backend is None) == (backend_factory is None)
        or (backend_factory is not None and not callable(backend_factory))
        or (
            backend is not None
            and getattr(type(backend), "requires_persistent_receipt", False) is not True
        )
        or terminal_preflight is None
        or commit_marker is None
        or terminal_sink is None
    ):
        raise PairUpgradeError("Boca dual upgrade requires protected terminal intent/receipt")
    with protected_boca_job_lease(plan.attempt_id) as lease:
        terminal_preflight(plan, lease)  # Must durable O_EXCL/fsync before first host effect.
        if backend_factory is not None:
            try:
                backend = backend_factory(plan, lease)
                if getattr(type(backend), "requires_persistent_receipt", False) is not True:
                    raise PairUpgradeError("Boca dual backend factory untrusted")
            except BaseException:
                # Factory callbacks may have unknown effects. Do not invent
                # restoration/finalization or allow a missing durable terminal.
                receipt = PairUpgradeReceipt(
                    attempt_id=plan.attempt_id,
                    state="NO_GO",
                    cleanup="INDETERMINATE",
                    old_restored=False,
                    commit_started=False,
                    controller_id=None,
                    worker_id=None,
                    failed_phase="ATTEST",
                )
                terminal_sink(plan, receipt, lease)
                return receipt
        if backend is None:
            raise PairUpgradeError("Boca dual backend unavailable")
        started = False
        commit_started = False
        restored = False
        done = False
        controller: str | None = None
        worker: str | None = None
        phase: PairPhase = "ATTEST"
        failed_phase: PairPhase = "NONE"
        try:
            backend.attest(plan, lease)
            started = True
            phase = "STAGE"
            backend.stage(plan, lease)
            phase = "PARK"
            backend.park(plan, lease)
            phase = "CREATE_WORKER"
            worker = backend.create_worker(plan, lease)
            if (
                type(worker) is not str
                or _HEX.fullmatch(worker) is None
                or worker in (plan.old_controller_id, plan.old_worker_id)
            ):
                raise PairUpgradeError("new worker exact container identity unverified")
            phase = "CREATE_CONTROLLER"
            controller = backend.create_controller(plan, worker, lease)
            if (
                type(controller) is not str
                or _HEX.fullmatch(controller) is None
                or controller in (worker, plan.old_controller_id, plan.old_worker_id)
            ):
                raise PairUpgradeError("new controller exact container identity unverified")
            phase = "ACCEPT"
            backend.accept(plan, controller, worker, lease)
            phase = "REPLACE_BINDING"
            backend.replace_binding(plan, controller, worker, lease)
            # Record that commitment *may* have been durable BEFORE issuing I/O.
            # Uncertain fsync never authorizes revival of the old containers.
            phase = "COMMIT_MARKER"
            commit_started = True
            commit_marker(plan, lease)
            phase = "RETIRE_OLD"
            backend.retire_old(plan, controller, worker, lease)
            done = True
        except BaseException:
            failed_phase = phase
            if started and not commit_started:
                try:
                    restored = backend.restore_old(plan, lease) is True
                except BaseException:
                    restored = False
        phase = "FINALIZE"
        cleanup: Literal["ACCEPT", "NO_GO", "INDETERMINATE"] = "INDETERMINATE"
        try:
            raw = backend.finalize(
                plan,
                commit_started=commit_started,
                controller_id=controller,
                worker_id=worker,
                lease=lease,
            )
            if raw in _CLEANUP:
                cleanup = raw  # type: ignore[assignment]
        except BaseException:
            if failed_phase == "NONE":
                failed_phase = phase
        accepted = done and commit_started and cleanup == "ACCEPT"
        state: Literal["ACCEPTED", "RECOVERED", "NO_GO"] = (
            "ACCEPTED" if accepted else "RECOVERED" if restored and cleanup == "ACCEPT" else "NO_GO"
        )
        receipt = PairUpgradeReceipt(
            attempt_id=plan.attempt_id,
            state=state,
            cleanup=cleanup,
            old_restored=restored,
            commit_started=commit_started,
            controller_id=controller,
            worker_id=worker,
            failed_phase=failed_phase,
        )
        terminal_sink(plan, receipt, lease)  # Failure must never emit ACCEPT by fallthrough.
        return receipt
