"""Minimal Boca-rootless dual-upgrade stage, tolerating older owned stage dirs.

Unlike the singleton Cutover V3 initializer this operation never inventories or
renames historical stage directories. The one fresh attempt-named child has
O_EXCL/fsync public Compose and seccomp bytes; historical Compose content and
inode must remain identical. No Docker, credentials or member database here.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from boca_socios import host_cutover_stage as guarded

_MARKER = "boca-pair-stage.json"
_FIELDS = {
    "base": ("compose.beta.yaml", "base_sha"),
    "overlay": ("compose.beta.browser.yaml", "overlay_sha"),
    "seccomp": ("seccomp_profile.json", "seccomp_sha"),
}


@dataclass(frozen=True, slots=True)
class PairSources:
    base: bytes
    overlay: bytes
    seccomp: bytes
    original_compose_sha: str
    base_sha: str
    overlay_sha: str
    seccomp_sha: str

    def validate(self) -> None:
        if (
            any(
                type(data) is not bytes or not 0 < len(data) <= guarded.MAX_FILE
                for data in (self.base, self.overlay, self.seccomp)
            )
            or any(
                type(value) is not str or guarded.SHA.fullmatch(value) is None
                for value in (
                    self.original_compose_sha,
                    self.base_sha,
                    self.overlay_sha,
                    self.seccomp_sha,
                )
            )
            or hashlib.sha256(self.base).hexdigest() != self.base_sha
            or hashlib.sha256(self.overlay).hexdigest() != self.overlay_sha
            or hashlib.sha256(self.seccomp).hexdigest() != self.seccomp_sha
            or len({self.overlay_sha, self.seccomp_sha, self.base_sha}) != 3
        ):
            raise guarded.StageError("Boca dual stage artifacts untrusted")


def _marker(attempt: str, sources: PairSources, *, device: int, inode: int) -> bytes:
    payload = {
        "schema": 1,
        "attempt": attempt,
        "original_compose_sha": sources.original_compose_sha,
        "original_compose_dev": device,
        "original_compose_inode": inode,
        "base_sha": sources.base_sha,
        "overlay_sha": sources.overlay_sha,
        "seccomp_sha": sources.seccomp_sha,
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("ascii")


def _child(attempt_id: str) -> str:
    if type(attempt_id) is not str or guarded.ATTEMPT.fullmatch(attempt_id) is None:
        raise guarded.StageError("Boca dual stage attempt invalid")
    return f"cutover-a-{attempt_id}"


def prepare(attempt_id: str, sources: PairSources) -> Path:
    """Exclusive private stage; leave interrupted attempts quarantined."""
    if type(sources) is not PairSources:
        raise guarded.StageError("Boca dual stage sources unavailable")
    sources.validate()
    name = _child(attempt_id)
    root = guarded._root_fd()
    try:
        _data, original = guarded._read_file(
            root,
            "compose.beta.yaml",
            sources.original_compose_sha,
            limit=guarded.MAX_FILE,
            historical_compose=True,
        )
        os.mkdir(name, 0o700, dir_fd=root)
        child = os.open(
            name, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root
        )
        try:
            os.fchmod(child, 0o700)
            guarded._checked_dir(child)
            if os.listdir(child):
                raise guarded.StageError("Boca dual stage child not empty")
            guarded._create_exclusive(
                child,
                _MARKER,
                _marker(attempt_id, sources, device=original.st_dev, inode=original.st_ino),
            )
            for slot, (filename, _) in _FIELDS.items():
                guarded._create_exclusive(child, filename, getattr(sources, slot))
            os.fsync(child)
        finally:
            os.close(child)
        os.fsync(root)
        _data, after = guarded._read_file(
            root,
            "compose.beta.yaml",
            sources.original_compose_sha,
            limit=guarded.MAX_FILE,
            historical_compose=True,
        )
        if not guarded._same_inode(original, after):
            raise guarded.StageError("historical Boca Compose changed during dual stage")
    except (OSError, OverflowError) as exc:
        raise guarded.StageError("Boca dual stage filesystem cannot be trusted") from exc
    finally:
        os.close(root)
    return verify(attempt_id, sources)


def verify(attempt_id: str, sources: PairSources) -> Path:
    """Read-only reattestation of exact attempt files and old Compose inode."""
    if type(sources) is not PairSources:
        raise guarded.StageError("Boca dual stage sources unavailable")
    sources.validate()
    name = _child(attempt_id)
    root = guarded._root_fd()
    child: int | None = None
    try:
        child = os.open(
            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root
        )
        guarded._checked_dir(child)
        if set(os.listdir(child)) != {_MARKER, *(file for file, _ in _FIELDS.values())}:
            raise guarded.StageError("Boca dual stage has missing or unreviewed entry")
        raw, _ = guarded._read_file(child, _MARKER, None, limit=guarded.MAX_MARKER)
        _data, original = guarded._read_file(
            root,
            "compose.beta.yaml",
            sources.original_compose_sha,
            limit=guarded.MAX_FILE,
            historical_compose=True,
        )
        if raw != _marker(attempt_id, sources, device=original.st_dev, inode=original.st_ino):
            raise guarded.StageError("Boca dual staged marker or old Compose identity changed")
        for slot, (filename, expected_field) in _FIELDS.items():
            reviewed = getattr(sources, slot)
            data, _ = guarded._read_file(
                child, filename, getattr(sources, expected_field), limit=guarded.MAX_FILE
            )
            if data != reviewed:
                raise guarded.StageError("Boca dual staged bytes differ from release")
        return guarded.ROOT / name
    except (OSError, OverflowError) as exc:
        raise guarded.StageError("Boca dual stage cannot be attested") from exc
    finally:
        if child is not None:
            os.close(child)
        os.close(root)
