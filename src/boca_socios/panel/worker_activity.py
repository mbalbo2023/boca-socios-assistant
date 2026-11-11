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
from typing import Literal
from urllib.parse import quote

from boca_socios.browser.activity_events import read_chromium_events
from boca_socios.panel.lifecycle_intents import (
    LifecycleIntentStore,
    LifecycleStorageUnavailable,
    _db_identity,
    host_marker,
)


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


def read_worker_activity(path: Path, *, observed_at: datetime) -> WorkerActivitySnapshot:
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
            if latest is not None:
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
                            "owner",
                            "progress",
                            "Solicitado: "
                            + ("inicio" if latest.target == "start" else "detención")
                            + (" del bot." if latest.component == "bot" else " de Chromium."),
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
                    "SELECT audit_id,action,recorded_at FROM audit_events "
                    "WHERE audit_id IN (?,?,?,?) ORDER BY rowid",
                    keys,
                ).fetchall()
                for event_id, stored_action, at in rows:
                    fixed = stages.get(event_id, {}).get(stored_action)
                    if fixed is None:
                        raise WorkerActivityUnavailable("unexpected activity receipt")
                    source, level, message = fixed
                    entries.append(WorkerActivityEvent(_at_sqlite(at), source, level, message))
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
        chromium = read_chromium_events(observed_at=observed_at)
        for stage in chromium.events:
            level, message = _CHROMIUM_STAGE_LABELS[stage.code]
            entries.append(WorkerActivityEvent(stage.at, "chromium", level, message))
        return WorkerActivitySnapshot(
            observed_at=observed_at.astimezone(UTC).isoformat(),
            browser_detail="fixed_stages_only",
            chromium_telemetry=chromium.state,
            events=tuple(sorted(entries, key=lambda item: item.at)[-30:]),
        )
    except (sqlite3.Error, OSError, LifecycleStorageUnavailable, ValueError, TypeError) as exc:
        raise WorkerActivityUnavailable("private activity unavailable") from exc
