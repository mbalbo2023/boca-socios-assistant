"""The Telegram field reader fixes an offline-only fake-vs-production gap."""

from __future__ import annotations

import json

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_telegram_production_reader as reader
from boca_socios.host_lifecycle_rootless_adapter import LifecycleAdapterNoGo

CONTAINER = "a" * 64
VOLUME = "boca-socios_boca_owner"


class _Owned(reader.TelegramProductionDockerIO):
    @property
    def uid(self) -> int:
        return 10001

    @property
    def gid(self) -> int:
        return 10001


def test_dedicated_reader_supports_existing_telegram_stopped_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def docker(*args: str) -> str:
        calls.append(args)
        return json.dumps(
            ["BOCA_RUNTIME_MODE=simulation", "BOCA_ENGINE_MODE=off"]
            if "Config.Env" in args
            else {"Name": "no", "MaximumRetryCount": 0}
        )

    monkeypatch.setattr(cleanup, "_docker", docker)
    instance = _Owned()
    assert instance.field("container", CONTAINER, "Config.Env") == [
        "BOCA_RUNTIME_MODE=simulation",
        "BOCA_ENGINE_MODE=off",
    ]
    assert instance.field("container", CONTAINER, "HostConfig.RestartPolicy") == {
        "Name": "no",
        "MaximumRetryCount": 0,
    }
    assert calls == [
        ("inspect", "--format", "{{json .Config.Env}}", CONTAINER),
        ("inspect", "--format", "{{json .HostConfig.RestartPolicy}}", CONTAINER),
    ]


@pytest.mark.parametrize(
    ("kind", "ident", "field"),
    [
        ("container", "foreign", "Config.Env"),
        ("container", CONTAINER, "Config.Secrets"),
        ("container", CONTAINER, "HostConfig.Binds"),
        ("volume", "foreign_project_data", "Mountpoint"),
        ("network", CONTAINER, "Containers"),
    ],
)
def test_reader_rejects_non_boca_or_unreviewed_fields_without_docker(
    monkeypatch: pytest.MonkeyPatch, kind: str, ident: str, field: str
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cleanup, "_docker", lambda *_args: calls.append("called"))
    with pytest.raises(LifecycleAdapterNoGo):
        _Owned().field(kind, ident, field)
    assert calls == []


def test_reader_denies_unverified_rootless_or_unbounded_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Foreign(_Owned):
        @property
        def uid(self) -> int:
            return 0

    calls: list[str] = []
    monkeypatch.setattr(cleanup, "_docker", lambda *_args: calls.append("called"))
    with pytest.raises(LifecycleAdapterNoGo):
        _Foreign().field("container", CONTAINER, "Config.User")
    assert calls == []
    monkeypatch.setattr(cleanup, "_docker", lambda *_args: " " * 16_385)
    with pytest.raises(LifecycleAdapterNoGo):
        _Owned().field("volume", VOLUME, "Mountpoint")
