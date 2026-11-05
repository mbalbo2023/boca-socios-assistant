"""One fake Telegram notice after real temporary V2 custody, sender still OFF.

Only temporary Boca fixtures and an invented BotFather-style token are used.
No provider request, host action, worker, message or deployment is made.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios import telegram_one_shot as one_shot
from boca_socios import telegram_pairing_cutover as cutover
from boca_socios import telegram_pairing_install as custody
from boca_socios import telegram_storage_gate as storage_gate
from boca_socios.notify.outbox import NoticeKind
from boca_socios.notify.telegram_transport import TelegramAck, TelegramNotice, TelegramTransport
from test_telegram_one_shot import _database
from test_telegram_pairing_cutover import KEY, _host
from test_telegram_pairing_resolver import CHAT, NOT_BEFORE, NOW, SOURCE, _FakeBotApi
from test_telegram_pairing_ui import TOKEN, _run


class FakeAcceptanceSender:
    """Deliberately not a TelegramTransport; no possible external network."""

    def __init__(self, *, ambiguous: bool) -> None:
        self.ambiguous = ambiguous
        self.calls: list[TelegramNotice] = []

    def preflight(self) -> None:
        return None

    async def send(self, notice: TelegramNotice) -> TelegramAck:
        self.calls.append(notice)
        if self.ambiguous:
            raise TimeoutError("synthetic transport ambiguity, no provider contact")
        return TelegramAck(42)


@pytest.mark.parametrize("ambiguous", [False, True])
def test_owner_bound_v2_then_one_synthetic_notice_keeps_sender_off_without_human_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    ambiguous: bool,
) -> None:
    # A local pretend owner recipient and encrypted Chrome V2 handoff.
    directory = tmp_path / "telegram"
    directory.mkdir(mode=0o700)
    prepared = bootstrap.prepare(directory, uid=os.geteuid())
    public_fragment = "#recipient=" + bootstrap._b64(bootstrap._canonical(asdict(prepared)))
    owner = _run(public_fragment)
    v2 = bootstrap._unb64(owner["output"], maximum=bootstrap.MAX_ENVELOPE)
    private = (directory / bootstrap.PRIVATE_KEY).read_bytes()
    assert TOKEN.encode() not in v2

    coordinates = cutover.CutoverCoordinates(
        attempt_id="41942000001",
        target_sha=SOURCE,
        image_digest="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64,
        owner_digest="b" * 64,
        lease_digest="c" * 64,
        controller_id="d" * 64,
        recipient_fingerprint=prepared.fingerprint,
    )
    owner_receipt = cutover.OwnerPairingReceipt(
        coordinates=coordinates,
        envelope_sha256=hashlib.sha256(v2).hexdigest(),
        issued_at=NOT_BEFORE,
        expires_at=NOT_BEFORE + 600,
        nonce="e" * 64,
        auth_tag=b"",
    )
    owner_receipt = replace(
        owner_receipt,
        auth_tag=hmac.new(
            KEY,
            cutover._PURPOSE + cutover._owner_payload(owner_receipt),
            hashlib.sha256,
        ).digest(),
    )

    api = _FakeBotApi(owner["command"][7:])
    observed_phases: list[str] = []
    nonce_ledger: set[str] = set()

    def fake_host(phase: str, coordinates_: cutover.CutoverCoordinates):
        observed_phases.append(phase)
        return _host(phase, coordinates_, observed_at=NOW)

    def consume_nonce(nonce: str, coordinates_: cutover.CutoverCoordinates) -> bool:
        assert coordinates_ == coordinates
        if nonce in nonce_ledger:
            return False
        nonce_ledger.add(nonce)
        return True

    # Only TEST adapters override the UID; production still requires UID10001.
    real_install = custody.install_v2_plan
    real_verify = custody.verify_v2_custody

    def install_local(directory_: Path, plan, *, expected_source_sha: str, now: int):
        return real_install(
            directory_,
            plan,
            expected_source_sha=expected_source_sha,
            now=now,
            uid=os.geteuid(),
        )

    def verify_local(directory_: Path, *, expected_source_sha: str):
        return real_verify(directory_, expected_source_sha=expected_source_sha, uid=os.geteuid())

    monkeypatch.setattr(cutover, "install_v2_plan", install_local)
    monkeypatch.setattr(cutover, "verify_v2_custody", verify_local)
    custody_receipt = cutover.execute_protected_pairing(
        coordinates=coordinates,
        owner_receipt=owner_receipt,
        owner_receipt_key=KEY,
        sealed_v2_envelope=v2,
        recipient=prepared,
        private_key=private,
        directory=directory,
        trusted_clock=lambda: NOW,
        recheck_host=fake_host,
        consume_owner_nonce=consume_nonce,
        api_fetch=api,
    )
    assert custody_receipt.state == "CUSTODY_COMMITTED_NO_SEND"
    assert custody_receipt.sender_state == "OFF"
    assert custody_receipt.human_notification_receipt == "UNVERIFIED"
    assert real_verify(directory, expected_source_sha=SOURCE, uid=os.geteuid())
    assert [method for method, _chat in api.calls] == [
        "getMe",
        "getWebhookInfo",
        "getUpdates",
        "getChat",
    ]
    assert observed_phases[0] == "BEFORE_API" and observed_phases[-1] == "AFTER_COMMIT"

    # This is a synthetic provider-ACK fixture, not a real user notification.
    database = tmp_path / "boca.sqlite3"
    _database(database)
    monkeypatch.setattr(
        storage_gate,
        "_identity",
        lambda path: (path.stat().st_dev, path.stat().st_ino),
    )
    storage_gate.verify(database)
    transport = TelegramTransport(directory / bootstrap.TOKEN_FILE, directory / bootstrap.CHAT_FILE)
    chat_pin = hmac.new(TOKEN.encode(), str(CHAT).encode(), hashlib.sha256).hexdigest()
    notice_id = one_shot.acceptance_notice_id(transport, SOURCE, custody_receipt.bot_id, chat_pin)
    sender = FakeAcceptanceSender(ambiguous=ambiguous)
    if ambiguous:
        with pytest.raises(one_shot.OneShotError):
            asyncio.run(
                one_shot.deliver_once(
                    database, sender, SOURCE, notice_id=notice_id, clock=lambda: float(NOW)
                )
            )
        with pytest.raises(one_shot.OneShotError):
            one_shot.verify_ready(database, transport, SOURCE, custody_receipt.bot_id, chat_pin)
    else:
        assert (
            asyncio.run(
                one_shot.deliver_once(
                    database, sender, SOURCE, notice_id=notice_id, clock=lambda: float(NOW)
                )
            )
            == "API_ACCEPTED"
        )
        one_shot.verify_ready(database, transport, SOURCE, custody_receipt.bot_id, chat_pin)
    assert len(sender.calls) == 1 and sender.calls[0].kind is NoticeKind.HEARTBEAT
    # Both accepted and ambiguous are terminal: never send an automatic retry.
    with pytest.raises(one_shot.OneShotError):
        asyncio.run(
            one_shot.deliver_once(
                database, sender, SOURCE, notice_id=notice_id, clock=lambda: float(NOW + 1)
            )
        )
    assert len(sender.calls) == 1

    # V2 one-use owner receipt cannot trigger even a second provider READ.
    prior_reads = list(api.calls)
    with pytest.raises(cutover.TelegramCutoverError, match="owner_pairing_nonce_unverified"):
        cutover.execute_protected_pairing(
            coordinates=coordinates,
            owner_receipt=owner_receipt,
            owner_receipt_key=KEY,
            sealed_v2_envelope=v2,
            recipient=prepared,
            private_key=private,
            directory=directory,
            trusted_clock=lambda: NOW,
            recheck_host=fake_host,
            consume_owner_nonce=consume_nonce,
            api_fetch=api,
        )
    assert api.calls == prior_reads
    assert custody_receipt.sender_state == "OFF"
    assert custody_receipt.human_notification_receipt == "UNVERIFIED"
    assert TOKEN not in repr(custody_receipt) + capsys.readouterr().out
    assert cutover.CLEANUP_TARGETS == ()
