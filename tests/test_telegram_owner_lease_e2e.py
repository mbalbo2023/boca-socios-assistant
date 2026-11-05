"""Synthetic Telegram owner stage -> held lease -> four GET -> sender OFF.

All network, Docker, credentials and host claims are invented. No GO is granted.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from boca_socios import host_telegram_owner_stage as stage
from boca_socios import telegram_pairing_cutover as cutover
from boca_socios import telegram_pairing_issuer as issuer
from boca_socios.telegram_pairing_install import PairingCustodyReceipt
from boca_socios.telegram_same_lease_stage import execute_staged_pairing_under_lease
from test_host_telegram_owner_stage import _prepared as host_fixture
from test_telegram_pairing_cutover import _host as synthetic_host_claim
from test_telegram_pairing_resolver import NOW, _FakeBotApi, _prepared as sealed_pair
from test_telegram_pairing_ui import TOKEN

_SIGNING_KEY = bytes(range(32))


def _inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    private, recipient, envelope, code = sealed_pair()
    monkeypatch.setattr("test_host_telegram_owner_stage._envelope", lambda: envelope)
    monkeypatch.setattr(stage.time, "time", lambda: NOW)
    pins, coords, lease, reader, data = host_fixture(tmp_path, monkeypatch)
    assert coords.recipient_fingerprint == recipient.fingerprint
    proof = stage.observe_owner_stage_under_same_lease(
        pins, coords, lease=lease, io=reader
    )
    assert proof.state == "OWNER_STAGE_VERIFIED_EGRESS_NO_GO"
    assert proof.sender_state == "OFF" and proof.bot_api_reads == 0
    assert proof.staged_at == NOW
    grant = issuer.issue_owner_pairing_receipt(
        coords, envelope, _SIGNING_KEY, NOW, discovery_not_before=proof.staged_at
    )
    return private, recipient, code, pins, coords, lease, reader, data, grant


def _invoke(tmp_path, args, monkeypatch, *, webhook: str = "", revoke: bool = False):
    private, recipient, code, pins, coords, lease, reader, data, grant = args
    api = _FakeBotApi(code, webhook={"url": webhook})
    phases: list[str] = []
    commits: list[str] = []
    custody = PairingCustodyReceipt(coords.target_sha, recipient.fingerprint, 123456)

    def commit(*_a, **_k):
        commits.append("commit")
        return custody

    monkeypatch.setattr(cutover, "install_v2_plan", commit)
    monkeypatch.setattr(cutover, "verify_v2_custody", lambda *_a, **_k: custody)
    if revoke:
        fields = reader.fields[("container", pins.controller_id, "Config.Env")]
        assert isinstance(fields, list)
        fields[-1] = "BOCA_OWNER_SUBJECT=foreign_owner"

    def recheck(phase, coordinates):
        assert coordinates == coords
        verified = stage.observe_owner_stage_under_same_lease(
            pins, coords, lease=lease, io=reader
        )
        assert verified.staged_at == NOW
        phases.append(phase)
        return synthetic_host_claim(phase, coordinates, observed_at=NOW)

    def run():
        return execute_staged_pairing_under_lease(
            stage_directory=data,
            custody_directory=tmp_path / "synthetic-custody",
            coordinates=coords,
            owner_receipt=grant,
            owner_receipt_key=_SIGNING_KEY,
            recipient=recipient,
            private_key=private,
            lease=lease,
            trusted_clock=lambda: NOW,
            inspect_host=recheck,
            api_fetch=api,
        )

    return run, api, phases, commits, reader, data, lease


def test_stage_owner_rechecked_each_get_and_ack_off(tmp_path, monkeypatch):
    args = _inputs(tmp_path, monkeypatch)
    run, api, phases, commits, reader, data, lease = _invoke(
        tmp_path, args, monkeypatch
    )
    result = run()
    assert result.state == "CUSTODY_COMMITTED_NO_SEND"
    assert result.sender_state == "OFF"
    assert result.human_notification_receipt == "UNVERIFIED"
    assert [method for method, _ in api.calls] == [
        "getMe", "getWebhookInfo", "getUpdates", "getChat"
    ]
    assert phases == [
        "BEFORE_API", "BEFORE_getMe", "BEFORE_getWebhookInfo",
        "BEFORE_getUpdates", "BEFORE_getChat", "BEFORE_COMMIT", "AFTER_COMMIT"
    ]
    assert commits == ["commit"]
    assert len(list(data.glob("boca_telegram_owner_nonce_v2_*.json"))) == 1
    assert TOKEN not in repr(result) and reader.effects == []
    assert lease.owner_pid == os.getpid()


@pytest.mark.parametrize("case", ["webhook", "revoked_owner"])
def test_failure_is_redacted_and_never_commits(tmp_path, monkeypatch, case):
    args = _inputs(tmp_path, monkeypatch)
    run, api, phases, commits, reader, data, _lease = _invoke(
        tmp_path, args, monkeypatch,
        webhook="https://synthetic.invalid/hook" if case == "webhook" else "",
        revoke=case == "revoked_owner",
    )
    with pytest.raises(cutover.TelegramCutoverError) as failure:
        run()
    assert TOKEN not in str(failure.value) and commits == []
    if case == "webhook":
        assert [method for method, _ in api.calls] == ["getMe", "getWebhookInfo"]
        assert len(list(data.glob("boca_telegram_owner_nonce_v2_*.json"))) == 1
    else:
        assert api.calls == [] and phases == []
        assert list(data.glob("boca_telegram_owner_nonce_v2_*.json")) == []
    assert reader.effects == []
