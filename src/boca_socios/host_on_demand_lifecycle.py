"""One authenticated owner intent, one rootless Boca lease, the existing legacy ledger."""

from __future__ import annotations

import errno
import hashlib
import os
import re
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
from typing import Literal, Protocol, cast
from uuid import UUID, uuid5

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_lifecycle as lifecycle
from boca_socios import host_first_deploy as deploy
from boca_socios import host_lifecycle_rootless_adapter as adapter
from boca_socios.host_boca_cleanup import (
    BocaJobLease,
    protected_boca_job_lease,
    verify_protected_boca_job_lease,
)
from boca_socios.host_cutover_ipc_probe import verify_controller_peer
from boca_socios.integration.engine_socket import EngineReceipt
from boca_socios.panel.lifecycle_intents import LifecycleIntentStore, LifecycleStatus, host_marker
from boca_socios.worker_start_capture import (
    CaptureFailure,
    CaptureResult,
    attach_output,
    is_capture_result,
)

Final = Literal["APPLIED", "REFUSED", "FAILED", "UNCERTAIN"]
Stopped = Literal["created", "exited"]
_TERMINAL = frozenset({"APPLIED", "REFUSED", "FAILED", "UNCERTAIN"})
_PHASES = frozenset(
    {
        "read",
        "claim",
        "arm",
        "eligible",
        "note",
        "witness",
        "stopped",
        "APPLIED",
        "REFUSED",
        "FAILED",
        "UNCERTAIN",
    }
)
_NO_DETAIL = "NONE|-|-|-"
_ISSUES = frozenset(
    {
        "NONE",
        "CANCELLED",
        "CLAIM_INTERRUPTED",
        "NO_STOP_PROOF",
        "PRESTATE",
        "WORKER_START",
        "CAPTURE_PREFLIGHT",
        "HEALTH_EXITED",
        "HEALTH_UNHEALTHY",
        "HEALTH_WAIT",
        "HEALTH_TIMEOUT",
        "IPC_UNVERIFIED",
        "ENGINE_UNVERIFIED",
        "WORKER_STOP",
        "POSTSTATE",
        "TRANSPORT",
    }
)
_SIGNATURE = re.compile(
    r"(?:UNKNOWN|EMPTY|PRESENT_UNCLASSIFIED)\.(?:UNKNOWN|EXITED|DEAD|OTHER)\.(?:UNKNOWN|EARLY_LT_5S|LATE_GE_5S)\.(?:UNKNOWN|RAN|NOT_RUN)\Z"
)
_FINGERPRINT = re.compile(r"[a-f0-9]{64}\Z")
_STOP_NAMESPACE = UUID("9737273d-deec-451c-bade-28259e2263ed")
_AUDIT = "boca_demand_v1_"
_WITNESSES = frozenset({"OFF_OFF", "OFF_ON", "ON_OFF", "ON_ON", "UNKNOWN"})


class OnDemandUnavailable(RuntimeError):
    """The request, installed coordinates or a durable receipt could not be verified."""


def _uuid(value: str) -> bool:
    try:
        ident = UUID(value)
    except (TypeError, ValueError, AttributeError):
        return False
    return ident.version == 4 and str(ident) == value


@dataclass(frozen=True, slots=True)
class OnDemandInstallation:
    installation_run_id: str
    source_sha: str
    controller_id: str
    controller_image: str
    worker_id: str
    worker_image: str
    database_path: Path
    pair: adapter.ReviewedInstalledPair

    def coordinates(self, operation_id: str) -> lifecycle.LifecycleHostCoordinates:
        if not _uuid(operation_id) or not isinstance(self.pair, adapter.ReviewedInstalledPair):
            raise OnDemandUnavailable("invalid Boca owner operation")
        self.pair.require()
        if self.installation_run_id != self.pair.original_browser_attempt:
            raise OnDemandUnavailable("Boca installation attempt differs")
        # STOP observes the pair even when the worker is still CREATED/failed.
        value = lifecycle.LifecycleHostCoordinates(
            self.installation_run_id,
            operation_id,
            "bot",
            "stop",
            self.source_sha,
            self.controller_id,
            self.controller_image,
            self.worker_id,
            self.worker_image,
            self.database_path,
        )
        value.validate()
        return value

    def fingerprint(self) -> str:
        pins = (
            self.installation_run_id,
            self.source_sha,
            self.controller_id,
            self.controller_image,
            self.worker_id,
            self.worker_image,
            self.pair.controller_config_hash,
            self.pair.worker_config_hash,
            self.pair.sender_id,
            self.pair.sender_config_hash,
            self.pair.sender_attempt_id,
            str(int(self.pair.sender_running)),
            str(self.database_path),
        )
        return hashlib.sha256("\n".join(pins).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class OnDemandReceipt:
    operation_id: str
    status: Final
    cause: str = "NONE"
    exit_code: int | None = None
    oom: bool | None = None
    exit_signature: str | None = None


class WorkerStartFailure(Exception):
    """Only a predeclared class and closed Docker state fields can reach SQLite."""

    def __init__(
        self,
        cause: str,
        *,
        exit_code: int | None = None,
        oom: bool | None = None,
        exit_signature: str | None = None,
    ) -> None:
        super().__init__("Boca worker lifecycle failure")
        self.cause = (
            cause
            if type(cause) is str and (cause in _ISSUES or is_capture_result(cause))
            else "TRANSPORT"
        )
        self.exit_code = exit_code if type(exit_code) is int and 0 <= exit_code <= 255 else None
        self.oom = oom if type(oom) is bool else None
        self.exit_signature = (
            exit_signature
            if type(exit_signature) is str and _SIGNATURE.fullmatch(exit_signature)
            else None
        )

    def encode(self) -> str:
        return "|".join(
            (
                self.cause,
                "-" if self.exit_code is None else str(self.exit_code),
                "-" if self.oom is None else "1" if self.oom else "0",
                self.exit_signature or "-",
            )
        )


def _detail(value: str) -> WorkerStartFailure:
    parts = value.split("|")
    if len(parts) != 4 or parts[1] != "-" and not re.fullmatch(r"[0-9]{1,3}", parts[1]):
        raise OnDemandUnavailable("invalid Boca categorical receipt")
    evidence = WorkerStartFailure(
        parts[0],
        exit_code=None if parts[1] == "-" else int(parts[1]),
        oom=None if parts[2] == "-" else parts[2] == "1",
        exit_signature=None if parts[3] == "-" else parts[3],
    )
    if evidence.encode() != value:
        raise OnDemandUnavailable("invalid Boca categorical receipt")
    return evidence


@dataclass(frozen=True, slots=True)
class _State:
    target: str
    status: str
    current: bool
    detail: str
    allowed: bool = True

    def receipt(self, operation_id: str) -> OnDemandReceipt:
        if self.status not in _TERMINAL:
            raise OnDemandUnavailable("Boca terminal receipt not present")
        details = _detail(self.detail)
        return OnDemandReceipt(
            operation_id,
            cast(Final, self.status),
            details.cause,
            details.exit_code,
            details.oom,
            details.exit_signature,
        )

    def wire(self) -> str:
        return " ".join(
            (self.target, self.status, str(int(self.current)), self.detail, str(int(self.allowed)))
        )

    @classmethod
    def read(cls, raw: str) -> _State:
        if len(raw) > 256:
            raise OnDemandUnavailable("Boca ledger receipt too large")
        parts = raw.removesuffix("\n").split(" ")
        if (
            len(parts) != 5
            or parts[0] not in ("start", "stop")
            or parts[1] not in {"REQUESTED", "CLAIMED", *_TERMINAL}
            or parts[2] not in ("0", "1")
            or parts[4] not in ("0", "1")
        ):
            raise OnDemandUnavailable("Boca ledger receipt invalid")
        _detail(parts[3])
        return cls(parts[0], parts[1], parts[2] == "1", parts[3], parts[4] == "1")


def _validate_command(operation: str, installation: str, phase: str, arg: str) -> None:
    if not _uuid(operation) or not _FINGERPRINT.fullmatch(installation) or phase not in _PHASES:
        raise OnDemandUnavailable("Boca ledger command unverified")
    if phase == "note":
        _detail(arg)
    elif phase == "witness":
        if arg not in _WITNESSES:
            raise OnDemandUnavailable("invalid Boca state witness")
    elif phase in ("stopped", "arm", "eligible"):
        if not _FINGERPRINT.fullmatch(arg) and not (
            phase in ("arm", "eligible") and arg == "created"
        ):
            raise OnDemandUnavailable("invalid Boca stopped-worker certificate")
    elif arg != "-":
        raise OnDemandUnavailable("unexpected Boca ledger argument")


def _marker_id(operation: str, installation: str, purpose: str) -> str:
    return str(uuid5(UUID(operation), f"boca-demand-v1:{installation}:{purpose}"))


def _transact(path: Path, operation: str, installation: str, phase: str, arg: str = "-") -> _State:
    """A single compare-and-append in the SAME controller database as WebAuthn intents."""
    _validate_command(operation, installation, phase, arg)

    def key(purpose: str) -> str:
        return _marker_id(operation, installation, purpose)

    with lifecycle._controller_ledger(path) as db, db:
        current = LifecycleIntentStore._current(db)
        item = LifecycleIntentStore.for_operation(db, operation)
        if not item or item.component != "bot" or not item.on_demand:
            raise OnDemandUnavailable("authenticated Boca bot request absent")
        latest = current is not None and current.operation_id == operation
        bound = db.execute(
            "SELECT action FROM audit_events WHERE audit_id=?", (key("binding"),)
        ).fetchone()
        if item.status != "REQUESTED" and bound != (_AUDIT + "bound",):
            raise OnDemandUnavailable("Boca request belongs to another installation")

        def append(audit_id: str, action: str) -> None:
            db.execute("INSERT INTO audit_events(audit_id,action) VALUES (?,?)", (audit_id, action))

        allowed = True
        if phase == "claim" and item.status == "REQUESTED":
            if not latest:
                raise OnDemandUnavailable("Boca request superseded before claim")
            append(*host_marker(operation, "bot", item.target, "CLAIMED"))
            append(key("binding"), _AUDIT + "bound")
        elif phase != "read":
            if item.status != "CLAIMED":
                raise OnDemandUnavailable("Boca request already claimed or completed")
            if phase in ("eligible", "arm"):
                armed = db.execute(
                    "SELECT 1 FROM audit_events WHERE audit_id=?", (key("armed"),)
                ).fetchone()
                if not latest or item.target != "start" or armed:
                    allowed = False
                elif arg != "created":
                    # A clean STOP certificate binds the exact installed ID and Docker
                    # execution timestamps. A stopped/failed container alone grants nothing.
                    cert = str(uuid5(_STOP_NAMESPACE, installation + ":stop:" + arg))
                    consumed = str(uuid5(_STOP_NAMESPACE, installation + ":spend:" + arg))
                    origin = db.execute(
                        "SELECT action FROM audit_events WHERE audit_id=?", (cert,)
                    ).fetchone()
                    if not origin or not origin[0].startswith(_AUDIT + "stopped_"):
                        allowed = False
                    else:
                        owner = origin[0].removeprefix(_AUDIT + "stopped_")
                        proof = LifecycleIntentStore.for_operation(db, owner)
                        match = db.execute(
                            "SELECT action FROM audit_events WHERE audit_id=?",
                            (_marker_id(owner, installation, "binding"),),
                        ).fetchone()
                        allowed = bool(
                            proof
                            and proof.component == "bot"
                            and proof.on_demand
                            and proof.status in ("APPLIED", "FAILED")
                            and match == (_AUDIT + "bound",)
                            and not db.execute(
                                "SELECT 1 FROM audit_events WHERE audit_id=?", (consumed,)
                            ).fetchone()
                        )
                    if allowed and phase == "arm":
                        append(consumed, _AUDIT + "resumed_" + operation)
                if phase == "arm" and allowed:
                    append(key("armed"), _AUDIT + "armed")
            elif phase == "stopped":
                cert = str(uuid5(_STOP_NAMESPACE, installation + ":stop:" + arg))
                append(cert, _AUDIT + "stopped_" + operation)
            elif phase in ("note", "witness"):
                append(key(phase), _AUDIT + phase + "_" + arg)
            elif phase in _TERMINAL:
                if phase == "APPLIED" and not latest:
                    allowed = False
                else:
                    append(
                        *host_marker(operation, "bot", item.target, cast(LifecycleStatus, phase))
                    )
            else:
                raise OnDemandUnavailable("Boca lifecycle transition invalid")
        updated = LifecycleIntentStore.for_operation(db, operation)
        if not updated:
            raise OnDemandUnavailable("Boca lifecycle receipt disappeared")
        note = db.execute(
            "SELECT action FROM audit_events WHERE audit_id=?", (key("note"),)
        ).fetchone()
        detail = _NO_DETAIL if not note else note[0].removeprefix(_AUDIT + "note_")
        _detail(detail)
        return _State(item.target, updated.status, latest, detail, allowed)


class OnDemandIO(Protocol):
    def observe(
        self, coordinates: lifecycle.LifecycleHostCoordinates, lease: BocaJobLease
    ) -> lifecycle.LifecycleHostSnapshot: ...
    def worker_state(self, worker_id: str) -> str: ...
    def stopped_token(self, worker_id: str) -> str: ...
    def start_worker(
        self, installation: OnDemandInstallation, state: Stopped, before_start: Callable[[], None]
    ) -> None: ...
    def verify_peer(self, controller_id: str) -> None: ...
    def engine_request(self, controller_id: str, operation: str) -> EngineReceipt: ...
    def stop_worker(self, worker_id: str) -> None: ...


class _RootlessIO(adapter.ProductionRootlessDockerIO):
    def __init__(self, installation: OnDemandInstallation) -> None:
        self._probe = adapter.RootlessLifecycleProbe(installation.pair, self, on_demand=True)

    def observe(
        self, coordinates: lifecycle.LifecycleHostCoordinates, lease: BocaJobLease
    ) -> lifecycle.LifecycleHostSnapshot:
        return self._probe.observe(coordinates, lease)

    def worker_state(self, worker_id: str) -> str:
        state = self.field("container", worker_id, "State.Status")
        pid = self.field("container", worker_id, "State.Pid")
        if (
            state not in ("running", "created", "exited")
            or type(pid) is not int
            or (pid > 0) != (state == "running")
            or pid < 0
        ):
            raise OnDemandUnavailable("Boca worker process state unverified")
        return str(state)

    def stopped_token(self, worker_id: str) -> str:
        if self.worker_state(worker_id) != "exited":
            raise OnDemandUnavailable("Boca worker has no stopped execution witness")
        first = deploy._worker_rfc3339nano_ns(self.field("container", worker_id, "State.StartedAt"))
        last = deploy._worker_rfc3339nano_ns(self.field("container", worker_id, "State.FinishedAt"))
        code = self.field("container", worker_id, "State.ExitCode")
        oom = self.field("container", worker_id, "State.OOMKilled")
        if (
            first is None
            or last is None
            or last <= first
            or type(code) is not int
            or not 0 <= code <= 255
            or oom is not False
        ):
            raise OnDemandUnavailable("Boca stopped execution witness invalid")
        return hashlib.sha256(f"{worker_id}:{first}:{last}:{code}".encode("ascii")).hexdigest()

    def start_worker(
        self, installation: OnDemandInstallation, state: Stopped, before_start: Callable[[], None]
    ) -> None:
        worker = installation.worker_id
        try:
            deploy._cutover_capture_preflight(
                worker,
                installation.worker_image,
                installation.source_sha,
                installation.installation_run_id,
                installation.pair.worker_config_hash,
                expected_state=state,
                on_demand=True,
            )
        except Exception:
            raise WorkerStartFailure("CAPTURE_PREFLIGHT") from None
        try:
            with attach_output(deploy.ROOTLESS_SOCKET, worker) as capture:
                before_start()
                try:
                    try:
                        acknowledged = deploy._run("docker", "start", worker, timeout=30) == worker
                    except deploy.PreflightError:
                        acknowledged = False
                    if not acknowledged and self.worker_state(worker) != "exited":
                        raise WorkerStartFailure("WORKER_START")
                    # A missing CLI ACK can coincide with an already exited PID.
                    # Retain that exact execution's finite capture before detaching.
                    deploy._browser_wait_healthy(worker)
                    if not acknowledged:
                        raise WorkerStartFailure("WORKER_START")
                except deploy.WorkerHealthPhaseError as exc:
                    cause = exc.phase
                    if cause == "HEALTH_EXITED":
                        try:
                            cause = CaptureResult(capture.finish()).value
                        except Exception:
                            cause = "TRANSPORT"
                    raise WorkerStartFailure(
                        cause,
                        exit_code=exc.exit_code if type(exc.exit_code) is int else None,
                        oom=exc.oom_killed if type(exc.oom_killed) is bool else None,
                        exit_signature=exc.exit_signature,
                    ) from None
                except WorkerStartFailure:
                    raise
                except Exception:
                    raise WorkerStartFailure("WORKER_START") from None
        except CaptureFailure as exc:
            raise WorkerStartFailure(exc.result.value) from None

    def verify_peer(self, controller_id: str) -> None:
        verify_controller_peer(controller_id)

    def stop_worker(self, worker_id: str) -> None:
        self.worker_action(worker_id, "stop")


@dataclass(frozen=True, slots=True)
class PanelStatus:
    operation_id: str
    target: str
    status: str
    cause: str
    exit_code: int | None
    oom: bool | None
    exit_signature: str | None


def validate_panel_status(status: PanelStatus) -> None:
    if (
        not isinstance(status, PanelStatus)
        or not _uuid(status.operation_id)
        or type(status.target) is not str
        or status.target not in ("start", "stop")
        or type(status.status) is not str
        or status.status not in {"REQUESTED", "CLAIMED", *_TERMINAL}
        or type(status.cause) is not str
        or not (is_capture_result(status.cause) or status.cause in _ISSUES)
        or status.exit_code is not None
        and (type(status.exit_code) is not int or not 0 <= status.exit_code <= 255)
        or status.oom is not None
        and type(status.oom) is not bool
        or status.exit_signature is not None
        and (
            type(status.exit_signature) is not str
            or not _SIGNATURE.fullmatch(status.exit_signature)
        )
        or status.status in ("APPLIED", "REQUESTED")
        and (
            status.cause != "NONE"
            or any(
                value is not None for value in (status.exit_code, status.oom, status.exit_signature)
            )
        )
    ):
        raise OnDemandUnavailable("invalid Boca public status")


def _status_wire(path: Path, fingerprint: str) -> str:
    if not _FINGERPRINT.fullmatch(fingerprint):
        raise OnDemandUnavailable("Boca release fingerprint required")
    with lifecycle._controller_ledger(path, readonly=True) as db:
        item = LifecycleIntentStore._current(db)
        if item is None:
            return "NONE"
        if not item.on_demand:
            if item.status in ("CLAIMED", "UNCERTAIN"):
                raise OnDemandUnavailable("unsettled Boca legacy host operation")
            return "NONE"
        if item.component != "bot" or not _uuid(item.operation_id):
            raise OnDemandUnavailable("no public on-demand request in this installation")

        def key(purpose: str) -> str:
            return _marker_id(item.operation_id, fingerprint, purpose)

        if item.status != "REQUESTED" and db.execute(
            "SELECT action FROM audit_events WHERE audit_id=?", (key("binding"),)
        ).fetchone() != (_AUDIT + "bound",):
            raise OnDemandUnavailable("Boca status belongs to another installation")
        note = db.execute(
            "SELECT action FROM audit_events WHERE audit_id=?", (key("note"),)
        ).fetchone()
        detail = note[0].removeprefix(_AUDIT + "note_") if note else _NO_DETAIL
        _detail(detail)
        return " ".join((item.operation_id, item.target, item.status, detail))


def _controller_command(controller_id: str, *args: str) -> str:
    if not _FINGERPRINT.fullmatch(controller_id):
        raise OnDemandUnavailable("exact Boca controller ID required")
    return cleanup._docker(
        "exec",
        "--user",
        "10001:10001",
        controller_id,
        "/app/.venv/bin/python",
        "-I",
        "-B",
        "-m",
        "boca_socios.host_on_demand_lifecycle",
        *args,
    )


def read_panel_status(installation: OnDemandInstallation) -> PanelStatus | None:
    """Called only after the read-only host operation has attested this pinned pair."""
    installation.coordinates("00000000-0000-4000-8000-000000000001")
    raw = _controller_command(
        installation.controller_id, "status", installation.fingerprint()
    ).removesuffix("\n")
    if raw == "NONE":
        return None
    if len(raw) > 256:
        raise OnDemandUnavailable("invalid Boca public status size")
    parts = raw.split(" ")
    if len(parts) != 4 or not _uuid(parts[0]):
        raise OnDemandUnavailable("invalid Boca public status")
    status = _State.read(" ".join((parts[1], parts[2], "1", parts[3], "1")))
    evidence = _detail(status.detail)
    result = PanelStatus(
        parts[0],
        status.target,
        status.status,
        evidence.cause,
        evidence.exit_code,
        evidence.oom,
        evidence.exit_signature,
    )
    validate_panel_status(result)
    return result


class _Transaction:
    def __init__(
        self,
        operation: str,
        installation: OnDemandInstallation,
        io: OnDemandIO | None,
        lease: BocaJobLease,
    ) -> None:
        self.coords = installation.coordinates(operation)
        self.install = installation
        self.lease = lease
        self.production = io is None
        self.io: OnDemandIO = _RootlessIO(installation) if io is None else io
        self.fp = installation.fingerprint()
        self.attempted = False
        self.phase = "PRESTATE"

    def transact(self, phase: str, arg: str = "-") -> _State:
        verify_protected_boca_job_lease(self.lease, self.coords.attempt_id)
        _validate_command(self.coords.request_id, self.fp, phase, arg)
        if self.production:
            raw = _controller_command(
                self.coords.controller_id, "ledger", self.coords.request_id, self.fp, phase, arg
            )
            return _State.read(raw)
        return _transact(self.coords.database_path, self.coords.request_id, self.fp, phase, arg)

    def observe(self) -> lifecycle.LifecycleHostSnapshot:
        verify_protected_boca_job_lease(self.lease, self.coords.attempt_id)
        state = self.io.observe(self.coords, self.lease)
        state.require(self.coords)
        return state

    def fence(self) -> None:
        current = self.transact("read")
        if not current.current or current.status != "CLAIMED":
            raise WorkerStartFailure("CANCELLED")

    def engine(self, target: str) -> None:
        self.phase = "ENGINE_UNVERIFIED"
        self.attempted = True
        receipt = self.io.engine_request(self.coords.controller_id, target)
        expected = "RUNNING" if target == "start" else "STOPPED"
        if (
            not isinstance(receipt, EngineReceipt)
            or receipt.state != expected
            or receipt.changed is not True
        ):
            raise WorkerStartFailure(self.phase)

    def off(self) -> None:
        before = self.observe()
        if before.bot_engine_running:
            self.engine("stop")
            before = self.observe()
        if before.bot_engine_running is not False:
            raise WorkerStartFailure("ENGINE_UNVERIFIED")
        if before.worker_running:
            self.phase = "WORKER_STOP"
            self.attempted = True
            self.io.stop_worker(self.coords.worker_id)
            stopped = self.observe()
            if stopped.worker_running or stopped.bot_engine_running is not False:
                raise WorkerStartFailure("POSTSTATE")
            self.transact("stopped", self.io.stopped_token(self.coords.worker_id))
        # A successful no-op STOP also needs a live panel and BOTH components off.
        after = self.observe()
        if after.bot_engine_running is not False or after.worker_running:
            raise WorkerStartFailure("POSTSTATE")

    def on(self, before: lifecycle.LifecycleHostSnapshot) -> None:
        if before.bot_engine_running is not False or before.worker_running:
            raise WorkerStartFailure("PRESTATE")
        state = self.io.worker_state(self.coords.worker_id)
        if state not in ("created", "exited"):
            raise WorkerStartFailure("PRESTATE")
        token = "created" if state == "created" else self.io.stopped_token(self.coords.worker_id)

        if state == "exited" and not self.transact("eligible", token).allowed:
            raise WorkerStartFailure("NO_STOP_PROOF")

        def armed() -> None:
            # Called by the active attach reader before sending the Docker start.
            self.fence()
            if state == "exited" and self.io.stopped_token(self.coords.worker_id) != token:
                raise WorkerStartFailure("NO_STOP_PROOF")
            permission = self.transact("arm", token)
            if not permission.allowed:
                raise WorkerStartFailure("NO_STOP_PROOF" if permission.current else "CANCELLED")
            self.attempted = True

        self.phase = "WORKER_START"
        self.io.start_worker(self.install, cast(Stopped, state), armed)
        self.fence()
        ready = self.observe()
        if not (
            self.attempted
            and ready.worker_running
            and ready.worker_healthy
            and ready.bot_engine_running is False
        ):
            raise WorkerStartFailure("HEALTH_WAIT")
        self.phase = "IPC_UNVERIFIED"
        self.io.verify_peer(self.coords.controller_id)
        self.fence()
        # Motor recovery itself needs SQLite writes; no SQLite writer is held
        # over this bounded IPC operation. A racing STOP invalidates the ACK.
        self.engine("start")
        self.fence()
        after = self.observe()
        if not (after.bot_engine_running and after.worker_running and after.worker_healthy):
            raise WorkerStartFailure("POSTSTATE")

    def run(self) -> OnDemandReceipt:
        # Attest inventory/mount to pinned controller before opening its private DB.
        before = self.observe()
        state = self.transact("read")
        if state.status in _TERMINAL:
            return state.receipt(self.coords.request_id)
        if state.status == "CLAIMED":
            # A previous process died after its durable claim. No automatic replay.
            if state.detail == _NO_DETAIL:
                self.transact("note", WorkerStartFailure("CLAIM_INTERRUPTED").encode())
            return self.transact("UNCERTAIN").receipt(self.coords.request_id)
        state = self.transact("claim")
        try:
            self.fence()
            if state.target == "start":
                self.on(before)
            else:
                self.off()
        except Exception as exc:
            failure = exc if isinstance(exc, WorkerStartFailure) else WorkerStartFailure(self.phase)
        else:
            # A lost response can follow a committed ACK. Read before deciding.
            # Never compensate an already APPLIED operation or replay its effects.
            try:
                final = self.transact("APPLIED")
            except Exception:
                final = self.transact("read")
                if final.status == "CLAIMED" and final.current:
                    return self.transact("UNCERTAIN").receipt(self.coords.request_id)
            if final.status in _TERMINAL:
                return final.receipt(self.coords.request_id)
            failure = WorkerStartFailure("CANCELLED")
        # Preserve a closed classification and physical pre-compensation state under
        # this UUID even after STOP superseded it. No raw stderr/Env reaches SQLite.
        try:
            self.transact("note", failure.encode())
            try:
                witness = self.observe()
                bits = (
                    "ON" if witness.bot_engine_running else "OFF",
                    "ON" if witness.worker_running else "OFF",
                )
                observed = "_".join(bits)
            except Exception:
                observed = "UNKNOWN"
            self.transact("witness", observed)
            recorded = True
        except Exception:
            recorded = False
        status: Final = "REFUSED"
        if self.attempted:
            status = "UNCERTAIN"
            try:
                if state.target == "start":
                    self.off()
                idle = self.observe()
                if idle.bot_engine_running is False and not idle.worker_running and recorded:
                    status = "FAILED"
            except Exception:
                status = "UNCERTAIN"  # A STOP with a lost confirmation cannot be replayed.
        elif not recorded:
            status = "UNCERTAIN"
        return self.transact(status).receipt(self.coords.request_id)


def apply_panel_request(
    operation_id: str,
    installation: OnDemandInstallation,
    *,
    io: OnDemandIO | None = None,
    lease_factory: Callable[[str], AbstractContextManager[BocaJobLease]] = protected_boca_job_lease,
) -> OnDemandReceipt:
    """Process this UUID only. Never create an owner request, retry an effect, or stop the panel."""
    try:
        if not isinstance(installation, OnDemandInstallation):
            raise OnDemandUnavailable("Boca installed release required")
        installation.coordinates(operation_id)
        with ExitStack() as scope:
            # Accept=yes spawns independent one-shots. STOP is already durable
            # while START owns the cooperative Boca lock. Wait only on a real
            # flock contention and only BEFORE opening the first transaction.
            deadline = monotonic() + 180
            while True:
                try:
                    lease = scope.enter_context(lease_factory(installation.installation_run_id))
                    break
                except cleanup.CleanupError as exc:
                    cause = exc.__cause__
                    if (
                        not isinstance(cause, BlockingIOError)
                        or cause.errno != errno.EAGAIN
                        or monotonic() >= deadline
                    ):
                        raise
                    sleep(0.25)
            return _Transaction(operation_id, installation, io, lease).run()
    except Exception:
        # Docker/stdio/SQLite details can contain confidential host paths.
        raise OnDemandUnavailable("Boca on-demand physical receipt unavailable") from None


def main(argv: list[str] | None = None) -> int:
    """Fixed in-controller ledger RPC; runs inside the attested controller UID namespace."""
    args = sys.argv[1:] if argv is None else argv
    if os.geteuid() != 10001 or os.getegid() != 10001:
        return 3
    path = Path("/data/boca.sqlite3")
    try:
        if args == ["ready"]:
            with lifecycle._controller_ledger(path, readonly=True):
                pass
            print("BOCA_LEDGER_READY")
        elif len(args) == 2 and args[0] == "status":
            print(_status_wire(path, args[1]))
        elif len(args) == 5 and args[0] == "ledger":
            print(_transact(path, args[1], args[2], args[3], args[4]).wire())
        else:
            return 3
    except Exception:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
