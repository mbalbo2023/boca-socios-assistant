"""Synthetic R33: one helper, one lease, one 4-GET round, durable nonce.

No real host, Docker, Bot API, owner credential or sender is exercised.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_telegram_protected_custody_caller as caller
from boca_socios import telegram_pairing_cutover as cutover
from boca_socios.host_telegram_active_helper_topology import TelegramActiveHelperTopologyWitness
from boca_socios.host_telegram_egress_helper import TelegramHelperPhaseProof
from boca_socios.telegram_pairing_install import PairingCustodyReceipt
from test_host_telegram_postcutover import _pins
from test_telegram_pairing_resolver import NOW, SOURCE, _FakeBotApi
from test_telegram_same_lease_stage import KEY, _host, _setup


def _exercise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, reject: str = ""):
    lease_root = tmp_path / "lease"
    lease_root.mkdir(mode=0o700)
    data = tmp_path / "data"
    data.mkdir(mode=0o700)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(cleanup, "EXPECTED_GID", os.getegid())
    monkeypatch.setattr(cleanup, "LEASE_DIR", lease_root)
    private, recipient, _envelope, code, coords, grant = _setup(data, monkeypatch)
    pins = replace(
        _pins(),
        attempt_id=coords.attempt_id,
        source_sha=coords.target_sha,
        controller_id=coords.controller_id,
        controller_image=coords.image_digest,
        owner_digest=coords.owner_digest,
        recipient_fingerprint=coords.recipient_fingerprint,
    )
    events: list[str] = []
    provider = _FakeBotApi(code)
    fake_custody = PairingCustodyReceipt(SOURCE, recipient.fingerprint, 123456)
    monkeypatch.setattr(cutover, "install_v2_plan", lambda *_a, **_k: fake_custody)
    monkeypatch.setattr(cutover, "verify_v2_custody", lambda *_a, **_k: fake_custody)

    class FakeSession:
        def __call__(self, token: str, method: str, chat_id: int | None) -> bytes:
            events.append("GET:" + method)
            return provider(token, method, chat_id)

        def attest_phase(self, phase: str) -> TelegramHelperPhaseProof:
            events.append("HELPER:" + phase)
            return TelegramHelperPhaseProof(
                coords.attempt_id, coords.target_sha, "DRIFT" if reject == "helper" else phase
            )

        def attest_topology(self, phase: str) -> TelegramActiveHelperTopologyWitness:
            events.append("TOPOLOGY:" + phase)
            return TelegramActiveHelperTopologyWitness(
                coords.attempt_id, coords.target_sha, "DRIFT" if reject == "topology" else phase
            )

    @contextmanager
    def fake_ephemeral(*_args: object, **_kwargs: object):
        events.append("OPEN")
        try:
            yield FakeSession()
        finally:
            events.append("CLOSE")

    def host_phase(phase: str, proof: TelegramHelperPhaseProof, checked):
        events.append("HOST:" + phase)
        assert checked == coords
        assert proof.state == "HELPER_ATTESTED_READONLY_NO_GO"
        return replace(_host(phase, checked), owner_authenticated=phase != reject)

    monkeypatch.setattr(caller, "protected_ephemeral_get_session", fake_ephemeral)

    def invoke(*, lease, owner_receipt=None, stage_directory=None):
        return caller.run_bound_telegram_staged_custody(
            pins,
            coords,
            lease=lease,
            stage_directory=data if stage_directory is None else stage_directory,
            custody_directory=tmp_path / "custody",
            owner_receipt=grant if owner_receipt is None else owner_receipt,
            owner_receipt_key=KEY,
            recipient=recipient,
            private_key=private,
            trusted_clock=lambda: NOW,
            phase_host_attestor=host_phase,
        )

    return invoke, events, provider, data, lease_root, grant


def test_one_helper_one_round_then_commits_custody_sender_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invoke, events, provider, data, _lease_root, _grant = _exercise(tmp_path, monkeypatch)
    with cleanup.protected_boca_job_lease("41937000001") as lease:
        result = invoke(lease=lease)
        assert result.state == "CUSTODY_COMMITTED_NO_SEND"
        assert result.sender_state == "OFF"
        assert result.human_notification_receipt == "UNVERIFIED"
        assert events.count("OPEN") == events.count("CLOSE") == 1
        assert [method for method, _chat in provider.calls] == [
            "getMe",
            "getWebhookInfo",
            "getUpdates",
            "getChat",
        ]
        phases = [event for event in events if event.startswith("HOST:")]
        assert phases == [
            "HOST:BEFORE_API",
            "HOST:BEFORE_getMe",
            "HOST:BEFORE_getWebhookInfo",
            "HOST:BEFORE_getUpdates",
            "HOST:BEFORE_getChat",
            "HOST:BEFORE_COMMIT",
            "HOST:AFTER_COMMIT",
        ]
        assert len([event for event in events if event.startswith("HELPER:")]) == 7
        assert len([event for event in events if event.startswith("TOPOLOGY:")]) == 7
        assert len(list(data.glob("boca_telegram_owner_nonce_v2_*.json"))) == 1
        with pytest.raises(caller.TelegramProtectedCustodyNoGo):
            invoke(lease=lease)
        assert len(provider.calls) == 4


@pytest.mark.parametrize("reject", ["helper", "topology", "BEFORE_getUpdates"])
def test_drift_closes_single_helper_no_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reject: str
) -> None:
    invoke, events, provider, data, _lease_root, _grant = _exercise(
        tmp_path, monkeypatch, reject=reject
    )
    with cleanup.protected_boca_job_lease("41937000001") as lease:
        with pytest.raises(caller.TelegramProtectedCustodyNoGo):
            invoke(lease=lease)
    assert events[-1] == "CLOSE"
    assert len(provider.calls) < 4
    assert not (tmp_path / "custody").exists()
    assert len(list(data.glob("boca_telegram_owner_nonce_v2_*.json"))) == (
        0 if reject in ("helper", "topology") else 1
    )


@pytest.mark.parametrize("reject", ["owner", "stage", "callback"])
def test_preflight_rejects_before_helper_creation_or_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reject: str
) -> None:
    invoke, events, provider, data, _lease_root, grant = _exercise(tmp_path, monkeypatch)
    with cleanup.protected_boca_job_lease("41937000001") as lease:
        if reject == "owner":
            with pytest.raises(caller.TelegramProtectedCustodyNoGo):
                invoke(lease=lease, owner_receipt=replace(grant, auth_tag=b"0" * 32))
        elif reject == "stage":
            with pytest.raises(caller.TelegramProtectedCustodyNoGo):
                invoke(lease=lease, stage_directory=tmp_path / "absent")
        else:
            with pytest.raises(caller.TelegramProtectedCustodyNoGo):
                caller.run_bound_telegram_staged_custody(
                    _pins(),  # wrong coordinates; callback missing is checked first
                    cutover.CutoverCoordinates("1", SOURCE, "", "", "", "", ""),
                    lease=lease,
                    stage_directory=data,
                    custody_directory=tmp_path / "custody",
                    owner_receipt=grant,
                    owner_receipt_key=KEY,
                    recipient=None,  # type: ignore[arg-type]
                    private_key=b"",
                    trusted_clock=lambda: NOW,
                    phase_host_attestor=None,  # type: ignore[arg-type]
                )
    assert events == []
    assert provider.calls == []
    assert not list(data.glob("boca_telegram_owner_nonce_v2_*.json"))
