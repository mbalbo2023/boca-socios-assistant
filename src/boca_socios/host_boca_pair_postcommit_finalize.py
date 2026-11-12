"""R186 one-shot, postcommit-only finalization for Boca incident 43217075287.

The dual pair was already installed in the *original* failed APPLY. This
program cannot recreate, restart or remove containers, alter systemd, access
member credentials or read SQLite bytes. Under a fresh authenticated rootless
lease, it verifies the original O_EXCL journal and every historical binding
byte, records its own non-replayable claim, and retires only the old parked
binding through the existing exact-file primitive. After claim, uncertainty
is always INDETERMINATE; the original NO_GO journal remains immutable.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass

from boca_socios import host_boca_binding_observe as binding_observe
from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_pair_postcommit as postcommit
from boca_socios import host_boca_pair_upgrade_cli as upgrade_cli
from boca_socios import host_boca_sqlite_identity as sqlite
from boca_socios import host_cutover_stage as stage
from boca_socios import host_first_deploy as host
from boca_socios import host_on_demand_replace as replace
from boca_socios import host_on_demand_service as service
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation

_INCIDENT = postcommit.FAILED_ATTEMPT
_OLD_ATTEMPT = "42806447101"
_OLD_SHA = "03df9a14bdd78cf768386a865876fed9d5656911"
_RELEASE = "43215180354"
_JOURNAL = ".boca-pair-upgrade-" + _INCIDENT
_FINAL = ".boca-postcommit-finalize-" + _INCIDENT
_PREFIX = b"BOCA_POSTCOMMIT_FINALIZE "
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_ID = re.compile(r"[a-f0-9]{64}\Z")
_FIELDS = frozenset(
    {
        "schema",
        "incident_attempt",
        "recovery_run_id",
        "state",
        "cleanup",
        "postcommit_only",
        "foreign_resources_touched",
        "ticket_actions",
    }
)


class FinalizeNoGo(ValueError):
    """One fixed Boca incident could not be safely certified."""


@dataclass(frozen=True, slots=True)
class OriginalJournal:
    old_controller_id: str
    old_worker_id: str
    digest: str
    intent: bytes
    commit: bytes
    terminal: bytes


@dataclass(frozen=True, slots=True, repr=False)
class _Evidence:
    journal: OriginalJournal
    old: OnDemandInstallation
    new: OnDemandInstallation
    sqlite_inode: sqlite.SqliteIdentity


def _unique(items: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for name, value in items:
        if name in output:
            raise FinalizeNoGo("duplicate original journal field")
        output[name] = value
    return output


def _canonical(value: dict[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def _journal() -> OriginalJournal:
    """Authenticate only the fixed original intent, commit and NO_GO terminal.

    Reads at most 1024 bytes per reviewed Boca-only inode, with no-follow,
    mode/owner/link checks. Never changes the failed deployment's record.
    """
    fd = stage._root_fd()
    try:
        intent, _ = stage._read_file(fd, _JOURNAL + ".intent", None, limit=1024)
        commit, _ = stage._read_file(fd, _JOURNAL + ".commit", None, limit=1024)
        terminal, _ = stage._read_file(fd, _JOURNAL + ".terminal", None, limit=1024)
    except (stage.StageError, OSError) as exc:
        raise FinalizeNoGo("original incident journal unavailable") from exc
    finally:
        os.close(fd)
    try:
        record = json.loads(intent, object_pairs_hook=_unique)
        upgrade_cli.verify_upgrade(terminal, _INCIDENT)
        receipt = json.loads(
            terminal.removeprefix(b"BOCA_PAIR_UPGRADE "), object_pairs_hook=_unique
        )
    except (ValueError, TypeError, UnicodeError) as exc:
        raise FinalizeNoGo("original incident journal malformed") from exc
    if (
        type(record) is not dict
        or record.keys()
        != {"attempt", "old_controller", "old_worker", "old_source", "new_source", "release"}
        or record["attempt"] != _INCIDENT
        or record["old_source"] != _OLD_SHA
        or record["new_source"] != postcommit.SOURCE_SHA
        or record["release"] != _RELEASE
        or type(record["old_controller"]) is not str
        or _ID.fullmatch(record["old_controller"]) is None
        or type(record["old_worker"]) is not str
        or _ID.fullmatch(record["old_worker"]) is None
        or len(
            {
                record["old_controller"],
                record["old_worker"],
                postcommit.CONTROLLER_ID,
                postcommit.WORKER_ID,
            }
        )
        != 4
        or intent != _canonical(record)
        or commit != hashlib.sha256(intent).hexdigest().encode("ascii")
        or receipt.get("state") != "NO_GO"
        or receipt.get("cleanup") != "INDETERMINATE"
        or receipt.get("commit_started") is not True
        or receipt.get("old_restored") is not False
        or receipt.get("failed_phase") != "RETIRE_OLD"
        or receipt.get("controller_id") not in (None, postcommit.CONTROLLER_ID)
        or receipt.get("worker_id") not in (None, postcommit.WORKER_ID)
    ):
        raise FinalizeNoGo("original journal does not prove fixed postcommit incident")
    return OriginalJournal(
        record["old_controller"],
        record["old_worker"],
        hashlib.sha256(intent).hexdigest(),
        intent,
        commit,
        terminal,
    )


def encode(recovery_run_id: str, state: str) -> bytes:
    if (
        type(recovery_run_id) is not str
        or _RUN.fullmatch(recovery_run_id) is None
        or recovery_run_id == _INCIDENT
        or state not in ("ACCEPTED", "NO_GO", "INDETERMINATE")
    ):
        raise FinalizeNoGo("invalid one-shot finalizer receipt")
    value: dict[str, object] = {
        "schema": 1,
        "incident_attempt": _INCIDENT,
        "recovery_run_id": recovery_run_id,
        "state": state,
        "cleanup": "ACCEPT"
        if state == "ACCEPTED"
        else "NO_GO"
        if state == "NO_GO"
        else "INDETERMINATE",
        "postcommit_only": True,
        "foreign_resources_touched": 0,
        "ticket_actions": 0,
    }
    raw = _PREFIX + _canonical(value) + b"\n"
    verify(raw, recovery_run_id)
    return raw


def verify(raw: bytes, run_id: str) -> bytes:
    if (
        type(raw) is not bytes
        or not 0 < len(raw) <= 512
        or not raw.startswith(_PREFIX)
        or not raw.endswith(b"\n")
        or raw.count(b"\n") != 1
        or type(run_id) is not str
        or _RUN.fullmatch(run_id) is None
        or run_id == _INCIDENT
    ):
        raise FinalizeNoGo("unbounded finalizer receipt")
    try:
        value = json.loads(raw[len(_PREFIX) : -1], object_pairs_hook=_unique)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise FinalizeNoGo("invalid finalizer JSON") from exc
    if (
        type(value) is not dict
        or value.keys() != _FIELDS
        or type(value["schema"]) is not int
        or value["schema"] != 1
        or value["incident_attempt"] != _INCIDENT
        or value["recovery_run_id"] != run_id
        or value["state"] not in ("ACCEPTED", "NO_GO", "INDETERMINATE")
        or value["cleanup"]
        != {"ACCEPTED": "ACCEPT", "NO_GO": "NO_GO", "INDETERMINATE": "INDETERMINATE"}[
            value["state"]
        ]
        or value["postcommit_only"] is not True
        or type(value["foreign_resources_touched"]) is not int
        or value["foreign_resources_touched"] != 0
        or type(value["ticket_actions"]) is not int
        or value["ticket_actions"] != 0
        or raw != _PREFIX + _canonical(value) + b"\n"
    ):
        raise FinalizeNoGo("finalizer receipt not canonical")
    return raw


def _claim(run_id: str, journal: OriginalJournal) -> None:
    """Durable, once-ever claim keyed by *incident*, not the recovery run.

    A missing acknowledgement, orphaned claim or partially retired parked
    files is not retryable. Never remove an existing claim automatically.
    """
    if type(run_id) is not str or _RUN.fullmatch(run_id) is None or run_id == _INCIDENT:
        raise FinalizeNoGo("invalid recovery lease")
    marker = _canonical(
        {
            "schema": 1,
            "incident_attempt": _INCIDENT,
            "recovery_run_id": run_id,
            "original_intent_sha256": journal.digest,
        }
    )
    fd = stage._root_fd()
    try:
        stage._create_exclusive(fd, _FINAL + ".claim", marker)
    except (stage.StageError, OSError) as exc:
        raise FinalizeNoGo("one-shot finalizer already claimed or indeterminate") from exc
    finally:
        os.close(fd)


def _terminal(run_id: str, state: str) -> None:
    fd = stage._root_fd()
    try:
        stage._create_exclusive(fd, _FINAL + ".terminal", encode(run_id, state))
    finally:
        os.close(fd)


def _attest_pair(run_id: str, *, parked: bool) -> None:
    raw = postcommit.observe(run_id)
    postcommit.verify(raw, run_id)
    value = json.loads(raw[len(postcommit.PREFIX) :], object_pairs_hook=_unique)
    if (
        value["pair"] != "PASS"
        or value["pair_reason"] != "NONE"
        or value["new_pair_only"] is not True
        or value["old_ids_absent"] is not True
        or value["socket_node"] != "ABSENT"
    ):
        raise FinalizeNoGo("fixed Boca pair no longer matches accepted installation")
    required = (
        {
            "parked": "DIRECTORY",
            "intent": "FILE",
            "socket_directory": "DIRECTORY",
            "parked_marker": "FILE",
            "parked_binding": "FILE",
            "parked_archive": "FILE",
            "parked_unit_socket": "FILE",
            "parked_unit_service": "FILE",
        }
        if parked
        else {
            "parked": "ABSENT",
            "intent": "ABSENT",
            "socket_directory": "ABSENT",
            "parked_marker": "ABSENT",
            "parked_binding": "ABSENT",
            "parked_archive": "ABSENT",
            "parked_unit_socket": "ABSENT",
            "parked_unit_service": "ABSENT",
        }
    )
    if any(value[name] != kind for name, kind in required.items()):
        raise FinalizeNoGo("unexpected historical binding state")


def _attest_binding(run_id: str) -> OnDemandInstallation:
    raw = binding_observe.observe(run_id)
    binding_observe.verify(raw, run_id)
    item = service._verified_installation(service._home())
    if (
        item.installation_run_id != _INCIDENT
        or item.source_sha != postcommit.SOURCE_SHA
        or item.controller_id != postcommit.CONTROLLER_ID
        or item.worker_id != postcommit.WORKER_ID
        or item.controller_image != postcommit.CONTROLLER_IMAGE
        or item.worker_image != postcommit.WORKER_IMAGE
        or item.database_path != service._HOME / service._DB
    ):
        raise FinalizeNoGo("binding changed from fixed incident")
    return item


def _attest_sqlite() -> sqlite.SqliteIdentity:
    docker = host._checked_docker_storage_dir()
    sqlite._attest_boundary(docker)
    before = sqlite.capture_sqlite_identity(docker)
    sqlite._attest_boundary(docker)
    if sqlite.capture_sqlite_identity(docker) != before:
        raise FinalizeNoGo("Boca SQLite inode changed during observation")
    return before


def _old_binding(journal: OriginalJournal) -> OnDemandInstallation:
    home = service._home()
    parked = home / (replace._PARKED_PREFIX + _INCIDENT)
    item, _ = service._decode(home, service._read(parked / service._BINDING, service._MAX_PLAN))
    if (
        item.installation_run_id != _OLD_ATTEMPT
        or item.source_sha != _OLD_SHA
        or item.controller_id != journal.old_controller_id
        or item.worker_id != journal.old_worker_id
        or item.database_path != service._HOME / service._DB
    ):
        raise FinalizeNoGo("original parked Boca provenance drift")
    replace._intended(home, item, _INCIDENT)
    replace._historic(parked, home, item)
    return item


def _preflight(run_id: str) -> _Evidence:
    first_journal = _journal()
    _attest_pair(run_id, parked=True)
    binding = _attest_binding(run_id)
    original = _old_binding(first_journal)
    inode = _attest_sqlite()
    _attest_pair(run_id, parked=True)
    if (
        _journal() != first_journal
        or _attest_binding(run_id) != binding
        or _old_binding(first_journal) != original
        or _attest_sqlite() != inode
    ):
        raise FinalizeNoGo("Boca binding, journal or SQLite changed between preflight captures")
    return _Evidence(first_journal, original, binding, inode)


def _postflight(run_id: str, before: _Evidence) -> None:
    _attest_pair(run_id, parked=False)
    if (
        _attest_binding(run_id) != before.new
        or _attest_sqlite() != before.sqlite_inode
        or _journal() != before.journal
    ):
        raise FinalizeNoGo("Boca postcommit state changed during historic retirement")


def finalize(run_id: str) -> bytes:
    """The only effectful entrypoint; quarantine any uncertainty after claim."""
    if type(run_id) is not str or _RUN.fullmatch(run_id) is None or run_id == _INCIDENT:
        raise FinalizeNoGo("recovery run is not a distinct protected job")
    with cleanup.protected_boca_job_lease(run_id) as lease:
        cleanup.verify_protected_boca_job_lease(lease, run_id)
        evidence = _preflight(run_id)
        cleanup.verify_protected_boca_job_lease(lease, run_id)
        # The claim is the irreversible boundary: NO automatic retry afterward.
        _claim(run_id, evidence.journal)
        try:
            replace.commit_binding_postcommit(evidence.old, evidence.new, _INCIDENT, run_id, lease)
            cleanup.verify_protected_boca_job_lease(lease, run_id)
            _postflight(run_id, evidence)
            _terminal(run_id, "ACCEPTED")
        except Exception:
            # An uncertain unlink, fsync, journal or postflight must not be
            # misreported as completed. The original NO_GO is unchanged.
            try:
                _terminal(run_id, "INDETERMINATE")
            except Exception:
                return encode(run_id, "INDETERMINATE")
            return encode(run_id, "INDETERMINATE")
        return encode(run_id, "ACCEPTED")


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] not in ("host", "verify"):
        return 3
    run_id = args[1]
    try:
        raw = finalize(run_id) if args[0] == "host" else verify(sys.stdin.buffer.read(513), run_id)
    except Exception:
        # Before claim, a NO_GO is read-only; after an uncertain marker write,
        # NO_GO is still conservative (never ACCEPTED) with host journals held.
        try:
            raw = encode(run_id, "NO_GO")
        except FinalizeNoGo:
            return 3
    sys.stdout.buffer.write(raw)
    return 0 if b'"state":"ACCEPTED"' in raw else 3


if __name__ == "__main__":  # pragma: no cover - host verified ZIP only
    raise SystemExit(main())
