"""Owner lifecycle *requests* only; trusted Actions alone may execute Docker.

This adapter reuses the existing legacy audit ledger without migrating it. An
HTTP request can create REQUESTED, never CLAIMED/APPLIED. Those two durable
receipts must come from a future exact-SHA Boca-only protected host operation
after verifying the real service identities. A green panel is not host ACK.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID, uuid5

if TYPE_CHECKING:
    from boca_socios.storage.database import Database

LifecycleComponent = Literal["bot", "chromium"]
LifecycleTarget = Literal["start", "stop"]
LifecycleStatus = Literal["REQUESTED", "CLAIMED", "APPLIED", "REFUSED", "UNCERTAIN"]

_COMPONENTS = ("bot", "chromium")
_TARGETS = ("start", "stop")
_RESULTS = ("APPLIED", "REFUSED")
_PREFIX = "owner_lifecycle_v1_"
_NAMESPACE = UUID("7a5e4b3a-2781-4f2d-978c-98bd64391508")
_REQUEST_ACTIONS = {
    (component, target): f"{_PREFIX}request_{component}_{target}"
    for component in _COMPONENTS
    for target in _TARGETS
}
_ALL_ACTIONS = frozenset(
    {*_REQUEST_ACTIONS.values()}
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


def _uuid(value: str) -> str:
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
    _uuid(operation_id)
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
    """Append-only, one-global-pending guard on the existing Boca audit log."""

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
    ) -> LifecycleIntent:
        """Persist one intent. Never start, stop, signal, dispatch or contact host."""
        action = _action(component, target)
        _uuid(operation_id)
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
                    result = state
                else:
                    if state is not None and state.status in (
                        "REQUESTED",
                        "CLAIMED",
                        "UNCERTAIN",
                    ):
                        raise LifecycleConflict("protected host operation remains unconfirmed")
                    connection.execute(
                        "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                        (operation_id, action),
                    )
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
    def _current(connection: sqlite3.Connection) -> LifecycleIntent | None:
        # Any future/unknown variant in this namespace is a schema mismatch,
        # not a reason to downgrade to an older supposedly successful state.
        for (observed_action,) in connection.execute(
            "SELECT action FROM audit_events WHERE substr(action,1,?)=?",
            (len(_PREFIX), _PREFIX),
        ):
            if observed_action not in _ALL_ACTIONS:
                raise LifecycleStorageUnavailable("unknown lifecycle ledger action")
        request = connection.execute(
            "SELECT rowid,audit_id,action,recorded_at FROM audit_events "
            "WHERE action IN (?,?,?,?) ORDER BY rowid DESC LIMIT 1",
            tuple(_REQUEST_ACTIONS.values()),
        ).fetchone()
        if request is None:
            if connection.execute(
                "SELECT 1 FROM audit_events WHERE substr(action,1,?)=? LIMIT 1",
                (len(_PREFIX), _PREFIX),
            ).fetchone():
                raise LifecycleStorageUnavailable("orphan lifecycle host receipt")
            return None
        rowid, operation_id, stored_action, recorded_at = request
        _uuid(operation_id)
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
            if (
                claim is None
                or type(ack[0]) is not int
                or ack[0] <= claim[0]
                or (uncertain is not None and ack[0] <= uncertain[0])
                or ack[1] not in allowed
            ):
                raise LifecycleStorageUnavailable("invalid lifecycle host ACK")
            status = cast(LifecycleStatus, allowed[ack[1]])
        return LifecycleIntent(operation_id, component, target, status, recorded_at)
