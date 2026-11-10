"""Append-only lifecycle intents, command bindings and physical receipts.

The panel records owner intent in the existing audit ledger. The coordinator
can also derive a stop from the terminal simulations bound to that activation.
Only the protected host executor claims an intent and records its result.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID, uuid4, uuid5

if TYPE_CHECKING:
    from boca_socios.storage.database import Database

LifecycleComponent = Literal["bot", "chromium"]
LifecycleTarget = Literal["start", "stop"]
LifecycleStatus = Literal["REQUESTED", "CLAIMED", "APPLIED", "REFUSED", "FAILED", "UNCERTAIN"]

_COMPONENTS = ("bot", "chromium")
_TARGETS = ("start", "stop")
_RESULTS = ("APPLIED", "REFUSED", "FAILED")
_OPEN = ("REQUESTED", "CLAIMED", "UNCERTAIN")
_PREFIX = "owner_lifecycle_v1_"
_NAMESPACE = UUID("7a5e4b3a-2781-4f2d-978c-98bd64391508")
_ON_DEMAND = "boca_bot_on_demand_v1:"
_WORK_BINDING = "boca_bot_work_v1:"
_WORK_STOP = "boca_bot_work_stop_v1:"
_REQUEST_ACTIONS = {
    (component, target): f"{_PREFIX}request_{component}_{target}"
    for component in _COMPONENTS
    for target in _TARGETS
}
_ALL_ACTIONS = frozenset(
    {*_REQUEST_ACTIONS.values()}
    | {f"{_PREFIX}ack_failed_bot_{target}" for target in _TARGETS}
    | {
        f"{_PREFIX}{phase}_{component}_{target}"
        for phase in ("claim", "uncertain", "ack_applied", "ack_refused")
        for component in _COMPONENTS
        for target in _TARGETS
    }
)


class LifecycleConflict(RuntimeError):
    """Another physical request has not received a safe terminal host receipt."""


class LifecycleStorageUnavailable(RuntimeError):
    """Legacy Boca audit ledger is unavailable, altered or inconsistent."""


@dataclass(frozen=True)
class LifecycleIntent:
    operation_id: str
    component: LifecycleComponent
    target: LifecycleTarget
    status: LifecycleStatus
    requested_at: str
    work_start_id: str | None = None
    on_demand: bool = False


def canonical_operation_id(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("canonical lifecycle request UUID required")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ValueError("canonical lifecycle request UUID required") from None
    if parsed.int == 0 or str(parsed) != value:
        raise ValueError("canonical lifecycle request UUID required")
    return value


def _action(component: str, target: str) -> str:
    try:
        return _REQUEST_ACTIONS[(component, target)]
    except (KeyError, TypeError):
        raise ValueError("unknown lifecycle control") from None


def _profile_marker(operation_id: str, request_action: str) -> tuple[str, str]:
    return str(uuid5(_NAMESPACE, _ON_DEMAND + operation_id)), _ON_DEMAND + request_action


def _insert_request(
    connection: sqlite3.Connection, operation_id: str, action: str, *, on_demand: bool
) -> None:
    insert = "INSERT INTO audit_events(audit_id,action) VALUES (?,?)"
    connection.execute(insert, (operation_id, action))
    if on_demand:
        connection.execute(insert, _profile_marker(operation_id, action))


def host_marker(
    operation_id: str,
    component: str,
    target: str,
    status: LifecycleStatus,
) -> tuple[str, str]:
    """Pure canonical ACK coordinates for the future *trusted* host executor.

    A marker tuple is not authority to perform an action; the protected
    workflow must hold the Boca host lease, attest exact container IDs, claim
    this request atomically and verify the physical result before appending an
    ACK. There is intentionally no HTTP endpoint that writes these markers.
    """
    canonical_operation_id(operation_id)
    _action(component, target)
    if status == "CLAIMED":
        phase = "claim"
        label = "claim"
    elif status == "UNCERTAIN":
        # Separate provisional marker; a later *verified* terminal ACK may
        # resolve uncertainty without deleting/replacing audit history.
        phase = "uncertain"
        label = "uncertain"
    elif status in _RESULTS:
        if status == "FAILED" and component != "bot":
            raise ValueError("confirmed on-demand failure requires a bot request")
        phase = "ack"
        label = f"ack_{status.lower()}"
    else:
        raise ValueError("only protected claim and final receipt coordinates exist")
    return (
        str(uuid5(_NAMESPACE, f"boca-lifecycle-v1:{phase}:{operation_id}")),
        f"{_PREFIX}{label}_{component}_{target}",
    )


def _db_identity(path: Path) -> tuple[int, int]:
    # The served runtime separately pins /data/boca.sqlite3. Reuse its
    # configured file so the disposable synthetic acceptance DB works too.
    if not isinstance(path, Path) or not path.is_absolute():
        raise LifecycleStorageUnavailable("configured Boca controller storage required")
    try:
        metadata = path.lstat()
    except OSError:
        raise LifecycleStorageUnavailable("Boca controller storage unavailable") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_gid != os.getegid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
    ):
        raise LifecycleStorageUnavailable("Boca controller storage identity unavailable")
    return metadata.st_dev, metadata.st_ino


class LifecycleIntentStore:
    """Serialize owner controls and simulation completion in the existing Boca audit log."""

    def __init__(self, database: Database) -> None:
        # Import only when constructing the panel DB facade. The protected
        # host ZIP uses the static legacy audit reader without crypto deps.
        from boca_socios.storage.database import Database

        if not isinstance(database, Database):
            raise ValueError("Boca Database required")
        self._database = database

    def current(self) -> LifecycleIntent | None:
        """Latest *request and host receipt*, never a claim of live host state."""
        before = _db_identity(self._database.path)
        try:
            with self._database.connection() as connection:
                # CLAIM and ACK can both commit while the owner opens Control.
                # Read the request and all its receipts from one WAL snapshot.
                connection.execute("BEGIN")
                state = self._current(connection)
            if _db_identity(self._database.path) != before:
                raise LifecycleStorageUnavailable("Boca controller storage identity changed")
            return state
        except (sqlite3.Error, OSError, ValueError, TypeError):
            raise LifecycleStorageUnavailable("Boca lifecycle ledger unavailable") from None

    def request(
        self,
        component: str,
        target: str,
        operation_id: str,
        *,
        on_demand: bool = False,
    ) -> LifecycleIntent:
        """Persist one intent. Never start, stop, signal, dispatch or contact host."""
        action = _action(component, target)
        canonical_operation_id(operation_id)
        if on_demand and component != "bot":
            raise ValueError("on-demand control requires the bot")
        before = _db_identity(self._database.path)
        try:
            with self._database.connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                # A repeated operation ID is idempotent across restarts.
                existing = connection.execute(
                    "SELECT action FROM audit_events WHERE audit_id=?", (operation_id,)
                ).fetchone()
                state = self._current(connection)
                if existing is not None:
                    if existing != (action,):
                        raise LifecycleConflict("lifecycle request UUID already used")
                    if state is None or state.operation_id != operation_id:
                        raise LifecycleConflict("lifecycle request already superseded")
                    if on_demand != state.on_demand:
                        raise LifecycleConflict(
                            "lifecycle request belongs to another control profile"
                        )
                    result = state
                elif (
                    on_demand
                    and state is not None
                    and state.on_demand
                    and state.component == component
                    and state.target == target
                    and (state.status in _OPEN or state.status == "APPLIED")
                ):
                    # Preserve the activation that owns in-flight work. Only
                    # REQUESTED needs another wake after loss of the first.
                    result = state
                else:
                    if (
                        state is not None
                        and state.status in _OPEN
                        and not (
                            on_demand
                            and state.on_demand
                            and state.component == "bot"
                            and state.target == "start"
                            and target == "stop"
                            and state.status in ("REQUESTED", "CLAIMED")
                        )
                        and not (on_demand and not state.on_demand and state.status == "REQUESTED")
                    ):
                        raise LifecycleConflict("protected host operation remains unconfirmed")
                    _insert_request(connection, operation_id, action, on_demand=on_demand)
                    fresh = self._current(connection)
                    if fresh is None or fresh.operation_id != operation_id:
                        raise LifecycleStorageUnavailable("Boca lifecycle request did not persist")
                    result = fresh
            if _db_identity(self._database.path) != before:
                raise LifecycleStorageUnavailable("Boca controller storage identity changed")
            return result
        except (sqlite3.Error, OSError, ValueError, TypeError):
            raise LifecycleStorageUnavailable("Boca lifecycle ledger unavailable") from None

    @staticmethod
    def _accepted_binding(
        connection: sqlite3.Connection, start_operation_id: str, command_id: str
    ) -> tuple[str, str] | None:
        canonical_operation_id(start_operation_id)
        canonical_operation_id(command_id)
        current = LifecycleIntentStore._current(connection)
        if (
            current is None
            or not current.on_demand
            or current.operation_id != start_operation_id
            or (current.component, current.target, current.status) != ("bot", "start", "APPLIED")
        ):
            return None
        command = connection.execute(
            "SELECT state FROM beta_commands WHERE command_id=?", (command_id,)
        ).fetchone()
        if command != ("accepted",):
            return None
        return str(
            uuid5(_NAMESPACE, _WORK_BINDING + command_id)
        ), _WORK_BINDING + start_operation_id + ":" + command_id

    @staticmethod
    def may_run_work(
        connection: sqlite3.Connection, start_operation_id: str, command_id: str
    ) -> bool:
        """Recheck the durable binding before changing accepted work to running."""
        binding = LifecycleIntentStore._accepted_binding(connection, start_operation_id, command_id)
        return binding is not None and connection.execute(
            "SELECT 1 FROM audit_events WHERE audit_id=? AND action=?", binding
        ).fetchone() == (1,)

    @staticmethod
    def bind_work(connection: sqlite3.Connection, start_operation_id: str, command_id: str) -> None:
        """Bind a fresh accepted simulation to the confirmed START in its enqueue transaction."""
        if not connection.in_transaction:
            raise LifecycleStorageUnavailable("command admission transaction required")
        binding = LifecycleIntentStore._accepted_binding(connection, start_operation_id, command_id)
        if binding is None:
            raise LifecycleConflict("current confirmed start and fresh accepted command required")
        key, action = binding
        existing = connection.execute(
            "SELECT action FROM audit_events WHERE audit_id=?", (key,)
        ).fetchone()
        if existing is None:
            connection.execute(
                "INSERT INTO audit_events(audit_id,action) VALUES (?,?)", (key, action)
            )
        elif existing != (action,):
            raise LifecycleConflict("simulation already bound to another start")

    def request_work_stop(self, start_operation_id: str) -> LifecycleIntent | None:
        """Derive one STOP from this run's terminal work, with no human request implied."""
        canonical_operation_id(start_operation_id)
        before = _db_identity(self._database.path)
        try:
            with self._database.connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE")
                current = self._current(connection)
                result = None
                if current is not None and current.work_start_id == start_operation_id:
                    result = current  # Recover an already committed wake after interruption.
                elif (
                    current is not None
                    and current.on_demand
                    and current.operation_id == start_operation_id
                    and (current.component, current.target, current.status)
                    == ("bot", "start", "APPLIED")
                    and self._work_finished(connection, start_operation_id)
                ):
                    stop_id = str(uuid4())
                    _insert_request(
                        connection, stop_id, _REQUEST_ACTIONS[("bot", "stop")], on_demand=True
                    )
                    connection.execute(
                        "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                        (
                            str(uuid5(_NAMESPACE, _WORK_STOP + stop_id)),
                            _WORK_STOP + start_operation_id,
                        ),
                    )
                    result = self._current(connection)
                    if (
                        result is None
                        or result.operation_id != stop_id
                        or result.work_start_id != start_operation_id
                    ):
                        raise LifecycleStorageUnavailable("work-stop correlation unavailable")
            if _db_identity(self._database.path) != before:
                raise LifecycleStorageUnavailable("Boca controller storage identity changed")
            return result
        except (sqlite3.Error, OSError, ValueError, TypeError):
            raise LifecycleStorageUnavailable("Boca work completion ledger unavailable") from None

    @staticmethod
    def _work_finished(connection: sqlite3.Connection, start_operation_id: str) -> bool:
        if connection.execute(
            "SELECT 1 FROM beta_commands WHERE state IN "
            "('accepted','running','stop_requested') LIMIT 1"
        ).fetchone():
            return False
        prefix = _WORK_BINDING + start_operation_id + ":"
        rows = connection.execute(
            "SELECT a.audit_id, substr(a.action,?), c.state, c.notice_enqueued, r.attempt_kind, r.state "
            "FROM audit_events a LEFT JOIN beta_commands c ON c.command_id=substr(a.action,?) "
            "LEFT JOIN reservation_attempts r ON r.request_id=c.request_id "
            "WHERE substr(a.action,1,?)=?",
            (len(prefix) + 1, len(prefix) + 1, len(prefix), prefix),
        )
        any_bound = False
        for key, command_id, state, notice, kind, outcome in rows:
            if (
                key != str(uuid5(_NAMESPACE, _WORK_BINDING + canonical_operation_id(command_id)))
                or state is None
            ):
                raise LifecycleStorageUnavailable("invalid work binding")
            any_bound = True
            if state == "completed" and (notice, kind, outcome) == (
                1,
                "simulation",
                "simulation_completed",
            ):
                continue
            if state not in ("stopped", "failed", "needs_review"):
                return False
        return any_bound

    @staticmethod
    def for_operation(connection: sqlite3.Connection, operation_id: str) -> LifecycleIntent | None:
        """Read this exact request, including its receipts after a superseding STOP."""
        return LifecycleIntentStore._current(
            connection, operation_id=canonical_operation_id(operation_id)
        )

    @staticmethod
    def _current(
        connection: sqlite3.Connection, *, operation_id: str | None = None
    ) -> LifecycleIntent | None:
        # Any future/unknown variant in this namespace is a schema mismatch,
        # not a reason to downgrade to an older supposedly successful state.
        for (observed_action,) in connection.execute(
            "SELECT action FROM audit_events WHERE substr(action,1,?)=?",
            (len(_PREFIX), _PREFIX),
        ):
            if observed_action not in _ALL_ACTIONS:
                raise LifecycleStorageUnavailable("unknown lifecycle ledger action")
        query = (
            "SELECT rowid,audit_id,action,recorded_at FROM audit_events WHERE action IN (?,?,?,?) "
        )
        parameters = tuple(_REQUEST_ACTIONS.values())
        if operation_id is not None:
            query += "AND audit_id=? "
            parameters += (operation_id,)
        request = connection.execute(query + "ORDER BY rowid DESC LIMIT 1", parameters).fetchone()
        if request is None:
            if (
                operation_id is None
                and connection.execute(
                    "SELECT 1 FROM audit_events WHERE substr(action,1,?)=? LIMIT 1",
                    (len(_PREFIX), _PREFIX),
                ).fetchone()
            ):
                raise LifecycleStorageUnavailable("orphan lifecycle host receipt")
            return None
        rowid, operation_id, stored_action, recorded_at = request
        canonical_operation_id(operation_id)
        matched = next(
            (
                (component, target)
                for (component, target), action in _REQUEST_ACTIONS.items()
                if action == stored_action
            ),
            None,
        )
        if (
            type(rowid) is not int
            or rowid < 1
            or matched is None
            or not isinstance(recorded_at, str)
            or len(recorded_at) != 19
        ):
            raise LifecycleStorageUnavailable("invalid lifecycle request row")
        component = cast(LifecycleComponent, matched[0])
        target = cast(LifecycleTarget, matched[1])
        profile_id, profile_action = _profile_marker(operation_id, stored_action)
        profile = connection.execute(
            "SELECT rowid,action FROM audit_events WHERE audit_id=?", (profile_id,)
        ).fetchone()
        on_demand = profile is not None
        if on_demand and (component != "bot" or profile != (rowid + 1, profile_action)):
            raise LifecycleStorageUnavailable("invalid on-demand request provenance")
        claim_id, claim_action = host_marker(operation_id, component, target, "CLAIMED")
        claim = connection.execute(
            "SELECT rowid,action FROM audit_events WHERE audit_id=?", (claim_id,)
        ).fetchone()
        uncertain_id, uncertain_action = host_marker(operation_id, component, target, "UNCERTAIN")
        uncertain = connection.execute(
            "SELECT rowid,action FROM audit_events WHERE audit_id=?", (uncertain_id,)
        ).fetchone()
        ack_id, _ = host_marker(operation_id, component, target, "APPLIED")
        ack = connection.execute(
            "SELECT rowid,action FROM audit_events WHERE audit_id=?", (ack_id,)
        ).fetchone()
        status: LifecycleStatus = "REQUESTED"
        if claim is not None:
            if type(claim[0]) is not int or claim[0] <= rowid or claim[1] != claim_action:
                raise LifecycleStorageUnavailable("invalid lifecycle host claim")
            status = "CLAIMED"
        if uncertain is not None:
            if (
                claim is None
                or type(uncertain[0]) is not int
                or uncertain[0] <= claim[0]
                or uncertain[1] != uncertain_action
            ):
                raise LifecycleStorageUnavailable("invalid lifecycle uncertainty")
            status = "UNCERTAIN"
        if ack is not None:
            allowed = {
                host_marker(operation_id, component, target, "APPLIED")[1]: "APPLIED",
                host_marker(operation_id, component, target, "REFUSED")[1]: "REFUSED",
                host_marker(operation_id, component, target, "UNCERTAIN")[1]: "UNCERTAIN",
            }
            if on_demand:
                allowed[host_marker(operation_id, component, target, "FAILED")[1]] = "FAILED"
            if (
                claim is None
                or type(ack[0]) is not int
                or ack[0] <= claim[0]
                or (uncertain is not None and ack[0] <= uncertain[0])
                or ack[1] not in allowed
            ):
                raise LifecycleStorageUnavailable("invalid lifecycle host ACK")
            status = cast(LifecycleStatus, allowed[ack[1]])
        work_start_id = None
        if (component, target) == ("bot", "stop"):
            correlation = connection.execute(
                "SELECT rowid,action FROM audit_events WHERE audit_id=?",
                (str(uuid5(_NAMESPACE, _WORK_STOP + operation_id)),),
            ).fetchone()
            if correlation is not None:
                if (
                    not on_demand
                    or correlation[0] <= rowid
                    or not correlation[1].startswith(_WORK_STOP)
                ):
                    raise LifecycleStorageUnavailable("invalid work-stop correlation")
                work_start_id = canonical_operation_id(correlation[1][len(_WORK_STOP) :])
                if not connection.execute(
                    "SELECT 1 FROM audit_events WHERE audit_id=? AND action=? AND rowid<?",
                    (work_start_id, _REQUEST_ACTIONS[("bot", "start")], rowid),
                ).fetchone():
                    raise LifecycleStorageUnavailable("work-stop start unavailable")
        return LifecycleIntent(
            operation_id, component, target, status, recorded_at, work_start_id, on_demand
        )
