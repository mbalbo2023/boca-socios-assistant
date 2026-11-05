"""Pure runner-side PREPARE GO_B proof shared by Boca Cutover A and official import.

This module is only a second local check of three O_EXCL files created AFTER
the protected workflow authenticates PREPARE Actions run + immutable artifact
and independently controlled Environment GO. It NEVER retrieves GitHub data,
writes a file, constructs SSH/Docker calls, or grants a host operation by itself.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

VERSION = "boca-protected-prepared-go-v1"
GO_DOMAINS = {
    "cutover-a-apply": b"boca-cutover-a-prepared-go-v1:\x00",
    "official-notice-import": b"boca-official-notice-import-prepared-go-v1:\x00",
}
GO_ENV = {
    "cutover-a-apply": "BOCA_CUTOVER_A_GO_BINDING_SHA256",
    "official-notice-import": "BOCA_OFFICIAL_IMPORT_GO_BINDING_SHA256",
}
RECEIPT_KEYS = frozenset(
    {
        "version",
        "operation",
        "repository",
        "actor",
        "ref",
        "source_sha",
        "release_run_id",
        "prepare_run_id",
        "prepare_attempt",
        "prepared_at_utc",
        "valid_until_utc",
        "public_context_sha256",
        "release_manifest_sha256",
        "browser_manifest_sha256",
        "bundle_sha256",
        "owner_subject_sha256",
    }
)
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")


class PreparedGoError(ValueError):
    """Runner cannot prove its independently reviewed PREPARE GO_B bytes."""


@dataclass(frozen=True)
class PreparedGoProof:
    prepare_run_id: str
    approved_sha256: str
    receipt_sha256: str


def _canonical(record: object) -> bytes:
    return json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key, value in pairs:
        if key in fields:
            raise PreparedGoError("PREPARE receipt duplicate key")
        fields[key] = value
    return fields


def _runner_dir(environment: Mapping[str, str]) -> Path:
    runner = Path(environment.get("RUNNER_TEMP", ""))
    try:
        info = runner.lstat()
        if (
            not runner.is_absolute()
            or runner.resolve(strict=True) != runner
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise PreparedGoError("PREPARE runner staging directory untrusted")
    except (OSError, RuntimeError):
        raise PreparedGoError("PREPARE runner staging unavailable") from None
    return runner


def _read_private(runner: Path, name: str, *, limit: int) -> bytes:
    if name not in (
        "boca-protected-legacy-go.approved",
        "boca-protected-legacy-go.prepare-id",
        "boca-protected-legacy-go.receipt.json",
    ):
        raise PreparedGoError("PREPARE runner filename not allowlisted")
    try:
        fd = os.open(runner / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            before = os.fstat(fd)
            content = os.read(fd, limit + 1)
            after = os.fstat(fd)
        finally:
            os.close(fd)
    except OSError:
        raise PreparedGoError("PREPARE runner evidence not readable") from None
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.geteuid()
        or before.st_nlink != 1
        or stat.S_IMODE(before.st_mode) != 0o600
        or not 0 < len(content) <= limit
        or len(content) != before.st_size
        or (before.st_dev, before.st_ino, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_mtime_ns)
    ):
        raise PreparedGoError("PREPARE runner proof bytes changed or untrusted")
    return content


def _utc_second(stamp: str) -> datetime:
    if type(stamp) is not str or not stamp.endswith("Z"):
        raise PreparedGoError("PREPARE receipt UTC stamp invalid")
    try:
        instant = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        raise PreparedGoError("PREPARE receipt UTC stamp malformed") from None
    if instant.tzinfo is None or instant.strftime("%Y-%m-%dT%H:%M:%SZ") != stamp:
        raise PreparedGoError("PREPARE receipt UTC stamp noncanonical")
    return instant.astimezone(UTC)


def hash_reviewed_file(path: Path, *, max_bytes: int = 2_500_000) -> str:
    """SHA256 a bounded regular runner artifact without following symlinks."""
    if not path.is_absolute() or path.is_symlink():
        raise PreparedGoError("PREPARE reviewed evidence path unsafe")
    try:
        before = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(before.st_mode)
            or not 0 < before.st_size <= max_bytes
            or before.st_nlink != 1
        ):
            raise PreparedGoError("PREPARE reviewed evidence type/size invalid")
        raw = path.read_bytes()
        after = path.stat(follow_symlinks=False)
    except OSError:
        raise PreparedGoError("PREPARE reviewed artifact unavailable") from None
    if (
        len(raw) != before.st_size
        or (before.st_dev, before.st_ino, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_mtime_ns)
    ):
        raise PreparedGoError("PREPARE reviewed artifact changed during hashing")
    return hashlib.sha256(raw).hexdigest()


def verify_legacy_prepared_go(
    *,
    operation: str,
    expected_public_context_sha256: Callable[[str], str],
    source_sha: str,
    release_run_id: str,
    release_manifest_sha256: str,
    browser_manifest_sha256: str,
    bundle_sha256: str,
    owner_subject: str,
    environ: Mapping[str, str],
    now: datetime | None = None,
) -> PreparedGoProof:
    """Return publicly pinned GO only after independently staged proof matches.

    The protected workflow must separately do PREPARE GitHub API/artifact
    verification BEFORE writing these three evidence files. All input fields
    are re-attested against current ACTIONS runtime and reviewed source bytes.
    """
    if operation not in GO_DOMAINS:
        raise PreparedGoError("PREPARE operation unsupported")
    current = environ.get("GITHUB_RUN_ID", "")
    if (
        environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
        or environ.get("BOCA_OPERATION") != operation
        or environ.get("GITHUB_REPOSITORY") != "mbalbo2023/boca-socios-assistant"
        or environ.get("GITHUB_ACTOR") != "mbalbo2023"
        or environ.get("GITHUB_REF") != "refs/heads/main"
        or environ.get("GITHUB_SHA") != environ.get("BOCA_SOURCE_SHA")
        or environ.get("GITHUB_SHA") != source_sha
        or _SHA40.fullmatch(source_sha) is None
        or environ.get("GITHUB_RUN_ATTEMPT") != "1"
        or _RUN.fullmatch(current) is None
        or _RUN.fullmatch(release_run_id) is None
        or not 1 <= len(owner_subject) <= 1024
        or any(
            type(pin) is not str or _HEX.fullmatch(pin) is None
            for pin in (
                release_manifest_sha256,
                browser_manifest_sha256,
                bundle_sha256,
            )
        )
    ):
        raise PreparedGoError("PREPARE runner Actions context or reviewed pins invalid")
    runner = _runner_dir(environ)
    approval = _read_private(runner, "boca-protected-legacy-go.approved", limit=65)
    prepare = _read_private(runner, "boca-protected-legacy-go.prepare-id", limit=21)
    raw = _read_private(runner, "boca-protected-legacy-go.receipt.json", limit=4096)
    approved = approval.decode("ascii", errors="replace")
    prepare_id = prepare.decode("ascii", errors="replace")
    if (
        _HEX.fullmatch(approved.removesuffix("\n")) is None
        or approved != approved.removesuffix("\n") + "\n"
        or _RUN.fullmatch(prepare_id.removesuffix("\n")) is None
        or prepare_id != prepare_id.removesuffix("\n") + "\n"
        or prepare_id.removesuffix("\n") == current
    ):
        raise PreparedGoError("PREPARE file GO or identity not canonical")
    prepare_id = prepare_id.removesuffix("\n")
    try:
        receipt = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
    except (UnicodeError, ValueError):
        raise PreparedGoError("PREPARE runner JSON malformed") from None
    if (
        type(receipt) is not dict
        or set(receipt) != RECEIPT_KEYS
        or any(type(value) is not str for value in receipt.values())
        or _canonical(receipt) != raw
    ):
        raise PreparedGoError("PREPARE runner JSON is not exact canonical receipt")
    try:
        expected_context = expected_public_context_sha256(prepare_id)
    except (ValueError, TypeError, OSError):
        raise PreparedGoError("PREPARE source/manifest review changed") from None
    if type(expected_context) is not str or _HEX.fullmatch(expected_context) is None:
        raise PreparedGoError("PREPARE reviewed context invalid")
    if (
        receipt["version"] != VERSION
        or receipt["operation"] != operation
        or receipt["repository"] != environ["GITHUB_REPOSITORY"]
        or receipt["actor"] != environ["GITHUB_ACTOR"]
        or receipt["ref"] != environ["GITHUB_REF"]
        or receipt["source_sha"] != source_sha
        or receipt["release_run_id"] != release_run_id
        or receipt["prepare_run_id"] != prepare_id
        or receipt["prepare_attempt"] != "1"
        or receipt["public_context_sha256"] != expected_context
        or receipt["release_manifest_sha256"] != release_manifest_sha256
        or receipt["browser_manifest_sha256"] != browser_manifest_sha256
        or receipt["bundle_sha256"] != bundle_sha256
        or receipt["owner_subject_sha256"]
        != hashlib.sha256(owner_subject.encode("utf-8")).hexdigest()
    ):
        raise PreparedGoError("PREPARE exact context, source or reviewed artifacts changed")
    instant = datetime.now(UTC) if now is None else now
    if instant.tzinfo is None:
        raise PreparedGoError("PREPARE runner clock timezone unknown")
    issued = _utc_second(receipt["prepared_at_utc"])
    expires = _utc_second(receipt["valid_until_utc"])
    if (
        expires - issued != timedelta(days=1)
        or instant.astimezone(UTC) < issued - timedelta(minutes=5)
        or instant.astimezone(UTC) > expires
    ):
        raise PreparedGoError("PREPARE receipt time/freshness unproven")
    go = hashlib.sha256(GO_DOMAINS[operation] + raw).hexdigest()
    actual = environ.get(GO_ENV[operation], "")
    if (
        type(actual) is not str
        or _HEX.fullmatch(actual) is None
        or not hmac.compare_digest(actual, go)
        or not hmac.compare_digest(approved[:-1], go)
    ):
        raise PreparedGoError("PREPARE GO_B independently configured digest differs")
    return PreparedGoProof(prepare_id, go, hashlib.sha256(raw).hexdigest())
