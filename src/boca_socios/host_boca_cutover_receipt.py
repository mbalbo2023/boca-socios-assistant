"""Durable exact-attempt Cutover A terminal receipt, independent of GH runner.

This does NOT authorize an effect. Only the single process already holding the
canonical Boca job lease may write once, after its CutoverReceipt/finalizer.
No file is replaced, no Docker/SQLite/network is touched and no secrets are
accepted. A missing/uncertain terminal receipt is physical NO_GO; a second
SSH Action may observe it but must never infer a cleanup or retry deletion.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from typing import Literal

from boca_socios import host_boca_cleanup as cleanup
from boca_socios.host_boca_cutover import CutoverPlan, CutoverReceipt

VERSION = "boca-cutover-a-terminal-v1"
MAX_RECEIPT_BYTES = 2048
TerminalState = Literal["ACCEPTED", "RECOVERED", "NO_GO"]


class TerminalReceiptError(ValueError):
    """Terminal cutover result absent, mutable or contradictory."""


@dataclass(frozen=True)
class TerminalRecord:
    attempt_id: str
    legacy_source_sha: str
    target_source_sha: str
    legacy_id: str
    state: TerminalState
    cleanup: Literal["ACCEPT", "NO_GO", "INDETERMINATE"]
    original_restored: bool
    irreversible_commit_started: bool
    candidate_id: str | None
    worker_id: str | None

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
            receipt.state,
            receipt.cleanup,
            receipt.original_restored,
            receipt.irreversible_commit_started,
            receipt.candidate_id,
            receipt.worker_id,
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
        # NO_GO is deliberately broad: an old ID may be parked, restored or
        # already gone, with positive/negative/unknown inventory. Preserve the
        # genuine uncertainty rather than rejecting an incident's evidence.
        payload = {
            "version": VERSION,
            "attempt_id": self.attempt_id,
            "legacy_source_sha": self.legacy_source_sha,
            "target_source_sha": self.target_source_sha,
            "legacy_id": self.legacy_id,
            "state": self.state,
            "cleanup": self.cleanup,
            "original_restored": self.original_restored,
            "irreversible_commit_started": self.irreversible_commit_started,
            "candidate_id": self.candidate_id,
            "worker_id": self.worker_id,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "ascii"
        )
        if not 0 < len(raw) <= MAX_RECEIPT_BYTES:
            raise TerminalReceiptError("cutover terminal bounded payload invalid")
        return raw


def _name(attempt_id: str) -> str:
    if not cleanup.ATTEMPT_ID.fullmatch(attempt_id):
        raise TerminalReceiptError("cutover immutable run ID invalid")
    return f"boca-cutover-a-result-{attempt_id}.json"


def _directory() -> int:
    try:
        fd = os.open(cleanup.LEASE_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(fd)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != cleanup.EXPECTED_UID
            or info.st_gid != cleanup.EXPECTED_UID
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise TerminalReceiptError("cutover terminal receipt owner directory invalid")
        return fd
    except BaseException:
        if "fd" in locals():
            os.close(fd)
        raise


def _read_exact(folder: int, name: str, expected: bytes) -> None:
    try:
        fd = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=folder
        )
    except OSError as exc:
        raise TerminalReceiptError("cutover terminal result disappeared") from exc
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != cleanup.EXPECTED_UID
            or before.st_gid != cleanup.EXPECTED_UID
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size != len(expected)
        ):
            raise TerminalReceiptError("cutover terminal receipt inode or mode changed")
        received = os.read(fd, MAX_RECEIPT_BYTES + 1)
        after = os.fstat(fd)
        if received != expected or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise TerminalReceiptError("cutover terminal receipt bytes changed during readback")
    finally:
        os.close(fd)


def write_once(record: TerminalRecord, *, lease: cleanup.BocaJobLease) -> str:
    """O_EXCL+fsync+readback while still holding the exact protected lease."""
    cleanup.verify_protected_boca_job_lease(lease, record.attempt_id)
    raw = record.serialized()
    name = _name(record.attempt_id)
    folder = _directory()
    try:
        try:
            fd = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=folder,
            )
        except OSError as exc:
            raise TerminalReceiptError(
                "cutover terminal result cannot be created exclusively"
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
            # Truncated/uncertain file is evidence; no delete and no retry.
            raise TerminalReceiptError("cutover terminal result persistence uncertain") from exc
    finally:
        os.close(folder)
    return hashlib.sha256(raw).hexdigest()
