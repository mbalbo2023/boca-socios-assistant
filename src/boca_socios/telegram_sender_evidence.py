"""Image-only read-only proof of one original Telegram acceptance identity."""

from __future__ import annotations

import hmac
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios.notify.telegram_transport import TelegramTransport
from boca_socios.panel.telegram_recipient import FILENAME, _document
from boca_socios.telegram_one_shot import (
    OneShotError,
    acceptance_notice_id,
    verified_v2_assertion,
    verify_ready,
)
from boca_socios.telegram_pairing_bootstrap import unseal_pairing
from boca_socios.telegram_pairing_cutover import CutoverCoordinates
from boca_socios.telegram_pairing_install import MARKER, MAX_MARKER, verify_v2_custody
from boca_socios.telegram_pairing_resolver import pairing_consumption_fence
from boca_socios.telegram_same_lease_stage import (
    _open_volume,
    read_stage_storage,
    stage_nonce_snapshot,
)
from boca_socios.telegram_storage_gate import verify as verify_storage


def inspect_sender_evidence(
    data: Path,
    custody: Path,
    coordinates: CutoverCoordinates,
    installation_fingerprint: str,
    verified_owner: dict[str, Any],
) -> dict[str, str]:
    """No provider transport, write, claim, retry, or private value in the result."""
    source = coordinates.target_sha
    verified = verify_v2_custody(custody, expected_source_sha=source)
    stage = read_stage_storage(data, coordinates=coordinates, trusted_now=None)
    if verified_owner != {"envelope_sha256": stage.envelope_sha256, "staged_at": stage.staged_at}:
        raise ValueError("sender_owner_stage_changed")
    parent = bootstrap._directory(custody, bootstrap.UID)
    folder = None
    try:
        folder = _open_volume(data)
        public_raw = bootstrap._read(folder, FILENAME, bootstrap.UID, maximum=1024)
        recipient, installation = _document(public_raw, source)
        if (
            installation != installation_fingerprint
            or recipient.fingerprint != coordinates.recipient_fingerprint
            or verified.recipient_fingerprint != recipient.fingerprint
        ):
            raise ValueError("sender_installation_changed")
        nonce = stage_nonce_snapshot(folder, stage, coordinates)
        original_attempt = nonce[3]
        if original_attempt is None:
            raise ValueError("sender_original_attempt_unverified")
        private = bootstrap._read(parent, bootstrap.PRIVATE_KEY, bootstrap.UID, maximum=32)
        staged_token, code = unseal_pairing(stage.envelope, private, recipient)
        token = bootstrap._read(parent, bootstrap.TOKEN_FILE, bootstrap.UID, maximum=150)
        raw = bootstrap._read(parent, MARKER, bootstrap.UID, maximum=MAX_MARKER)
        marker = json.loads(raw, object_pairs_hook=bootstrap._unique)
        if (
            not hmac.compare_digest(staged_token, token)
            or marker["pairing_observed_at"] < stage.staged_at
            or not hmac.compare_digest(
                marker["one_time_fence"],
                pairing_consumption_fence(token, source, marker["discovery_update_id"], code),
            )
        ):
            raise ValueError("sender_stage_custody_unverified")
        bot_id, chat_hmac = verified_v2_assertion(custody, expected_source_sha=source)
        transport = TelegramTransport(custody / bootstrap.TOKEN_FILE, custody / bootstrap.CHAT_FILE)
        notice = acceptance_notice_id(
            transport, source, bot_id, chat_hmac, attempt_id=original_attempt
        )
        database = data / "boca.sqlite3"
        verify_storage(database)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=3)) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA trusted_schema=OFF")
            counts = tuple(
                conn.execute(query, (str(notice),)).fetchone()[0]
                for query in (
                    "SELECT COUNT(*) FROM notification_outbox WHERE idempotency_key=?",
                    "SELECT COUNT(*) FROM telegram_delivery_attempts WHERE idempotency_key=?",
                )
            )
        if counts == (0, 0):
            state = "NOT_ATTEMPTED"
        elif counts == (1, 1):
            try:
                verify_ready(
                    database, transport, source, bot_id, chat_hmac, attempt_id=original_attempt
                )
                state = "API_ACCEPTED"
            except OneShotError:
                state = "INDETERMINATE"
        else:
            state = "INDETERMINATE"
        # Bracket all derived evidence before releasing the categorical response.
        if (
            read_stage_storage(data, coordinates=coordinates, trusted_now=None) != stage
            or stage_nonce_snapshot(folder, stage, coordinates) != nonce
            or bootstrap._read(folder, FILENAME, bootstrap.UID, maximum=1024) != public_raw
            or bootstrap._read(parent, MARKER, bootstrap.UID, maximum=MAX_MARKER) != raw
            or verify_v2_custody(custody, expected_source_sha=source) != verified
        ):
            raise ValueError("sender_evidence_changed")
        return {
            "source_sha": source,
            "original_attempt_id": original_attempt,
            "acceptance_state": state,
        }
    finally:
        if folder is not None:
            os.close(folder)
        os.close(parent)
