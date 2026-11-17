"""Owner-only, local DATA staging. This module never installs or contacts Telegram."""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from boca_socios import telegram_bootstrap as boot
from boca_socios.panel.telegram_pairing_staging import STAGING_FILENAME as V2_STAGE
from boca_socios.panel.telegram_recipient import _public_data_directory

FILENAME = "boca_telegram_direct_stage_v1.json"
PURPOSE = "boca-telegram-direct-owner-stage-v1"
_TEMP_NAME = re.compile(r"\." + re.escape(FILENAME) + r"\.[a-f0-9]{32}\.tmp")


class DirectStageConflict(ValueError):
    """A previous submission is preserved unchanged."""


@dataclass(frozen=True, slots=True, repr=False)
class DirectStageRequest:
    bot_token: str
    chat_id: str
    source_sha: str

    def validate(self) -> None:
        boot._token(self.bot_token)
        boot._chat(self.chat_id)
        for value in (self.bot_token.partition(":")[0], self.chat_id):
            if not 0 < int(value) < 2**52 or str(int(value)) != value:
                raise ValueError("invalid_secret_material")
        if not re.fullmatch("[0-9a-f]{40}", self.source_sha):
            raise ValueError("direct_stage_unavailable")


@dataclass(frozen=True, slots=True)
class DirectStageReceipt:
    state: str = "PENDING_INSTALLATION"


@contextmanager
def _directory(path: Path, identity: tuple[int, int] | None = None) -> Iterator[int]:
    if path.name != FILENAME:
        raise ValueError("direct_stage_unavailable")
    fd = _public_data_directory(path.parent)
    try:
        attrs = os.fstat(fd)
        if (identity is not None and identity != (attrs.st_dev, attrs.st_ino)) or not os.access(
            ".", os.W_OK | os.X_OK, dir_fd=fd, effective_ids=True
        ):
            raise ValueError("direct_stage_unavailable")
        yield fd
    finally:
        os.close(fd)


def _private_file(fd: int) -> os.stat_result:
    attrs = os.fstat(fd)
    if (
        not stat.S_ISREG(attrs.st_mode)
        or stat.S_IMODE(attrs.st_mode) != 0o600
        or (attrs.st_uid, attrs.st_gid) != (boot.UID, boot.UID)
        or attrs.st_nlink != 1
    ):
        raise ValueError("direct_stage_unavailable")
    return attrs


def _fields(request: DirectStageRequest) -> dict[str, object]:
    return dict(
        version=1,
        purpose=PURPOSE,
        repository=boot.REPOSITORY,
        uid=10001,
        source_sha=request.source_sha,
        bot_token=request.bot_token,
        chat_id=request.chat_id,
    )


def _pending(fd: int, source: str) -> bool:
    try:
        opened = os.open(FILENAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        return False
    with os.fdopen(opened, "rb") as stream:
        attrs = _private_file(stream.fileno())
        if not 0 < attrs.st_size <= 2048:
            raise ValueError("direct_stage_unavailable")
        raw = stream.read(2049)
    try:
        obj = json.loads(raw, object_pairs_hook=boot._unique)
        req = DirectStageRequest(obj["bot_token"], obj["chat_id"], source)
        req.validate()
        expected = dict(_fields(req), stage_id=obj["stage_id"], staged_at=obj["staged_at"])
        if (
            type(obj["staged_at"]) is not int
            or obj["staged_at"] <= 0
            or re.fullmatch("[0-9a-f]{64}", obj["stage_id"]) is None
            or boot._canonical(expected) != raw
        ):
            raise ValueError
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise ValueError("direct_stage_unavailable") from None
    return True


def _require_no_interrupted_write(fd: int) -> None:
    # Never open, unlink or reinterpret an interrupted writer's private file.
    with os.scandir(fd) as entries:
        if any(_TEMP_NAME.fullmatch(entry.name) for entry in entries):
            raise ValueError("direct_stage_indeterminate")


@dataclass(frozen=True, slots=True)
class DirectStage:
    path: Path
    source: str
    identity: tuple[int, int] | None

    @classmethod
    def bind(cls, path: Path, source: str) -> DirectStage:
        # Preserve an unavailable direct route as a 503, never a silent fallback.
        identity = None
        if re.fullmatch("[a-f0-9]{40}", source):
            try:
                with _directory(path) as fd:
                    info = os.fstat(fd)
                    identity = (info.st_dev, info.st_ino)
            except (ValueError, OSError):
                pass
        return cls(path, source, identity)

    def pending(self) -> bool:
        if self.identity is None:
            raise ValueError("direct_stage_unavailable")
        with _directory(self.path, self.identity) as fd:
            _require_no_interrupted_write(fd)
            if boot._exists(fd, V2_STAGE):
                raise DirectStageConflict("previous_stage")
            return _pending(fd, self.source)

    def save(self, request: DirectStageRequest) -> DirectStageReceipt:
        if self.identity is None or request.source_sha != self.source:
            raise ValueError("direct_stage_unavailable")
        return stage_private_direct_telegram(self.path, request, identity=self.identity)


def stage_private_direct_telegram(
    path: Path, request: DirectStageRequest, *, identity: tuple[int, int] | None = None
) -> DirectStageReceipt:
    request.validate()
    doc = boot._canonical(
        dict(_fields(request), stage_id=secrets.token_hex(32), staged_at=int(time.time()))
    )
    try:
        with _directory(path, identity) as fd:
            # One writer (including concurrent controller processes) may inspect
            # or create its temp at a time. Crash releases this kernel lock only.
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DirectStageConflict("another_writer") from None
            _require_no_interrupted_write(fd)
            if boot._exists(fd, FILENAME) or boot._exists(fd, V2_STAGE):
                raise DirectStageConflict("previous_stage")
            name = f".{FILENAME}.{secrets.token_hex(16)}.tmp"
            temp = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd
            )
            published = durable = False
            try:
                with os.fdopen(temp, "wb") as stream:
                    _private_file(stream.fileno())
                    stream.write(doc)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Refuse a replaced DATA directory before making the pair visible.
                info = os.fstat(fd)
                with _directory(path, (info.st_dev, info.st_ino)):
                    if boot._exists(fd, V2_STAGE):
                        raise DirectStageConflict("previous_stage")
                    try:
                        os.link(name, FILENAME, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
                        published = True
                    except FileExistsError:
                        raise DirectStageConflict("previous_stage") from None
                # Persist publication before removing its recovery evidence.
                # An ambiguous fsync leaves both names and blocks another save.
                os.fsync(fd)
                durable = True
            finally:
                if not published or durable:
                    os.unlink(name, dir_fd=fd)
            os.fsync(fd)
        return DirectStageReceipt()
    except OSError:
        raise ValueError("direct_stage_unavailable") from None
