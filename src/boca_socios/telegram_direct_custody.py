"""Private in-image operation. Only non-secret evidence crosses its boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from boca_socios import telegram_bootstrap as boot
from boca_socios.panel.telegram_direct_staging import (
    FILENAME as STAGE,
)
from boca_socios.panel.telegram_direct_staging import (
    PURPOSE,
    DirectStageRequest,
    _require_no_interrupted_write,
)
from boca_socios.panel.telegram_pairing_staging import STAGING_FILENAME as V2_STAGE

TOKEN = "direct_bot_token"  # noqa: S105 - separated from legacy sender filenames
CHAT = "direct_chat_id"
MARKER = "telegram_direct_commit_v1"
_PENDING = ".telegram_direct_commit_v1.pending"
_FIELDS = {
    "version",
    "purpose",
    "repository",
    "uid",
    "source_sha",
    "stage_id",
    "staged_at",
    "bot_token",
    "chat_id",
}


def _require(value: bool) -> None:
    if not value:
        raise ValueError("direct_custody_unverified")


def _id(meta: os.stat_result) -> tuple[int, int]:
    return meta.st_dev, meta.st_ino


def _stamp(meta: os.stat_result) -> tuple[int, ...]:
    return (
        *_id(meta),
        meta.st_uid,
        meta.st_gid,
        meta.st_mode,
        meta.st_nlink,
        meta.st_size,
        meta.st_mtime_ns,
        meta.st_ctime_ns,
    )


def _data(path: Path, uid: int) -> int:
    _require(path.is_absolute() and ".." not in path.parts and len(path.parts) <= 32)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        m = os.fstat(fd)
        _require(m.st_uid == m.st_gid == uid and stat.S_IMODE(m.st_mode) in {0o700, 0o755})
        return fd
    except BaseException:
        os.close(fd)
        raise


def _stage(data: int, uid: int, src: str) -> tuple[dict[str, Any], tuple[int, ...], bytes, bytes]:
    _require_no_interrupted_write(data)
    _require(not boot._exists(data, V2_STAGE))
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(STAGE, flags, dir_fd=data), "rb") as stream:
        m = os.fstat(stream.fileno())
        _require(
            stat.S_ISREG(m.st_mode)
            and stat.S_IMODE(m.st_mode) == 0o600
            and m.st_uid == m.st_gid == uid
            and m.st_nlink == 1
            and 0 < m.st_size <= 2048
        )
        raw = stream.read(2049)
        _require(
            len(raw) == m.st_size
            and _stamp(os.fstat(stream.fileno())) == _stamp(m)
            and _stamp(os.stat(STAGE, dir_fd=data, follow_symlinks=False)) == _stamp(m)
        )
    v = json.loads(raw, object_pairs_hook=boot._unique)
    _require(
        type(v) is dict
        and set(v) == _FIELDS
        and boot._canonical(v) == raw
        and type(v["version"]) is int
        and v["version"] == 1
        and type(v["uid"]) is int
        and v["uid"] == 10001
        and v["purpose"] == PURPOSE
        and v["repository"] == boot.REPOSITORY
        and v["source_sha"] == src
        and re.fullmatch("[0-9a-f]{64}", v["stage_id"]) is not None
        and type(v["staged_at"]) is int
        and 0 < v["staged_at"] <= int(time.time())
    )
    DirectStageRequest(v["bot_token"], v["chat_id"], src).validate()
    return v, _stamp(m), v["bot_token"].encode("ascii"), v["chat_id"].encode("ascii")


def _key(fd: int, uid: int) -> tuple[int, ...] | None:
    if not boot._exists(fd, boot.PRIVATE_KEY):
        return None
    m = os.stat(boot.PRIVATE_KEY, dir_fd=fd, follow_symlinks=False)
    secret = boot._read(fd, boot.PRIVATE_KEY, uid, maximum=32)
    _require(len(secret) == 32)
    boot._receipt(secret, "PREPARED")
    _require(_stamp(m) == _stamp(os.stat(boot.PRIVATE_KEY, dir_fd=fd, follow_symlinks=False)))
    return _stamp(m)


def _marker(fd: int, source: str, stage_id: str, witness: str, token: bytes, chat: bytes) -> bytes:
    fields = {"source_sha": source, "stage_id": stage_id, "witness": witness}
    authenticated: dict[str, object] = {
        **fields,
        "sender": "OFF",
        "bot": token.partition(b":")[0].decode("ascii"),
        "chat": chat.decode("ascii"),
        "volume": _id(os.fstat(fd)),
    }
    tag = hmac.digest(token, b"boca-direct-commit-v1\0" + boot._canonical(authenticated), "sha256")
    return boot._canonical({**fields, "tag": tag.hex()})


def _publish_marker(parent: int, content: bytes, uid: int) -> None:
    # Never expose a partially written final name. Any interrupted temporary is
    # evidence: leave it in place, and refuse both replay and certification.
    boot._write_new(parent, _PENDING, content, uid)
    _require(hmac.compare_digest(content, boot._read(parent, _PENDING, uid, maximum=512)))
    before = os.stat(_PENDING, dir_fd=parent, follow_symlinks=False)
    os.link(_PENDING, MARKER, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
    os.fsync(parent)
    for name in (_PENDING, MARKER):
        current = os.stat(name, dir_fd=parent, follow_symlinks=False)
        _require(
            _id(current) == _id(before)
            and current.st_nlink == 2
            and current.st_uid == current.st_gid == uid
            and current.st_size == len(content)
            and current.st_mode == before.st_mode
        )
    os.unlink(_PENDING, dir_fd=parent)
    os.fsync(parent)


def verify_committed(
    directory: Path, source: str, stage_id: str, *, uid: int = boot.UID
) -> dict[str, str]:
    """Inspect only final files, even after separate cleanup of the exact transient stage."""
    try:
        boot._identity(uid)
        _require(
            re.fullmatch("[0-9a-f]{40}", source) is not None
            and re.fullmatch("[0-9a-f]{64}", stage_id) is not None
        )
        fd = boot._directory(directory, uid)
        try:
            names = {TOKEN, CHAT, MARKER} | ({boot.PRIVATE_KEY} if _key(fd, uid) else set())
            _require(set(os.listdir(fd)) == names)

            def sample() -> bytes:
                raw = boot._read(fd, MARKER, uid, maximum=512)
                doc = json.loads(raw, object_pairs_hook=boot._unique)
                witness = doc["witness"]
                _require(re.fullmatch("[0-9a-f]{64}", witness) is not None)
                token = boot._token(boot._read(fd, TOKEN, uid, maximum=150).decode("ascii"))
                chat = boot._chat(boot._read(fd, CHAT, uid, maximum=21).decode("ascii"))
                _require(
                    hmac.compare_digest(raw, _marker(fd, source, stage_id, witness, token, chat))
                )
                return raw

            _require(
                sample() == sample()
                and set(os.listdir(fd)) == names
                and _id(directory.lstat()) == _id(os.fstat(fd))
            )
            return {"state": "INSTALLED_SENDER_OFF"}
        finally:
            os.close(fd)
    except Exception:
        raise ValueError("direct_custody_unverified") from None


def execute_direct(
    operation: str,
    data_path: Path,
    final_path: Path,
    request: dict[str, Any],
    *,
    uid: int = boot.UID,
) -> dict[str, str]:
    """Only inspect returns a public lease-bound witness; never return material or paths."""
    try:
        boot._identity(uid)
        base = {"source_sha", "lease_binding"}
        _require(
            operation in {"inspect-direct", "install-direct", "verify-direct"}
            and type(request) is dict
            and set(request) == (base if operation == "inspect-direct" else base | {"witness"})
            and re.fullmatch("[0-9a-f]{40}", request["source_sha"]) is not None
            and re.fullmatch("[0-9a-f]{64}", request["lease_binding"]) is not None
        )
        with ExitStack() as stack:
            data = _data(data_path, uid)
            stack.callback(os.close, data)
            final = boot._directory(final_path, uid)
            stack.callback(os.close, final)
            data_id, final_id = _id(os.fstat(data)), _id(os.fstat(final))
            _require(data_id != final_id)
            v, stamp, token, chat = _stage(data, uid, request["source_sha"])
            key = _key(final, uid)
            names = {boot.PRIVATE_KEY} if key else set()
            _require(
                set(os.listdir(final))
                == (names | {TOKEN, CHAT, MARKER} if operation == "verify-direct" else names)
            )
            public = {
                "source_sha": v["source_sha"],
                "stage_id": v["stage_id"],
                "lease_binding": request["lease_binding"],
                "data": data_id,
                "custody": final_id,
                "key": key,
                "stage": stamp,
            }
            witness = hashlib.sha256(boot._canonical(public)).hexdigest()
            marker = _marker(final, v["source_sha"], v["stage_id"], witness, token, chat)

            def stable() -> None:
                _require_no_interrupted_write(data)
                _require(
                    _id(data_path.lstat()) == data_id
                    and _id(final_path.lstat()) == final_id
                    and not boot._exists(data, V2_STAGE)
                    and _stamp(os.stat(STAGE, dir_fd=data, follow_symlinks=False)) == stamp
                    and _key(final, uid) == key
                )

            def check_pair() -> None:
                _require(
                    hmac.compare_digest(token, boot._read(final, TOKEN, uid, maximum=150))
                    and hmac.compare_digest(chat, boot._read(final, CHAT, uid, maximum=21))
                )

            stable()
            if operation == "inspect-direct":
                return {"witness": witness}
            _require(hmac.compare_digest(request["witness"], witness))
            if operation == "install-direct":
                boot._write_new(final, TOKEN, token, uid)
                boot._write_new(final, CHAT, chat, uid)
                check_pair()
                stable()
                _require(set(os.listdir(final)) == names | {TOKEN, CHAT})
                _publish_marker(final, marker, uid)
            check_pair()
            _require(
                hmac.compare_digest(marker, boot._read(final, MARKER, uid, maximum=512))
                and verify_committed(final_path, v["source_sha"], v["stage_id"], uid=uid)
                == {"state": "INSTALLED_SENDER_OFF"}
            )
            stable()
            return {
                "state": "WRITTEN_SENDER_OFF"
                if operation == "install-direct"
                else "INSTALLED_SENDER_OFF_STAGE_CLEANUP_PENDING"
            }
    except Exception:
        raise ValueError("direct_custody_unverified") from None
