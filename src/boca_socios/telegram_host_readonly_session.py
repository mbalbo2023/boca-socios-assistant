"""Telegram four-GET owner-stage read session under one existing Boca lease.

CODE ONLY: this is NOT a host CLI, Docker helper, Telegram sender or GO gate.
A future protected Boca job must provide one authentic ephemeral session
factory, actual rootless phase rechecks and an independent Environment GO.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Literal

from boca_socios import telegram_pairing_cutover as cutover
from boca_socios import telegram_pairing_resolver as resolver
from boca_socios.host_boca_cleanup import BocaJobLease
from boca_socios.host_telegram_production_reader import TelegramProductionDockerIO
from boca_socios.host_lifecycle_rootless_adapter import (
    LifecycleDockerIO,
)
from boca_socios.host_telegram_owner_stage import (
    _verified_host_volumes,
    observe_owner_stage_under_same_lease,
)
from boca_socios.host_telegram_postcutover import TelegramHostPins
from boca_socios.telegram_bootstrap import RecipientReceipt
from boca_socios.telegram_pairing_cutover import CutoverCoordinates, HostRecheckReceipt
from boca_socios.telegram_same_lease_stage import read_encrypted_telegram_stage

_METHODS = ("getMe", "getWebhookInfo", "getUpdates", "getChat")
SessionFactory = Callable[[], AbstractContextManager[resolver.TelegramApiFetch]]
HostRecheck = Callable[[str, CutoverCoordinates], HostRecheckReceipt]


class TelegramReadOnlyNoGo(ValueError):
    """Fixed redacted failures; never provider responses, token or chat ID."""


@dataclass(frozen=True, slots=True)
class TelegramFourGetProof:
    """A completed READ-only phase, NOT custody, notification or sender approval."""

    attempt_id: str
    source_sha: str
    recipient_fingerprint: str
    bot_id: int
    methods: Literal[4] = 4
    state: Literal["READ_ONLY_FOUR_GETS_COMPLETE_NOT_AUTHORIZED"] = (
        "READ_ONLY_FOUR_GETS_COMPLETE_NOT_AUTHORIZED"
    )
    sender_state: Literal["OFF"] = "OFF"
    custody_state: Literal["UNCOMMITTED"] = "UNCOMMITTED"
    human_receipt: Literal["UNVERIFIED"] = "UNVERIFIED"
    host_go: Literal[False] = False


def four_gets_under_existing_lease(
    pins: TelegramHostPins,
    coordinates: CutoverCoordinates,
    *,
    lease: BocaJobLease,
    recipient: RecipientReceipt,
    private_key: bytes,
    session_factory: SessionFactory,
    recheck_host: HostRecheck,
    trusted_clock: Callable[[], int],
    io: LifecycleDockerIO | None = None,
) -> TelegramFourGetProof:
    """Read signed Chrome stage, run four GETs within ONE ephemeral context.

    Owner-stage/topology is verified with egress absent both before opening
    and after closing the injected helper. While the helper is active, each
    GET requires one fresh host recheck and immutable stage under held lease.
    The context manager must stop/clean its own exact Boca helper on exit.
    No nonce, custody or sender state is written by this coordinator.
    """
    if (
        not callable(session_factory)
        or not callable(recheck_host)
        or not callable(trusted_clock)
        or type(private_key) is not bytes
        or len(private_key) != 32
    ):
        raise TelegramReadOnlyNoGo("telegram_readonly_inputs_unverified")
    reader = TelegramProductionDockerIO() if io is None else io
    try:
        proof = observe_owner_stage_under_same_lease(pins, coordinates, lease=lease, io=reader)
        data, _owner = _verified_host_volumes(reader)
        stage = read_encrypted_telegram_stage(
            data, coordinates=coordinates, lease=lease, trusted_now=trusted_clock()
        )
        if (
            proof.staged_at != stage.staged_at
            or proof.envelope_sha256 != stage.envelope_sha256
            or proof.recipient_fingerprint != recipient.fingerprint
            or coordinates.recipient_fingerprint != recipient.fingerprint
        ):
            raise ValueError("owner stage mismatch")
    except Exception:
        raise TelegramReadOnlyNoGo("telegram_readonly_owner_stage_unverified") from None

    methods_seen: list[str] = []
    plan: resolver.PairingInstallPlan | None = None
    failed = False
    try:
        with session_factory() as api_fetch:
            if not callable(api_fetch):
                raise ValueError("injected transport invalid")
            cutover._recheck(recheck_host, "BEFORE_API", coordinates, trusted_clock)

            def guarded_fetch(token: str, method: str, chat_id: int | None) -> bytes:
                if (
                    len(methods_seen) >= 4
                    or method != _METHODS[len(methods_seen)]
                    or (method == "getChat") != (type(chat_id) is int)
                ):
                    raise TelegramReadOnlyNoGo("telegram_readonly_sequence_unverified")
                current = read_encrypted_telegram_stage(
                    data, coordinates=coordinates, lease=lease, trusted_now=trusted_clock()
                )
                if current != stage:
                    raise TelegramReadOnlyNoGo("telegram_readonly_stage_changed")
                cutover._recheck(recheck_host, f"BEFORE_{method}", coordinates, trusted_clock)
                methods_seen.append(method)
                return api_fetch(token, method, chat_id)

            plan = resolver.plan_private_telegram_pairing(
                stage.envelope,
                private_key,
                recipient,
                coordinates.target_sha,
                not_before=stage.staged_at,
                now=trusted_clock(),
                api_fetch=guarded_fetch,
            )
            if tuple(methods_seen) != _METHODS:
                raise TelegramReadOnlyNoGo("telegram_readonly_sequence_unverified")
            cutover._recheck(recheck_host, "AFTER_READS", coordinates, trusted_clock)
    except Exception:
        # Includes any transport error, context manager error or cryptographic
        # rejection. None of those raw errors are safe to emit to GitHub logs.
        failed = True
    try:
        # The session must be CLOSED before this no-helper topology observer.
        after = observe_owner_stage_under_same_lease(pins, coordinates, lease=lease, io=reader)
        latest = read_encrypted_telegram_stage(
            data, coordinates=coordinates, lease=lease, trusted_now=trusted_clock()
        )
        if latest != stage or after.envelope_sha256 != proof.envelope_sha256:
            raise ValueError("stage changed after egress")
    except Exception:
        raise TelegramReadOnlyNoGo("telegram_readonly_postflight_unverified") from None

    if failed or plan is None:
        raise TelegramReadOnlyNoGo("telegram_readonly_four_gets_no_go")
    return TelegramFourGetProof(
        attempt_id=coordinates.attempt_id,
        source_sha=coordinates.target_sha,
        recipient_fingerprint=coordinates.recipient_fingerprint,
        bot_id=plan.receipt.bot_id,
    )


def main(argv: tuple[str, ...] | None = None) -> int:
    """Inert CLI until a separately reviewed protected host factory is wired."""
    args = tuple(sys.argv[1:]) if argv is None else argv
    reason = "HOST_BINDING_NOT_CONNECTED" if args == ("four-gets",) else "INVALID_PHASE"
    print(f"BOCA_TELEGRAM_HOST_READS state=NO_GO reason={reason} sender=OFF")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
