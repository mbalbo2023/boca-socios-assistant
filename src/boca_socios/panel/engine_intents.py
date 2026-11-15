"""Durable logical engine ownership over the existing physical lifecycle.

No method starts a process or performs IPC. Returned physical intents become
eligible for a wake only after the enclosing SQLite transaction has committed.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4, uuid5

from boca_socios.panel.lifecycle_intents import (
    _REQUEST_ACTIONS,
    ENGINE_HOLD_PREFIX,
    ENGINE_NAMESPACE,
    ENGINE_RELEASE_PREFIX,
    LifecycleConflict,
    LifecycleIntent,
    LifecycleIntentStore,
    LifecycleStorageUnavailable,
    _db_identity,
    _insert_request,
    canonical_operation_id,
)
from boca_socios.storage.database import Database

EngineId = Literal["queues_tokens", "browsers_members"]
EngineState = Literal[
    "REQUESTED", "STARTING", "RUNNING", "STOP_REQUESTED", "STOPPED", "FAILED", "UNCERTAIN"
]
ENGINES: tuple[EngineId, ...] = ("queues_tokens", "browsers_members")
BROWSER_TYPES = ("chromium", "firefox", "webkit")
MAX_CONTEXTS = 50
_PREFIX = "boca_engine_v1:"
_START = _PREFIX + "start:"
_STATE = _PREFIX + "state:"
_CONTROL = _PREFIX + "control:"
_LIVE = frozenset({"REQUESTED", "STARTING", "RUNNING"})
_TRANSITIONS: dict[str, frozenset[str]] = {
    "REQUESTED": frozenset(
        {"STARTING", "RUNNING", "STOP_REQUESTED", "STOPPED", "FAILED", "UNCERTAIN"}
    ),
    "STARTING": frozenset({"RUNNING", "STOP_REQUESTED", "STOPPED", "FAILED", "UNCERTAIN"}),
    "RUNNING": frozenset({"STOP_REQUESTED", "STOPPED", "FAILED", "UNCERTAIN"}),
    "STOP_REQUESTED": frozenset({"STOPPED", "FAILED", "UNCERTAIN"}),
    "FAILED": frozenset({"UNCERTAIN"}),
    "UNCERTAIN": frozenset({"STOPPED"}),
    "STOPPED": frozenset(),
}


class EngineConflict(LifecycleConflict):
    """The requested engine identity, ownership or physical state conflicts."""


class EngineStorageUnavailable(LifecycleStorageUnavailable):
    """The existing audit ledger cannot prove safe engine ownership."""


@dataclass(frozen=True)
class EngineActivation:
    engine: EngineId
    activation_id: str
    generation: int
    boot_id: str
    physical_start_id: str
    member_id: str | None
    counts: dict[str, int]
    state: EngineState
    requested_at: str
    updated_at: str
    released: bool = False
    credential_fingerprint: str | None = None

    @property
    def requested_contexts(self) -> int:
        return sum(self.counts.values())


@dataclass(frozen=True)
class EngineDecision:
    activation: EngineActivation
    physical_intent: LifecycleIntent | None = None


def _engine(value: str) -> EngineId:
    if value not in ENGINES:
        raise ValueError("unknown functional engine")
    return value


def _counts(value: Mapping[str, int]) -> dict[str, int]:
    if (
        not isinstance(value, Mapping)
        or set(value) != set(BROWSER_TYPES)
        or any(type(item) is not int or not 0 <= item <= MAX_CONTEXTS for item in value.values())
        or not 1 <= sum(value.values()) <= MAX_CONTEXTS
    ):
        raise ValueError("browser counts must reserve between one and fifty contexts")
    return {browser: value[browser] for browser in BROWSER_TYPES}


def _generation(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ValueError("positive engine generation required")
    return value


def _credential_fingerprint(connection: sqlite3.Connection, member_id: str | None) -> str | None:
    """Opaque revision fence over existing ciphertext, never its plaintext.

    The existing credential audit also fences a revoke/reinsert of identical
    ciphertext; comparing ciphertext alone would miss that ABA sequence.
    """
    if member_id is None:
        return None
    row = connection.execute(
        "SELECT key_id,nonce,ciphertext FROM credentials WHERE member_id=?", (member_id,)
    ).fetchone()
    if (
        row is None
        or not isinstance(row[0], str)
        or not isinstance(row[1], bytes)
        or not isinstance(row[2], bytes)
    ):
        return None
    revision = connection.execute(
        "SELECT audit_id FROM audit_events WHERE member_id=? AND "
        "action IN ('member.enrolled','credential.rotated','credential.revoked') "
        "ORDER BY rowid DESC LIMIT 1",
        (member_id,),
    ).fetchone()
    value: dict[str, object] = {
        "key_id": row[0],
        "nonce": row[1].hex(),
        "ciphertext": row[2].hex(),
        "revision": None if revision is None else canonical_operation_id(revision[0]),
    }
    return hashlib.sha256(_json(value).encode("ascii")).hexdigest()


def _json(value: dict[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _insert(connection: sqlite3.Connection, key: str, action: str) -> None:
    connection.execute("INSERT INTO audit_events(audit_id,action) VALUES (?,?)", (key, action))


def _marker(connection: sqlite3.Connection, action: str) -> None:
    _insert(connection, str(uuid5(ENGINE_NAMESPACE, action)), action)


def _control(target: str, activation: EngineActivation) -> str:
    return (
        f"{_CONTROL}{target}:{activation.engine}:{activation.activation_id}:{activation.generation}"
    )


def _wake(intent: LifecycleIntent | None) -> LifecycleIntent | None:
    return intent if intent is not None and intent.status == "REQUESTED" else None


class EngineIntentStore:
    """Two independent jobs, one atomic budget and one physical lifecycle ledger."""

    def __init__(self, database: Database, *, boot_id: str) -> None:
        if not isinstance(database, Database):
            raise ValueError("Boca Database required")
        self._database = database
        self.boot_id = canonical_operation_id(boot_id)

    @contextmanager
    def _transaction(
        self, *, write: bool, before_commit: Callable[[], None] | None = None
    ) -> Iterator[sqlite3.Connection]:
        try:
            before = _db_identity(self._database.path)
            with self._database.connection() as connection, connection:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield connection
                if _db_identity(self._database.path) != before:
                    raise EngineStorageUnavailable("engine storage identity changed")
                if before_commit is not None:
                    before_commit()
        except EngineStorageUnavailable:
            raise
        except (sqlite3.Error, OSError, LifecycleStorageUnavailable, ValueError, TypeError):
            raise EngineStorageUnavailable("engine audit ledger unavailable") from None

    def snapshot(self) -> tuple[EngineActivation, ...]:
        """Latest activation of each engine, including closed history; no resume."""
        with self._transaction(write=False) as connection:
            latest = self._load(connection)
            return tuple(latest[engine] for engine in ENGINES if engine in latest)

    def restartable_engines(self) -> frozenset[EngineId]:
        """Read-only readiness after a physical STOP, before explicit reconciliation.

        The panel can offer a new START without writing on GET. Its next POST
        still performs recover_cold and rechecks every durable ownership fence.
        """
        with self._transaction(write=False) as connection:
            latest = self._load(connection)
            held = tuple(item for item in latest.values() if not item.released)
            physically_closed = bool(held) and all(
                self._physical_closed(connection, item) for item in held
            )
            if held and not physically_closed:
                try:
                    self._owned_physical(connection, latest)
                except EngineConflict:
                    return frozenset()
                if sum(item.requested_contexts for item in held) >= MAX_CONTEXTS:
                    return frozenset()
            elif not held:
                physical = LifecycleIntentStore._current(connection)
                if physical is not None and (
                    physical.component,
                    physical.target,
                    physical.status,
                ) != ("bot", "stop", "APPLIED"):
                    return frozenset()
            return frozenset(
                engine
                for engine in ENGINES
                if engine not in latest or latest[engine].released or physically_closed
            )

    @staticmethod
    def _legacy_recovery(
        connection: sqlite3.Connection,
    ) -> Literal["NONE", "REQUIRED", "REQUESTED", "CLAIMED"]:
        if any(not item.released for item in EngineIntentStore._load(connection).values()):
            return "NONE"
        physical = LifecycleIntentStore._current(connection)
        if physical is None:
            return "NONE"
        if (physical.component, physical.target) == ("bot", "stop"):
            if physical.status == "APPLIED":
                return "NONE"
            if physical.status in {"REQUESTED", "CLAIMED"} and physical.on_demand:
                return cast(Literal["REQUESTED", "CLAIMED"], physical.status)
        return "REQUIRED"

    def legacy_recovery_state(self) -> str:
        """Read-only advice for old physical history without logical ownership."""
        with self._transaction(write=False) as connection:
            return self._legacy_recovery(connection)

    def request_legacy_stop(self, operation_id: str) -> LifecycleIntent:
        """Explicit owner recovery without an invented logical activation.

        Admission and request share the writer lock with engine START. Old
        uncertainty remains in history; only the runner can certify closure.
        """
        canonical_operation_id(operation_id)
        with self._transaction(write=True) as connection:
            if any(not item.released for item in self._load(connection).values()):
                raise EngineConflict("logical engines require their own scoped STOP")
            physical = LifecycleIntentStore._current(connection)
            existing = connection.execute(
                "SELECT action FROM audit_events WHERE audit_id=?", (operation_id,)
            ).fetchone()
            if existing is not None:
                if (
                    existing != (_REQUEST_ACTIONS[("bot", "stop")],)
                    or physical is None
                    or physical.operation_id != operation_id
                    or not physical.on_demand
                ):
                    raise EngineConflict("recovery operation already used or superseded")
                return physical
            state = self._legacy_recovery(connection)
            if state == "NONE":
                raise EngineConflict("no orphan physical activation requires recovery")
            if state == "REQUESTED":
                assert physical is not None
                return physical
            _insert_request(
                connection, operation_id, _REQUEST_ACTIONS[("bot", "stop")], on_demand=True
            )
            physical = LifecycleIntentStore._current(connection)
            if physical is None or physical.operation_id != operation_id:
                raise EngineStorageUnavailable("physical recovery did not persist")
            return physical

    def start(
        self,
        engine: str,
        operation_id: str,
        *,
        member_id: str | None = None,
        counts: Mapping[str, int],
    ) -> EngineDecision:
        """Reserve contexts and bind the job to an owned current-boot START."""
        selected = _engine(engine)
        canonical_operation_id(operation_id)
        requested = _counts(counts)
        if member_id is not None:
            canonical_operation_id(member_id)
        if selected == "queues_tokens" and member_id is not None:
            raise EngineConflict("queue engine has no member authentication selection")
        if selected == "browsers_members" and member_id is None:
            raise EngineConflict("member engine requires an active member credential")
        with self._transaction(write=True) as connection:
            latest = self._load(connection)
            current = latest.get(selected)
            physical: LifecycleIntent | None
            if member_id is not None and not LifecycleIntentStore._active_member(
                connection, member_id
            ):
                raise EngineConflict("active member credential required")
            fingerprint = _credential_fingerprint(connection, member_id)
            if member_id is not None and fingerprint is None:
                raise EngineConflict("active member credential required")
            existing = connection.execute(
                "SELECT action FROM audit_events WHERE audit_id=?", (operation_id,)
            ).fetchone()
            if existing is not None:
                if current is None or not (
                    operation_id == current.activation_id
                    or existing == (_control("start", current),)
                ):
                    raise EngineConflict("engine operation UUID already used")
            if current is not None and not current.released:
                if (
                    current.boot_id != self.boot_id
                    or current.state not in _LIVE
                    or current.member_id != member_id
                    or current.counts != requested
                    or current.credential_fingerprint != fingerprint
                ):
                    raise EngineConflict("current activation cannot change or resume")
                physical = self._owned_physical(connection, latest)
                if existing is None:
                    _insert(connection, operation_id, _control("start", current))
                result = EngineDecision(current, _wake(physical))
            else:
                if existing is not None:
                    raise EngineConflict("engine operation already superseded")
                held = [item for item in latest.values() if not item.released]
                if (
                    sum(item.requested_contexts for item in held) + sum(requested.values())
                    > MAX_CONTEXTS
                ):
                    raise EngineConflict("global context capacity is already reserved")
                if held:
                    physical = self._owned_physical(connection, latest)
                else:
                    physical = LifecycleIntentStore._current(connection)
                    if physical is not None and (
                        physical.component,
                        physical.target,
                        physical.status,
                    ) != ("bot", "stop", "APPLIED"):
                        raise EngineConflict("previous physical activation is not closed")
                    start_id = str(uuid4())
                    _insert_request(
                        connection, start_id, _REQUEST_ACTIONS[("bot", "start")], on_demand=True
                    )
                    physical = LifecycleIntentStore._current(connection)
                    if physical is None or physical.operation_id != start_id:
                        raise EngineStorageUnavailable("physical start did not persist")
                generation = 1 if current is None else _generation(current.generation + 1)
                record: dict[str, object] = {
                    "engine": selected,
                    "generation": generation,
                    "boot_id": self.boot_id,
                    "physical_start_id": physical.operation_id,
                    "member_id": member_id,
                    "counts": requested,
                    "credential_fingerprint": fingerprint,
                }
                _insert(connection, operation_id, _START + _json(record))
                _marker(connection, ENGINE_HOLD_PREFIX + physical.operation_id + ":" + operation_id)
                result = EngineDecision(self._load(connection)[selected], _wake(physical))
        return result

    def stop(
        self,
        engine: str,
        operation_id: str,
        *,
        activation_id: str,
        generation: int,
    ) -> EngineDecision:
        """Fence this generation before its coordinator attempts bounded teardown."""
        selected = _engine(engine)
        canonical_operation_id(operation_id)
        canonical_operation_id(activation_id)
        _generation(generation)
        with self._transaction(write=True) as connection:
            current = self._required(connection, selected, activation_id, generation, old_boot=True)
            action = _control("stop", current)
            existing = connection.execute(
                "SELECT action FROM audit_events WHERE audit_id=?", (operation_id,)
            ).fetchone()
            if existing is not None and existing != (action,):
                raise EngineConflict("engine operation UUID already used")
            if existing is None:
                _insert(connection, operation_id, action)
            if current.state in _LIVE and not current.released:
                state: EngineState = (
                    "STOP_REQUESTED" if current.boot_id == self.boot_id else "UNCERTAIN"
                )
                self._set_state(connection, current, state)
            current = self._load(connection)[selected]
            physical = None
            if current.released:
                physical = self._last_stop(connection, current)
            elif current.boot_id != self.boot_id or current.state in {"UNCERTAIN", "FAILED"}:
                physical = self._cold_stop(connection, current, new_request=existing is None)
                current = self._load(connection)[selected]
            result = EngineDecision(current, physical)
        return result

    def transition(
        self, engine: str, activation_id: str, generation: int, state: str
    ) -> EngineActivation:
        selected = _engine(engine)
        canonical_operation_id(activation_id)
        _generation(generation)
        if state not in {"STARTING", "RUNNING", "FAILED", "UNCERTAIN"}:
            raise ValueError("engine transition requires an observed execution state")
        with self._transaction(write=True) as connection:
            current = self._required(connection, selected, activation_id, generation)
            if current.released:
                raise EngineConflict("engine activation already released")
            if state in {"STARTING", "RUNNING"} and not self._may_publish(connection, current):
                raise EngineConflict("current physical APPLIED receipt and member required")
            self._set_state(connection, current, cast(EngineState, state))
            result = self._load(connection)[selected]
        return result

    def publish_if_current(
        self,
        engine: str,
        activation_id: str,
        generation: int,
        publish: Callable[[], None],
        *,
        member_id: str | None = None,
    ) -> bool:
        """Publish only a private in-memory result under the STOP/revocation lock.

        The callback must perform no IPC, network, filesystem or nested DB I/O.
        """
        selected = _engine(engine)
        canonical_operation_id(activation_id)
        _generation(generation)
        if member_id is not None:
            canonical_operation_id(member_id)
        permitted = False

        def publish_checked() -> None:
            if permitted:
                publish()

        with self._transaction(write=True, before_commit=publish_checked) as connection:
            current = self._load(connection).get(selected)
            if (
                current is None
                or (current.activation_id, current.generation) != (activation_id, generation)
                or member_id is not None
                and current.member_id != member_id
                or not self._may_publish(connection, current)
            ):
                return False
            permitted = True
        return True

    def credential_read_authorized(
        self,
        connection: sqlite3.Connection,
        engine: str,
        activation_id: str,
        generation: int,
        member_id: str,
    ) -> bool:
        """Fence sealed-credential selection inside its existing read snapshot.

        The auth service owns this short read-only transaction and file-identity
        checks. No new connection, decryption, IPC or publication occurs here.
        """
        selected = _engine(engine)
        canonical_operation_id(activation_id)
        canonical_operation_id(member_id)
        _generation(generation)
        main = next(
            (row for row in connection.execute("PRAGMA database_list") if row[1] == "main"),
            None,
        )
        if (
            selected != "browsers_members"
            or not connection.in_transaction
            or connection.execute("PRAGMA query_only").fetchone() != (1,)
            or main is None
            or Path(main[2]) != self._database.path.absolute()
        ):
            return False
        current = self._load(connection).get(selected)
        return bool(
            current is not None
            and (current.activation_id, current.generation, current.member_id)
            == (activation_id, generation, member_id)
            and self._may_publish(connection, current)
        )

    def release(
        self, engine: str, activation_id: str, generation: int, *, closed: bool
    ) -> EngineDecision:
        """Retain uncertain holds; release only after context teardown is proven.

        A previous controller boot cannot attest its lost contexts. Only a
        subsequent physical STOP/APPLIED receipt can release that cold hold.
        """
        selected = _engine(engine)
        canonical_operation_id(activation_id)
        _generation(generation)
        if type(closed) is not bool:
            raise ValueError("explicit context closure result required")
        with self._transaction(write=True) as connection:
            current = self._required(connection, selected, activation_id, generation, old_boot=True)
            if not current.released:
                if (
                    closed
                    and current.boot_id != self.boot_id
                    and not self._physical_closed(connection, current)
                ):
                    raise EngineConflict("cold activation requires a physical closure receipt")
                if not closed:
                    self._set_state(connection, current, "UNCERTAIN")
                else:
                    self._close(connection, current)
                current = self._load(connection)[selected]
            result = EngineDecision(
                current, self._last_stop(connection, current) if current.released else None
            )
        return result

    def recover_cold(self) -> tuple[EngineActivation, ...]:
        """Quarantine lost generations; never turn a historical START into resume."""
        with self._transaction(write=True) as connection:
            for current in self._load(connection).values():
                if current.released:
                    continue
                if self._physical_closed(connection, current):
                    self._close(connection, current)
                elif current.boot_id != self.boot_id:
                    self._set_state(connection, current, "UNCERTAIN")
            latest = self._load(connection)
            result = tuple(latest[engine] for engine in ENGINES if engine in latest)
        return result

    def _required(
        self,
        connection: sqlite3.Connection,
        engine: EngineId,
        activation_id: str,
        generation: int,
        *,
        old_boot: bool = False,
    ) -> EngineActivation:
        current = self._load(connection).get(engine)
        if (
            current is None
            or (current.activation_id, current.generation) != (activation_id, generation)
            or not old_boot
            and current.boot_id != self.boot_id
        ):
            raise EngineConflict("engine activation generation is not current")
        return current

    def _owned_physical(
        self, connection: sqlite3.Connection, latest: dict[EngineId, EngineActivation]
    ) -> LifecycleIntent:
        held = [item for item in latest.values() if not item.released]
        physical = LifecycleIntentStore._current(connection)
        if (
            not held
            or any(item.boot_id != self.boot_id or item.state == "UNCERTAIN" for item in held)
            or physical is None
            or not physical.on_demand
            or (physical.component, physical.target) != ("bot", "start")
            or physical.status not in {"REQUESTED", "CLAIMED", "APPLIED"}
            or any(item.physical_start_id != physical.operation_id for item in held)
        ):
            raise EngineConflict("current boot does not own a usable physical start")
        return physical

    def _may_publish(self, connection: sqlite3.Connection, current: EngineActivation) -> bool:
        physical = LifecycleIntentStore._current(connection)
        return (
            current.boot_id == self.boot_id
            and not current.released
            and current.state in _LIVE
            and physical is not None
            and physical.on_demand
            and physical.operation_id == current.physical_start_id
            and (physical.component, physical.target, physical.status)
            == ("bot", "start", "APPLIED")
            and (
                current.member_id is None
                or LifecycleIntentStore._active_member(connection, current.member_id)
            )
            and current.credential_fingerprint
            == _credential_fingerprint(connection, current.member_id)
        )

    @staticmethod
    def _set_state(
        connection: sqlite3.Connection, current: EngineActivation, state: EngineState
    ) -> None:
        if current.state == state:
            return
        if current.released or state not in _TRANSITIONS[current.state]:
            raise EngineConflict("invalid engine state transition")
        _marker(connection, _STATE + current.activation_id + ":" + state)

    @staticmethod
    def _close(connection: sqlite3.Connection, current: EngineActivation) -> None:
        if current.state != "FAILED":
            EngineIntentStore._set_state(connection, current, "STOPPED")
        _marker(
            connection,
            ENGINE_RELEASE_PREFIX + current.physical_start_id + ":" + current.activation_id,
        )

    @staticmethod
    def _physical_closed(connection: sqlite3.Connection, current: EngineActivation) -> bool:
        physical = LifecycleIntentStore._current(connection)
        if physical is None or (physical.component, physical.target, physical.status) != (
            "bot",
            "stop",
            "APPLIED",
        ):
            return False
        return bool(
            connection.execute(
                "SELECT 1 FROM audit_events s JOIN audit_events e ON e.audit_id=? "
                "WHERE s.audit_id=? AND s.rowid>e.rowid",
                (current.physical_start_id, physical.operation_id),
            ).fetchone()
        )

    def _last_stop(
        self, connection: sqlite3.Connection, current: EngineActivation
    ) -> LifecycleIntent | None:
        if any(not item.released for item in self._load(connection).values()):
            return None
        physical = LifecycleIntentStore._current(connection)
        if physical is None:
            raise EngineStorageUnavailable("engine physical start disappeared")
        if physical.work_start_id == current.physical_start_id:
            return _wake(physical)
        if (
            not physical.on_demand
            or physical.operation_id != current.physical_start_id
            or (physical.component, physical.target) != ("bot", "start")
            or physical.status == "UNCERTAIN"
            or not LifecycleIntentStore._work_finished(
                connection, current.physical_start_id, allow_idle=True
            )
        ):
            return None
        return LifecycleIntentStore._insert_work_stop(connection, current.physical_start_id)

    def _cold_stop(
        self,
        connection: sqlite3.Connection,
        current: EngineActivation,
        *,
        new_request: bool,
    ) -> LifecycleIntent | None:
        """Explicit owner STOP can recover quarantined scopes through the runner.

        Uncertain contexts keep their durable holds until that runner confirms
        physical closure. A live job from this boot cannot be stopped here;
        an uncertain same-boot scope can recover once every peer is fenced.
        """
        held = [item for item in self._load(connection).values() if not item.released]
        if not held or any(
            (item.boot_id == self.boot_id and item.state in _LIVE)
            or item.physical_start_id != current.physical_start_id
            for item in held
        ):
            return None
        for item in held:
            self._set_state(connection, item, "UNCERTAIN")
        physical = LifecycleIntentStore._current(connection)
        if physical is None or not physical.on_demand:
            return None
        if physical.work_start_id == current.physical_start_id:
            if new_request and physical.status in {"CLAIMED", "REFUSED", "FAILED", "UNCERTAIN"}:
                # A fresh owner operation may ask the protected runner to
                # reconfirm closure. Replaying the old ambiguous operation
                # cannot create a second physical effect or erase its receipt.
                return LifecycleIntentStore._insert_work_stop(connection, current.physical_start_id)
            return _wake(physical)
        if physical.operation_id != current.physical_start_id or (
            physical.component,
            physical.target,
        ) != ("bot", "start"):
            return None
        # Explicit owner recovery may supersede uncertain START evidence once
        # every logical scope is fenced. Holds still require real STOP/APPLIED;
        # the automatic _last_stop path deliberately retains its stricter guard.
        return LifecycleIntentStore._insert_work_stop(connection, current.physical_start_id)

    @staticmethod
    def _load(connection: sqlite3.Connection) -> dict[EngineId, EngineActivation]:
        """Validate the append-only namespace before deriving authority from it."""
        activations: dict[str, EngineActivation] = {}
        latest: dict[EngineId, EngineActivation] = {}
        holds: set[str] = set()
        physical_ids: set[str] = set()
        item: EngineActivation | None
        for _rowid, key, action, at in connection.execute(
            "SELECT rowid,audit_id,action,recorded_at FROM audit_events "
            "WHERE substr(action,1,?)=? ORDER BY rowid",
            (len(_PREFIX), _PREFIX),
        ):
            canonical_operation_id(key)
            if not isinstance(at, str) or len(at) != 19 or len(action) > 1024:
                raise EngineStorageUnavailable("invalid engine ledger row")
            if action.startswith(_START):
                raw = action[len(_START) :]
                data = json.loads(raw)
                if (
                    not isinstance(data, dict)
                    or set(data)
                    != {
                        "engine",
                        "generation",
                        "boot_id",
                        "physical_start_id",
                        "member_id",
                        "counts",
                        "credential_fingerprint",
                    }
                    or _json(data) != raw
                ):
                    raise EngineStorageUnavailable("invalid engine start record")
                engine = _engine(data["engine"])
                generation = _generation(data["generation"])
                boot_id = canonical_operation_id(data["boot_id"])
                physical_id = canonical_operation_id(data["physical_start_id"])
                counts = _counts(data["counts"])
                member = data["member_id"]
                fingerprint = data["credential_fingerprint"]
                if member is not None:
                    canonical_operation_id(member)
                if (engine == "browsers_members") != (member is not None):
                    raise EngineStorageUnavailable("invalid engine member selection")
                if (member is not None) != (fingerprint is not None) or (
                    fingerprint is not None
                    and (
                        not isinstance(fingerprint, str)
                        or len(fingerprint) != 64
                        or not set(fingerprint) <= set("0123456789abcdef")
                    )
                ):
                    raise EngineStorageUnavailable("invalid engine credential revision")
                previous = latest.get(engine)
                if generation != (1 if previous is None else previous.generation + 1) or (
                    previous is not None and not previous.released
                ):
                    raise EngineStorageUnavailable("invalid engine generation history")
                if physical_id not in physical_ids:
                    physical = LifecycleIntentStore.for_operation(connection, physical_id)
                    if (
                        physical is None
                        or not physical.on_demand
                        or (physical.component, physical.target) != ("bot", "start")
                    ):
                        raise EngineStorageUnavailable("engine physical start is missing")
                    physical_ids.add(physical_id)
                item = EngineActivation(
                    engine,
                    key,
                    generation,
                    boot_id,
                    physical_id,
                    member,
                    counts,
                    "REQUESTED",
                    at,
                    at,
                    credential_fingerprint=fingerprint,
                )
                activations[key] = latest[engine] = item
            elif action.startswith(_CONTROL):
                parts = action[len(_CONTROL) :].split(":")
                if len(parts) != 4 or parts[0] not in {"start", "stop"}:
                    raise EngineStorageUnavailable("invalid engine control")
                item = activations.get(parts[2])
                if (
                    item is None
                    or item.activation_id not in holds
                    or (parts[1], parts[3]) != (item.engine, str(item.generation))
                    or latest[item.engine] != item
                ):
                    raise EngineStorageUnavailable("orphan engine control")
            elif action.startswith(_STATE):
                parts = action[len(_STATE) :].split(":")
                if len(parts) != 2 or key != str(uuid5(ENGINE_NAMESPACE, action)):
                    raise EngineStorageUnavailable("invalid engine state marker")
                previous = activations.get(parts[0])
                if (
                    previous is None
                    or previous.released
                    or parts[1] not in _TRANSITIONS[previous.state]
                ):
                    raise EngineStorageUnavailable("invalid engine state history")
                item = replace(previous, state=cast(EngineState, parts[1]), updated_at=at)
                activations[item.activation_id] = latest[item.engine] = item
            elif action.startswith((ENGINE_HOLD_PREFIX, ENGINE_RELEASE_PREFIX)):
                releasing = action.startswith(ENGINE_RELEASE_PREFIX)
                prefix = ENGINE_RELEASE_PREFIX if releasing else ENGINE_HOLD_PREFIX
                parts = action[len(prefix) :].split(":")
                if len(parts) != 2 or key != str(uuid5(ENGINE_NAMESPACE, action)):
                    raise EngineStorageUnavailable("invalid engine ownership marker")
                item = activations.get(parts[1])
                if item is None or item.physical_start_id != parts[0] or item.released:
                    raise EngineStorageUnavailable("orphan engine ownership marker")
                if releasing:
                    if item.activation_id not in holds or item.state not in {"STOPPED", "FAILED"}:
                        raise EngineStorageUnavailable("engine released without confirmed closure")
                    item = replace(item, released=True, updated_at=at)
                    activations[item.activation_id] = latest[item.engine] = item
                else:
                    if item.activation_id in holds:
                        raise EngineStorageUnavailable("duplicate engine hold")
                    holds.add(item.activation_id)
            else:
                raise EngineStorageUnavailable("unknown engine ledger action")
        if (
            set(activations) != holds
            or sum(item.requested_contexts for item in activations.values() if not item.released)
            > MAX_CONTEXTS
        ):
            raise EngineStorageUnavailable("engine ownership or budget is inconsistent")
        return latest
