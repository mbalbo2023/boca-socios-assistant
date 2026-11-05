"""Offline cutover-A transaction contract for the already installed controller.

This is deliberately NOT an effectful host entrypoint.  Unlike the new-only
``host_boca_transaction`` helper, cutover must preserve the exact running legacy
controller until a separately authenticated candidate is accepted.  A future
single-host backend must implement this protocol and obtain one protected
Actions authorization before making it callable on a real host.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from boca_socios.host_boca_cleanup import BocaJobLease, protected_boca_job_lease

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[1-9][0-9]{0,19}\Z")
_OWNER = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_CONTROLLER_IMAGE = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_WORKER_IMAGE = re.compile(
    r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z"
)
CleanupStatus = Literal["ACCEPT", "NO_GO", "INDETERMINATE"]


class CutoverError(ValueError):
    """Cutover has no acceptable positive evidence for an effect."""


@dataclass(frozen=True)
class CutoverPlan:
    attempt_id: str
    legacy_id: str
    legacy_sha: str
    legacy_image: str
    legacy_compose_sha: str
    target_sha: str
    target_image: str
    browser_image: str
    target_compose_sha: str
    overlay_sha: str
    seccomp_sha: str
    owner_subject: str
    origin: str = "http://localhost:8443"

    def validate(self) -> None:
        if (
            not _ATTEMPT.fullmatch(self.attempt_id)
            or not _DIGEST.fullmatch(self.legacy_id)
            or not _SHA.fullmatch(self.legacy_sha)
            or not _SHA.fullmatch(self.target_sha)
            or self.legacy_sha == self.target_sha
            or not _CONTROLLER_IMAGE.fullmatch(self.legacy_image)
            or not _CONTROLLER_IMAGE.fullmatch(self.target_image)
            or self.legacy_image == self.target_image
            or not _WORKER_IMAGE.fullmatch(self.browser_image)
            or not _OWNER.fullmatch(self.owner_subject)
            or self.origin != "http://localhost:8443"
            or any(
                not _DIGEST.fullmatch(value)
                for value in (
                    self.legacy_compose_sha,
                    self.target_compose_sha,
                    self.overlay_sha,
                    self.seccomp_sha,
                )
            )
            or len(
                {
                    self.legacy_compose_sha,
                    self.target_compose_sha,
                    self.overlay_sha,
                    self.seccomp_sha,
                }
            )
            != 4
        ):
            raise CutoverError("cutover A exact historical/target coordinates untrusted")


@dataclass(frozen=True)
class CutoverReceipt:
    attempt_id: str
    state: Literal["ACCEPTED", "RECOVERED", "NO_GO"]
    cleanup: CleanupStatus
    original_restored: bool
    irreversible_commit_started: bool
    candidate_id: str | None
    worker_id: str | None

    @property
    def accepted(self) -> bool:
        return self.state == "ACCEPTED" and self.cleanup == "ACCEPT"


class CutoverBackend(Protocol):
    """One-process host effects, all independently attested by exact ID.

    Backend methods MUST retain the original supplied lease, verify the
    installed singleton before/after any Docker mutation, and never perform a
    broad Docker prune.  In particular ``bootstrap_owner_session`` must use
    #321's *separate* SQLite file under the existing Boca volume while legacy
    is positively stopped; it must never migrate legacy schema to 0008.
    """

    def attest_original(self, plan: CutoverPlan, lease: BocaJobLease) -> None: ...

    def stage(self, plan: CutoverPlan, lease: BocaJobLease) -> None: ...

    def prepare_worker(self, plan: CutoverPlan, lease: BocaJobLease) -> str: ...

    def park_original(self, plan: CutoverPlan, lease: BocaJobLease) -> None: ...

    def bootstrap_owner_session(self, plan: CutoverPlan, lease: BocaJobLease) -> None: ...

    def activate_candidate(self, plan: CutoverPlan, worker_id: str, lease: BocaJobLease) -> str: ...

    def accept_candidate(
        self, plan: CutoverPlan, candidate_id: str, worker_id: str, lease: BocaJobLease
    ) -> None: ...

    def retire_original(
        self, plan: CutoverPlan, candidate_id: str, worker_id: str, lease: BocaJobLease
    ) -> None: ...

    def recover_original(self, plan: CutoverPlan, lease: BocaJobLease) -> bool: ...

    def finalize(
        self,
        plan: CutoverPlan,
        *,
        commit_started: bool,
        candidate_id: str | None,
        worker_id: str | None,
        lease: BocaJobLease,
    ) -> CleanupStatus: ...


TerminalSink = Callable[[CutoverPlan, CutoverReceipt, BocaJobLease], None]


def run_cutover_a(
    plan: CutoverPlan, *, backend: CutoverBackend, terminal_sink: TerminalSink | None = None
) -> CutoverReceipt:
    """Unit-testable sequencing only; no concrete backend or host CLI exists.

    A single lease spans all effects and the unconditional postflight.  The
    irreversible old-ID retirement is intentionally last.  Once it *starts*,
    a lost receipt must not trigger an unsafe revival over localhost:8443.
    A hard SSH/runner loss yields no receipt; a future Actions ``if: always()``
    assertion must make that NO_GO.  Synthetic tests cannot confer host GO.
    """
    plan.validate()  # No host operation for malformed coordinates.
    with protected_boca_job_lease(plan.attempt_id) as lease:
        effect_started = False
        committed = False
        commit_started = False
        restored = False
        candidate: str | None = None
        worker: str | None = None
        final_status: CleanupStatus = "NO_GO"
        try:
            backend.attest_original(plan, lease)
            effect_started = True
            backend.stage(plan, lease)
            worker = backend.prepare_worker(plan, lease)
            if not _DIGEST.fullmatch(worker) or worker == plan.legacy_id:
                raise CutoverError("cutover A worker identity untrusted")
            backend.park_original(plan, lease)
            # Mandatory Option B boundary: legacy DB ledger remains 0001-0007.
            backend.bootstrap_owner_session(plan, lease)
            candidate = backend.activate_candidate(plan, worker, lease)
            if not _DIGEST.fullmatch(candidate) or candidate in (worker, plan.legacy_id):
                raise CutoverError("cutover A candidate identity untrusted")
            backend.accept_candidate(plan, candidate, worker, lease)
            commit_started = True
            backend.retire_original(plan, candidate, worker, lease)
            committed = True
        except BaseException as exc:
            # Fail closed; only backend's independent exact-ID reinspection may
            # report positive recovery.  Never guess what a lost Docker receipt did.
            if effect_started and not commit_started:
                try:
                    restored = backend.recover_original(plan, lease) is True
                except Exception:
                    restored = False
            if not isinstance(exc, Exception):
                # Cancellation/SystemExit cannot become a successful receipt.
                # The finally postflight still executes before propagation.
                raise
        finally:
            if effect_started:
                try:
                    final_status = backend.finalize(
                        plan,
                        commit_started=commit_started,
                        candidate_id=candidate,
                        worker_id=worker,
                        lease=lease,
                    )
                except Exception:
                    final_status = "NO_GO"
                if final_status not in ("ACCEPT", "NO_GO", "INDETERMINATE"):
                    final_status = "NO_GO"
        state: Literal["ACCEPTED", "RECOVERED", "NO_GO"] = "NO_GO"
        if final_status == "ACCEPT" and committed:
            state = "ACCEPTED"
        elif final_status == "ACCEPT" and restored and not commit_started:
            state = "RECOVERED"
        receipt = CutoverReceipt(
            plan.attempt_id, state, final_status, restored, commit_started, candidate, worker
        )
        # O_EXCL result must be persisted *before releasing the SAME flock*.
        # Callers cannot safely write it after run_cutover_a returns. Missing
        # or failed sink never yields a successful physical receipt.
        if terminal_sink is not None:
            terminal_sink(plan, receipt, lease)
        return receipt
