"""Offline-only physical Telegram helper contract; no Docker or Bot API calls."""

from __future__ import annotations

import base64
import json
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_telegram_egress_helper as helper
from boca_socios.host_boca_cleanup import Container, Image, Network
from boca_socios.telegram_pairing_cutover import CutoverCoordinates
from test_host_lifecycle_rootless_adapter import CONTROLLER_REF
from test_host_telegram_postcutover import _fake, _lease, _pins

_HELPER = "a" * 64
_IMAGE = "sha256:" + "b" * 64
_NAME = "boca-socios-telegram-readonly-" + _pins().attempt_id
_EGRESS = "boca-socios_boca_telegram_egress"


def _coordinates() -> CutoverCoordinates:
    pins = _pins()
    return CutoverCoordinates(
        pins.attempt_id,
        pins.source_sha,
        CONTROLLER_REF,
        pins.owner_digest,
        "3" * 64,
        pins.controller_id,
        pins.recipient_fingerprint,
    )


def _attested_reader(tmp_path: Path):
    reader = _fake(tmp_path)
    inventory = reader.inventory_value
    item = Container(
        _HELPER,
        "/" + _NAME,
        _IMAGE,
        True,
        (
            ("com.docker.compose.project", "boca-socios"),
            (helper._LABEL_ATTEMPT, _pins().attempt_id),
            (helper._LABEL_REVISION, _pins().source_sha),
        ),
        (),
        (_EGRESS,),
    )
    networks = tuple(
        replace(network, attached_ids=(_HELPER,)) if network.name == _EGRESS else network
        for network in inventory.networks
    )
    reader.inventory_value = replace(
        inventory,
        containers=inventory.containers + (item,),
        images=inventory.images + (Image(_IMAGE, (CONTROLLER_REF,), helper._IMAGE_SOURCE),),
        networks=networks,
    )
    fields = {
        "Config.Image": CONTROLLER_REF,
        "Config.User": "10001:10001",
        "Config.Cmd": helper._CMD,
        "State.Running": True,
        "State.Restarting": False,
        "HostConfig.NetworkMode": _EGRESS,
        "HostConfig.ReadonlyRootfs": True,
        "HostConfig.Privileged": False,
        "HostConfig.PublishAllPorts": False,
        "HostConfig.PortBindings": None,
        "HostConfig.Memory": helper._MEMORY,
        "HostConfig.PidsLimit": 32,
        "HostConfig.CapDrop": ["ALL"],
        "Mounts": [],
        "NetworkSettings.Networks": {_EGRESS: {}},
        "Config.Env": [
            "BOCA_RUNTIME_MODE=simulation",
            "BOCA_ENGINE_MODE=off",
            "BOCA_TELEGRAM_READONLY_MODE=explicit",
        ],
    }
    for name, value in fields.items():
        reader.fields[("container", _HELPER, name)] = value
    return reader


def test_ephemeral_one_lease_four_private_gets_and_positive_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = _attested_reader(tmp_path)
    coords = _coordinates()
    phases: list[str] = []

    def verify(_lease, attempt: str) -> None:
        assert attempt == coords.attempt_id
        phases.append("LEASE")

    def private_exec(ident: str, payload: bytes) -> bytes:
        assert ident == _HELPER
        value = json.loads(payload)
        assert value["token"] == "test-token"
        phases.append(value["method"])
        return json.dumps(
            {
                "version": 1,
                "response_base64url": base64.urlsafe_b64encode(b'{"ok":true}').rstrip(b"=").decode(),
            }
        ).encode()

    monkeypatch.setattr(helper, "verify_protected_boca_job_lease", verify)
    monkeypatch.setattr(helper, "_run_helper", lambda *_args: phases.append("RUN") or _HELPER)
    monkeypatch.setattr(helper, "_private_exec", private_exec)
    monkeypatch.setattr(helper, "_remove_helper", lambda ident: phases.append("REMOVE:" + ident))

    with helper.protected_ephemeral_get_session(_pins(), coords, lease=_lease(), reader=reader) as get:
        for method, chat_id in (
            ("getMe", None),
            ("getWebhookInfo", None),
            ("getUpdates", None),
            ("getChat", 12345),
        ):
            assert get("test-token", method, chat_id) == b'{"ok":true}'

    assert phases.count("LEASE") == 6
    assert phases.count("RUN") == 1
    assert phases[-1] == "REMOVE:" + _HELPER
    assert [phase for phase in phases if phase in helper._METHODS] == [
        "getMe", "getWebhookInfo", "getUpdates", "getChat"
    ]


def test_active_helper_recheck_drift_closes_exact_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = _attested_reader(tmp_path)
    removed: list[str] = []
    executed: list[str] = []
    monkeypatch.setattr(helper, "verify_protected_boca_job_lease", lambda *_args: None)
    monkeypatch.setattr(helper, "_run_helper", lambda *_args: _HELPER)
    monkeypatch.setattr(helper, "_private_exec", lambda *_args: executed.append("GET"))
    monkeypatch.setattr(helper, "_remove_helper", lambda ident: removed.append(ident))

    with helper.protected_ephemeral_get_session(
        _pins(), _coordinates(), lease=_lease(), reader=reader
    ) as get:
        reader.fields[("container", _HELPER, "State.Restarting")] = True
        with pytest.raises(helper.TelegramPhysicalNoGo):
            get("test-token", "getMe", None)

    assert executed == []
    assert removed == [_HELPER]


def test_mismatched_source_refuses_to_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    touched: list[str] = []
    monkeypatch.setattr(helper, "_run_helper", lambda *_args: touched.append("RUN"))
    wrong = replace(_coordinates(), target_sha="f" * 40)
    with pytest.raises(helper.TelegramPhysicalNoGo):
        with helper.protected_ephemeral_get_session(
            _pins(), wrong, lease=_lease(), reader=_attested_reader(tmp_path)
        ):
            pytest.fail("unreviewed helper opened")
    assert touched == []


def test_helper_allowlist_never_accepts_sender_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(helper, "verify_protected_boca_job_lease", lambda *_args: None)
    monkeypatch.setattr(helper, "_run_helper", lambda *_args: _HELPER)
    monkeypatch.setattr(helper, "_remove_helper", lambda _id: None)
    monkeypatch.setattr(helper, "_private_exec", lambda *_args: pytest.fail("Docker exec"))
    with helper.protected_ephemeral_get_session(
        _pins(), _coordinates(), lease=_lease(), reader=_attested_reader(tmp_path)
    ) as get:
        with pytest.raises(helper.TelegramPhysicalNoGo):
            get("test-token", "sendMessage", 42)
