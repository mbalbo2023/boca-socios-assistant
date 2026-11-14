"""Private, read-only, fixed-label worker and Chromium activity projection.

No Docker daemon, stdout, URLs, member identity or raw SQLite action may reach
this view. Persisted receipts and worker-emitted stages retain distinct sources.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

from boca_socios.browser.activity_events import read_chromium_events
from boca_socios.panel.lifecycle_intents import (
    AUTOMATIC_CHECK_PREFIX,
    LifecycleIntent,
    LifecycleIntentStore,
    LifecycleStorageUnavailable,
    _db_identity,
    automatic_check_marker,
    canonical_operation_id,
    host_marker,
)
from boca_socios.queue import QueueSnapshot
from boca_socios.storage.database import Database

if TYPE_CHECKING:
    from boca_socios.queue.private_pass_monitor import TokenObservationActivity


class WorkerActivityUnavailable(RuntimeError):
    """Private status facts cannot be read consistently; redact the cause."""


Source = Literal["owner", "host", "simulation", "chromium"]
Level = Literal["progress", "success", "warning", "error"]


@dataclass(frozen=True, slots=True)
class WorkerActivityEvent:
    at: str
    source: Source
    level: Level
    message: str


@dataclass(frozen=True, slots=True)
class WorkerActivitySnapshot:
    observed_at: str
    browser_detail: Literal["fixed_stages_only"]
    chromium_telemetry: Literal["available", "missing", "degraded"]
    events: tuple[WorkerActivityEvent, ...]


_CHROMIUM_STAGE_LABELS: dict[str, tuple[Level, str]] = {
    "launch_requested": ("progress", "Chromium: solicitada la apertura del navegador aislado."),
    "launched": ("success", "Chromium: proceso del navegador creado."),
    "context_ready": ("progress", "Chromium: contexto aislado preparado."),
    "page_ready": ("success", "Chromium: página sintética preparada."),
    "context_closed": ("progress", "Chromium: contexto aislado cerrado."),
    "browser_closed": ("success", "Chromium: navegador cerrado."),
    "operation_failed": ("error", "Chromium: operación interrumpida; revisar recibo del host."),
}

_SIMULATION_LABELS: dict[str, tuple[Level, str]] = {
    "accepted": ("progress", "Simulación local: solicitud admitida, a la espera del motor."),
    "running": ("progress", "Simulación local: ejecución iniciada, resultado pendiente."),
    "stop_requested": ("warning", "Simulación local: detención solicitada."),
    "stopped": ("success", "Simulación local: detención registrada."),
    "completed": ("success", "Simulación local: resultado sintético registrado."),
    "failed": ("error", "Simulación local: fallo registrado."),
    "needs_review": ("warning", "Simulación local: resultado incierto; requiere revisión."),
}

_QUEUE_PREFIX = "boca_simulation_queue_v1:"
_QUEUE_LABELS: dict[str, tuple[Level, str]] = {
    "created": ("progress", "Cola simulada: solicitud creada."),
    "prequeue": ("progress", "Cola simulada: espera previa a la apertura."),
    "waiting": ("progress", "Cola simulada: solicitud en espera."),
    "admitted": ("progress", "Cola simulada: admisión local registrada."),
    "closed": ("success", "Cola simulada: solicitud cerrada."),
    "cancelled": ("warning", "Cola simulada: solicitud cancelada."),
    "expired": ("warning", "Cola simulada: plazo local agotado."),
    "error": ("error", "Cola simulada: ejecución interrumpida."),
}
_OBSERVATION_LABELS: dict[str, tuple[Level, str]] = {
    "automatic_checking": ("progress", "Worker: detección automática en curso."),
    "automatic_observed": (
        "progress",
        "Worker: observación automática recibida; consulte el estado de evento y cola.",
    ),
    "automatic_no_event": (
        "warning",
        "La página informa ausencia de eventos; finaliza la comprobación automática.",
    ),
    "automatic_no_queue": (
        "warning",
        "La página informa cola inactiva; finaliza la comprobación automática.",
    ),
    "automatic_failed": (
        "warning",
        "La comprobación automática requiere revisión; no equivale a ausencia de evento.",
    ),
}
_AUTOMATIC_LABELS: dict[str, tuple[Level, str]] = {
    "CHECKING": ("progress", "Worker: comprobando evento y cola virtual de la sesión del titular."),
    "QUEUE_ACTIVE": (
        "progress",
        "Evento detectado: cola virtual activa; observando la misma sesión.",
    ),
    "PREQUEUE": ("progress", "Evento anunciado: prefila observada; esperando la apertura."),
    "QUEUE_INACTIVE": (
        "warning",
        "Cola virtual inactiva según la página recibida; comprobación finalizada.",
    ),
    "NO_EVENT_OBSERVED": (
        "warning",
        "La página informa que no hay eventos disponibles; comprobación finalizada.",
    ),
    "TARGET_OBSERVED": (
        "success",
        "Enlace de acceso con token recibido; disponible en el monitor privado, sin validar compra.",
    ),
    "CHALLENGE": (
        "warning",
        "La página requiere intervención; comprobación finalizada sin eludir el bloqueo.",
    ),
    "UNKNOWN": (
        "warning",
        "Página sin señales suficientes para determinar evento o cola; comprobación finalizada.",
    ),
    "CHECK_FAILED": (
        "error",
        "No se pudo completar la consulta de evento y cola; comprobación finalizada.",
    ),
}


def record_simulation_queue_stage(
    database: Database, *, command_id: str, snapshot: QueueSnapshot, at: datetime
) -> None:
    """Persist one actual queue state, bound to its running local command.

    Reuse the existing audit table without a schema migration. A state is
    recorded only after the simulator supplies it, and cannot be inferred
    from a provider token or from command completion after a restart.
    """
    canonical_operation_id(command_id)
    if snapshot.state.value not in _QUEUE_LABELS or at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("simulation queue receipt unavailable")
    action = _QUEUE_PREFIX + command_id + ":" + snapshot.state.value
    marker = str(uuid5(NAMESPACE_URL, action))
    identity = _db_identity(database.path)
    with (
        closing(
            sqlite3.connect(database.path.as_uri() + "?mode=rw", uri=True, timeout=1.0)
        ) as connection,
        connection,
    ):
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("BEGIN IMMEDIATE")
        bound = connection.execute(
            "SELECT 1 FROM beta_commands c JOIN ticket_requests t ON t.request_id=c.request_id "
            "WHERE c.command_id=? AND t.member_id=? AND t.event_id=? "
            "AND c.state IN ('running','stop_requested')",
            (command_id, snapshot.member_id, snapshot.event_id),
        ).fetchone()
        if bound != (1,):
            raise ValueError("simulation queue receipt requires its running command")
        existing = connection.execute(
            "SELECT action FROM audit_events WHERE audit_id=?", (marker,)
        ).fetchone()
        if existing is None:
            connection.execute(
                "INSERT INTO audit_events(audit_id,action,recorded_at) VALUES (?,?,?)",
                (marker, action, at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")),
            )
        elif existing != (action,):
            raise ValueError("simulation queue receipt conflicts")
        if _db_identity(database.path) != identity:
            raise ValueError("simulation queue receipt storage changed")


def _at_sqlite(value: object) -> str:
    if type(value) is not str or len(value) != 19:
        raise WorkerActivityUnavailable("invalid local activity timestamp")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        raise WorkerActivityUnavailable("invalid local activity timestamp") from None
    if parsed.strftime("%Y-%m-%d %H:%M:%S") != value:
        raise WorkerActivityUnavailable("invalid local activity timestamp")
    return parsed.isoformat()


def _at_epoch(value: object) -> str:
    if (
        not isinstance(value, (float, int))
        or isinstance(value, bool)
        or not isfinite(value)
        or value < 0
    ):
        raise WorkerActivityUnavailable("invalid local command timestamp")
    try:
        return datetime.fromtimestamp(value, UTC).isoformat()
    except (ValueError, OverflowError, OSError):
        raise WorkerActivityUnavailable("invalid local command timestamp") from None


def read_worker_activity(
    path: Path,
    *,
    observed_at: datetime,
    observation_events: tuple[TokenObservationActivity, ...] = (),
) -> WorkerActivitySnapshot:
    """Bounded snapshot: most recent lifecycle operation and safe command states.

    The lifecycle ledger is validated inside the *same read transaction* used
    for its receipts, so a forged or superseded ACK cannot become an activity.
    """
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    try:
        identity = _db_identity(path)
        uri = f"file:{quote(str(path), safe='/')}?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute("BEGIN")
            latest = LifecycleIntentStore._current(connection)
            entries: list[WorkerActivityEvent] = []
            receipts: list[tuple[int, WorkerActivityEvent]] = []
            operations: list[LifecycleIntent] = []
            if latest is not None and latest.work_start_id is not None:
                original = LifecycleIntentStore.for_operation(connection, latest.work_start_id)
                if original is None:
                    raise WorkerActivityUnavailable("automatic stop start receipt unavailable")
                operations.append(original)
            if latest is not None:
                operations.append(latest)
            for latest in operations:
                automatic_start = latest.work_start_id or latest.operation_id
                automatic_prefix = AUTOMATIC_CHECK_PREFIX + automatic_start + ":"
                automatic_rows = connection.execute(
                    "SELECT rowid,audit_id,action,recorded_at FROM audit_events "
                    "WHERE substr(action,1,?)=? ORDER BY rowid",
                    (len(automatic_prefix), automatic_prefix),
                ).fetchall()
                if latest.work_start_id is None:
                    for rowid, marker, action, at in automatic_rows:
                        code = action.removeprefix(automatic_prefix)
                        if code not in _AUTOMATIC_LABELS or (
                            marker,
                            action,
                        ) != automatic_check_marker(automatic_start, code):
                            raise WorkerActivityUnavailable("automatic observation receipt invalid")
                        level, message = _AUTOMATIC_LABELS[code]
                        receipts.append(
                            (rowid, WorkerActivityEvent(_at_sqlite(at), "chromium", level, message))
                        )
                action = f"owner_lifecycle_v1_request_{latest.component}_{latest.target}"
                request = (latest.operation_id, action)
                claim = host_marker(latest.operation_id, latest.component, latest.target, "CLAIMED")
                uncertain = host_marker(
                    latest.operation_id, latest.component, latest.target, "UNCERTAIN"
                )
                applied = host_marker(
                    latest.operation_id, latest.component, latest.target, "APPLIED"
                )
                refused = host_marker(
                    latest.operation_id, latest.component, latest.target, "REFUSED"
                )
                stages: dict[str, dict[str, tuple[Source, Level, str]]] = {
                    request[0]: {
                        request[1]: (
                            ("chromium" if automatic_rows else "simulation")
                            if latest.work_start_id is not None
                            else "owner",
                            "progress",
                            (
                                (
                                    "Bot: comprobación finalizada; detención automática solicitada."
                                    if automatic_rows
                                    else "Simulación local: trabajo finalizado; detención automática solicitada."
                                )
                                if latest.work_start_id is not None
                                else "Solicitado: "
                                + ("inicio" if latest.target == "start" else "detención")
                                + (" del bot." if latest.component == "bot" else " de Chromium.")
                            ),
                        )
                    },
                    claim[0]: {
                        claim[1]: (
                            "host",
                            "progress",
                            "Ejecutor: solicitud recibida, verificando el servicio Boca.",
                        )
                    },
                    uncertain[0]: {
                        uncertain[1]: (
                            "host",
                            "warning",
                            "Ejecutor: resultado indeterminado, no repetir sin conciliación.",
                        )
                    },
                    applied[0]: {
                        applied[1]: (
                            "host",
                            "success",
                            "Ejecutor: resultado físico confirmado en el momento del recibo.",
                        ),
                        refused[1]: (
                            "host",
                            "warning",
                            "Ejecutor: solicitud rechazada sin aplicar cambios.",
                        ),
                    },
                }
                if latest.component == "bot":
                    failed = host_marker(
                        latest.operation_id, latest.component, latest.target, "FAILED"
                    )
                    stages[failed[0]][failed[1]] = (
                        "host",
                        "error",
                        "Ejecutor: fallo del worker confirmado.",
                    )
                keys = tuple(stages)
                rows = connection.execute(
                    "SELECT rowid,audit_id,action,recorded_at FROM audit_events "
                    "WHERE audit_id IN (?,?,?,?) ORDER BY rowid",
                    keys,
                ).fetchall()
                for rowid, event_id, stored_action, at in rows:
                    fixed = stages.get(event_id, {}).get(stored_action)
                    if fixed is None:
                        raise WorkerActivityUnavailable("unexpected activity receipt")
                    source, level, message = fixed
                    receipts.append(
                        (rowid, WorkerActivityEvent(_at_sqlite(at), source, level, message))
                    )
            queue_rows = connection.execute(
                "SELECT a.rowid,a.audit_id,a.action,a.recorded_at,c.command_id "
                "FROM audit_events a LEFT JOIN beta_commands c "
                "ON c.command_id=substr(a.action,?,36) "
                "WHERE substr(a.action,1,?)=? ORDER BY a.rowid DESC LIMIT 48",
                (len(_QUEUE_PREFIX) + 1, len(_QUEUE_PREFIX), _QUEUE_PREFIX),
            ).fetchall()
            for rowid, marker, action, at, command_id in queue_rows:
                canonical_operation_id(command_id)
                prefix = _QUEUE_PREFIX + command_id + ":"
                code = action.removeprefix(prefix)
                if (
                    not action.startswith(prefix)
                    or code not in _QUEUE_LABELS
                    or marker != str(uuid5(NAMESPACE_URL, action))
                ):
                    raise WorkerActivityUnavailable("simulation queue receipt unavailable")
                level, message = _QUEUE_LABELS[code]
                receipts.append(
                    (rowid, WorkerActivityEvent(_at_sqlite(at), "simulation", level, message))
                )
            # Audit row order resolves same-second receipts without fabricating
            # a more precise timestamp or displaying private correlation IDs.
            entries.extend(event for _rowid, event in sorted(receipts, key=lambda item: item[0]))
            command_rows = connection.execute(
                "SELECT state,updated_at FROM beta_commands "
                "ORDER BY updated_at DESC,command_id DESC LIMIT 12"
            ).fetchall()
            for state, at in command_rows:
                if type(state) is not str or state not in _SIMULATION_LABELS:
                    raise WorkerActivityUnavailable("unexpected command state")
                level, message = _SIMULATION_LABELS[state]
                entries.append(WorkerActivityEvent(_at_epoch(at), "simulation", level, message))
        if _db_identity(path) != identity:
            raise WorkerActivityUnavailable("local data identity changed")
        if len(observation_events) > 32:
            raise WorkerActivityUnavailable("observation activity limit exceeded")
        for observed in observation_events:
            if (
                observed.code not in _OBSERVATION_LABELS
                or observed.at.tzinfo is None
                or observed.at.utcoffset() is None
            ):
                raise WorkerActivityUnavailable("observation activity unavailable")
            level, message = _OBSERVATION_LABELS[observed.code]
            entries.append(
                WorkerActivityEvent(
                    observed.at.astimezone(UTC).isoformat(), "chromium", level, message
                )
            )
        chromium = read_chromium_events(observed_at=observed_at)
        for stage in chromium.events:
            level, message = _CHROMIUM_STAGE_LABELS[stage.code]
            entries.append(WorkerActivityEvent(stage.at, "chromium", level, message))
        if chromium.stale:
            entries.append(
                WorkerActivityEvent(
                    observed_at.astimezone(UTC).isoformat(),
                    "chromium",
                    "warning",
                    "Chromium: sólo hay telemetría antigua; no confirma un proceso activo.",
                )
            )
        return WorkerActivitySnapshot(
            observed_at=observed_at.astimezone(UTC).isoformat(),
            browser_detail="fixed_stages_only",
            chromium_telemetry=chromium.state,
            events=tuple(sorted(entries, key=lambda item: item.at)[-30:]),
        )
    except (sqlite3.Error, OSError, LifecycleStorageUnavailable, ValueError, TypeError) as exc:
        raise WorkerActivityUnavailable("private activity unavailable") from exc
