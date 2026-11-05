"""Synthetic host Telegram four-GET session; no real provider or Docker."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from boca_socios import telegram_host_readonly_session as host
from boca_socios.telegram_pairing_cutover import CutoverCoordinates
from test_telegram_owner_lease_e2e import _inputs
from test_telegram_pairing_cutover import _host as claimed_host
from test_telegram_pairing_resolver import NOW, _FakeBotApi
from test_telegram_pairing_ui import TOKEN


def _prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    private, recipient, code, pins, coords, lease, reader, data, _grant = _inputs(
        tmp_path, monkeypatch
    )
    return private, recipient, code, pins, coords, lease, reader, data


def _run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    webhook: str = "",
    reject_phase: str = "",
    failed_exit: bool = False,
    changed_postflight: bool = False,
):
    private, recipient, code, pins, coords, lease, reader, data = _prepare(tmp_path, monkeypatch)
    api = _FakeBotApi(code, webhook={"url": webhook})
    events: list[str] = []
    phases: list[str] = []

    @contextmanager
    def session():
        events.append("OPEN")
        try:
            yield api
        finally:
            events.append("CLOSE")
            if changed_postflight:
                fields = reader.fields[("container", pins.controller_id, "Config.Env")]
                assert isinstance(fields, list)
                fields[-1] = "BOCA_OWNER_SUBJECT=other"
            if failed_exit:
                raise RuntimeError("leaked synthetic token " + TOKEN)

    def recheck(phase: str, coordinates: CutoverCoordinates):
        phases.append(phase)
        return claimed_host(
            phase,
            coordinates,
            owner_authenticated=phase != reject_phase,
            observed_at=NOW,
        )

    def execute():
        return host.four_gets_under_existing_lease(
            pins,
            coords,
            lease=lease,
            recipient=recipient,
            private_key=private,
            session_factory=session,
            recheck_host=recheck,
            trusted_clock=lambda: NOW,
            io=reader,
        )

    return execute, api, events, phases, data, reader, coords


def test_exact_four_gets_one_ephemeral_context_no_sender_or_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    execute, api, events, phases, data, reader, coords = _run(tmp_path, monkeypatch)
    proof = execute()
    assert proof.state == "READ_ONLY_FOUR_GETS_COMPLETE_NOT_AUTHORIZED"
    assert proof.sender_state == "OFF"
    assert proof.custody_state == "UNCOMMITTED"
    assert proof.human_receipt == "UNVERIFIED"
    assert proof.host_go is False and proof.methods == 4
    assert proof.source_sha == coords.target_sha
    assert [method for method, _chat in api.calls] == [
        "getMe",
        "getWebhookInfo",
        "getUpdates",
        "getChat",
    ]
    assert phases == [
        "BEFORE_API",
        "BEFORE_getMe",
        "BEFORE_getWebhookInfo",
        "BEFORE_getUpdates",
        "BEFORE_getChat",
        "AFTER_READS",
    ]
    assert events == ["OPEN", "CLOSE"]
    assert not list(data.glob("boca_telegram_owner_nonce_v2_*.json"))
    assert TOKEN not in repr(proof) and reader.effects == []


@pytest.mark.parametrize(
    "case",
    ["webhook", "host_drift", "transport_close", "postflight_drift"],
)
def test_failures_close_helper_and_never_authorize_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    execute, api, events, _phases, data, reader, _coords = _run(
        tmp_path,
        monkeypatch,
        webhook="https://synthetic.invalid/hook" if case == "webhook" else "",
        reject_phase="BEFORE_getWebhookInfo" if case == "host_drift" else "",
        failed_exit=case == "transport_close",
        changed_postflight=case == "postflight_drift",
    )
    with pytest.raises(host.TelegramReadOnlyNoGo) as failure:
        execute()
    assert TOKEN not in str(failure.value)
    assert events == ["OPEN", "CLOSE"]
    assert not list(data.glob("boca_telegram_owner_nonce_v2_*.json"))
    assert reader.effects == []
    if case == "host_drift":
        assert [method for method, _chat in api.calls] == ["getMe"]
    if case == "webhook":
        assert [method for method, _chat in api.calls] == [
            "getMe",
            "getWebhookInfo",
        ]
    if case == "postflight_drift":
        assert str(failure.value) == "telegram_readonly_postflight_unverified"


@pytest.mark.parametrize("args", [("four-gets",), ("sendMessage",), ()])
def test_cli_fails_closed_until_protected_caller_is_reviewed(
    capsys: pytest.CaptureFixture[str], args: tuple[str, ...]
) -> None:
    assert host.main(args) == 1
    output = capsys.readouterr().out
    assert output.startswith("BOCA_TELEGRAM_HOST_READS state=NO_GO reason=")
    assert output.endswith("sender=OFF\n")
