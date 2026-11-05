"""Private Telegram V2 stage/nonce adapter for the canonical Boca job lease.

This code has no standalone CLI, host workflow, Docker control or provider
credentials. A future independently authorized Cutover A host backend may call
``execute_staged_pairing_under_lease`` while holding its *existing* canonical
``BocaJobLease`` and supplying authoritative owner/host receipts. Merely
constructing these Python arguments never constitutes physical host GO.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios.host_boca_cleanup import (
    BocaJobLease,
    CleanupError,
    verify_protected_boca_job_lease,
)
from boca_socios.panel.telegram_pairing_staging import (
    STAGING_FILENAME,
    _validate_public_v2_header,
)
from boca_socios.telegram_pairing_cutover import (
    CutoverCoordinates,
    HostRecheckReceipt,
    OwnerPairingReceipt,
    ProtectedPairingReceipt,
    _coordinates_valid,
    execute_protected_pairing,
)
from boca_socios.telegram_pairing_resolver import TelegramApiFetch

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_STAGE_PURPOSE = "boca-telegram-private-encrypted-stage-v2"
_NONCE_PURPOSE = "boca-telegram-protected-owner-nonce-v2"
_NONCE_PREFIX = "boca_telegram_owner_nonce_v2_"
_MAX_STAGE_BYTES = 8192
_MAX_NONCE_BYTES = 2048


class SameLeasePairingError(ValueError):
    """No raw paths, host claims, pairing code or token in any failure."""


@dataclass(frozen=True, slots=True)
class EncryptedPairingStage:
    """Authenticated-by-filesystem snapshot, NOT by owner lease alone."""

    stage_id: str = field(repr=False)
    staged_at: int
    envelope_sha256: str
    recipient_fingerprint: str
    file_identity: tuple[int, int, int, int] = field(repr=False)
    envelope: bytes = field(repr=False)


def _require_lease(lease: BocaJobLease, coordinates: CutoverCoordinates) -> None:
    try:
        if not _coordinates_valid(coordinates):
            raise ValueError("coordinates")
        verify_protected_boca_job_lease(lease, coordinates.attempt_id)
    except (CleanupError, ValueError, TypeError, OSError):
        raise SameLeasePairingError("telegram_same_lease_unverified") from None


def _open_volume(directory: Path) -> int:
    if not isinstance(directory, Path) or not directory.is_absolute() or ".." in directory.parts:
        raise SameLeasePairingError("telegram_volume_unverified")
    try:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        meta = os.fstat(fd)
        # The Docker host must additionally attest this as a named Boca volume.
        # A path supplied to this helper is not sufficient host proof.
        if (
            not stat.S_ISDIR(meta.st_mode)
            or meta.st_uid != os.geteuid()
            or meta.st_gid != os.getegid()
            or meta.st_mode & 0o022
        ):
            raise ValueError("directory")
    except (OSError, ValueError, TypeError):
        if "fd" in locals():
            os.close(fd)
        raise SameLeasePairingError("telegram_volume_unverified") from None
    return fd


def _read_staged_bytes(folder_fd: int) -> tuple[bytes, tuple[int, int, int, int]]:
    try:
        fd = os.open(
            STAGING_FILENAME,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=folder_fd,
        )
    except OSError:
        raise SameLeasePairingError("telegram_encrypted_stage_unverified") from None
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_gid != os.getegid()
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 0 < before.st_size <= _MAX_STAGE_BYTES
        ):
            raise ValueError("stage_inode")
        data = os.read(fd, _MAX_STAGE_BYTES + 1)
        after = os.fstat(fd)
        named = os.stat(STAGING_FILENAME, dir_fd=folder_fd, follow_symlinks=False)
        identity = (before.st_dev, before.st_ino, before.st_ctime_ns, before.st_mtime_ns)
        if (
            len(data) != before.st_size
            or (after.st_dev, after.st_ino, after.st_ctime_ns, after.st_mtime_ns) != identity
            or (named.st_dev, named.st_ino, named.st_ctime_ns, named.st_mtime_ns) != identity
        ):
            raise ValueError("stage_changed")
        return data, identity
    except (OSError, ValueError):
        raise SameLeasePairingError("telegram_encrypted_stage_unverified") from None
    finally:
        os.close(fd)


def read_encrypted_telegram_stage(
    directory: Path,
    *,
    coordinates: CutoverCoordinates,
    lease: BocaJobLease,
    trusted_now: int | None = None,
) -> EncryptedPairingStage:
    """Read one immutable ciphertext without exposing/consuming its stage ID.

    The stage is a non-authorizing Chrome handoff. Before any provider read a
    separately HMAC-signed owner receipt and durable protected nonce are needed.
    """
    _require_lease(lease, coordinates)
    folder = _open_volume(directory)
    try:
        raw, identity = _read_staged_bytes(folder)
        try:
            document = json.loads(raw.decode("ascii"), object_pairs_hook=bootstrap._unique)
            if (
                not isinstance(document, dict)
                or set(document)
                != {
                    "version",
                    "purpose",
                    "stage_id",
                    "staged_at",
                    "envelope_sha256",
                    "recipient_fingerprint",
                    "envelope_base64url",
                }
                or bootstrap._canonical(document) != raw
                or type(document["version"]) is not int
                or document["version"] != 2
                or document["purpose"] != _STAGE_PURPOSE
                or type(document["stage_id"]) is not str
                or _DIGEST.fullmatch(document["stage_id"]) is None
                or type(document["staged_at"]) is not int
                or document["staged_at"] <= 0
                or (
                    trusted_now is not None
                    and (type(trusted_now) is not int or document["staged_at"] > trusted_now + 30)
                )
                or type(document["envelope_sha256"]) is not str
                or _DIGEST.fullmatch(document["envelope_sha256"]) is None
                or type(document["recipient_fingerprint"]) is not str
                or document["recipient_fingerprint"] != coordinates.recipient_fingerprint
            ):
                raise ValueError("stage_document")
            envelope = bootstrap._unb64(
                document["envelope_base64url"], maximum=bootstrap.MAX_ENVELOPE
            )
            if (
                not hmac.compare_digest(
                    hashlib.sha256(envelope).hexdigest(), document["envelope_sha256"]
                )
                or _validate_public_v2_header(envelope) != coordinates.recipient_fingerprint
            ):
                raise ValueError("stage_envelope")
        except (ValueError, TypeError, KeyError, UnicodeError, bootstrap.BootstrapError):
            raise SameLeasePairingError("telegram_encrypted_stage_unverified") from None
        result = EncryptedPairingStage(
            stage_id=document["stage_id"],
            staged_at=document["staged_at"],
            envelope_sha256=document["envelope_sha256"],
            recipient_fingerprint=document["recipient_fingerprint"],
            file_identity=identity,
            envelope=envelope,
        )
        _require_lease(lease, coordinates)
        return result
    finally:
        os.close(folder)


def consume_telegram_owner_nonce(
    directory: Path,
    nonce: str,
    coordinates: CutoverCoordinates,
    *,
    lease: BocaJobLease,
) -> bool:
    """Durably spend HMAC nonce once, inside the *held* canonical Boca flock.

    O_EXCL is the consume linearization point. If later fsync or a provider
    phase fails, the marker is never removed: ambiguous is terminal and a
    fresh owner-signed nonce is required. It is NOT a Telegram send receipt.
    """
    _require_lease(lease, coordinates)
    if type(nonce) is not str or _DIGEST.fullmatch(nonce) is None:
        raise SameLeasePairingError("telegram_nonce_invalid")
    digest = hashlib.sha256(bytes.fromhex(nonce)).hexdigest()
    marker = f"{_NONCE_PREFIX}{digest}.json"
    payload = bootstrap._canonical(
        {
            "version": 2,
            "purpose": _NONCE_PURPOSE,
            "attempt_id": coordinates.attempt_id,
            "target_sha": coordinates.target_sha,
            "image_digest": coordinates.image_digest,
            "owner_digest": coordinates.owner_digest,
            "lease_digest": coordinates.lease_digest,
            "controller_id": coordinates.controller_id,
            "recipient_fingerprint": coordinates.recipient_fingerprint,
            "nonce_sha256": digest,
        }
    )
    if len(payload) > _MAX_NONCE_BYTES:
        raise SameLeasePairingError("telegram_nonce_unverified")
    folder = _open_volume(directory)
    try:
        _require_lease(lease, coordinates)
        try:
            fd = os.open(
                marker,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=folder,
            )
        except FileExistsError:
            return False
        except OSError:
            raise SameLeasePairingError("telegram_nonce_unverified") from None
        try:
            with os.fdopen(fd, "wb") as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.fsync(folder)
            _require_lease(lease, coordinates)
        except (OSError, ValueError, SameLeasePairingError):
            # Never unlink: a partial O_EXCL file must permanently block replay.
            raise SameLeasePairingError("telegram_nonce_uncertain") from None
        return True
    finally:
        os.close(folder)


def execute_staged_pairing_under_lease(
    *,
    stage_directory: Path,
    custody_directory: Path,
    coordinates: CutoverCoordinates,
    owner_receipt: OwnerPairingReceipt,
    owner_receipt_key: bytes,
    recipient: bootstrap.RecipientReceipt,
    private_key: bytes,
    lease: BocaJobLease,
    trusted_clock: Callable[[], int],
    inspect_host: Callable[[str, CutoverCoordinates], HostRecheckReceipt],
    api_fetch: TelegramApiFetch,
) -> ProtectedPairingReceipt:
    """Bridge ciphertext+held lease to existing V2 custody, leaving sender OFF.

    No production caller is wired. Only the single protected Cutover A backend
    may supply the real owner/passkey proof, lease, Docker reinspection and
    dedicated Telegram egress; fakes remain strictly offline test fixtures.
    """
    _require_lease(lease, coordinates)
    try:
        now = trusted_clock()
    except Exception:
        raise SameLeasePairingError("telegram_clock_unverified") from None
    stage = read_encrypted_telegram_stage(
        stage_directory, coordinates=coordinates, lease=lease, trusted_now=now
    )
    if (
        type(owner_receipt) is not OwnerPairingReceipt
        or owner_receipt.coordinates != coordinates
        or not hmac.compare_digest(owner_receipt.envelope_sha256, stage.envelope_sha256)
    ):
        raise SameLeasePairingError("telegram_owner_stage_binding_unverified")

    def assert_stage_and_lease() -> None:
        _require_lease(lease, coordinates)
        latest = read_encrypted_telegram_stage(
            stage_directory, coordinates=coordinates, lease=lease, trusted_now=trusted_clock()
        )
        if latest != stage:
            raise SameLeasePairingError("telegram_stage_changed")

    def guarded_recheck(phase: str, checked: CutoverCoordinates) -> HostRecheckReceipt:
        assert_stage_and_lease()
        observed = inspect_host(phase, checked)
        assert_stage_and_lease()
        return observed

    def guarded_consume(nonce: str, checked: CutoverCoordinates) -> bool:
        assert_stage_and_lease()
        return consume_telegram_owner_nonce(stage_directory, nonce, checked, lease=lease)

    return execute_protected_pairing(
        coordinates=coordinates,
        owner_receipt=owner_receipt,
        owner_receipt_key=owner_receipt_key,
        sealed_v2_envelope=stage.envelope,
        recipient=recipient,
        private_key=private_key,
        directory=custody_directory,
        trusted_clock=trusted_clock,
        recheck_host=guarded_recheck,
        consume_owner_nonce=guarded_consume,
        api_fetch=api_fetch,
    )
