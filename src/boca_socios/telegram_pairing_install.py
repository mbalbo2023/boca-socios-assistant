"""Fail-closed V2 visibility commit above existing offline Telegram V1 custody.

This **source-only** coordinator is not a host workflow or CLI. A protected
caller must first prove that the exact installed controller/sender is stopped,
the Boca-only volume and owner UID are correct, the image/source digest is
pinned, and the V2 plan came from fresh genuine Telegram identity evidence.

POSIX does not atomically install the two legacy V1 secret filenames and a
third marker together. We preserve V1, install its pair with its existing
exclusive-create code, and publish a V2 visibility marker **last**. V2-aware
consumers must use ``verify_v2_custody`` and keep the sender OFF unless it
succeeds. Any partial file, stale stage, link count or crash is preserved as
NO_GO; this code never rolls back, purges or retries ambiguous mutations.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios.telegram_pairing_resolver import PairingInstallPlan, PairingInstallReceipt

MARKER = "telegram_pairing_commit_v2"
STAGING = "telegram_pairing_pending_v2"
PURPOSE = "boca-telegram-pairing-commit-v2"
MAX_MARKER = 2048
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MARKER_FIELDS = frozenset(
    {
        "version",
        "repository",
        "purpose",
        "source_sha",
        "recipient_fingerprint",
        "bot_id",
        "discovery_update_id",
        "pairing_observed_at",
        "expected_chat_hmac",
        "one_time_fence",
        "notification_receipt",
        "state",
    }
)


class PairingCustodyError(ValueError):
    """Only fixed redacted failures may be logged by a protected host caller."""


@dataclass(frozen=True, slots=True)
class PairingCustodyReceipt:
    """No token, private chat ID, HMAC pins, replay code or secret envelope."""

    source_sha: str
    recipient_fingerprint: str
    bot_id: int
    state: str = "CUSTODY_COMMITTED_NO_SEND"
    notification_receipt: str = "UNVERIFIED"


def _lock(directory_fd: int, *, exclusive: bool) -> None:
    try:
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(directory_fd, operation | fcntl.LOCK_NB)
    except OSError:
        raise PairingCustodyError("custody_lock_unavailable") from None


def _prepared(directory_fd: int, uid: int) -> tuple[bytes, bootstrap.RecipientReceipt]:
    private = bootstrap._read(directory_fd, bootstrap.PRIVATE_KEY, uid, maximum=32)
    return private, bootstrap._receipt(private, "PREPARED")


def _receipt_valid(receipt: PairingInstallReceipt, expected_source_sha: str, now: int) -> bool:
    return (
        isinstance(receipt, PairingInstallReceipt)
        and receipt.state == "READY_FOR_PROTECTED_INSTALL"
        and receipt.notification_receipt == "UNVERIFIED"
        and receipt.source_sha == expected_source_sha
        and isinstance(receipt.recipient_fingerprint, str)
        and _DIGEST.fullmatch(receipt.recipient_fingerprint) is not None
        and type(receipt.bot_id) is int
        and 0 < receipt.bot_id < 2**52
        and type(receipt.discovery_update_id) is int
        and receipt.discovery_update_id >= 0
        and type(receipt.pairing_observed_at) is int
        and 0 <= now - receipt.pairing_observed_at <= 600
        and isinstance(receipt.expected_chat_hmac, str)
        and _DIGEST.fullmatch(receipt.expected_chat_hmac) is not None
        and isinstance(receipt.one_time_fence, str)
        and _DIGEST.fullmatch(receipt.one_time_fence) is not None
    )


def _marker_fields(receipt: PairingInstallReceipt, token: bytes, chat: bytes) -> dict[str, object]:
    numeric_chat = int(chat.decode("ascii"))
    if (
        numeric_chat <= 0
        or numeric_chat >= 2**52
        or str(numeric_chat).encode("ascii") != chat
        or token.partition(b":")[0] != str(receipt.bot_id).encode("ascii")
        or not hmac.compare_digest(
            receipt.expected_chat_hmac,
            hmac.new(token, chat, hashlib.sha256).hexdigest(),
        )
    ):
        raise PairingCustodyError("paired_identity_unverified")
    return {
        "version": 2,
        "repository": bootstrap.REPOSITORY,
        "purpose": PURPOSE,
        "source_sha": receipt.source_sha,
        "recipient_fingerprint": receipt.recipient_fingerprint,
        "bot_id": receipt.bot_id,
        "discovery_update_id": receipt.discovery_update_id,
        "pairing_observed_at": receipt.pairing_observed_at,
        "expected_chat_hmac": receipt.expected_chat_hmac,
        "one_time_fence": receipt.one_time_fence,
        "notification_receipt": "UNVERIFIED",
        "state": "CUSTODY_COMMITTED_NO_SEND",
    }


def _marker_bytes(fields: dict[str, object], token: bytes) -> bytes:
    # A keyed integrity tag also authenticates the replay fence. It does not
    # substitute for live Bot API evidence or a human message receipt.
    tag = hmac.new(
        token,
        b"boca-telegram-pairing-commit-v2:" + bootstrap._canonical(fields),
        hashlib.sha256,
    ).hexdigest()
    data = bootstrap._canonical({**fields, "commit_tag": tag})
    if len(data) > MAX_MARKER:
        raise PairingCustodyError("commit_marker_unverified")
    return data


def install_v2_plan(
    directory: Path,
    plan: PairingInstallPlan,
    *,
    expected_source_sha: str,
    now: int,
    uid: int = bootstrap.UID,
) -> PairingCustodyReceipt:
    """Consume one V2 fence as a last-published marker after V1 pair writes.

    This method has genuine local filesystem effects. It is **not called by
    any deployed route, CLI, workflow or startup path**. Synthetic tests run
    only against temporary local directories with fake credentials.
    """
    if (
        not isinstance(expected_source_sha, str)
        or _SHA.fullmatch(expected_source_sha) is None
        or type(now) is not int
        or not isinstance(plan, PairingInstallPlan)
        or not _receipt_valid(plan.receipt, expected_source_sha, now)
    ):
        raise PairingCustodyError("prepared_pairing_unverified")
    bootstrap._identity(uid)
    parent = bootstrap._directory(directory, uid)
    try:
        _lock(parent, exclusive=True)
        # No purge or overwrite if a previous attempt is incomplete or done.
        if any(
            bootstrap._exists(parent, entry)
            for entry in (MARKER, STAGING, bootstrap.TOKEN_FILE, bootstrap.CHAT_FILE)
        ):
            raise PairingCustodyError("custody_already_or_partially_configured")
        private, prepared = _prepared(parent, uid)
        if plan.receipt.recipient_fingerprint != prepared.fingerprint:
            raise PairingCustodyError("recipient_identity_unverified")
        try:
            token, chat = bootstrap._decrypt(plan.sealed_v1_envelope, private, prepared)
        except bootstrap.BootstrapError:
            raise PairingCustodyError("sealed_install_unverified") from None
        fields = _marker_fields(plan.receipt, token, chat)
        marker = _marker_bytes(fields, token)
        try:
            installed_fingerprint = bootstrap.install(directory, plan.sealed_v1_envelope, uid=uid)
            if (
                installed_fingerprint != prepared.fingerprint
                or bootstrap.verify(directory, uid=uid) != prepared.fingerprint
            ):
                raise PairingCustodyError("custody_install_uncertain")
        except bootstrap.BootstrapError:
            # Even if one V1 file was written, never delete/overwrite/retry it.
            raise PairingCustodyError("custody_install_uncertain") from None
        # Stage fully durable content first. Readers require the final marker
        # with nlink=1 and *absence* of the staging name.
        try:
            bootstrap._write_new(parent, STAGING, marker, uid)
            os.link(
                STAGING,
                MARKER,
                src_dir_fd=parent,
                dst_dir_fd=parent,
                follow_symlinks=False,
            )
            # The last unlink is the logical visibility transition for V2.
            os.unlink(STAGING, dir_fd=parent)
            os.fsync(parent)
        except (OSError, bootstrap.BootstrapError):
            raise PairingCustodyError("custody_commit_uncertain") from None
        result = _verify_locked(parent, uid, expected_source_sha)
        if result.recipient_fingerprint != prepared.fingerprint:
            raise PairingCustodyError("custody_commit_uncertain")
        return result
    finally:
        os.close(parent)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in pairs:
        if key in values:
            raise PairingCustodyError("commit_marker_unverified")
        values[key] = value
    return values


def _verify_locked(parent: int, uid: int, expected_source_sha: str) -> PairingCustodyReceipt:
    if bootstrap._exists(parent, STAGING):
        raise PairingCustodyError("custody_partial_commit_preserved")
    private, prepared = _prepared(parent, uid)
    try:
        token = bootstrap._read(parent, bootstrap.TOKEN_FILE, uid, maximum=150)
        chat = bootstrap._read(parent, bootstrap.CHAT_FILE, uid, maximum=21)
        raw = bootstrap._read(parent, MARKER, uid, maximum=MAX_MARKER)
        data = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
        if (
            not isinstance(data, dict)
            or bootstrap._canonical(data) != raw
            or set(data) != _MARKER_FIELDS | {"commit_tag"}
        ):
            raise ValueError("marker")
        tag = data.pop("commit_tag", None)
        token_id = int(token.partition(b":")[0])
        numeric_chat = int(chat.decode("ascii"))
        if (
            type(data.get("version")) is not int
            or data["version"] != 2
            or data["repository"] != bootstrap.REPOSITORY
            or data["purpose"] != PURPOSE
            or data["source_sha"] != expected_source_sha
            or data["recipient_fingerprint"] != prepared.fingerprint
            or type(data["bot_id"]) is not int
            or data["bot_id"] != token_id
            or token.partition(b":")[0] != str(token_id).encode("ascii")
            or not 0 < numeric_chat < 2**52
            or chat != str(numeric_chat).encode("ascii")
            or type(data["discovery_update_id"]) is not int
            or data["discovery_update_id"] < 0
            or type(data["pairing_observed_at"]) is not int
            or data["pairing_observed_at"] < 0
            or not isinstance(data["expected_chat_hmac"], str)
            or _DIGEST.fullmatch(data["expected_chat_hmac"]) is None
            or not hmac.compare_digest(
                data["expected_chat_hmac"],
                hmac.new(token, chat, hashlib.sha256).hexdigest(),
            )
            or not isinstance(data["one_time_fence"], str)
            or _DIGEST.fullmatch(data["one_time_fence"]) is None
            or data["state"] != "CUSTODY_COMMITTED_NO_SEND"
            or data["notification_receipt"] != "UNVERIFIED"
            or not isinstance(tag, str)
            or _DIGEST.fullmatch(tag) is None
            or not hmac.compare_digest(
                tag,
                hmac.new(
                    token,
                    b"boca-telegram-pairing-commit-v2:" + bootstrap._canonical(data),
                    hashlib.sha256,
                ).hexdigest(),
            )
        ):
            raise ValueError("marker")
        return PairingCustodyReceipt(
            source_sha=expected_source_sha,
            recipient_fingerprint=prepared.fingerprint,
            bot_id=data["bot_id"],
        )
    except (ValueError, TypeError, UnicodeError, KeyError, bootstrap.BootstrapError):
        raise PairingCustodyError("commit_marker_unverified") from None


def verify_v2_custody(
    directory: Path, *, expected_source_sha: str, uid: int = bootstrap.UID
) -> PairingCustodyReceipt:
    """Mandatory future sender gate: V1 pair alone is never enough for V2."""
    if not isinstance(expected_source_sha, str) or _SHA.fullmatch(expected_source_sha) is None:
        raise PairingCustodyError("source_unverified")
    bootstrap._identity(uid)
    parent = bootstrap._directory(directory, uid)
    try:
        _lock(parent, exclusive=False)
        # Reject every ambiguous/crashed V1 partial state or temporary marker.
        try:
            if bootstrap.verify(directory, uid=uid) is None:
                raise PairingCustodyError("legacy_pair_unverified")
        except bootstrap.BootstrapError:
            raise PairingCustodyError("legacy_pair_unverified") from None
        return _verify_locked(parent, uid, expected_source_sha)
    finally:
        os.close(parent)
