"""Publish the last verified installed observation, never an inferred heartbeat."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from boca_socios import telegram_bootstrap as bootstrap

if TYPE_CHECKING:
    from boca_socios.host_telegram_installed_context import InstalledTelegramContext
    from boca_socios.host_telegram_maintenance import InstalledMaintenance


def publish_installed_status(
    context: InstalledTelegramContext,
    maintenance: InstalledMaintenance,
    *,
    expected_custody: str | None = None,
) -> None:
    if expected_custody not in {None, "ABSENT", "VERIFIED"}:
        raise ValueError("telegram_status_expectation_unverified")
    context.healthy()
    item = context.installation
    sender_id = item.pair.sender_id or None
    request: dict[str, object] = {
        "source_sha": item.source_sha,
        "observation_run_id": context.attempt_id,
        "installation_run_id": item.installation_run_id,
        "controller_id": item.controller_id,
        "worker_id": item.worker_id,
        "sender_id": sender_id,
        "sender": "RUNNING" if item.pair.sender_running else "STOPPED" if sender_id else "ABSENT",
        "observed_at": datetime.now(UTC).isoformat(),
    }
    present = "boca-socios_boca_telegram" in dict(context.volumes)
    result = maintenance.call("publish-status" if present else "publish-status-absent", request)
    if (
        set(result) != {"state", "sha256", "configured", "paired"}
        or result["state"] != "STATUS_PUBLISHED"
        or (result["configured"], result["paired"])
        not in {("ABSENT", "NOT_PAIRED"), ("VERIFIED", "VERIFIED"), ("UNVERIFIED", "UNVERIFIED")}
    ):
        raise ValueError("telegram_status_publication_unverified")
    raw = (
        bootstrap._canonical(
            {
                "version": 1,
                **request,
                "configured": result["configured"],
                "paired": result["paired"],
                "human_receipt": "UNVERIFIED",
            }
        )
        + b"\n"
    )
    if result["sha256"] != hashlib.sha256(raw).hexdigest():
        raise ValueError("telegram_status_publication_unverified")
    context.healthy()
    expected = (
        ("VERIFIED", "VERIFIED")
        if item.pair.sender_running or expected_custody == "VERIFIED"
        else ("ABSENT", "NOT_PAIRED")
        if expected_custody == "ABSENT"
        else None
    )
    if expected is not None and (result["configured"], result["paired"]) != expected:
        # Keep the truthful downgraded observation on disk, but do not turn it
        # into PREPARED/READY. Restoration-only recovery may report uncertainty.
        raise ValueError("telegram_status_custody_changed")
