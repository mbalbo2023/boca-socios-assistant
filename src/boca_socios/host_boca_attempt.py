"""Code-only first/beta/update attempt identity producer for cleanup #323.

These immutable O_EXCL receipts and the Compose label overlay are NOT wired
to the live install workflow. They cannot authorize Docker deletion on their
own: a protected caller must verify the exact main/release/host evidence and
hold the same BocaJobLease from before effect until cleanup postflight.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from boca_socios import host_boca_cleanup as cleanup
from boca_socios.host_boca_cleanup import (
    ATTEMPT_ID,
    EXPECTED_UID,
    HEX_ID,
    BocaJobLease,
    CleanupError,
    verify_protected_boca_job_lease,
)

SOURCE_SHA = re.compile(r"[0-9a-f]{40}\Z")
FULL_SHA = re.compile(r"[0-9a-f]{64}\Z")
MARKER_DIR = Path(f"/run/user/{EXPECTED_UID}")
MARKER_VERSION = "boca-postdeploy-attempt-v1"
OPERATIONS = {
    "first-install": "boca.socios.install-attempt",
    "beta-install": "boca.socios.beta-install-attempt",
    "update": "boca.socios.update-attempt",
}
MAX_MARKER = 2048


class AttemptError(ValueError):
    """Attempt evidence or exact owner lease cannot be authenticated."""


@dataclass(frozen=True)
class Intent:
    attempt_id: str
    operation: str
    source_sha: str
    base_compose_sha: str
    overlay_sha: str
    original_controller_id: str | None


@dataclass(frozen=True)
class Result:
    attempt_id: str
    intent_sha: str
    outcome: str
    created_controller_id: str | None
    accepted_controller_id: str | None


def _serialized(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def _intent_payload(intent: Intent) -> dict[str, object]:
    if (
        not ATTEMPT_ID.fullmatch(intent.attempt_id)
        or intent.operation not in OPERATIONS
        or not SOURCE_SHA.fullmatch(intent.source_sha)
        or not FULL_SHA.fullmatch(intent.base_compose_sha)
        or not FULL_SHA.fullmatch(intent.overlay_sha)
        or (
            intent.original_controller_id is not None
            and not HEX_ID.fullmatch(intent.original_controller_id)
        )
    ):
        raise AttemptError("Boca install intent coordinates invalid")
    return {"version": MARKER_VERSION, **intent.__dict__}


def _result_payload(result: Result) -> dict[str, object]:
    if (
        not ATTEMPT_ID.fullmatch(result.attempt_id)
        or not FULL_SHA.fullmatch(result.intent_sha)
        or result.outcome not in ("SUCCESS", "FAILURE")
        or any(
            ident is not None and not HEX_ID.fullmatch(ident)
            for ident in (result.created_controller_id, result.accepted_controller_id)
        )
        or (result.outcome == "FAILURE" and result.accepted_controller_id is not None)
        or (result.outcome == "SUCCESS" and result.accepted_controller_id is None)
    ):
        raise AttemptError("Boca install result coordinates invalid")
    return {"version": MARKER_VERSION, **result.__dict__}


def label_overlay(operation: str, attempt_id: str, source_sha: str) -> bytes:
    """Exact Compose controller label in a reviewed, public overlay.

    Caller must supply this as a *second* -f during first/beta/update. It is
    not an environment variable with an unsafe default, and cannot affect
    any other Compose project, network, port, service or volume.
    """
    if (
        operation not in OPERATIONS
        or not ATTEMPT_ID.fullmatch(attempt_id)
        or not SOURCE_SHA.fullmatch(source_sha)
    ):
        raise AttemptError("Boca attempted Compose label coordinates invalid")
    label = OPERATIONS[operation]
    return (
        "name: boca-socios\n"
        "services:\n"
        "  controller:\n"
        "    labels:\n"
        f'      {label}: "{attempt_id}"\n'
        f'      boca.socios.source-sha: "{source_sha}"\n'
    ).encode("ascii")


def intended(
    operation: str,
    attempt_id: str,
    source_sha: str,
    base_compose_sha: str,
    original_controller_id: str | None,
) -> tuple[Intent, bytes]:
    overlay = label_overlay(operation, attempt_id, source_sha)
    intent = Intent(
        attempt_id,
        operation,
        source_sha,
        base_compose_sha,
        hashlib.sha256(overlay).hexdigest(),
        original_controller_id,
    )
    _intent_payload(intent)
    return intent, overlay


def _lease(lease: BocaJobLease, attempt_id: str) -> None:
    try:
        verify_protected_boca_job_lease(lease, attempt_id)
    except CleanupError as exc:
        raise AttemptError("Boca attempt requires same held canonical protected job lease") from exc


def _open_dir() -> int:
    try:
        folder = os.open(MARKER_DIR, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise AttemptError("Boca attempt marker owner directory unavailable") from exc
    item = os.fstat(folder)
    if (
        not stat.S_ISDIR(item.st_mode)
        or item.st_uid != EXPECTED_UID
        or item.st_gid != EXPECTED_UID
        or stat.S_IMODE(item.st_mode) != 0o700
    ):
        os.close(folder)
        raise AttemptError("Boca attempt marker directory owner/mode unsafe")
    return folder


def _filename(attempt_id: str, kind: str) -> str:
    if not ATTEMPT_ID.fullmatch(attempt_id) or kind not in ("intent", "result"):
        raise AttemptError("Boca attempt marker filename invalid")
    return f"boca-postdeploy-{attempt_id}-{kind}.json"


def _create_marker(attempt_id: str, kind: str, payload: bytes) -> str:
    if not 0 < len(payload) <= MAX_MARKER:
        raise AttemptError("Boca marker payload outside bounded budget")
    folder = _open_dir()
    try:
        try:
            fd = os.open(
                _filename(attempt_id, kind),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=folder,
            )
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(folder)
        except OSError as exc:
            # Unknown write outcome is quarantined: NEVER replace/retry.
            raise AttemptError("Boca exclusive attempt marker write uncertain") from exc
        return hashlib.sha256(payload).hexdigest()
    finally:
        os.close(folder)


def _read_marker(attempt_id: str, kind: str) -> tuple[dict[str, object], str]:
    folder = _open_dir()
    try:
        try:
            fd = os.open(
                _filename(attempt_id, kind),
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=folder,
            )
        except OSError as exc:
            raise AttemptError("Boca attempt marker absent/unsafe") from exc
        try:
            item = os.fstat(fd)
            if (
                not stat.S_ISREG(item.st_mode)
                or item.st_uid != EXPECTED_UID
                or item.st_gid != EXPECTED_UID
                or item.st_nlink != 1
                or stat.S_IMODE(item.st_mode) != 0o600
                or not 0 < item.st_size <= MAX_MARKER
            ):
                raise AttemptError("Boca attempt marker inode invalid")
            raw = os.read(fd, MAX_MARKER + 1)
            after = os.fstat(fd)
            if len(raw) != item.st_size or (
                item.st_dev,
                item.st_ino,
                item.st_size,
                item.st_mtime_ns,
                item.st_ctime_ns,
            ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise AttemptError("Boca attempt marker changed while reading")
        finally:
            os.close(fd)
        try:
            # Disallow repeated JSON keys by comparing to canonical bytes.
            result = json.loads(raw.decode("ascii"))
        except (ValueError, UnicodeError) as exc:
            raise AttemptError("Boca attempt marker JSON invalid") from exc
        if not isinstance(result, dict) or _serialized(result) != raw:
            raise AttemptError("Boca attempt marker noncanonical/duplicate JSON")
        return result, hashlib.sha256(raw).hexdigest()
    finally:
        os.close(folder)


def begin(intent: Intent, *, lease: BocaJobLease) -> str:
    """Write intent BEFORE any Docker effect. No installed object is deleted."""
    _lease(lease, intent.attempt_id)
    return _create_marker(intent.attempt_id, "intent", _serialized(_intent_payload(intent)))


def finish(result: Result, *, lease: BocaJobLease) -> str:
    """Write immutable result only after exact controller inspection/receipt."""
    _lease(lease, result.attempt_id)
    intent, digest = read_intent(result.attempt_id, lease=lease)
    if result.intent_sha != digest:
        raise AttemptError("Boca attempt result does not bind immutable intent")
    if (
        intent.operation in ("first-install", "beta-install")
        and intent.original_controller_id is not None
    ):
        raise AttemptError("new-only Boca install unexpectedly had original controller")
    if (
        result.outcome == "SUCCESS"
        and result.accepted_controller_id != result.created_controller_id
    ):
        raise AttemptError("successful Boca install must accept exact created controller ID")
    return _create_marker(result.attempt_id, "result", _serialized(_result_payload(result)))


def _required(value: dict[str, object], key: str) -> str:
    item = value[key]
    if not isinstance(item, str):
        raise AttemptError("Boca attempt marker required string invalid")
    return item


def _optional(value: dict[str, object], key: str) -> str | None:
    item = value[key]
    if item is not None and not isinstance(item, str):
        raise AttemptError("Boca attempt marker optional string invalid")
    return item


def read_intent(attempt_id: str, *, lease: BocaJobLease) -> tuple[Intent, str]:
    _lease(lease, attempt_id)
    value, digest = _read_marker(attempt_id, "intent")
    try:
        result = Intent(
            _required(value, "attempt_id"),
            _required(value, "operation"),
            _required(value, "source_sha"),
            _required(value, "base_compose_sha"),
            _required(value, "overlay_sha"),
            _optional(value, "original_controller_id"),
        )
    except (KeyError, TypeError) as exc:
        raise AttemptError("Boca attempt intent fields incomplete") from exc
    if value != _intent_payload(result):
        raise AttemptError("Boca attempt intent schema changed")
    return result, digest


def read_result(attempt_id: str, *, lease: BocaJobLease) -> Result:
    _lease(lease, attempt_id)
    _, expected_intent_sha = read_intent(attempt_id, lease=lease)
    value, _digest = _read_marker(attempt_id, "result")
    try:
        result = Result(
            _required(value, "attempt_id"),
            _required(value, "intent_sha"),
            _required(value, "outcome"),
            _optional(value, "created_controller_id"),
            _optional(value, "accepted_controller_id"),
        )
    except (KeyError, TypeError) as exc:
        raise AttemptError("Boca attempt result fields incomplete") from exc
    if value != _result_payload(result) or result.intent_sha != expected_intent_sha:
        raise AttemptError("Boca attempt result/intent linkage invalid")
    return result


def cleanup_ids(result: Result, *, lease: BocaJobLease) -> tuple[frozenset[str], frozenset[str]]:
    """Derive preserve/retire IDs from a verified positive attempt receipt."""
    verified = read_result(result.attempt_id, lease=lease)
    intent, _ = read_intent(result.attempt_id, lease=lease)
    if result != verified:
        raise AttemptError("Boca cleanup caller supplied forged result")
    if intent.operation == "update":
        raise AttemptError("Boca update original-ID retirement remains physical NO_GO")
    if result.outcome == "SUCCESS":
        if result.accepted_controller_id is None:
            raise AttemptError("Boca successful result lacks accepted exact controller ID")
        return frozenset({result.accepted_controller_id}), frozenset()
    if result.created_controller_id is not None:
        return frozenset(), frozenset({result.created_controller_id})
    return frozenset(), frozenset()


def finalize_attempt(
    result: Result,
    *,
    lease: BocaJobLease,
    preserve_images: frozenset[str],
) -> cleanup.CleanupReceipt:
    """Unwired host finalizer: verify exact Docker labels before any cleanup.

    No CLI/workflow exposes this function. Protected job must call it from the
    *same host process* and original lease as the installer, on both outcomes.
    A missing result means NO_GO and makes NO deletion attempt.
    """
    _lease(lease, result.attempt_id)
    intent, _ = read_intent(result.attempt_id, lease=lease)
    preserve, retire = cleanup_ids(result, lease=lease)
    snapshot = cleanup.capture_inventory()
    for ident in preserve | retire:
        matches = [container for container in snapshot.containers if container.ident == ident]
        if len(matches) != 1:
            raise AttemptError("Boca finalizer exact controller missing from host inventory")
        container = matches[0]
        labels = dict(container.labels)
        if (
            len(labels) != len(container.labels)
            or labels.get("com.docker.compose.project") != cleanup.BOCA_PROJECT
            or labels.get("com.docker.compose.service") != "controller"
            or labels.get(OPERATIONS[intent.operation]) != result.attempt_id
            or labels.get("boca.socios.source-sha") != intent.source_sha
            or not container.name.removeprefix("/").startswith("boca-socios-")
        ):
            raise AttemptError("Boca finalizer exact controller identity/labels unproven")
    if result.outcome not in ("SUCCESS", "FAILURE"):
        raise AttemptError("Boca finalizer outcome untrusted")
    verified_outcome: cleanup.OUTCOME = "SUCCESS" if result.outcome == "SUCCESS" else "FAILURE"
    return cleanup.execute_protected(
        verified_outcome,
        result.attempt_id,
        preserve_images=preserve_images,
        preserve_containers=preserve,
        retire_containers=retire,
        lease=lease,
    )
