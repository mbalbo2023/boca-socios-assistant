"""Controller-only vault to bounded private worker authentication adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from time import monotonic
from typing import Protocol

from boca_socios.browser.boca_auth_protocol import BocaAuthReadiness, BocaAuthReply, BocaAuthRequest
from boca_socios.security.credential_vault import CredentialVault
from boca_socios.security.member_auth_contract import (
    BocaAuthObservation,
    BocaAuthUnavailable,
    BocaMemberAuthService,
    CredentialReadAuthority,
)
from boca_socios.storage.database import Database


class AuthWorker(Protocol):
    async def login_boca(self, request: BocaAuthRequest) -> BocaAuthReply: ...


class _PreparedTransport:
    def __init__(self, worker: AuthWorker, readiness: BocaAuthReadiness) -> None:
        self._worker = worker
        self._readiness = readiness
        self._deadline = monotonic() + readiness.remaining_seconds
        self._used = False

    def login(self, *, email: str, password: str) -> bytes:
        ready = self._readiness
        if self._used or not ready.ready or ready.nonce is None or monotonic() >= self._deadline:
            raise BocaAuthUnavailable("worker readiness expired")
        self._used = True
        reply = asyncio.run(
            self._worker.login_boca(
                BocaAuthRequest(ready.operation_id, ready.nonce, email, password)
            )
        )
        if (reply.operation_id, reply.nonce) != (ready.operation_id, ready.nonce):
            raise BocaAuthUnavailable("worker response correlation unavailable")
        return reply.provider_payload


async def authenticate_member(
    database: Database,
    vault: CredentialVault,
    worker: AuthWorker,
    member_id: str,
    readiness: BocaAuthReadiness,
    *,
    credential_read_authority: CredentialReadAuthority | None = None,
    exchange_authority: Callable[[], bool] | None = None,
) -> BocaAuthObservation:
    """Parse received bytes without publishing; the coordinator owns the final fence."""
    service = BocaMemberAuthService(
        database,
        vault,
        transport=_PreparedTransport(worker, readiness),
        monitor=None,
        credential_read_authority=credential_read_authority,
        exchange_authority=exchange_authority,
    )
    return await asyncio.to_thread(service.authenticate, member_id)
