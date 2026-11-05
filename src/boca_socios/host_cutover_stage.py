"""Inert-to-workflow, isolated staging contract for a future Boca cutover A.

The working singleton's ``/srv/boca-socios/compose.beta.yaml`` is immutable.
This module can only create a new, attempt-scoped child directory on its
dedicated Boca host when explicitly called by a future, separately reviewed
executor.  No workflow/CLI currently invokes these functions.

Each input is a public reviewed file (Compose or seccomp), never a secret.
An interrupted transfer remains quarantined and blocks retries; it must not
overwrite either the live file or a previously completed staged file.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import BinaryIO

ROOT = Path("/srv/boca-socios")
UID = 10001
GID = 10001
ATTEMPT = re.compile(r"[1-9][0-9]{0,19}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
SOURCE = re.compile(r"[0-9a-f]{40}\Z")
CONTAINER = re.compile(r"[0-9a-f]{64}\Z")
CONTROLLER = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
WORKER = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z")
FILES = {
    "base": ("compose.beta.yaml", "target_compose_sha"),
    "overlay": ("compose.beta.browser.yaml", "overlay_compose_sha"),
    "seccomp": ("seccomp_profile.json", "seccomp_sha"),
}
MARKER = "cutover-a-marker.json"
VERSION = "cutover-a-stage-v1"
COMMIT_INTENT = "cutover-a-commit-intent.json"
COMMIT_RESULT = "cutover-a-commit-result.json"
COMMIT_VERSION = "cutover-a-compose-promotion-v1"
MAX_FILE = 32_768
MAX_MARKER = 1024


class StageError(ValueError):
    """An exact, immutable cutover attempt cannot be staged or authenticated."""


def _unique(fields: list[tuple[str, object]]) -> dict[str, object]:
    record: dict[str, object] = {}
    for name, value in fields:
        if name in record:
            raise StageError("duplicate staged coordinate")
        record[name] = value
    return record


def _same_inode(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )


def _checked_dir(handle: int) -> os.stat_result:
    details = os.fstat(handle)
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != UID
        or details.st_gid != GID
        or stat.S_IMODE(details.st_mode) != 0o700
    ):
        raise StageError("Boca cutover directory identity unsafe")
    return details


def _root_fd() -> int:
    if os.geteuid() != UID or os.getegid() != GID:
        raise StageError("cutover stage requires dedicated Boca rootless identity")
    try:
        fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            _checked_dir(fd)
        except BaseException:
            os.close(fd)
            raise
        return fd
    except OSError as exc:
        raise StageError("Boca live root unavailable") from exc


def _read_file(
    handle: int, name: str, expected_sha: str | None, *, limit: int
) -> tuple[bytes, os.stat_result]:
    try:
        fd = os.open(
            name,
            os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=handle,
        )
        try:
            before = os.fstat(fd)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_uid != UID
                or before.st_gid != GID
                or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) != 0o600
                or not 0 < before.st_size <= limit
            ):
                raise StageError("Boca cutover file inode/owner/mode unsafe")
            contents = bytearray()
            while len(contents) <= limit:
                chunk = os.read(fd, limit + 1 - len(contents))
                if not chunk:
                    break
                contents.extend(chunk)
            if len(contents) != before.st_size or not _same_inode(before, os.fstat(fd)):
                raise StageError("Boca cutover file changed during bounded read")
            if expected_sha is not None and hashlib.sha256(contents).hexdigest() != expected_sha:
                raise StageError("Boca cutover file SHA differs from reviewed artifact")
            return bytes(contents), before
        finally:
            os.close(fd)
    except OSError as exc:
        raise StageError("Boca cutover file cannot be authenticated") from exc


def _stage_name(attempt_id: str) -> str:
    if not ATTEMPT.fullmatch(attempt_id):
        raise StageError("cutover stage attempt is not an immutable run ID")
    return f"cutover-a-{attempt_id}"


def _marker_payload(
    attempt_id: str,
    legacy_id: str,
    legacy_sha: str,
    legacy_compose_sha: str,
    target_sha: str,
    target_image: str,
    browser_image: str,
    target_compose_sha: str,
    overlay_compose_sha: str,
    seccomp_sha: str,
    original_stat: os.stat_result,
) -> dict[str, str | int]:
    if (
        not CONTAINER.fullmatch(legacy_id)
        or not SOURCE.fullmatch(legacy_sha)
        or not SOURCE.fullmatch(target_sha)
        or target_sha == legacy_sha
        or not CONTROLLER.fullmatch(target_image)
        or not WORKER.fullmatch(browser_image)
        or any(
            not SHA.fullmatch(value)
            for value in (legacy_compose_sha, target_compose_sha, overlay_compose_sha, seccomp_sha)
        )
        # Historical and target Compose may be byte-identical for a code/image-only cutover.
        # Overlay and seccomp are distinct roles, never aliases of either Compose file.
        or len({target_compose_sha, overlay_compose_sha, seccomp_sha}) != 3
        or legacy_compose_sha in (overlay_compose_sha, seccomp_sha)
    ):
        raise StageError("cutover stage lacks independent historical/target coordinates")
    return {
        "version": VERSION,
        "attempt_id": attempt_id,
        "legacy_controller_id": legacy_id,
        "legacy_source_sha": legacy_sha,
        "legacy_compose_sha": legacy_compose_sha,
        "legacy_compose_dev": original_stat.st_dev,
        "legacy_compose_ino": original_stat.st_ino,
        "target_source_sha": target_sha,
        "target_image": target_image,
        "browser_image": browser_image,
        "target_compose_sha": target_compose_sha,
        "overlay_compose_sha": overlay_compose_sha,
        "seccomp_sha": seccomp_sha,
    }


def _canonical(marker: dict[str, str | int]) -> bytes:
    return json.dumps(marker, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode(
        "ascii"
    )


def _create_exclusive(fd: int, name: str, payload: bytes) -> None:
    try:
        out = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=fd,
        )
        with os.fdopen(out, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(fd)
    except OSError as exc:
        # Failed exclusive creation/write remains an attempt-specific residue.
        # No automatic unlink: a path may have changed after a transport error.
        raise StageError("cutover exclusive write failed; quarantine attempt") from exc


def initialize(
    attempt_id: str,
    legacy_id: str,
    legacy_sha: str,
    legacy_compose_sha: str,
    target_sha: str,
    target_image: str,
    browser_image: str,
    target_compose_sha: str,
    overlay_compose_sha: str,
    seccomp_sha: str,
) -> None:
    """Create *only* an isolated child, leaving original Compose inode intact."""
    stage = _stage_name(attempt_id)
    root = _root_fd()
    try:
        if set(os.listdir(root)) != {"compose.beta.yaml"}:
            raise StageError("cutover root is not exactly the known live singleton")
        _, original = _read_file(root, "compose.beta.yaml", legacy_compose_sha, limit=MAX_FILE)
        marker = _marker_payload(
            attempt_id,
            legacy_id,
            legacy_sha,
            legacy_compose_sha,
            target_sha,
            target_image,
            browser_image,
            target_compose_sha,
            overlay_compose_sha,
            seccomp_sha,
            original,
        )
        try:
            os.mkdir(stage, 0o700, dir_fd=root)
            child = os.open(
                stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root
            )
        except OSError as exc:
            raise StageError("cutover attempt child cannot be created exclusively") from exc
        try:
            os.fchmod(child, 0o700)
            _checked_dir(child)
            if os.listdir(child):
                raise StageError("new cutover child is not empty")
            _create_exclusive(child, MARKER, _canonical(marker))
        finally:
            os.close(child)
        os.fsync(root)
        _, after = _read_file(root, "compose.beta.yaml", legacy_compose_sha, limit=MAX_FILE)
        if not _same_inode(original, after):
            raise StageError("live original Compose inode changed during staging")
    finally:
        os.close(root)


def _authenticated_stage(
    attempt_id: str, legacy_compose_sha: str, *, promoted: bool = False
) -> tuple[int, int, dict[str, str | int]]:
    stage = _stage_name(attempt_id)
    if not SHA.fullmatch(legacy_compose_sha):
        raise StageError("legacy Compose digest invalid")
    root = _root_fd()
    child: int | None = None
    try:
        expected_root = (
            {"compose.beta.yaml", "compose.beta.browser.yaml", "seccomp_profile.json", stage}
            if promoted
            else {"compose.beta.yaml", stage}
        )
        if set(os.listdir(root)) != expected_root:
            raise StageError("Boca root contains unexpected cutover state")
        child = os.open(
            stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root
        )
        _checked_dir(child)
        raw, _ = _read_file(child, MARKER, None, limit=MAX_MARKER)
        try:
            marker = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
        except (UnicodeError, ValueError, TypeError) as exc:
            raise StageError("cutover marker JSON invalid") from exc
        if (
            not isinstance(marker, dict)
            or marker.get("version") != VERSION
            or marker.get("attempt_id") != attempt_id
            or marker.get("legacy_compose_sha") != legacy_compose_sha
            or any(
                type(marker.get(name)) is not int or marker[name] < 0
                for name in ("legacy_compose_dev", "legacy_compose_ino")
            )
            or not CONTAINER.fullmatch(str(marker.get("legacy_controller_id")))
            or not SOURCE.fullmatch(str(marker.get("legacy_source_sha")))
            or not SOURCE.fullmatch(str(marker.get("target_source_sha")))
            or marker.get("target_source_sha") == marker.get("legacy_source_sha")
            or not CONTROLLER.fullmatch(str(marker.get("target_image")))
            or not WORKER.fullmatch(str(marker.get("browser_image")))
            or any(
                not SHA.fullmatch(str(marker.get(name)))
                for name in ("target_compose_sha", "overlay_compose_sha", "seccomp_sha")
            )
            or set(marker)
            != {
                "version",
                "attempt_id",
                "legacy_controller_id",
                "legacy_source_sha",
                "legacy_compose_sha",
                "legacy_compose_dev",
                "legacy_compose_ino",
                "target_source_sha",
                "target_image",
                "browser_image",
                "target_compose_sha",
                "overlay_compose_sha",
                "seccomp_sha",
            }
            or _canonical(marker) != raw
        ):
            raise StageError("cutover marker immutable schema invalid")
        if promoted:
            for filename, sha_field in FILES.values():
                _read_file(root, filename, str(marker[sha_field]), limit=MAX_FILE)
        else:
            _, original = _read_file(root, "compose.beta.yaml", legacy_compose_sha, limit=MAX_FILE)
            if (original.st_dev, original.st_ino) != (
                marker["legacy_compose_dev"],
                marker["legacy_compose_ino"],
            ):
                raise StageError("live original Compose inode replaced during cutover staging")
        return root, child, marker
    except BaseException:
        if child is not None:
            os.close(child)
        os.close(root)
        raise


def upload(
    slot: str, expected_sha: str, attempt_id: str, legacy_compose_sha: str, stream: BinaryIO
) -> None:
    """Add one reviewed file atomically to an existing isolated child."""
    if slot not in FILES or not SHA.fullmatch(expected_sha):
        raise StageError("unreviewed cutover staging slot/digest")
    payload = stream.read(MAX_FILE + 1)
    if not 0 < len(payload) <= MAX_FILE or hashlib.sha256(payload).hexdigest() != expected_sha:
        raise StageError("truncated, altered or oversized cutover payload")
    root, child, marker = _authenticated_stage(attempt_id, legacy_compose_sha)
    try:
        filename, sha_field = FILES[slot]
        if marker[sha_field] != expected_sha:
            raise StageError("cutover payload does not match immutable marker")
        entries = set(os.listdir(child))
        if filename in entries or not entries <= {MARKER, *(name for name, _ in FILES.values())}:
            raise StageError("cutover staged file exists or quarantined transfer residue")
        for existing_filename, existing_sha_field in FILES.values():
            if existing_filename in entries:
                _read_file(
                    child, existing_filename, str(marker[existing_sha_field]), limit=MAX_FILE
                )
        temporary = f".cutover-{slot}-{attempt_id}.part"
        _create_exclusive(child, temporary, payload)
        try:
            os.link(temporary, filename, src_dir_fd=child, dst_dir_fd=child, follow_symlinks=False)
            os.unlink(temporary, dir_fd=child)
            os.fsync(child)
        except OSError as exc:
            raise StageError("cutover atomic file activation interrupted; quarantine") from exc
    finally:
        os.close(child)
        os.close(root)


def verify(attempt_id: str, legacy_compose_sha: str) -> Path:
    """Return a *verified private path*; not authority to start/stop Docker."""
    root, child, marker = _authenticated_stage(attempt_id, legacy_compose_sha)
    try:
        if set(os.listdir(child)) != {MARKER, *(name for name, _ in FILES.values())}:
            raise StageError("cutover attempt incomplete or has unreviewed residue")
        for filename, sha_field in FILES.values():
            _read_file(child, filename, str(marker[sha_field]), limit=MAX_FILE)
        return ROOT / _stage_name(attempt_id)
    finally:
        os.close(child)
        os.close(root)


def read_verified(attempt_id: str, legacy_compose_sha: str, slot: str) -> bytes:
    """Read a reviewed public artifact through owned FDs, never path traversal."""
    if slot not in FILES:
        raise StageError("unreviewed cutover read slot")
    root, child, marker = _authenticated_stage(attempt_id, legacy_compose_sha)
    try:
        if set(os.listdir(child)) != {MARKER, *(name for name, _ in FILES.values())}:
            raise StageError("cutover stage incomplete before immutable read")
        for filename, sha_field in FILES.values():
            payload, _ = _read_file(child, filename, str(marker[sha_field]), limit=MAX_FILE)
            if FILES[slot][0] == filename:
                result = payload
        return result
    finally:
        os.close(child)
        os.close(root)


def _promotion_payload(marker: dict[str, str | int], candidate_id: str, worker_id: str) -> bytes:
    original_id = marker["legacy_controller_id"]
    if (
        not CONTAINER.fullmatch(candidate_id)
        or not CONTAINER.fullmatch(worker_id)
        or len({original_id, candidate_id, worker_id}) != 3
    ):
        raise StageError("cutover promotion exact controller and worker IDs invalid")
    return _canonical(
        {
            "version": COMMIT_VERSION,
            "attempt_id": marker["attempt_id"],
            "legacy_id": original_id,
            "candidate_id": candidate_id,
            "worker_id": worker_id,
            "base_sha": marker["target_compose_sha"],
            "overlay_sha": marker["overlay_compose_sha"],
            "seccomp_sha": marker["seccomp_sha"],
        }
    )


def _read_exact_promotion(child: int, name: str, expected: bytes) -> None:
    raw, _ = _read_file(child, name, hashlib.sha256(expected).hexdigest(), limit=MAX_MARKER)
    if raw != expected:
        raise StageError("cutover durable promotion record does not match accepted IDs")


def promote_accepted(
    attempt_id: str, legacy_compose_sha: str, candidate_id: str, worker_id: str
) -> None:
    """After accepted candidate only: fix-forward three files with durable intent.

    This is *not* an atomic multi-file rename. Intent is O_EXCL + fsynced
    before any original file is replaced; a crash before the result leaves
    visible partial state that forbids silent recovery/retry/legacy restart.
    No backup or deletion of persistent Boca data/key/owner is performed.
    """
    verify(attempt_id, legacy_compose_sha)
    root, child, marker = _authenticated_stage(attempt_id, legacy_compose_sha)
    try:
        expected_files = {MARKER, *(filename for filename, _ in FILES.values())}
        if set(os.listdir(child)) != expected_files:
            raise StageError("cutover stage changed before irreversible promotion")
        intent = _promotion_payload(marker, candidate_id, worker_id)
        payloads = {
            filename: _read_file(child, filename, str(marker[sha_field]), limit=MAX_FILE)[0]
            for filename, sha_field in FILES.values()
        }
        # The first durable intent marks the irreversible fix-forward boundary.
        _create_exclusive(child, COMMIT_INTENT, intent)
        promoted = {"compose.beta.yaml", _stage_name(attempt_id)}
        for slot, (filename, sha_field) in FILES.items():
            # The old base is replaced first. Overlay/seccomp MUST be absent
            # until their exact individual write; a foreign root object is
            # never overwritten by a guessed continuation.
            if set(os.listdir(root)) != promoted:
                raise StageError("cutover promotion root gained unexpected object")
            name = f".cutover-promote-{slot}-{attempt_id}.part"
            _create_exclusive(root, name, payloads[filename])
            try:
                os.replace(name, filename, src_dir_fd=root, dst_dir_fd=root)
                os.fsync(root)
            except OSError as exc:
                raise StageError("cutover promotion outcome uncertain; fix-forward only") from exc
            _read_file(root, filename, str(marker[sha_field]), limit=MAX_FILE)
            promoted.add(filename)
        _create_exclusive(child, COMMIT_RESULT, intent)
        _read_exact_promotion(child, COMMIT_RESULT, intent)
        os.fsync(child)
    finally:
        os.close(child)
        os.close(root)


def discard_recovered(attempt_id: str, legacy_compose_sha: str) -> None:
    """Remove only a positively verified *uncommitted* stage after old-ID recovery.

    A .part, unknown file or promotion-intent marker is quarantined/NO_GO; no
    broad recursive delete is ever attempted. Each unlink is one exact name.
    """
    root, child, marker = _authenticated_stage(attempt_id, legacy_compose_sha)
    try:
        entries = set(os.listdir(child))
        reviewed = {MARKER, *(filename for filename, _ in FILES.values())}
        if not {MARKER} <= entries <= reviewed:
            raise StageError("cutover uncommitted stage has unknown/partial residue")
        for filename, sha_field in FILES.values():
            if filename in entries:
                _read_file(child, filename, str(marker[sha_field]), limit=MAX_FILE)
        for filename in sorted(entries - {MARKER}):
            os.unlink(filename, dir_fd=child)
        os.unlink(MARKER, dir_fd=child)
        os.fsync(child)
        os.close(child)
        child = -1
        os.rmdir(_stage_name(attempt_id), dir_fd=root)
        os.fsync(root)
        if set(os.listdir(root)) != {"compose.beta.yaml"}:
            raise StageError("cutover failed-stage cleanup left unreviewed root residue")
    except OSError as exc:
        raise StageError("cutover recovered stage cleanup uncertain") from exc
    finally:
        if child >= 0:
            os.close(child)
        os.close(root)


def finalize_promoted(
    attempt_id: str, legacy_compose_sha: str, candidate_id: str, worker_id: str
) -> None:
    """Delete exact staging residue after *independent* accepted-ID retirement.

    Caller must first positively attest old ID absent and candidate+worker
    healthy. Root now holds the reviewed target files (no legacy replacement
    unless the O_EXCL promotion intent and positive result both exist).
    """
    root, child, marker = _authenticated_stage(attempt_id, legacy_compose_sha, promoted=True)
    try:
        expected = {MARKER, COMMIT_INTENT, COMMIT_RESULT, *(name for name, _ in FILES.values())}
        if set(os.listdir(child)) != expected:
            raise StageError("cutover promotion stage residue/receipt incomplete")
        intent = _promotion_payload(marker, candidate_id, worker_id)
        _read_exact_promotion(child, COMMIT_INTENT, intent)
        _read_exact_promotion(child, COMMIT_RESULT, intent)
        for filename, sha_field in FILES.values():
            _read_file(child, filename, str(marker[sha_field]), limit=MAX_FILE)
        for filename in sorted(expected - {MARKER}):
            os.unlink(filename, dir_fd=child)
        os.unlink(MARKER, dir_fd=child)
        os.fsync(child)
        os.close(child)
        child = -1
        os.rmdir(_stage_name(attempt_id), dir_fd=root)
        os.fsync(root)
        if set(os.listdir(root)) != {
            "compose.beta.yaml",
            "compose.beta.browser.yaml",
            "seccomp_profile.json",
        }:
            raise StageError("cutover promoted root includes unexpected staging residue")
    except OSError as exc:
        raise StageError("cutover promoted stage cleanup uncertain") from exc
    finally:
        if child >= 0:
            os.close(child)
        os.close(root)
