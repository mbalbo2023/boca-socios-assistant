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
from boca_socios.telegram_owner_webauthn import (
    TelegramOwnerWitnessError,
    TelegramStageOwnerWitness,
    parse_witness_document,
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
from boca_socios.telegram_pairing_storage import PairingStorage

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
    owner_witness: TelegramStageOwnerWitness | None = field(default=None, repr=False)


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
    return _read_private_bytes(folder_fd, STAGING_FILENAME, _MAX_STAGE_BYTES)


def _read_private_bytes(
    folder_fd: int, name: str, maximum: int
) -> tuple[bytes, tuple[int, int, int, int]]:
    try:
        fd = os.open(
            name,
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
            or not 0 < before.st_size <= maximum
        ):
            raise ValueError("stage_inode")
        data = os.read(fd, maximum + 1)
        after = os.fstat(fd)
        named = os.stat(name, dir_fd=folder_fd, follow_symlinks=False)
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
    _require_lease(lease, coordinates)
    result = read_stage_storage(directory, coordinates=coordinates, trusted_now=trusted_now)
    _require_lease(lease, coordinates)
    return result


def read_stage_storage(
    directory: Path,
    *,
    coordinates: CutoverCoordinates,
    trusted_now: int | None = None,
) -> EncryptedPairingStage:
    """Read one immutable ciphertext without exposing/consuming its stage ID.

    The stage is a non-authorizing Chrome handoff. Before any provider read a
    separately HMAC-signed owner receipt and durable protected nonce are needed.
    """
    folder = _open_volume(directory)
    try:
        raw, identity = _read_staged_bytes(folder)
        try:
            document = json.loads(raw.decode("ascii"), object_pairs_hook=bootstrap._unique)
            if (
                not isinstance(document, dict)
                or set(document)
                not in (
                    {
                        "version",
                        "purpose",
                        "stage_id",
                        "staged_at",
                        "envelope_sha256",
                        "recipient_fingerprint",
                        "envelope_base64url",
                    },
                    {
                        "version",
                        "purpose",
                        "stage_id",
                        "staged_at",
                        "envelope_sha256",
                        "recipient_fingerprint",
                        "envelope_base64url",
                        "owner_witness",
                    },
                )
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
            witness = (
                parse_witness_document(document["owner_witness"])
                if "owner_witness" in document
                else None
            )
            if (
                witness is not None
                and not 0 <= document["staged_at"] - witness.challenged_at <= 120
            ):
                raise ValueError("stage_owner_age")
        except (
            ValueError,
            TypeError,
            KeyError,
            UnicodeError,
            bootstrap.BootstrapError,
            TelegramOwnerWitnessError,
        ):
            raise SameLeasePairingError("telegram_encrypted_stage_unverified") from None
        result = EncryptedPairingStage(
            stage_id=document["stage_id"],
            staged_at=document["staged_at"],
            envelope_sha256=document["envelope_sha256"],
            recipient_fingerprint=document["recipient_fingerprint"],
            file_identity=identity,
            envelope=envelope,
            owner_witness=witness,
        )
        return result
    finally:
        os.close(folder)


def consume_telegram_owner_nonce(
    directory: Path, nonce: str, coordinates: CutoverCoordinates, *, lease: BocaJobLease
) -> bool:
    _require_lease(lease, coordinates)
    result = consume_nonce_storage(directory, nonce, coordinates)
    _require_lease(lease, coordinates)
    return result


def consume_nonce_storage(
    directory: Path,
    nonce: str,
    coordinates: CutoverCoordinates,
) -> bool:
    """Durably spend HMAC nonce once, inside the *held* canonical Boca flock.

    O_EXCL is the consume linearization point. If later fsync or a provider
    phase fails, the marker is never removed: ambiguous is terminal and a
    fresh owner-signed nonce is required. It is NOT a Telegram send receipt.
    """
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
    private_key: bytes | None,
    lease: BocaJobLease,
    trusted_clock: Callable[[], int],
    inspect_host: Callable[[str, CutoverCoordinates], HostRecheckReceipt],
    api_fetch: TelegramApiFetch,
    storage: PairingStorage | None = None,
) -> ProtectedPairingReceipt:
    """Bridge ciphertext+held lease to existing V2 custody, leaving sender OFF.

    Only the protected installed backend may supply the real owner/passkey
    proof, lease, Docker reinspection and
    dedicated Telegram egress; fakes remain strictly offline test fixtures.
    """
    _require_lease(lease, coordinates)
    try:
        now = trusted_clock()
    except Exception:
        raise SameLeasePairingError("telegram_clock_unverified") from None
    stage = (read_encrypted_telegram_stage if storage is None else storage.read_stage)(
        stage_directory, coordinates=coordinates, lease=lease, trusted_now=now
    )
    if (
        type(owner_receipt) is not OwnerPairingReceipt
        or owner_receipt.coordinates != coordinates
        or not hmac.compare_digest(owner_receipt.envelope_sha256, stage.envelope_sha256)
        # The server-staged time is part of the signed owner receipt, so a
        # pre-receipt /start can still be discovered by a later Actions run.
        or type(owner_receipt.discovery_not_before) is not int
        or owner_receipt.discovery_not_before != stage.staged_at
        or stage.staged_at > owner_receipt.issued_at
        or now - stage.staged_at > 3600
    ):
        raise SameLeasePairingError("telegram_owner_stage_binding_unverified")

    def assert_stage_and_lease() -> None:
        _require_lease(lease, coordinates)
        latest = (read_encrypted_telegram_stage if storage is None else storage.read_stage)(
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
        return (consume_telegram_owner_nonce if storage is None else storage.consume_nonce)(
            stage_directory, nonce, checked, lease=lease
        )

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
        storage=storage,
    )


_HISTORY_PREFIX = "boca_telegram_stage_history_v2_"


def stage_nonce_snapshot(
    folder: int, stage: EncryptedPairingStage, coordinates: CutoverCoordinates
) -> tuple[str, bytes | None, tuple[int, int, int, int] | None, str | None]:
    """Read the existing deterministic stage nonce without consuming or changing it."""
    marker_identity = None
    original_attempt = None
    nonce = hashlib.sha256(("stage-v2:" + stage.stage_id).encode("ascii")).hexdigest()
    digest = hashlib.sha256(bytes.fromhex(nonce)).hexdigest()
    marker = _NONCE_PREFIX + digest + ".json"
    marker_raw = None
    try:
        os.stat(marker, dir_fd=folder, follow_symlinks=False)
    except FileNotFoundError:
        pass  # Explicit owner-authorized renewal also repairs a lost HTTP 202.
    else:
        marker_raw, marker_identity = _read_private_bytes(folder, marker, _MAX_NONCE_BYTES)
        value = json.loads(marker_raw, object_pairs_hook=bootstrap._unique)
        required = {
            "version": 2,
            "purpose": _NONCE_PURPOSE,
            "target_sha": coordinates.target_sha,
            "image_digest": coordinates.image_digest,
            "owner_digest": coordinates.owner_digest,
            "controller_id": coordinates.controller_id,
            "recipient_fingerprint": coordinates.recipient_fingerprint,
            "nonce_sha256": digest,
        }
        if (
            type(value) is not dict
            or set(value) != set(required) | {"attempt_id", "lease_digest"}
            or bootstrap._canonical(value) != marker_raw
            or type(value["version"]) is not int
            or any(value[k] != v for k, v in required.items())
            or not isinstance(value["attempt_id"], str)
            or re.fullmatch(r"[1-9][0-9]{0,19}", value["attempt_id"]) is None
            or not isinstance(value["lease_digest"], str)
            or _DIGEST.fullmatch(value["lease_digest"]) is None
        ):
            raise SameLeasePairingError("telegram_renew_nonce_unverified")
        original_attempt = value["attempt_id"]
    return marker, marker_raw, marker_identity, original_attempt


def archive_stage_storage(
    directory: Path, *, coordinates: CutoverCoordinates, stage: EncryptedPairingStage, now: int
) -> None:
    """Explicit protected renewal only; preserve nonce and exact old ciphertext.

    A new exclusively created directory reserves the destination. With the
    controller stopped and the same host lease held, rename into that empty
    private directory is atomic and never overwrites an existing archive.
    An interrupted reservation/rename remains evidence, never an auto-retry.
    """
    if type(now) is not int or now < stage.staged_at or stage.owner_witness is None:
        raise SameLeasePairingError("telegram_renew_stage_unverified")
    folder = _open_volume(directory)
    history = None
    try:
        original, identity = _read_staged_bytes(folder)
        if identity != stage.file_identity:
            raise SameLeasePairingError("telegram_stage_changed")
        marker, marker_raw, marker_identity, _ = stage_nonce_snapshot(folder, stage, coordinates)
        entries = [name for name in os.listdir(folder) if name.startswith(_HISTORY_PREFIX)]
        if len(entries) >= 8:
            raise SameLeasePairingError("telegram_stage_history_full")
        for name in entries:
            meta = os.stat(name, dir_fd=folder, follow_symlinks=False)
            if (
                _DIGEST.fullmatch(name.removeprefix(_HISTORY_PREFIX)) is None
                or not stat.S_ISDIR(meta.st_mode)
                or meta.st_uid != os.geteuid()
                or meta.st_gid != os.getegid()
                or stat.S_IMODE(meta.st_mode) != 0o700
            ):
                raise SameLeasePairingError("telegram_stage_history_unverified")
        target = _HISTORY_PREFIX + stage.stage_id
        os.mkdir(target, mode=0o700, dir_fd=folder)  # Existing target is always NO_GO.
        history = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=folder)
        os.fsync(folder)
        if _read_staged_bytes(folder) != (original, identity):
            raise SameLeasePairingError("telegram_stage_changed")
        if marker_raw is not None and _read_private_bytes(folder, marker, _MAX_NONCE_BYTES) != (
            marker_raw,
            marker_identity,
        ):
            raise SameLeasePairingError("telegram_nonce_changed")
        if marker_raw is None:
            try:
                os.stat(marker, dir_fd=folder, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise SameLeasePairingError("telegram_nonce_changed")
        named = os.stat(target, dir_fd=folder, follow_symlinks=False)
        opened = os.fstat(history)
        if (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino) or os.listdir(history):
            raise SameLeasePairingError("telegram_stage_history_unverified")
        os.rename(STAGING_FILENAME, STAGING_FILENAME, src_dir_fd=folder, dst_dir_fd=history)
        os.fsync(history)
        os.fsync(folder)
        archived, archived_identity = _read_staged_bytes(history)
        if archived != original or archived_identity[:2] != identity[:2]:
            raise SameLeasePairingError("telegram_stage_archive_unverified")
    except (OSError, ValueError, TypeError, KeyError):
        raise SameLeasePairingError("telegram_stage_archive_state_preserved") from None
    finally:
        if history is not None:
            os.close(history)
        os.close(folder)
