"""Persistent exact-attempt Cutover A intent/result, independent of GH runner.

This does NOT authorize an effect. Only the single process already holding the
canonical Boca job lease may write once, after its CutoverReceipt/finalizer.
The same lease reserves an O_EXCL intent BEFORE any Docker phase. Both markers
live under the dedicated rootless Boca user's disk-backed, host-only home,
never volatile /run, the strict /srv/boca-socios Compose stage, or a controller
RW volume. No file is replaced, no Docker/SQLite/network is touched and no
secrets are accepted. A missing/uncertain result is physical NO_GO; a later
read-only observation must never infer cleanup or retry deletion.
"""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from boca_socios import host_boca_cleanup as cleanup
from boca_socios.host_boca_cutover import (
    WORKER_COMPENSATION_STATES,
    WORKER_PRIMARY_PHASES,
    CutoverPlan,
    CutoverReceipt,
    valid_worker_exit_evidence,
)

VERSION = "boca-cutover-a-terminal-v1"
VERSION_V2 = "boca-cutover-a-terminal-v2"
VERSION_V3 = "boca-cutover-a-terminal-v3"
INTENT_VERSION = "boca-cutover-a-intent-v1"
RECEIPT_DIR_NAME = ".boca-socios-cutover-receipts"
MAX_RECEIPT_BYTES = 2048
MIN_FREE_BYTES = 1024 * 1024
MIN_FREE_INODES = 8
PERSISTENT_FS = frozenset({"ext4", "xfs", "btrfs", "zfs", "f2fs", "bcachefs"})
MOUNTINFO = Path("/proc/self/mountinfo")
TerminalState = Literal["ACCEPTED", "RECOVERED", "NO_GO"]


class TerminalReceiptError(ValueError):
    """Terminal cutover result absent, mutable or contradictory."""


@dataclass(frozen=True)
class TerminalRecord:
    attempt_id: str
    legacy_source_sha: str
    target_source_sha: str
    legacy_id: str
    intent_sha256: str
    state: TerminalState
    cleanup: Literal["ACCEPT", "NO_GO", "INDETERMINATE"]
    original_restored: bool
    irreversible_commit_started: bool
    candidate_id: str | None
    worker_id: str | None
    worker_primary_phase: str = "NONE"
    worker_compensation: str = "NONE"
    worker_exit_code: int | Literal["UNKNOWN"] | None = None
    worker_oom_killed: bool | Literal["UNKNOWN"] | None = None

    @classmethod
    def from_receipt(cls, plan: CutoverPlan, receipt: CutoverReceipt) -> TerminalRecord:
        plan.validate()
        if receipt.attempt_id != plan.attempt_id:
            raise TerminalReceiptError("cutover terminal result run mismatch")
        if (
            receipt.state == "ACCEPTED"
            and (
                not receipt.accepted
                or not receipt.irreversible_commit_started
                or receipt.original_restored
            )
            or receipt.state == "RECOVERED"
            and (
                not receipt.original_restored
                or receipt.irreversible_commit_started
                or receipt.cleanup != "ACCEPT"
            )
        ):
            raise TerminalReceiptError("cutover success or recovery result is inconsistent")
        return cls(
            plan.attempt_id,
            plan.legacy_sha,
            plan.target_sha,
            plan.legacy_id,
            hashlib.sha256(_intent_bytes(plan)).hexdigest(),
            receipt.state,
            receipt.cleanup,
            receipt.original_restored,
            receipt.irreversible_commit_started,
            receipt.candidate_id,
            receipt.worker_id,
            receipt.worker_primary_phase if receipt.failed_phase == "PREPARE_WORKER" else "NONE",
            receipt.worker_compensation if receipt.failed_phase == "PREPARE_WORKER" else "NONE",
            receipt.worker_exit_code if receipt.failed_phase == "PREPARE_WORKER" else None,
            receipt.worker_oom_killed if receipt.failed_phase == "PREPARE_WORKER" else None,
        )

    def serialized(self) -> bytes:
        if (
            not cleanup.ATTEMPT_ID.fullmatch(self.attempt_id)
            or not cleanup.HEX_ID.fullmatch(self.legacy_id)
            or any(
                not cleanup.HEX_ID.fullmatch(value)
                for value in (self.candidate_id, self.worker_id)
                if value is not None
            )
            or self.state not in ("ACCEPTED", "RECOVERED", "NO_GO")
            or self.cleanup not in ("ACCEPT", "NO_GO", "INDETERMINATE")
            or type(self.original_restored) is not bool
            or type(self.irreversible_commit_started) is not bool
            or any(
                len(value) != 40 or any(char not in "0123456789abcdef" for char in value)
                for value in (self.legacy_source_sha, self.target_source_sha)
            )
            or self.legacy_source_sha == self.target_source_sha
            or not re.fullmatch(r"[0-9a-f]{64}", self.intent_sha256)
        ):
            raise TerminalReceiptError("cutover terminal payload coordinates invalid")
        if self.state == "ACCEPTED" and (
            self.cleanup != "ACCEPT"
            or not self.irreversible_commit_started
            or self.original_restored
            or self.candidate_id is None
            or self.worker_id is None
            or len({self.legacy_id, self.candidate_id, self.worker_id}) != 3
        ):
            raise TerminalReceiptError("cutover positive terminal result untrusted")
        if self.state == "RECOVERED" and (
            self.cleanup != "ACCEPT"
            or not self.original_restored
            or self.irreversible_commit_started
        ):
            raise TerminalReceiptError("cutover recovered result untrusted")
        typed = (self.worker_primary_phase, self.worker_compensation) != ("NONE", "NONE")
        if typed and (
            self.state == "ACCEPTED"
            or self.worker_primary_phase not in WORKER_PRIMARY_PHASES
            or self.worker_compensation not in WORKER_COMPENSATION_STATES
        ):
            raise TerminalReceiptError("cutover typed worker failure invalid")
        v3 = self.worker_exit_code is not None or self.worker_oom_killed is not None
        if v3 and (
            not typed
            or not valid_worker_exit_evidence(
                self.worker_primary_phase, self.worker_exit_code, self.worker_oom_killed
            )
        ):
            raise TerminalReceiptError("cutover worker exit evidence schema invalid")
        # NO_GO is deliberately broad: an old ID may be parked, restored or
        # already gone, with positive/negative/unknown inventory. Preserve the
        # genuine uncertainty rather than rejecting an incident's evidence.
        payload = {
            "version": VERSION_V3 if v3 else VERSION_V2 if typed else VERSION,
            "attempt_id": self.attempt_id,
            "legacy_source_sha": self.legacy_source_sha,
            "target_source_sha": self.target_source_sha,
            "legacy_id": self.legacy_id,
            "intent_sha256": self.intent_sha256,
            "state": self.state,
            "cleanup": self.cleanup,
            "original_restored": self.original_restored,
            "irreversible_commit_started": self.irreversible_commit_started,
            "candidate_id": self.candidate_id,
            "worker_id": self.worker_id,
        }
        if typed:
            payload["worker_primary_phase"] = self.worker_primary_phase
            payload["worker_compensation"] = self.worker_compensation
        if v3:
            payload["worker_exit_code"] = self.worker_exit_code
            payload["worker_oom_killed"] = self.worker_oom_killed
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "ascii"
        )
        if not 0 < len(raw) <= MAX_RECEIPT_BYTES:
            raise TerminalReceiptError("cutover terminal bounded payload invalid")
        return raw


def _name(attempt_id: str, kind: Literal["intent", "result"] = "result") -> str:
    if not cleanup.ATTEMPT_ID.fullmatch(attempt_id) or kind not in ("intent", "result"):
        raise TerminalReceiptError("cutover immutable run ID/marker kind invalid")
    return f"boca-cutover-a-{kind}-{attempt_id}.json"


def _intent_bytes(plan: CutoverPlan) -> bytes:
    plan.validate()
    data = {
        "version": INTENT_VERSION,
        "attempt_id": plan.attempt_id,
        "legacy_id": plan.legacy_id,
        "legacy_source_sha": plan.legacy_sha,
        "legacy_image_ref": plan.legacy_image,
        "legacy_compose_sha": plan.legacy_compose_sha,
        "target_source_sha": plan.target_sha,
        "target_image_ref": plan.target_image,
        "browser_image_ref": plan.browser_image,
        "target_compose_sha": plan.target_compose_sha,
        "overlay_sha": plan.overlay_sha,
        "seccomp_sha": plan.seccomp_sha,
        "owner_subject_sha256": hashlib.sha256(plan.owner_subject.encode("utf-8")).hexdigest(),
        "origin": plan.origin,
    }
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    if not 0 < len(payload) <= MAX_RECEIPT_BYTES:
        raise TerminalReceiptError("cutover persistent intent payload unbounded")
    return payload


def _account_home() -> Path:
    try:
        account = pwd.getpwuid(cleanup.EXPECTED_UID)
    except KeyError as exc:
        raise TerminalReceiptError("cutover Boca account unavailable") from exc
    home = Path(account.pw_dir)
    if (
        account.pw_name != "boca-deploy"
        or not home.is_absolute()
        or ".." in home.parts
        or home == Path("/")
        or len(home.parts) < 3
        or home.parts[1] in {"run", "tmp", "var", "dev", "proc", "sys"}
        or home == Path("/srv/boca-socios")
        or Path("/srv/boca-socios") in home.parents
    ):
        raise TerminalReceiptError("cutover private persistent Boca home untrusted")
    return home


def _persistent_mount(home: Path) -> None:
    """Require a disk-backed home mount, never tmpfs/ramfs/overlay runtime."""
    try:
        raw = MOUNTINFO.read_text(encoding="utf-8")
        if not 0 < len(raw) <= 256_000:
            raise TerminalReceiptError("cutover mount inventory unbounded")
    except (OSError, UnicodeError) as exc:
        raise TerminalReceiptError("cutover durable mountpoint unverifiable") from exc
    selected: tuple[int, str] | None = None
    for line in raw.splitlines():
        sections = line.split(" - ", 1)
        if len(sections) != 2:
            raise TerminalReceiptError("cutover mount inventory malformed")
        details, filesystem = sections[0].split(), sections[1].split()
        if len(details) < 5 or len(filesystem) < 1:
            raise TerminalReceiptError("cutover mount inventory malformed")
        # Linux mountinfo encodes spaces/backslashes in paths as octal escapes.
        location = re.sub(
            r"\\([0-7]{3})",
            lambda match: chr(int(match.group(1), 8)),
            details[4],
        )
        mount = Path(location)
        if mount == home or mount in home.parents:
            depth = len(mount.parts)
            if selected is None or depth > selected[0]:
                selected = (depth, filesystem[0])
            elif depth == selected[0]:
                # Stacked mounts at the same path cannot be disambiguated by
                # a simple longest-prefix match. Never assume the first is
                # still the active disk-backed filesystem.
                raise TerminalReceiptError("cutover durable mount stack ambiguous")
    if selected is None or selected[1] not in PERSISTENT_FS:
        raise TerminalReceiptError("cutover terminal home is not proven persistent storage")


def _directory(*, create: bool = False) -> int:
    home = _account_home()
    if home.resolve(strict=True) != home:
        raise TerminalReceiptError("cutover Boca home path redirects through a symlink")
    _persistent_mount(home)
    parent: int | None = None
    child: int | None = None
    try:
        parent = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(parent)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != cleanup.EXPECTED_UID
            or info.st_gid != cleanup.EXPECTED_UID
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise TerminalReceiptError("cutover Boca home owner/mode untrusted")
        capacity = os.statvfs(parent)
        if (
            capacity.f_bavail * capacity.f_frsize < MIN_FREE_BYTES
            or capacity.f_favail < MIN_FREE_INODES
        ):
            raise TerminalReceiptError("cutover persistent receipt disk/inodes exhausted")
        if create:
            try:
                os.mkdir(RECEIPT_DIR_NAME, 0o700, dir_fd=parent)
                os.fsync(parent)
            except FileExistsError:
                pass
        child = os.open(
            RECEIPT_DIR_NAME,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent,
        )
        # A child bind/tmpfs mount can hide underneath an otherwise durable
        # home. Recheck the *actual receipt directory* after its FD is open.
        _persistent_mount(home / RECEIPT_DIR_NAME)
        metadata = os.fstat(child)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != cleanup.EXPECTED_UID
            or metadata.st_gid != cleanup.EXPECTED_UID
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_nlink != 2
        ):
            raise TerminalReceiptError("cutover persistent receipt directory unsafe")
        entries = os.listdir(child)
        if len(entries) > 2048 or any(
            re.fullmatch(r"boca-cutover-a-(?:intent|result)-[1-9][0-9]{0,19}\.json", name) is None
            for name in entries
        ):
            raise TerminalReceiptError("cutover persistent receipt directory has unknown entries")
        for name in entries:
            entry = os.stat(name, dir_fd=child, follow_symlinks=False)
            if (
                not stat.S_ISREG(entry.st_mode)
                or entry.st_uid != cleanup.EXPECTED_UID
                or entry.st_gid != cleanup.EXPECTED_UID
                or entry.st_nlink != 1
                or stat.S_IMODE(entry.st_mode) != 0o600
            ):
                raise TerminalReceiptError(
                    "cutover persistent receipt directory contains unsafe file"
                )
        result = child
        child = None
        return result
    except OSError as exc:
        raise TerminalReceiptError("cutover persistent receipt destination unavailable") from exc
    finally:
        if child is not None:
            os.close(child)
        if parent is not None:
            os.close(parent)


def _read_exact(folder: int, name: str, expected: bytes) -> None:
    received = _read_marker(folder, name)
    if received != expected:
        raise TerminalReceiptError("cutover persistent receipt differs from original bytes")


def _read_marker(folder: int, name: str) -> bytes:
    try:
        fd = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=folder
        )
    except OSError as exc:
        raise TerminalReceiptError("cutover persistent receipt marker unavailable") from exc
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != cleanup.EXPECTED_UID
            or before.st_gid != cleanup.EXPECTED_UID
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 0 < before.st_size <= MAX_RECEIPT_BYTES
        ):
            raise TerminalReceiptError("cutover persistent receipt inode or mode changed")
        received = os.read(fd, MAX_RECEIPT_BYTES + 1)
        after = os.fstat(fd)
        if len(received) != before.st_size or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise TerminalReceiptError("cutover persistent receipt bytes changed during readback")
        return received
    finally:
        os.close(fd)


def _create_once(folder: int, name: str, raw: bytes) -> str:
    try:
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=folder,
        )
    except OSError as exc:
        raise TerminalReceiptError(
            "cutover persistent marker cannot be created exclusively"
        ) from exc
    try:
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.fsync(folder)
        _read_exact(folder, name, raw)
    except OSError as exc:
        # A truncated/unknown marker is evidence; no delete and no retry.
        raise TerminalReceiptError("cutover persistent marker outcome uncertain") from exc
    return hashlib.sha256(raw).hexdigest()


def prepare_destination(plan: CutoverPlan, lease: cleanup.BocaJobLease) -> str:
    """Reserve disk-backed intent before any Docker/legacy controller phase.

    O_EXCL intent plus positive disk/UID/mode/inode readback precede all host
    transitions. Existing intent/result forbids reusing the same GitHub run;
    loss of terminal result later is quarantined, never auto-cleaned/retried.
    """
    cleanup.verify_protected_boca_job_lease(lease, plan.attempt_id)
    raw = _intent_bytes(plan)
    folder = _directory(create=True)
    try:
        try:
            os.stat(_name(plan.attempt_id), dir_fd=folder, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise TerminalReceiptError("cutover exact attempt already has a terminal marker")
        return _create_once(folder, _name(plan.attempt_id, "intent"), raw)
    finally:
        os.close(folder)


def write_once(record: TerminalRecord, *, plan: CutoverPlan, lease: cleanup.BocaJobLease) -> str:
    """Post-finalizer terminal O_EXCL+fsync under SAME lease and persistent intent."""
    cleanup.verify_protected_boca_job_lease(lease, record.attempt_id)
    intent = _intent_bytes(plan)
    expected_intent_sha = hashlib.sha256(intent).hexdigest()
    if (
        plan.attempt_id != record.attempt_id
        or plan.legacy_sha != record.legacy_source_sha
        or plan.target_sha != record.target_source_sha
        or plan.legacy_id != record.legacy_id
        or record.intent_sha256 != expected_intent_sha
    ):
        raise TerminalReceiptError("cutover terminal record not bound to persistent plan")
    raw = record.serialized()
    folder = _directory()
    try:
        _read_exact(folder, _name(plan.attempt_id, "intent"), intent)
        return _create_once(folder, _name(plan.attempt_id), raw)
    finally:
        os.close(folder)


Reconciliation = Literal["INTENT_ONLY_NO_GO", "RECORD_PRESENT_RUNTIME_UNVERIFIED"]


def reconcile_persisted(plan: CutoverPlan) -> Reconciliation:
    """Read-only post-reboot reconciliation; NEVER grants runtime GO or deletion.

    A result can prove what an earlier process durably claimed, but cannot
    attest Docker/loopback/Telegram state after a restart. The pending intent
    without result is explicit quarantine/NO_GO, not permission to replay.
    """
    intent = _intent_bytes(plan)
    folder = _directory()
    try:
        _read_exact(folder, _name(plan.attempt_id, "intent"), intent)
        try:
            os.stat(_name(plan.attempt_id), dir_fd=folder, follow_symlinks=False)
        except FileNotFoundError:
            return "INTENT_ONLY_NO_GO"
        raw = _read_marker(folder, _name(plan.attempt_id))
        try:
            payload = json.loads(raw.decode("ascii"), object_pairs_hook=_unique_fields)
            if not isinstance(payload, dict):
                raise TerminalReceiptError("cutover stored terminal result schema invalid")
            version = payload.pop("version", None)
            fields = set(TerminalRecord.__dataclass_fields__)
            v3_fields = {"worker_exit_code", "worker_oom_killed"}
            v2_fields = {"worker_primary_phase", "worker_compensation"}
            expected = {
                VERSION: fields - v2_fields - v3_fields,
                VERSION_V2: fields - v3_fields,
                VERSION_V3: fields,
            }.get(version)
            if expected is None or set(payload) != expected:
                raise TerminalReceiptError("cutover stored terminal result fields untrusted")
            result = TerminalRecord(**payload)
            if (
                result.serialized() != raw
                or result.attempt_id != plan.attempt_id
                or result.intent_sha256 != hashlib.sha256(intent).hexdigest()
                or result.legacy_source_sha != plan.legacy_sha
                or result.target_source_sha != plan.target_sha
                or result.legacy_id != plan.legacy_id
            ):
                raise TerminalReceiptError("cutover stored terminal result conflicts with intent")
        except (UnicodeError, json.JSONDecodeError, TypeError) as exc:
            raise TerminalReceiptError("cutover stored terminal result malformed") from exc
        return "RECORD_PRESENT_RUNTIME_UNVERIFIED"
    finally:
        os.close(folder)


def verify_persisted_exact(plan: CutoverPlan, receipt: CutoverReceipt) -> None:
    """Require the *exact* terminal result, not merely a present result file.

    A previous NO_GO marker for the same run must never authorize a fabricated
    ACCEPTED CLI response. Reconcile the immutable source intent and every
    serialized field against the current in-process CutoverReceipt.
    """
    expected = TerminalRecord.from_receipt(plan, receipt).serialized()
    folder = _directory()
    try:
        _read_exact(folder, _name(plan.attempt_id, "intent"), _intent_bytes(plan))
        _read_exact(folder, _name(plan.attempt_id), expected)
    finally:
        os.close(folder)


def _unique_fields(fields: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in fields:
        if key in result:
            raise TerminalReceiptError("cutover persistent result duplicate field")
        result[key] = value
    return result
