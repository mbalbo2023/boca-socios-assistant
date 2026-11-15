"""Image-side public status using actual custody and the existing strict writer."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path

from boca_socios import telegram_bootstrap as bootstrap

_FIELDS = frozenset(
    {
        "source_sha",
        "observation_run_id",
        "installation_run_id",
        "controller_id",
        "worker_id",
        "sender_id",
        "sender",
        "observed_at",
    }
)


def _custody_state(custody: Path | None, source: str) -> tuple[str, str]:
    if custody is None:
        return "ABSENT", "NOT_PAIRED"
    from boca_socios.telegram_pairing_install import verify_v2_custody

    try:
        receipt = verify_v2_custody(custody, expected_source_sha=source)
        if receipt.source_sha != source or receipt.state != "CUSTODY_COMMITTED_NO_SEND":
            raise ValueError("custody")
        return "VERIFIED", "VERIFIED"
    except (ValueError, OSError):
        parent = bootstrap._directory(custody, bootstrap.UID)
        try:
            names = set(os.listdir(parent))
            if names == {bootstrap.PRIVATE_KEY}:
                key = bootstrap._read(parent, bootstrap.PRIVATE_KEY, bootstrap.UID, maximum=32)
                bootstrap._receipt(key, "PREPARED")
                return "ABSENT", "NOT_PAIRED"
            if not names:
                return "ABSENT", "NOT_PAIRED"
            return "UNVERIFIED", "UNVERIFIED"
        finally:
            os.close(parent)


def publish(
    directory: Path,
    custody: Path | None,
    request: dict[str, object],
) -> dict[str, object]:
    """Host supplies freshly attested public topology; image derives custody facts."""
    if type(request) is not dict or set(request) != _FIELDS:
        raise ValueError("telegram_status_request_unverified")
    source = request["source_sha"]
    if type(source) is not str or re.fullmatch(r"[a-f0-9]{40}", source) is None:
        raise ValueError("telegram_status_source_unverified")
    configured, paired = _custody_state(custody, source)
    value = {
        "version": 1,
        **request,
        "configured": configured,
        "paired": paired,
        "human_receipt": "UNVERIFIED",
    }
    raw = bootstrap._canonical(value) + b"\n"
    from boca_socios.host_boca_installed_admin import publish_telegram_observation

    digest = publish_telegram_observation(
        directory / "boca.sqlite3",
        raw,
        expected_source_sha=source,
        now=datetime.now(UTC),
    )
    return {
        "state": "STATUS_PUBLISHED",
        "sha256": digest,
        "configured": configured,
        "paired": paired,
    }
