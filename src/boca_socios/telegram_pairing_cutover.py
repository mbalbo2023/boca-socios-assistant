"""Protected-cutover *adapter* for private Telegram pairing; not a host gate.

Only the existing Boca first-deploy transaction may supply the authoritative
same-lease host recheck, authenticated-owner receipt key and durable nonce
consumer. This module creates no host lease, container, route or workflow.
Its CLI deliberately cannot authorize any phase or contact Telegram.

The injectable function has real Bot API reads and local custody effects IF
the trusted cutover owner eventually wires it. Until then it is unreachable
from the canonical workflow. Source-only tests use invented credentials and
fake IO; they do not exercise the physical host or Telegram provider.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios.telegram_pairing_install import (
    PairingCustodyError,
    install_v2_plan,
    verify_v2_custody,
)
from boca_socios.telegram_pairing_resolver import (
    PairingResolutionError,
    TelegramApiFetch,
    plan_private_telegram_pairing,
)

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ATTEMPT = re.compile(r"[1-9][0-9]{0,19}\Z")
_IMAGE = re.compile(r"ghcr[.]io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_PURPOSE = b"boca-telegram-owner-pairing-cutover-v2:\x00"
_MAX_OWNER_WINDOW = 600
_METHOD_SEQUENCE = ("getMe", "getWebhookInfo", "getUpdates", "getChat")
# This adapter creates no disposable Docker resources, volumes or IPC entries.
# Boca-owned Telegram secrets, markers and persistent data are NEVER cleanup targets.
CLEANUP_TARGETS: tuple[str, ...] = ()


class TelegramCutoverError(ValueError):
    """Only fixed redacted failure codes; never secret-bearing exceptions."""


@dataclass(frozen=True, slots=True)
class CutoverCoordinates:
    """Nonsecret exact lease/owner/controller/source identifiers from #227."""

    attempt_id: str
    target_sha: str
    image_digest: str
    owner_digest: str
    lease_digest: str
    controller_id: str
    recipient_fingerprint: str


@dataclass(frozen=True, slots=True)
class OwnerPairingReceipt:
    """HMAC from authenticated owner handoff; never a bearer token in logs."""

    coordinates: CutoverCoordinates
    envelope_sha256: str
    issued_at: int
    expires_at: int
    nonce: str = field(repr=False)
    auth_tag: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class HostRecheckReceipt:
    """Observations made by the canonical host adapter, not independently trusted."""

    coordinates: CutoverCoordinates
    phase: str
    observed_at: int
    rootless_uid: int
    owner_authenticated: bool
    singleton_controller_stopped: bool
    sender_off: bool
    schema_0007_ready: bool
    exclusive_lease_held: bool
    dedicated_telegram_egress: bool
    no_competing_poller: bool
    recipient_custody_verified: bool
    unrelated_services_untouched: bool


@dataclass(frozen=True, slots=True)
class ProtectedPairingReceipt:
    """Redacted postcommit state; does NOT approve a real sender or notification."""

    attempt_id: str
    source_sha: str
    recipient_fingerprint: str
    bot_id: int
    state: str = "CUSTODY_COMMITTED_NO_SEND"
    sender_state: str = "OFF"
    human_notification_receipt: str = "UNVERIFIED"


def _coordinates_valid(value: CutoverCoordinates) -> bool:
    return (
        type(value) is CutoverCoordinates
        and all(
            type(item) is str
            for item in (
                value.attempt_id,
                value.target_sha,
                value.image_digest,
                value.owner_digest,
                value.lease_digest,
                value.controller_id,
                value.recipient_fingerprint,
            )
        )
        and _ATTEMPT.fullmatch(value.attempt_id) is not None
        and _SHA.fullmatch(value.target_sha) is not None
        and _IMAGE.fullmatch(value.image_digest) is not None
        and all(
            _DIGEST.fullmatch(item) is not None
            for item in (
                value.owner_digest,
                value.lease_digest,
                value.controller_id,
                value.recipient_fingerprint,
            )
        )
    )


def _owner_payload(receipt: OwnerPairingReceipt) -> bytes:
    """Fixed HMAC domain and canonical fields; issuer lives in owner auth gate."""
    c = receipt.coordinates
    return bootstrap._canonical(
        {
            "version": 2,
            "repository": bootstrap.REPOSITORY,
            "purpose": "private-telegram-pairing-cutover",
            "attempt_id": c.attempt_id,
            "target_sha": c.target_sha,
            "image_digest": c.image_digest,
            "owner_digest": c.owner_digest,
            "lease_digest": c.lease_digest,
            "controller_id": c.controller_id,
            "recipient_fingerprint": c.recipient_fingerprint,
            "envelope_sha256": receipt.envelope_sha256,
            "issued_at": receipt.issued_at,
            "expires_at": receipt.expires_at,
            "nonce": receipt.nonce,
        }
    )


def _verify_owner_receipt(
    coordinates: CutoverCoordinates,
    owner_receipt: OwnerPairingReceipt,
    owner_receipt_key: bytes,
    v2_envelope: bytes,
    trusted_now: int,
) -> None:
    if (
        not _coordinates_valid(coordinates)
        or type(owner_receipt) is not OwnerPairingReceipt
        or owner_receipt.coordinates != coordinates
        or type(owner_receipt_key) is not bytes
        or len(owner_receipt_key) != 32
        or type(v2_envelope) is not bytes
        or not 0 < len(v2_envelope) <= bootstrap.MAX_ENVELOPE
        or type(trusted_now) is not int
        or type(owner_receipt.issued_at) is not int
        or type(owner_receipt.expires_at) is not int
        or not 0 <= owner_receipt.issued_at <= trusted_now <= owner_receipt.expires_at
        or owner_receipt.expires_at - owner_receipt.issued_at > _MAX_OWNER_WINDOW
        or type(owner_receipt.nonce) is not str
        or _DIGEST.fullmatch(owner_receipt.nonce) is None
        or type(owner_receipt.envelope_sha256) is not str
        or _DIGEST.fullmatch(owner_receipt.envelope_sha256) is None
        or not hmac.compare_digest(
            owner_receipt.envelope_sha256, hashlib.sha256(v2_envelope).hexdigest()
        )
        or type(owner_receipt.auth_tag) is not bytes
        or len(owner_receipt.auth_tag) != 32
        or not hmac.compare_digest(
            owner_receipt.auth_tag,
            hmac.new(
                owner_receipt_key, _PURPOSE + _owner_payload(owner_receipt), hashlib.sha256
            ).digest(),
        )
    ):
        raise TelegramCutoverError("owner_pairing_receipt_unverified")


def _recheck(
    recheck_host: Callable[[str, CutoverCoordinates], HostRecheckReceipt],
    phase: str,
    coordinates: CutoverCoordinates,
    trusted_clock: Callable[[], int],
) -> None:
    try:
        now = trusted_clock()
        actual = recheck_host(phase, coordinates)
        if (
            type(now) is not int
            or type(actual) is not HostRecheckReceipt
            or actual.coordinates != coordinates
            or actual.phase != phase
            or type(actual.observed_at) is not int
            or abs(now - actual.observed_at) > 30
            or type(actual.rootless_uid) is not int
            or actual.rootless_uid != bootstrap.UID
            or any(
                value is not True
                for value in (
                    actual.owner_authenticated,
                    actual.singleton_controller_stopped,
                    actual.sender_off,
                    actual.schema_0007_ready,
                    actual.exclusive_lease_held,
                    actual.dedicated_telegram_egress,
                    actual.no_competing_poller,
                    actual.recipient_custody_verified,
                    actual.unrelated_services_untouched,
                )
            )
        ):
            raise ValueError("host claims")
    except Exception:
        # Caller observations/transport may embed private host data.
        raise TelegramCutoverError("cutover_host_recheck_unverified") from None


def execute_protected_pairing(
    *,
    coordinates: CutoverCoordinates,
    owner_receipt: OwnerPairingReceipt,
    owner_receipt_key: bytes,
    sealed_v2_envelope: bytes,
    recipient: bootstrap.RecipientReceipt,
    private_key: bytes,
    directory: Path,
    trusted_clock: Callable[[], int],
    recheck_host: Callable[[str, CutoverCoordinates], HostRecheckReceipt],
    consume_owner_nonce: Callable[[str, CutoverCoordinates], bool],
    api_fetch: TelegramApiFetch,
) -> ProtectedPairingReceipt:
    """Owner HMAC → same-lease host → durable nonce → Bot API → V2 commit.

    No production caller exists. Host #227 must implement genuine, fresh,
    same-lock rechecks and an atomic durable one-use nonce ledger. A forged
    callback with truthy claims is **not** authorization; this adapter never
    accepts a standalone CLI, JSON flag or environment variable as a grant.
    """
    if (
        not _coordinates_valid(coordinates)
        or not callable(trusted_clock)
        or not callable(recheck_host)
        or not callable(consume_owner_nonce)
        or not callable(api_fetch)
        or type(recipient) is not bootstrap.RecipientReceipt
        or recipient.state != "PREPARED"
        or type(recipient.fingerprint) is not str
        or not _DIGEST.fullmatch(recipient.fingerprint)
        or recipient.fingerprint != coordinates.recipient_fingerprint
        or type(private_key) is not bytes
        or len(private_key) != 32
        or not isinstance(directory, Path)
        or not directory.is_absolute()
    ):
        raise TelegramCutoverError("cutover_pairing_inputs_unverified")
    try:
        now = trusted_clock()
    except Exception:
        raise TelegramCutoverError("cutover_clock_unverified") from None
    _verify_owner_receipt(coordinates, owner_receipt, owner_receipt_key, sealed_v2_envelope, now)
    _recheck(recheck_host, "BEFORE_API", coordinates, trusted_clock)
    try:
        consumed = consume_owner_nonce(owner_receipt.nonce, coordinates)
    except Exception:
        raise TelegramCutoverError("owner_pairing_nonce_unverified") from None
    if consumed is not True:
        raise TelegramCutoverError("owner_pairing_nonce_unverified")

    next_method = 0

    def checked_fetch(token: str, method: str, chat_id: int | None) -> bytes:
        nonlocal next_method
        if next_method >= len(_METHOD_SEQUENCE) or method != _METHOD_SEQUENCE[next_method]:
            raise TelegramCutoverError("telegram_read_sequence_unverified")
        _verify_owner_receipt(
            coordinates,
            owner_receipt,
            owner_receipt_key,
            sealed_v2_envelope,
            trusted_clock(),
        )
        _recheck(recheck_host, f"BEFORE_{method}", coordinates, trusted_clock)
        next_method += 1
        return api_fetch(token, method, chat_id)

    try:
        plan = plan_private_telegram_pairing(
            sealed_v2_envelope,
            private_key,
            recipient,
            coordinates.target_sha,
            not_before=owner_receipt.issued_at,
            now=trusted_clock(),
            api_fetch=checked_fetch,
        )
    except (PairingResolutionError, TelegramCutoverError):
        raise TelegramCutoverError("telegram_private_discovery_unverified") from None
    except Exception:
        raise TelegramCutoverError("telegram_private_discovery_unverified") from None
    if next_method != len(_METHOD_SEQUENCE):
        raise TelegramCutoverError("telegram_read_sequence_unverified")
    _verify_owner_receipt(
        coordinates,
        owner_receipt,
        owner_receipt_key,
        sealed_v2_envelope,
        trusted_clock(),
    )
    _recheck(recheck_host, "BEFORE_COMMIT", coordinates, trusted_clock)
    try:
        commit = install_v2_plan(
            directory,
            plan,
            expected_source_sha=coordinates.target_sha,
            now=trusted_clock(),
        )
        verified = verify_v2_custody(directory, expected_source_sha=coordinates.target_sha)
    except PairingCustodyError:
        raise TelegramCutoverError("telegram_custody_unverified") from None
    except Exception:
        raise TelegramCutoverError("telegram_custody_unverified") from None
    _recheck(recheck_host, "AFTER_COMMIT", coordinates, trusted_clock)
    if (
        commit != verified
        or commit.state != "CUSTODY_COMMITTED_NO_SEND"
        or commit.source_sha != coordinates.target_sha
        or commit.recipient_fingerprint != coordinates.recipient_fingerprint
        or type(commit.bot_id) is not int
        or not 0 < commit.bot_id < 2**52
    ):
        raise TelegramCutoverError("telegram_custody_unverified")
    return ProtectedPairingReceipt(
        attempt_id=coordinates.attempt_id,
        source_sha=commit.source_sha,
        recipient_fingerprint=commit.recipient_fingerprint,
        bot_id=commit.bot_id,
    )


def main(argv: tuple[str, ...] | None = None) -> int:
    """CLI contract is inert until the sole protected cutover explicitly wires it."""
    args = tuple(sys.argv[1:]) if argv is None else argv
    if args not in (("preflight",), ("commit",), ("verify",)):
        print("BOCA_TELEGRAM_V2 state=NO_GO reason=INVALID_PHASE", file=sys.stderr)
        return 2
    print("BOCA_TELEGRAM_V2 state=NO_GO host_authorization=NOT_CONNECTED sender=OFF")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
