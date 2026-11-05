"""Offline wiring proof: exact Boca helper-phase attestation before four GETs."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from boca_socios import host_telegram_protected_readonly_caller as caller
from boca_socios.host_telegram_egress_helper import TelegramHelperPhaseProof
from boca_socios.telegram_pairing_cutover import CutoverCoordinates
from test_telegram_host_readonly_session import _prepare
from test_telegram_pairing_cutover import _host as synthetic_host_claim
from test_telegram_pairing_resolver import NOW, _FakeBotApi


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, reject: str = ""):
    private, recipient, code, pins, coords, lease, reader, data = _prepare(tmp_path, monkeypatch)
    provider = _FakeBotApi(code)
    events: list[str] = []

    class FakeSession:
        def __call__(self, token: str, method: str, chat_id: int | None) -> bytes:
            return provider(token, method, chat_id)

        def attest_phase(self, phase: str) -> TelegramHelperPhaseProof:
            events.append("HELPER:" + phase)
            return TelegramHelperPhaseProof(
                pins.attempt_id,
                pins.source_sha,
                "WRONG" if reject == "wrong_phase" else phase,
            )

    @contextmanager
    def fake_ephemeral(*_args: object, **_kwargs: object):
        events.append("OPEN")
        try:
            yield FakeSession()
        finally:
            events.append("CLOSE")

    def host_phase(phase: str, proof: TelegramHelperPhaseProof, coordinates: CutoverCoordinates):
        events.append("HOST:" + phase)
        assert proof.state == "HELPER_ATTESTED_READONLY_NO_GO"
        return synthetic_host_claim(
            phase,
            coordinates,
            owner_authenticated=phase != reject,
            observed_at=NOW,
        )

    monkeypatch.setattr(caller, "protected_ephemeral_get_session", fake_ephemeral)

    def execute():
        return caller.run_bound_telegram_four_gets(
            pins,
            coords,
            lease=lease,
            recipient=recipient,
            private_key=private,
            trusted_clock=lambda: NOW,
            phase_host_attestor=host_phase,
            reader=reader,
        )

    return execute, events, provider, data


def test_readonly_caller_uses_one_helper_and_real_phase_hook_each_get(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    execute, events, provider, data = _run(tmp_path, monkeypatch)
    proof = execute()
    assert proof.state == "READ_ONLY_FOUR_GETS_COMPLETE_NOT_AUTHORIZED"
    assert proof.sender_state == "OFF"
    assert proof.custody_state == "UNCOMMITTED"
    assert proof.human_receipt == "UNVERIFIED"
    assert proof.host_go is False
    assert [name for name, _chat in provider.calls] == [
        "getMe",
        "getWebhookInfo",
        "getUpdates",
        "getChat",
    ]
    assert events[0] == "OPEN"
    assert events[-1] == "CLOSE"
    assert len([event for event in events if event.startswith("HELPER:")]) == 6
    assert len([event for event in events if event.startswith("HOST:")]) == 6
    assert not list(data.glob("boca_telegram_owner_nonce_v2_*.json"))


@pytest.mark.parametrize("reject", ["wrong_phase", "BEFORE_getUpdates"])
def test_recheck_rejects_drift_and_closes_helper_without_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reject: str
) -> None:
    execute, events, provider, data = _run(tmp_path, monkeypatch, reject=reject)
    with pytest.raises(caller.TelegramProtectedReadOnlyNoGo):
        execute()
    assert events[-1] == "CLOSE"
    assert len(provider.calls) < 4
    assert not list(data.glob("boca_telegram_owner_nonce_v2_*.json"))


def test_missing_phase_host_attestor_fails_before_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private, recipient, _code, pins, coords, lease, reader, _data = _prepare(tmp_path, monkeypatch)
    with pytest.raises(caller.TelegramProtectedReadOnlyNoGo):
        caller.run_bound_telegram_four_gets(
            pins,
            coords,
            lease=lease,
            recipient=recipient,
            private_key=private,
            trusted_clock=lambda: NOW,
            phase_host_attestor=None,  # type: ignore[arg-type]
            reader=reader,
        )
