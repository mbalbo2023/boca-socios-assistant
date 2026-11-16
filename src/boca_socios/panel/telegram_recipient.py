"""Public recipient handoff; no private custody is mounted in the owner panel."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from dataclasses import asdict
from pathlib import Path

from boca_socios import telegram_bootstrap as bootstrap

FILENAME = "telegram_recipient_public_v2.json"
PURPOSE = "boca-telegram-prepared-recipient-v2"
PUBLIC_DATA_DIR = Path("/data")


def _public_data_directory(directory: Path) -> int:
    """Open PUBLIC DATA only, preserving exact private-custody mode policy."""
    bootstrap._identity(bootstrap.UID)
    if (
        directory != PUBLIC_DATA_DIR
        or not directory.is_absolute()
        or ".." in directory.parts
        or not 1 < len(directory.parts) <= 32
    ):
        raise bootstrap.BootstrapError("telegram_directory_unsafe")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        ancestor = os.open("/", flags)
        try:
            for part in directory.parts[1:-1]:
                child = os.open(part, flags, dir_fd=ancestor)
                os.close(ancestor)
                ancestor = child
            before = os.stat(directory.name, dir_fd=ancestor, follow_symlinks=False)
            parent = os.open(directory.name, flags, dir_fd=ancestor)
            try:
                current = os.fstat(parent)
                after = os.stat(directory.name, dir_fd=ancestor, follow_symlinks=False)

                def identity(meta: os.stat_result) -> tuple[int, ...]:
                    return (
                        meta.st_dev,
                        meta.st_ino,
                        meta.st_mode,
                        meta.st_uid,
                        meta.st_gid,
                        meta.st_nlink,
                        meta.st_size,
                        meta.st_mtime_ns,
                        meta.st_ctime_ns,
                    )

                if (
                    identity(before) != identity(current)
                    or identity(after) != identity(current)
                    or not stat.S_ISDIR(current.st_mode)
                    or (current.st_uid, current.st_gid) != (bootstrap.UID, bootstrap.UID)
                    or stat.S_IMODE(current.st_mode) not in (0o700, 0o755)
                ):
                    raise bootstrap.BootstrapError("telegram_directory_unsafe")
                result, parent = parent, -1
                return result
            finally:
                if parent >= 0:
                    os.close(parent)
        finally:
            os.close(ancestor)
    except OSError:
        raise bootstrap.BootstrapError("telegram_directory_unsafe") from None


def _document(raw: bytes, expected_source_sha: str) -> tuple[bootstrap.RecipientReceipt, str]:
    try:
        value = json.loads(raw, object_pairs_hook=bootstrap._unique)
        if (
            type(value) is not dict
            or set(value)
            != {"version", "purpose", "source_sha", "installation_fingerprint", "recipient"}
            or value["version"] != 2
            or type(value["version"]) is not int
            or value["purpose"] != PURPOSE
            or value["source_sha"] != expected_source_sha
            or re.fullmatch(r"[a-f0-9]{40}", expected_source_sha) is None
            or re.fullmatch(r"[a-f0-9]{64}", value["installation_fingerprint"]) is None
            or bootstrap._canonical(value) != raw
        ):
            raise ValueError("binding")
        recipient = bootstrap.RecipientReceipt(**value["recipient"])
        public = bootstrap._unb64(recipient.public_key, 32)
        if recipient.state != "PREPARED" or not hmac.compare_digest(
            hashlib.sha256(public).hexdigest(), recipient.fingerprint
        ):
            raise ValueError("recipient")
        return recipient, value["installation_fingerprint"]
    except Exception:
        raise ValueError("telegram_public_recipient_unverified") from None


def read_prepared_recipient(
    directory: Path, *, expected_source_sha: str
) -> bootstrap.RecipientReceipt:
    parent = _public_data_directory(directory)
    try:
        raw = bootstrap._read(parent, FILENAME, bootstrap.UID, maximum=1024)
        return _document(raw, expected_source_sha)[0]
    finally:
        os.close(parent)


def publish_prepared_recipient(
    directory: Path,
    recipient: bootstrap.RecipientReceipt,
    *,
    source_sha: str,
    installation_fingerprint: str,
) -> None:
    raw = bootstrap._canonical(
        {
            "version": 2,
            "purpose": PURPOSE,
            "source_sha": source_sha,
            "installation_fingerprint": installation_fingerprint,
            "recipient": {**asdict(recipient), "state": "PREPARED"},
        }
    )
    _document(raw, source_sha)
    parent = _public_data_directory(directory)
    try:
        if bootstrap._exists(parent, FILENAME):
            if bootstrap._read(parent, FILENAME, bootstrap.UID, maximum=1024) != raw:
                raise ValueError("telegram_public_recipient_conflict")
        else:
            bootstrap._write_new(parent, FILENAME, raw, bootstrap.UID)
    finally:
        os.close(parent)
