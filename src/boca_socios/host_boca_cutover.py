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
from typing import Literal, Protocol, get_args

from boca_socios.host_boca_cleanup import BocaJobLease, CleanupReceipt, protected_boca_job_lease
from boca_socios.worker_start_capture import is_capture_result

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[1-9][0-9]{0,19}\Z")
_OWNER = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_CONTROLLER_IMAGE = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_WORKER_IMAGE = re.compile(
    r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z"
)
CleanupStatus = Literal["ACCEPT", "NO_GO", "INDETERMINATE"]
CutoverPhase = Literal[
    "NONE",
    "ATTEST_ORIGINAL",
    "CONSUME_PREPARE",
    "STAGE",
    "PREPARE_WORKER",
    "PARK_ORIGINAL",
    "BOOTSTRAP_SESSION",
    "ACTIVATE_CANDIDATE",
    "ACCEPT_CANDIDATE",
    "RETIRE_ORIGINAL",
    "FINALIZE",
]
CUTOVER_FAILURE_PHASES: frozenset[str] = frozenset(get_args(CutoverPhase)) - {"NONE"}
WORKER_PRIMARY_PHASES: frozenset[str] = frozenset(
    {
        "ATTEST",
        "STORAGE",
        "PULL",
        "IPC",
        "CREATE",
        "CAPTURE_PREPARE",
        "START",
        "HEALTH",
        "HEALTH_WAIT",
        "HEALTH_EXITED",
        "HEALTH_UNHEALTHY",
        "HEALTH_TIMEOUT",
        "HEALTH_POSTFLIGHT",
        "UNVERIFIED",
    }
)
WORKER_COMPENSATION_STATES: frozenset[str] = frozenset({"VERIFIED", "INDETERMINATE", "UNVERIFIED"})


def valid_worker_exit_evidence(primary: object, exit_code: object, oom_killed: object) -> bool:
    """Only typed Docker ExitCode/OOMKilled, never Python bool-as-int or raw inspect."""
    return (
        primary == "HEALTH_EXITED"
        and (type(exit_code) is int and 0 <= exit_code <= 255 or exit_code == "UNKNOWN")
        and (type(oom_killed) is bool or oom_killed == "UNKNOWN")
    )


_WORKER_EXIT_SIGNATURE = re.compile(
    r"(?:EMPTY|PRESENT_UNCLASSIFIED|UNKNOWN)\."
    r"(?:EXITED|DEAD|OTHER|UNKNOWN)\."
    r"(?:EARLY_LT_5S|LATE_GE_5S|UNKNOWN)\."
    r"(?:NOT_RUN|RAN|UNKNOWN)\Z"
)


def valid_worker_exit_signature(value: object) -> bool:
    """A finite, four-part fingerprint, never Docker strings or BLACKBOX text."""
    return type(value) is str and _WORKER_EXIT_SIGNATURE.fullmatch(value) is not None


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
            # The old and new controller may legitimately use identical
            # Compose bytes across distinct source/image releases.  Keep
            # unrelated overlay/seccomp evidence independently identifiable.
            or len({self.target_compose_sha, self.overlay_sha, self.seccomp_sha}) != 3
            or self.legacy_compose_sha in (self.overlay_sha, self.seccomp_sha)
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
    cleanup_receipt: CleanupReceipt | None = None
    # A redacted diagnostic only, never evidence of physical acceptance.
    failed_phase: CutoverPhase = "NONE"
    worker_primary_phase: str = "NONE"
    worker_compensation: str = "NONE"
    worker_exit_code: int | Literal["UNKNOWN"] | None = None
    worker_oom_killed: bool | Literal["UNKNOWN"] | None = None
    worker_exit_signature: str | None = None
    worker_stderr_observation: str | None = None
    idle_installed: bool = False

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
    ) -> CleanupStatus | CleanupReceipt: ...


TerminalSink = Callable[[CutoverPlan, CutoverReceipt, BocaJobLease], None]
TerminalPreflight = Callable[[CutoverPlan, BocaJobLease], None]
PreparedGoConsumer = Callable[[CutoverPlan, str, BocaJobLease], None]


def run_cutover_a(
    plan: CutoverPlan,
    *,
    backend: CutoverBackend,
    terminal_sink: TerminalSink | None = None,
    terminal_preflight: TerminalPreflight | None = None,
    prepare_run_id: str | None = None,
    prepared_go_consumer: PreparedGoConsumer | None = None,
) -> CutoverReceipt:
    """Unit-testable sequencing only; no concrete backend or host CLI exists.

    A single lease spans all effects and the unconditional postflight.  The
    irreversible old-ID retirement is intentionally last.  Once it *starts*,
    a lost receipt must not trigger an unsafe revival over localhost:8443.
    A hard SSH/runner loss yields no receipt; a future Actions ``if: always()``
    assertion must make that NO_GO.  Synthetic tests cannot confer host GO.
    """
    plan.validate()  # No host operation for malformed coordinates.
    if prepare_run_id is not None:
        if (
            type(prepare_run_id) is not str
            or _ATTEMPT.fullmatch(prepare_run_id) is None
            or prepare_run_id == plan.attempt_id
            or prepared_go_consumer is None
        ):
            raise CutoverError("prepared cutover GO consumer or identity unavailable")
    elif prepared_go_consumer is not None:
        raise CutoverError("prepared GO consumer without approved PREPARE identity")
    if getattr(type(backend), "requires_persistent_receipt", False) is True and (
        terminal_sink is None or terminal_preflight is None
    ):
        raise CutoverError("effectful Boca backend requires durable terminal intent and result")
    with protected_boca_job_lease(plan.attempt_id) as lease:
        if terminal_sink is not None:
            if terminal_preflight is None:
                raise CutoverError(
                    "persistent terminal destination must be prepared before effects"
                )
            # The single protected process reserves an O_EXCL persistent
            # intent and validates storage BEFORE any Docker read/write phase.
            terminal_preflight(plan, lease)
        elif terminal_preflight is not None:
            raise CutoverError("terminal intent without a matching result sink forbidden")
        effect_started = False
        committed = False
        commit_started = False
        restored = False
        candidate: str | None = None
        worker: str | None = None
        final_status: CleanupStatus = "NO_GO"
        final_evidence: CleanupReceipt | None = None
        phase: CutoverPhase = "ATTEST_ORIGINAL"
        failed_phase: CutoverPhase = "NONE"
        worker_primary_phase = "NONE"
        worker_compensation = "NONE"
        worker_exit_code: int | Literal["UNKNOWN"] | None = None
        worker_oom_killed: bool | Literal["UNKNOWN"] | None = None
        worker_exit_signature: str | None = None
        worker_stderr_observation: str | None = None
        try:
            backend.attest_original(plan, lease)
            # PREPARE consumption is durable under the SAME flock, strictly
            # after exact rootless/container attestation and BEFORE stage/pull/
            # stop/SQLite. A failed/ambiguous O_EXCL marker aborts all effects.
            if prepare_run_id is not None:
                assert prepared_go_consumer is not None
                phase = "CONSUME_PREPARE"
                prepared_go_consumer(plan, prepare_run_id, lease)
            effect_started = True
            phase = "STAGE"
            backend.stage(plan, lease)
            phase = "PREPARE_WORKER"
            worker = backend.prepare_worker(plan, lease)
            if not _DIGEST.fullmatch(worker) or worker == plan.legacy_id:
                raise CutoverError("cutover A worker identity untrusted")
            phase = "PARK_ORIGINAL"
            backend.park_original(plan, lease)
            # Mandatory Option B boundary: legacy DB ledger remains 0001-0007.
            phase = "BOOTSTRAP_SESSION"
            backend.bootstrap_owner_session(plan, lease)
            phase = "ACTIVATE_CANDIDATE"
            candidate = backend.activate_candidate(plan, worker, lease)
            if not _DIGEST.fullmatch(candidate) or candidate in (worker, plan.legacy_id):
                raise CutoverError("cutover A candidate identity untrusted")
            phase = "ACCEPT_CANDIDATE"
            backend.accept_candidate(plan, candidate, worker, lease)
            commit_started = True
            phase = "RETIRE_ORIGINAL"
            backend.retire_original(plan, candidate, worker, lease)
            committed = True
        except BaseException as exc:
            failed_phase = phase
            # Fixed enum-only diagnostic. Exception messages and Docker output
            # must never enter persistent receipts or Actions stdout.
            if phase == "PREPARE_WORKER":
                primary = getattr(exc, "primary", None)
                compensation = getattr(exc, "compensation", None)
                if (
                    type(primary) is str
                    and primary in WORKER_PRIMARY_PHASES
                    and type(compensation) is str
                    and compensation in WORKER_COMPENSATION_STATES
                ):
                    worker_primary_phase = primary
                    worker_compensation = compensation
                    maybe_exit = getattr(exc, "exit_code", None)
                    maybe_oom = getattr(exc, "oom_killed", None)
                    if valid_worker_exit_evidence(primary, maybe_exit, maybe_oom):
                        worker_exit_code = maybe_exit
                        worker_oom_killed = maybe_oom
                        maybe_signature = getattr(exc, "exit_signature", None)
                        if valid_worker_exit_signature(maybe_signature):
                            worker_exit_signature = maybe_signature
                            observation = getattr(exc, "capture_result", None)
                            captured_id = getattr(exc, "capture_worker_id", None)
                            if (
                                getattr(exc, "capture_recorded", False) is True
                                and type(captured_id) is str
                                and _DIGEST.fullmatch(captured_id)
                                and captured_id != plan.legacy_id
                                and is_capture_result(observation)
                            ):
                                worker_stderr_observation = observation
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
                    phase = "FINALIZE"
                    result = backend.finalize(
                        plan,
                        commit_started=commit_started,
                        candidate_id=candidate,
                        worker_id=worker,
                        lease=lease,
                    )
                    if isinstance(result, CleanupReceipt):
                        if result.attempt_id != plan.attempt_id:
                            final_status = "NO_GO"
                        else:
                            final_status = result.status
                            final_evidence = result
                    else:
                        final_status = result
                except Exception:
                    if failed_phase == "NONE":
                        failed_phase = "FINALIZE"
                    final_status = "NO_GO"
                if final_status not in ("ACCEPT", "NO_GO", "INDETERMINATE"):
                    final_status = "NO_GO"
                if (
                    getattr(type(backend), "requires_persistent_receipt", False) is True
                    and final_status == "ACCEPT"
                    and final_evidence is None
                ):
                    final_status = "NO_GO"
                if final_status != "ACCEPT" and failed_phase == "NONE":
                    failed_phase = "FINALIZE"
        state: Literal["ACCEPTED", "RECOVERED", "NO_GO"] = "NO_GO"
        if final_status == "ACCEPT" and committed:
            state = "ACCEPTED"
        elif final_status == "ACCEPT" and restored and not commit_started:
            state = "RECOVERED"
        receipt = CutoverReceipt(
            plan.attempt_id,
            state,
            final_status,
            restored,
            commit_started,
            candidate,
            worker,
            final_evidence,
            failed_phase if state != "ACCEPTED" else "NONE",
            worker_primary_phase if state != "ACCEPTED" else "NONE",
            worker_compensation if state != "ACCEPTED" else "NONE",
            worker_exit_code if state != "ACCEPTED" else None,
            worker_oom_killed if state != "ACCEPTED" else None,
            worker_exit_signature if state != "ACCEPTED" else None,
            worker_stderr_observation if state != "ACCEPTED" else None,
            state == "ACCEPTED" and getattr(backend, "idle_installed", False) is True,
        )
        # O_EXCL result must be persisted *before releasing the SAME flock*.
        # Callers cannot safely write it after run_cutover_a returns. Missing
        # or failed sink never yields a successful physical receipt.
        if terminal_sink is not None:
            terminal_sink(plan, receipt, lease)
        return receipt
