"""The container can remain healthy while its motor stays inert."""

import json

import pytest

from boca_socios import runtime


class StopImmediately:
    def wait(self, timeout: int) -> bool:
        return True


def test_idle_startup_has_no_motor_or_site_calls(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BOCA_ENGINE_MODE", "off")
    monkeypatch.setattr(runtime.CredentialVault, "from_secret_file", lambda _path: object())
    monkeypatch.setattr(runtime.Database, "migrate", lambda _self: None)
    monkeypatch.setattr(runtime, "Event", StopImmediately)
    monkeypatch.setattr(runtime.signal, "signal", lambda _sig, _handler: None)
    assert runtime.main() == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert events[0] == {
        "event": "started",
        "mode": "simulation",
        "engine": "off",
        "site_calls": 0,
    }
    assert events[1]["event"] == "stopped"
