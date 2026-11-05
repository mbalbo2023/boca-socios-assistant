"""Code-only, exact-artifact import of ONE non-actionable public Boca notice.

No network, Actions dispatch, Docker, browser, SQLite, Telegram or ticket I/O.
The future protected Cutover owner must independently review and pin the
GitHub artifact before supplying its bytes. This code neither obtains a host
GO nor authenticates a claimed GitHub URL by making a network request.
"""

from __future__ import annotations

import fcntl
import hashlib
import io
import json
import os
import re
import secrets
import stat
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from .official_catalog import OfficialCatalogError, load_observed_notice
from .official_news_receipt import (
    _REQUIRED_MARKERS,
    OFFICIAL_NEWS_URL,
    split_public_observation_envelope,
)
from .official_snapshot import (
    OFFICIAL_SNAPSHOT_NAME,
    OfficialSnapshotError,
    _identity,
    _open_parent_no_symlinks,
    _read_snapshot,
    load_official_snapshot,
)

_ARTIFACT_URL = re.compile(
    r"https://github\.com/mbalbo2023/boca-socios-assistant/actions/runs/"
    r"[1-9][0-9]*/artifacts/[1-9][0-9]*\Z"
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ZIP_MAX_BYTES = 128 * 1024
_JSONL_MAX_BYTES = 16_384
_RECEIPT_MAX_BYTES = 8_192
_STAGING_PREFIX = ".boca-official-import-"
_REPLACE_LOCK_NAME = ".boca-official-import.lock"
_ARTIFACT_PARTS = {
    "boca-official-news-catalog.jsonl": _JSONL_MAX_BYTES,
    "boca-official-news-receipt.json": _RECEIPT_MAX_BYTES,
}
_RECEIPT_FIELDS = frozenset(
    {
        "schema",
        "source_url",
        "observed_at_utc",
        "http_status",
        "content_length",
        "source_sha256",
        "server_date_utc",
        "state",
        "reason",
        "markers",
        "request_count",
        "tls_policy",
        "redirects_followed",
        "credentials_sent",
        "feed_verified",
        "availability_verified",
        "actionable",
        "offline_snapshot_state",
        "offline_snapshot_reason",
    }
)
_EVENT_KEY = "boca-defensa-y-justicia-20261107"
_EVENT_TITLE = "Boca-Defensa: Información al socio"
_EXPECTED_AREAS = (
    ("activos_interior", "generales"),
    ("adherentes", "generales"),
    ("abonados", "plateas"),
    ("abono_solidario", "plateas"),
    ("vitalicios", "plateas_y_generales"),
)
_LEASE_SENTINEL = object()


class OfficialImportError(OfficialSnapshotError):
    """An artifact, lease or atomic publication failed closed; details redacted."""


@dataclass(frozen=True)
class ReviewedOfficialArtifactPin:
    """Externally reviewed expected values; a claim, not live GitHub proof.

    ``artifact_sha256`` binds exact ZIP bytes. ``snapshot_sha256`` independently
    binds the extracted JSONL. The source digest pins the public HTML from the
    receipt; those HTML bytes are NOT present in the redacted GitHub artifact.
    """

    artifact_url: str
    artifact_sha256: str
    snapshot_sha256: str
    source_url: str
    source_sha256: str
    observed_at_utc: str


@dataclass(frozen=True)
class OfficialImportReceipt:
    outcome: Literal["CREATED", "REPLACED", "UNCHANGED"]
    artifact_sha256: str
    snapshot_sha256: str
    source_url: str
    source_sha256: str
    observed_at_utc: str
    windows_count: Literal[5] = 5
    actionable: Literal[False] = False


class OfficialSnapshotReplaceLease:
    """Non-serializable in-process handle to an acquired owner-only flock."""

    def __init__(
        self,
        *,
        _sentinel: object,
        lock_fd: int,
        parent_fd: int,
        expected_current_sha256: str,
    ) -> None:
        if _sentinel is not _LEASE_SENTINEL:
            raise OfficialImportError("official replace lease must be acquired")
        self._lock_fd = lock_fd
        self._parent_fd = parent_fd
        self.expected_current_sha256 = expected_current_sha256
        self._active = True


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _validate_pin(pin: ReviewedOfficialArtifactPin) -> None:
    if (
        type(pin) is not ReviewedOfficialArtifactPin
        or type(pin.artifact_url) is not str
        or not _ARTIFACT_URL.fullmatch(pin.artifact_url)
        or pin.source_url != OFFICIAL_NEWS_URL
        or not all(
            _is_sha256(digest)
            for digest in (pin.artifact_sha256, pin.snapshot_sha256, pin.source_sha256)
        )
        or type(pin.observed_at_utc) is not str
        or len(pin.observed_at_utc) > 45
    ):
        raise OfficialImportError("exact reviewed public artifact pin invalid")
    try:
        observed = datetime.fromisoformat(pin.observed_at_utc)
    except ValueError:
        raise OfficialImportError("reviewed public observation time invalid") from None
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise OfficialImportError("reviewed public observation timezone missing")


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("duplicate public receipt key")
        data[key] = value
    return data


def _read_exact_artifact_parts(artifact_zip: bytes) -> tuple[dict[str, object], bytes]:
    if type(artifact_zip) is not bytes or not 0 < len(artifact_zip) <= _ZIP_MAX_BYTES:
        raise OfficialImportError("public artifact ZIP invalid or exceeds budget")
    try:
        with zipfile.ZipFile(io.BytesIO(artifact_zip)) as archive:
            entries = archive.infolist()
            if len(entries) != len(_ARTIFACT_PARTS) or {info.filename for info in entries} != set(
                _ARTIFACT_PARTS
            ):
                raise OfficialImportError("public artifact files not allowlisted")
            parts: dict[str, bytes] = {}
            for info in entries:
                capacity = _ARTIFACT_PARTS[info.filename]
                # Reject paths, duplicates, ZIP bombs, encryption and symlinks.
                if (
                    info.is_dir()
                    or stat.S_ISLNK(info.external_attr >> 16)
                    or info.flag_bits & 1
                    or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    or not 0 < info.file_size <= capacity
                    or not 0 < info.compress_size <= _ZIP_MAX_BYTES
                ):
                    raise OfficialImportError("public artifact ZIP member invalid")
                with archive.open(info, "r") as source:
                    data = source.read(capacity + 1)
                if len(data) != info.file_size:
                    raise OfficialImportError("public artifact ZIP member capacity exceeded")
                parts[info.filename] = data
    except (OSError, ValueError, RuntimeError, EOFError, zipfile.BadZipFile, NotImplementedError):
        raise OfficialImportError("public artifact ZIP unreadable") from None
    try:
        receipt = json.loads(
            parts["boca-official-news-receipt.json"].decode("utf-8"),
            object_pairs_hook=_unique_pairs,
        )
    except (ValueError, UnicodeError, TypeError):
        raise OfficialImportError("public artifact receipt malformed") from None
    if type(receipt) is not dict or set(receipt) != _RECEIPT_FIELDS:
        raise OfficialImportError("public artifact receipt contract changed")
    return receipt, parts["boca-official-news-catalog.jsonl"]


def _verified_jsonl(artifact_zip: bytes, pin: ReviewedOfficialArtifactPin) -> bytes:
    _validate_pin(pin)
    if type(artifact_zip) is not bytes or not 0 < len(artifact_zip) <= _ZIP_MAX_BYTES:
        raise OfficialImportError("public artifact ZIP invalid or exceeds budget")
    if _digest(artifact_zip) != pin.artifact_sha256:
        raise OfficialImportError("public artifact ZIP digest differs from reviewed pin")
    receipt, jsonl = _read_exact_artifact_parts(artifact_zip)
    markers = receipt.get("markers")
    if _digest(jsonl) != pin.snapshot_sha256:
        raise OfficialImportError("public JSONL digest differs from reviewed pin")
    if (
        receipt.get("source_url") != pin.source_url
        or receipt.get("source_sha256") != pin.source_sha256
        or receipt.get("observed_at_utc") != pin.observed_at_utc
        or receipt.get("offline_snapshot_reason") != "public_article_fields_bound"
        or receipt.get("reason") != "public_content_markers_present_only"
        or not isinstance(markers, dict)
        or set(markers) != set(_REQUIRED_MARKERS)
        or any(marker is not True for marker in markers.values())
    ):
        raise OfficialImportError("reviewed public receipt source/time evidence differs")
    try:
        decoded = jsonl.decode("utf-8")
        redacted, identical = split_public_observation_envelope(
            {**receipt, "offline_snapshot_jsonl": decoded}
        )
        notice = load_observed_notice(decoded[:-1])
    except (UnicodeError, ValueError, OfficialCatalogError):
        raise OfficialImportError("public artifact JSONL cannot be bound to receipt") from None
    if (
        identical != decoded
        or redacted != receipt
        or notice.event_key != _EVENT_KEY
        or notice.title != _EVENT_TITLE
        or notice.published_on.isoformat() != "2026-11-03"
        or notice.kickoff_at.isoformat(timespec="minutes") != "2026-11-07T17:30-03:00"
        or tuple((item.member_category, item.seat_area) for item in notice.windows)
        != _EXPECTED_AREAS
        or notice.source_url != OFFICIAL_NEWS_URL
        or notice.actionable is not False
        or notice.verification_state != "SOURCE_OBSERVED_UNVERIFIED"
        or len(notice.windows) != 5
    ):
        raise OfficialImportError("public article event identity or safety mismatch")
    return jsonl


def _data_directory_fd(directory: Path) -> int:
    if not isinstance(directory, Path) or not directory.is_absolute():
        raise OfficialImportError("Boca data directory not canonical")
    try:
        return _open_parent_no_symlinks(directory)
    except OfficialSnapshotError:
        raise OfficialImportError("Boca data directory unavailable or unsafe") from None


def _current_bytes(parent_fd: int) -> bytes | None:
    try:
        return _read_snapshot(parent_fd)
    except OfficialSnapshotError:
        raise OfficialImportError("existing Boca snapshot unsafe or unreadable") from None


def _check_lease(lease: OfficialSnapshotReplaceLease | None, parent_fd: int) -> str:
    if type(lease) is not OfficialSnapshotReplaceLease or not lease._active:
        raise OfficialImportError("exact active replace lease required")
    try:
        first = os.fstat(parent_fd)
        held = os.fstat(lease._parent_fd)
        lock_info = os.fstat(lease._lock_fd)
        named = os.stat(_REPLACE_LOCK_NAME, dir_fd=lease._parent_fd, follow_symlinks=False)
    except OSError:
        raise OfficialImportError("replace lease directory or lock changed") from None
    if (
        (first.st_dev, first.st_ino) != (held.st_dev, held.st_ino)
        or _identity(lock_info) != _identity(named)
        or not stat.S_ISREG(lock_info.st_mode)
        or lock_info.st_uid != os.geteuid()
        or stat.S_IMODE(lock_info.st_mode) != 0o600
        or lock_info.st_nlink != 1
        or not _is_sha256(lease.expected_current_sha256)
    ):
        raise OfficialImportError("replace lease owner, identity or digest invalid")
    return lease.expected_current_sha256


@contextmanager
def hold_official_snapshot_replace_lease(
    data_directory: Path, *, expected_current_sha256: str
) -> Iterator[OfficialSnapshotReplaceLease]:
    """Acquire a nonblocking, Boca-directory-scoped exclusive update lease.

    Replacement requires both this LIVE lease and the exact SHA of the existing
    file. The lock is advisory between cooperating Boca importers; no attempt
    is made to interrupt an unrelated writer. The 0600 lock inode persists,
    contains no secrets and is not a backup.
    """
    if not _is_sha256(expected_current_sha256):
        raise OfficialImportError("replace lease digest invalid")
    parent_fd = _data_directory_fd(data_directory)
    lock_fd = -1
    try:
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            lock_fd = os.open(
                _REPLACE_LOCK_NAME,
                flags | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=parent_fd,
            )
        except FileExistsError:
            lock_fd = os.open(_REPLACE_LOCK_NAME, flags, dir_fd=parent_fd)
        info = os.fstat(lock_fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise OfficialImportError("replace lease lock owner or mode invalid")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise OfficialImportError("replace lease already held") from None
        existing = _current_bytes(parent_fd)
        if existing is None or _digest(existing) != expected_current_sha256:
            raise OfficialImportError("replace lease existing snapshot digest mismatch")
        lease = OfficialSnapshotReplaceLease(
            _sentinel=_LEASE_SENTINEL,
            lock_fd=lock_fd,
            parent_fd=parent_fd,
            expected_current_sha256=expected_current_sha256,
        )
        try:
            yield lease
        finally:
            lease._active = False
    except OSError:
        raise OfficialImportError("replace lease unavailable or unsafe") from None
    finally:
        if lock_fd >= 0:
            os.close(lock_fd)
        os.close(parent_fd)


def _publish(
    parent_fd: int, payload: bytes, *, replaces: bool, expected_before: bytes | None
) -> None:
    """Write a private O_EXCL stage, then atomic no-clobber create or leased replace."""
    stage = _STAGING_PREFIX + secrets.token_hex(12) + ".tmp"
    fd = -1
    staged = False
    try:
        fd = os.open(
            stage,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent_fd,
        )
        staged = True
        os.fchmod(fd, 0o600)
        cursor = 0
        while cursor < len(payload):
            written = os.write(fd, payload[cursor:])
            if written <= 0:
                raise OfficialImportError("public snapshot stage write incomplete")
            cursor += written
        os.fsync(fd)
        os.close(fd)
        fd = -1
        if replaces:
            # Fail if a concurrent or non-cooperating writer changed the file
            # between the lease's validation and publication. The flock is
            # advisory: external writers MUST observe the same lease contract.
            before_now = _current_bytes(parent_fd)
            if before_now is None or before_now != expected_before:
                raise OfficialImportError("leased snapshot changed before atomic replace")
            os.replace(stage, OFFICIAL_SNAPSHOT_NAME, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            staged = False
        else:
            # Linking a fully fsynced temporary file with an existing-name
            # failure provides atomic NO-REPLACE without Linux-specific FFI.
            # The transient nlink=2 window is fail-closed for the strict reader.
            os.link(
                stage,
                OFFICIAL_SNAPSHOT_NAME,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        if staged:
            os.unlink(stage, dir_fd=parent_fd)
            staged = False
        os.fsync(parent_fd)
    except FileExistsError:
        raise OfficialImportError("public snapshot already exists or stage collision") from None
    except OSError:
        raise OfficialImportError("public snapshot atomic publication failed") from None
    finally:
        if fd >= 0:
            os.close(fd)
        if staged:
            try:
                os.unlink(stage, dir_fd=parent_fd)
            except OSError:
                # Failure to clean an attempt-owned stage remains visible to
                # the protected owner postflight; never touch other files.
                pass


def import_reviewed_official_artifact(
    data_directory: Path,
    *,
    artifact_zip: bytes,
    reviewed_pin: ReviewedOfficialArtifactPin,
    replace_lease: OfficialSnapshotReplaceLease | None = None,
) -> OfficialImportReceipt:
    """Publish exactly one reviewed, non-actionable official notice JSONL.

    Caller explicitly supplies the existing *trusted Boca data directory*,
    exact GitHub Actions artifact ZIP bytes and externally verified pins.
    The function NEVER downloads an artifact nor consults GitHub/club data.
    A different existing snapshot cannot be overwritten without a held lease
    bound to that directory and the existing SHA; same bytes are idempotent.
    """
    jsonl = _verified_jsonl(artifact_zip, reviewed_pin)
    parent_fd = _data_directory_fd(data_directory)
    outcome: Literal["CREATED", "REPLACED", "UNCHANGED"]
    try:
        previous = _current_bytes(parent_fd)
        if previous == jsonl:
            outcome = "UNCHANGED"
        elif previous is None:
            if replace_lease is not None:
                raise OfficialImportError("replace lease cannot create an absent snapshot")
            _publish(parent_fd, jsonl, replaces=False, expected_before=None)
            outcome = "CREATED"
        else:
            if _check_lease(replace_lease, parent_fd) != _digest(previous):
                raise OfficialImportError("lease digest does not match existing snapshot")
            _publish(parent_fd, jsonl, replaces=True, expected_before=previous)
            outcome = "REPLACED"
    finally:
        os.close(parent_fd)
    # Confirm the canonical strict reader accepts the exact installed bytes.
    # An error after atomic publication is NO_GO/inspection, not rollback.
    try:
        installed = load_official_snapshot(data_directory / OFFICIAL_SNAPSHOT_NAME)
    except OfficialSnapshotError:
        raise OfficialImportError("published Boca snapshot postflight invalid") from None
    if len(installed) != 1 or installed[0].source_sha256 != reviewed_pin.source_sha256:
        raise OfficialImportError("published Boca snapshot postflight identity mismatch")
    return OfficialImportReceipt(
        outcome=outcome,
        artifact_sha256=reviewed_pin.artifact_sha256,
        snapshot_sha256=reviewed_pin.snapshot_sha256,
        source_url=reviewed_pin.source_url,
        source_sha256=reviewed_pin.source_sha256,
        observed_at_utc=reviewed_pin.observed_at_utc,
    )
