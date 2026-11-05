"""Single-slot private staging of *encrypted* Telegram V2 owner handoff.

This is NOT authorization to read the Bot API, pair a chat, start a sender,
or consume a cutover nonce. A separate Actions-protected, same-lease host
transaction must validate the owner receipt and consume its own durable nonce.
The owner HTTP process never acquires that host lease or receives a bot token.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios.telegram_owner_webauthn import (
    TelegramStageOwnerWitness,
    parse_witness_document,
    witness_document,
)
from boca_socios.telegram_pairing_bootstrap import PURPOSE, VERSION

STAGING_FILENAME = "boca_telegram_pairing_stage_v2.json"
_STAGING_PURPOSE = "boca-telegram-private-encrypted-stage-v2"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class PairingStageUnavailable(ValueError):
    """Fixed redacted failure: never print ciphertext or filesystem details."""


class PairingStageConflict(PairingStageUnavailable):
    """A first encrypted handoff already exists and cannot be overwritten."""


@dataclass(frozen=True, slots=True)
class PairingStageReceipt:
    envelope_sha256: str
    recipient_fingerprint: str
    state: str = "STAGED_PENDING_PROTECTED_CUTOVER"


@dataclass(frozen=True, slots=True, repr=False)
class PairingStageRequest:
    """Verified owner UI handoff; stage still gives NO host/Telegram authority."""

    sealed_envelope: bytes
    owner_witness: TelegramStageOwnerWitness


def _validate_public_v2_header(envelope: bytes) -> str:
    """Check canonical encrypted frame, never decrypt or access Bot API."""
    try:
        if type(envelope) is not bytes or not 0 < len(envelope) <= bootstrap.MAX_ENVELOPE:
            raise ValueError("invalid size")
        document = json.loads(envelope.decode("ascii"), object_pairs_hook=bootstrap._unique)
        if not isinstance(document, dict) or set(document) != {
            "version",
            "repository",
            "purpose",
            "uid",
            "recipient_public_key",
            "recipient_fingerprint",
            "ephemeral_public_key",
            "salt",
            "nonce",
            "ciphertext",
        }:
            raise ValueError("invalid fields")
        if bootstrap._canonical(document) != envelope:
            raise ValueError("not canonical")
        if (
            type(document["version"]) is not int
            or document["version"] != VERSION
            or document["repository"] != bootstrap.REPOSITORY
            or document["purpose"] != PURPOSE
            or type(document["uid"]) is not int
            or document["uid"] != bootstrap.UID
            or type(document["recipient_fingerprint"]) is not str
            or _DIGEST.fullmatch(document["recipient_fingerprint"]) is None
        ):
            raise ValueError("invalid header")
        public = bootstrap._unb64(document["recipient_public_key"], 32)
        if hashlib.sha256(public).hexdigest() != document["recipient_fingerprint"]:
            raise ValueError("recipient mismatch")
        bootstrap._unb64(document["ephemeral_public_key"], 32)
        bootstrap._unb64(document["salt"], 16)
        bootstrap._unb64(document["nonce"], 12)
        ciphertext = bootstrap._unb64(document["ciphertext"], maximum=2048)
        if len(ciphertext) < 16:
            raise ValueError("ciphertext without tag")
        return document["recipient_fingerprint"]
    except (ValueError, TypeError, UnicodeError, KeyError, bootstrap.BootstrapError):
        raise PairingStageUnavailable("pairing_stage_unverified") from None


def stage_private_telegram_pairing(
    path: Path, request: PairingStageRequest | bytes
) -> PairingStageReceipt:
    """Persist one ciphertext using a private preexisting Boca volume directory.

    An atomic hard link publishes a complete fsynced file with O_EXCL semantics;
    an existing stage (including a symlink) is never overwritten or removed.
    This stage's random ID is *not* a host-cutover authorization nonce.
    """
    # Legacy bytes are retained for independent OFFLINE contract tests and
    # historical fixture compatibility. They never include owner proof.
    owner_witness = request.owner_witness if isinstance(request, PairingStageRequest) else None
    sealed_v2_envelope = (
        request.sealed_envelope if isinstance(request, PairingStageRequest) else request
    )
    fingerprint = _validate_public_v2_header(sealed_v2_envelope)
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or path.name != STAGING_FILENAME
        or ".." in path.parts
    ):
        raise PairingStageUnavailable("pairing_stage_unavailable")
    digest = hashlib.sha256(sealed_v2_envelope).hexdigest()
    staged_at = int(time.time())
    stage_fields: dict[str, object] = {
        "version": 2,
        "purpose": _STAGING_PURPOSE,
        "stage_id": secrets.token_hex(32),
        "staged_at": staged_at,
        "envelope_sha256": digest,
        "recipient_fingerprint": fingerprint,
        "envelope_base64url": bootstrap._b64(sealed_v2_envelope),
    }
    if owner_witness is not None:
        try:
            witness = parse_witness_document(witness_document(owner_witness))
            if not 0 <= staged_at - witness.challenged_at <= 120:
                raise ValueError("expired")
            stage_fields["owner_witness"] = witness_document(witness)
        except (ValueError, TypeError):
            raise PairingStageUnavailable("pairing_stage_unverified") from None
    document = bootstrap._canonical(stage_fields)
    if len(document) > 8192:
        raise PairingStageUnavailable("pairing_stage_unverified")
    directory_fd: int | None = None
    temp_fd: int | None = None
    temp_name: str | None = None
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        attrs = os.fstat(directory_fd)
        if not stat.S_ISDIR(attrs.st_mode) or attrs.st_uid != os.geteuid() or attrs.st_mode & 0o022:
            raise PairingStageUnavailable("pairing_stage_unavailable")
        temp_name = f".{STAGING_FILENAME}.{secrets.token_hex(16)}.tmp"
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        with os.fdopen(temp_fd, "wb", closefd=True) as stream:
            temp_fd = None
            stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(
                temp_name,
                STAGING_FILENAME,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            raise PairingStageConflict("pairing_stage_exists") from None
        os.fsync(directory_fd)
        return PairingStageReceipt(digest, fingerprint)
    except PairingStageUnavailable:
        raise
    except OSError:
        raise PairingStageUnavailable("pairing_stage_unavailable") from None
    finally:
        if temp_fd is not None:
            os.close(temp_fd)
        if temp_name is not None and directory_fd is not None:
            try:
                os.unlink(temp_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        if directory_fd is not None:
            os.close(directory_fd)
