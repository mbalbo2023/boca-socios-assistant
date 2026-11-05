"""Boca-only Telegram post-cutover owner stage proof under the existing host lease.

This is the missing PASSKEY+stage READ-ONLY piece, not a Telegram activation
runner. It never decrypts the ciphertext, consumes a nonce, makes a Bot API
request, starts a sender, or emits an activation GO/ACK. Physical GET egress
attestation and a distinct protected GO are still required (ADR0171).
"""

from __future__ import annotations

import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from boca_socios.host_boca_cleanup import BocaJobLease, verify_protected_boca_job_lease
from boca_socios.host_telegram_production_reader import TelegramProductionDockerIO
from boca_socios.host_lifecycle_rootless_adapter import (
    LifecycleDockerIO,
)
from boca_socios.host_telegram_postcutover import (
    TelegramHostPins,
    observe_telegram_host,
)
from boca_socios.panel.passkey import PasskeyOwnerAuthentication
from boca_socios.telegram_owner_webauthn import verify_stage_owner_witness
from boca_socios.telegram_pairing_cutover import CutoverCoordinates, _coordinates_valid
from boca_socios.telegram_same_lease_stage import read_encrypted_telegram_stage

_DATA = "boca-socios_boca_data"
_OWNER = "boca-socios_boca_owner"
_ORIGIN = "http://localhost:8443"
_OWNER_PERMISSIONS = frozenset(
    {"members:enroll", "members:read", "members:write", "simulation:write", "local-status:read"}
)
_SUBJECT = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


class TelegramOwnerStageNoGo(ValueError):
    """Only fixed, redacted failure codes leave this host-only preflight."""


@dataclass(frozen=True, slots=True)
class OwnerStagePreflight:
    """Genuine offline passkey evidence, explicitly NOT host egress authority."""

    attempt_id: str
    source_sha: str
    envelope_sha256: str
    recipient_fingerprint: str
    staged_at: int
    state: Literal["OWNER_STAGE_VERIFIED_EGRESS_NO_GO"] = "OWNER_STAGE_VERIFIED_EGRESS_NO_GO"
    sender_state: Literal["OFF"] = "OFF"
    authorized: Literal[False] = False
    host_effects: Literal[False] = False
    nonce_consumed: Literal[False] = False
    bot_api_reads: Literal[0] = 0
    human_receipt: Literal["UNVERIFIED"] = "UNVERIFIED"


def _verified_host_volumes(reader: LifecycleDockerIO) -> tuple[Path, Path]:
    """Bind paths to two independently inspected named volumes, not caller argv."""
    try:
        data_value = reader.field("volume", _DATA, "Mountpoint")
        owner_value = reader.field("volume", _OWNER, "Mountpoint")
        if not isinstance(data_value, str) or not isinstance(owner_value, str):
            raise ValueError("volume mountpoints")
        data = Path(data_value)
        owner = Path(owner_value)
        if (
            not data.is_absolute()
            or ".." in data.parts
            or data.name != "_data"
            or data.parent.name != _DATA
            or owner != data.parent.parent / _OWNER / "_data"
            or data.resolve(strict=True) != data
            or owner.resolve(strict=True) != owner
        ):
            raise ValueError("volume boundary")
        return data, owner
    except (OSError, ValueError, RuntimeError, TypeError):
        raise TelegramOwnerStageNoGo("boca_telegram_named_volume_mount_unverified") from None


def _read_owner_public_file(folder: Path, name: str, maximum: int) -> bytes:
    """Read the controller's PUBLIC passkey files without following symlinks."""
    parent: int | None = None
    handle: int | None = None
    try:
        parent = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        root = os.fstat(parent)
        if (
            not stat.S_ISDIR(root.st_mode)
            or root.st_uid != os.geteuid()
            or root.st_gid != os.getegid()
            or stat.S_IMODE(root.st_mode) & 0o022
        ):
            raise ValueError("owner directory")
        handle = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent
        )
        before = os.fstat(handle)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid not in (0, os.geteuid())
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) & 0o022
            or not 0 < before.st_size <= maximum
        ):
            raise ValueError("owner public file")
        content = os.read(handle, maximum + 1)
        after = os.fstat(handle)
        named = os.stat(name, dir_fd=parent, follow_symlinks=False)
        identity = (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns)
        if (
            len(content) != before.st_size
            or (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns) != identity
            or (named.st_dev, named.st_ino, named.st_mtime_ns, named.st_ctime_ns) != identity
        ):
            raise ValueError("owner file changed")
        return content
    except (OSError, ValueError, TypeError):
        raise TelegramOwnerStageNoGo("boca_telegram_owner_public_credential_unverified") from None
    finally:
        if handle is not None:
            os.close(handle)
        if parent is not None:
            os.close(parent)


def _controller_owner_subject(reader: LifecycleDockerIO, controller_id: str) -> str:
    """Obtain subject from the installed STOPPED controller, never workflow claims."""
    try:
        entries = reader.field("container", controller_id, "Config.Env")
        if not isinstance(entries, list) or not all(type(item) is str for item in entries):
            raise ValueError("environment")
        environment: dict[str, str] = {}
        for entry in entries:
            key, mark, value = entry.partition("=")
            if not mark or key in environment:
                raise ValueError("duplicate environment")
            environment[key] = value
        required = {
            "BOCA_PANEL_ORIGIN": _ORIGIN,
            "BOCA_RUNTIME_MODE": "simulation",
            "BOCA_ENGINE_MODE": "off",
            "BOCA_TELEGRAM_PAIRING_STAGE_MODE": "encrypted-only",
            "BOCA_PASSKEY_CREDENTIAL_ID_FILE": "/run/owner/credential_id",
            "BOCA_PASSKEY_PUBLIC_KEY_DER_FILE": "/run/owner/public_key.der",
        }
        if any(environment.get(key) != value for key, value in required.items()):
            raise ValueError("controller configuration")
        subject = environment.get("BOCA_OWNER_SUBJECT", "")
        if not _SUBJECT.fullmatch(subject):
            raise ValueError("owner subject")
        return subject
    except (OSError, ValueError, TypeError):
        raise TelegramOwnerStageNoGo("boca_telegram_owner_controller_config_unverified") from None


def observe_owner_stage_under_same_lease(
    pins: TelegramHostPins,
    coordinates: CutoverCoordinates,
    *,
    lease: BocaJobLease,
    io: LifecycleDockerIO | None = None,
) -> OwnerStagePreflight:
    """Read+verify the exact immutable stage and fresh ES256 UV owner witness.

    Production must use the real UID10001 Docker reader (io=None); CI fake
    readers only exercise data validation and NEVER confer GO. Rootless
    subuid ownership mismatches fail closed and require a separately reviewed
    egress-helper protocol, not chmod/chown or new Docker resources here.
    """
    try:
        pins.require()
        if (
            not _coordinates_valid(coordinates)
            or coordinates.attempt_id != pins.attempt_id
            or coordinates.target_sha != pins.source_sha
            or coordinates.image_digest != pins.controller_image
            or coordinates.owner_digest != pins.owner_digest
            or coordinates.controller_id != pins.controller_id
            or coordinates.recipient_fingerprint != pins.recipient_fingerprint
            or pins.cutover_attempt == pins.attempt_id
        ):
            raise TelegramOwnerStageNoGo("boca_telegram_cutover_coordinate_mismatch")
        verify_protected_boca_job_lease(lease, pins.attempt_id)
        reader = TelegramProductionDockerIO() if io is None else io
        observe_telegram_host(pins, lease=lease, io=reader)
        data, owner = _verified_host_volumes(reader)
        subject = _controller_owner_subject(reader, pins.controller_id)
        credential_id = _read_owner_public_file(owner, "credential_id", 1024)
        public_key = _read_owner_public_file(owner, "public_key.der", 4096)
        verifier = PasskeyOwnerAuthentication(
            credential_id=credential_id,
            public_key_der=public_key,
            rp_id="localhost",
            origin=_ORIGIN,
            owner_subject=subject,
            permissions=_OWNER_PERMISSIONS,
        )
        now = int(time.time())
        stage = read_encrypted_telegram_stage(
            data, coordinates=coordinates, lease=lease, trusted_now=now
        )
        if (
            stage.owner_witness is None
            or stage.staged_at > now
            or now - stage.staged_at > 3600
            or not verify_stage_owner_witness(
                stage.owner_witness,
                stage.envelope,
                verifier,
                staged_at=stage.staged_at,
            )
        ):
            raise TelegramOwnerStageNoGo("boca_telegram_fresh_owner_webauthn_unverified")
        verify_protected_boca_job_lease(lease, pins.attempt_id)
        again = read_encrypted_telegram_stage(
            data, coordinates=coordinates, lease=lease, trusted_now=int(time.time())
        )
        if again != stage:
            raise TelegramOwnerStageNoGo("boca_telegram_stage_changed_during_host_check")
        observe_telegram_host(pins, lease=lease, io=reader)
        verify_protected_boca_job_lease(lease, pins.attempt_id)
    except TelegramOwnerStageNoGo:
        raise
    except Exception:
        raise TelegramOwnerStageNoGo("boca_telegram_owner_stage_host_preflight_no_go") from None
    return OwnerStagePreflight(
        attempt_id=pins.attempt_id,
        source_sha=pins.source_sha,
        envelope_sha256=stage.envelope_sha256,
        recipient_fingerprint=stage.recipient_fingerprint,
        staged_at=stage.staged_at,
    )
