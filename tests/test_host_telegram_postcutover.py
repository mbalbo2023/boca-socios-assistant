"""Source-only Telegram host topology witness; all Docker/lease IO is fake."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_telegram_postcutover as host
from boca_socios.host_boca_cleanup import (
    BocaJobLease,
    Container,
    Inventory,
    Network,
    Volume,
)
from test_host_lifecycle_rootless_adapter import (
    CI,
    CONFIG_CONTROLLER,
    CONFIG_SENDER,
    CONFIG_WORKER,
    CONTROLLER,
    CONTROLLER_REF,
    FakeIO,
    INSTALLED,
    IPC_ATTEMPT,
    SENDER,
    SENDER_ATTEMPT,
    SOURCE,
    WI,
    WORKER,
    WORKER_REF,
)

_ATTEMPT = "3456789012"
_TG = "boca-socios_boca_telegram"


def _pins(*, stopped_sender: bool = False) -> host.TelegramHostPins:
    return host.TelegramHostPins(
        version="boca-protected-action-v1",
        kind="telegram",
        attempt_id=_ATTEMPT,
        source_sha=SOURCE,
        controller_id=CONTROLLER,
        controller_image=CONTROLLER_REF,
        worker_id=WORKER,
        worker_image=WORKER_REF,
        browser_attempt=INSTALLED,
        controller_config_hash=CONFIG_CONTROLLER,
        worker_config_hash=CONFIG_WORKER,
        data_mountpoint="/data",
        cutover_attempt="123456789",
        cutover_receipt_sha256="d" * 64,
        owner_digest="e" * 64,
        recipient_fingerprint="f" * 64,
        sender_expected_state="stopped" if stopped_sender else "absent",
        sender_id=SENDER if stopped_sender else "",
        sender_image=CONTROLLER_REF if stopped_sender else "",
        sender_config_hash=CONFIG_SENDER if stopped_sender else "",
        sender_attempt=SENDER_ATTEMPT if stopped_sender else "",
    )


def _volume(name: str) -> Volume:
    return Volume(
        name,
        (
            ("com.docker.compose.project", "boca-socios"),
            ("com.docker.compose.volume", name.removeprefix("boca-socios_")),
        ),
    )


def _network(name: str, *, attached: tuple[str, ...] = ()) -> Network:
    return Network(
        name,
        "2" * 64 if name.endswith("boca_private") else "3" * 64,
        attached,
        (
            ("com.docker.compose.project", "boca-socios"),
            (
                "com.docker.compose.network",
                "boca_private" if name.endswith("boca_private") else "telegram_egress",
            ),
        ),
    )


def _fake(tmp_path: Path, *, stopped_sender: bool = False) -> FakeIO:
    io = FakeIO(
        tmp_path,
        worker_running=False,
        sender_running=False if stopped_sender else None,
    )
    io.set_state(CONTROLLER, False)
    if io.inventory_value.containers[0].image_id != CI:
        raise AssertionError("fixture controller changed")
    if io.inventory_value.containers[1].image_id != WI:
        raise AssertionError("fixture worker changed")
    io.inventory_value = replace(
        io.inventory_value,
        volumes=tuple(
            _volume(name)
            for name in (
                "boca-socios_boca_data",
                "boca-socios_boca_key",
                "boca-socios_boca_owner",
                "boca-socios_boca_browser_ipc",
                _TG,
            )
        ),
        networks=(
            _network("boca-socios_boca_private"),
            _network("boca-socios_boca_telegram_egress"),
        ),
    )
    io.fields[("volume", _TG, "Mountpoint")] = str(tmp_path)
    return io


@pytest.fixture(autouse=True)
def _lease_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    def _verify(lease: BocaJobLease, attempt: str) -> None:
        assert lease.active and lease.attempt_id == attempt and lease.owner_pid == os.getpid()

    monkeypatch.setattr(host, "verify_protected_boca_job_lease", _verify)


def _lease() -> BocaJobLease:
    return BocaJobLease(_ATTEMPT, 9, os.getpid(), True)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("version", "1"),
        ("kind", "lifecycle"),
        ("attempt_id", "0"),
        ("source_sha", "z" * 40),
        ("controller_id", "abc"),
        ("controller_image", "ghcr.io/evil@sha256:" + "a" * 64),
        ("worker_image", "ghcr.io/evil@sha256:" + "a" * 64),
        ("controller_config_hash", "bad"),
        ("worker_config_hash", CONFIG_CONTROLLER),
        ("browser_attempt", "1;echo bad"),
        ("data_mountpoint", "/tmp"),
        ("cutover_attempt", "abc"),
        ("cutover_receipt_sha256", "bad"),
        ("owner_digest", "bad"),
        ("recipient_fingerprint", "bad"),
    ],
)
def test_public_pins_fail_closed(field: str, invalid: str) -> None:
    pins = replace(_pins(), **{field: invalid})
    with pytest.raises(host.TelegramHostNoGo):
        pins.require()


def test_sender_absent_does_not_accept_pins_or_undocumented_state() -> None:
    with pytest.raises(host.TelegramHostNoGo):
        replace(_pins(), sender_id=SENDER).require()
    with pytest.raises(host.TelegramHostNoGo):
        replace(_pins(), sender_expected_state="running").require()  # type: ignore[arg-type]


def test_sender_stopped_requires_all_four_exact_pins() -> None:
    _pins(stopped_sender=True).require()
    for field in ("sender_id", "sender_image", "sender_config_hash", "sender_attempt"):
        with pytest.raises(host.TelegramHostNoGo):
            replace(_pins(stopped_sender=True), **{field: ""}).require()


@pytest.mark.parametrize("stopped_sender", [False, True])
def test_observes_boca_topology_but_never_authorizes(
    tmp_path: Path, stopped_sender: bool
) -> None:
    io = _fake(tmp_path, stopped_sender=stopped_sender)
    result = host.observe_telegram_host(\n        _pins(stopped_sender=stopped_sender), lease=_lease(), io=io\n    )
    assert result.phase == "TOPOLOGY_OBSERVED_NOT_AUTHORIZED"
    assert result.authorized is False
    assert result.host_effects is False
    assert result.sender_state == "OFF"
    assert result.human_receipt == "UNVERIFIED"
    assert io.effects == []


def test_controller_must_be_physically_stopped(tmp_path: Path) -> None:
    io = _fake(tmp_path)
    io.set_state(CONTROLLER, True)
    with pytest.raises(host.TelegramHostNoGo):
        host.observe_telegram_host(_pins(), lease=_lease(), io=io)


def test_sender_off_is_observed_not_claimed(tmp_path: Path) -> None:
    io = _fake(tmp_path, stopped_sender=True)
    io.set_state(SENDER, True)
    with pytest.raises(host.TelegramHostNoGo):
        host.observe_telegram_host(_pins(stopped_sender=True), lease=_lease(), io=io)


def test_egress_with_competing_pollers_is_no_go(tmp_path: Path) -> None:
    io = _fake(tmp_path)
    networks = list(io.inventory_value.networks)
    networks[1] = replace(networks[1], attached_ids=(SENDER,))
    io.inventory_value = replace(io.inventory_value, networks=tuple(networks))
    with pytest.raises(host.TelegramHostNoGo, match="competing_poller"):
        host.observe_telegram_host(_pins(), lease=_lease(), io=io)


def test_foreign_container_or_volume_is_never_inspected_or_modified(tmp_path: Path) -> None:
    io = _fake(tmp_path)
    foreign = Container("9" * 64, "/foreign", "sha256:" + "8" * 64, False, ())
    io.inventory_value = replace(
        io.inventory_value, containers=(*io.inventory_value.containers, foreign)
    )
    with pytest.raises(host.TelegramHostNoGo):
        host.observe_telegram_host(_pins(), lease=_lease(), io=io)
    assert io.effects == []


def test_missing_recipient_volume_denied(tmp_path: Path) -> None:
    io = _fake(tmp_path)
    io.inventory_value = replace(
        io.inventory_value,
        volumes=tuple(volume for volume in io.inventory_value.volumes if volume.name != _TG),
    )
    with pytest.raises(host.TelegramHostNoGo):
        host.observe_telegram_host(_pins(), lease=_lease(), io=io)


def test_config_label_drift_denied(tmp_path: Path) -> None:
    io = _fake(tmp_path)
    containers = list(io.inventory_value.containers)
    changed = dict(containers[0].labels)
    changed["com.docker.compose.config-hash"] = "0" * 64
    containers[0] = replace(containers[0], labels=tuple(sorted(changed.items())))
    io.inventory_value = replace(io.inventory_value, containers=tuple(containers))
    with pytest.raises(host.TelegramHostNoGo):
        host.observe_telegram_host(_pins(), lease=_lease(), io=io)


def test_mount_and_port_drift_denied(tmp_path: Path) -> None:
    io = _fake(tmp_path)
    io.fields[("container", CONTROLLER, "NetworkSettings.Ports")] = {
        "8443/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8443"}]
    }
    with pytest.raises(host.TelegramHostNoGo):
        host.observe_telegram_host(_pins(), lease=_lease(), io=io)


def test_lease_identity_enforced_before_docker(tmp_path: Path) -> None:
    io = _fake(tmp_path)
    with pytest.raises(AssertionError):
        host.observe_telegram_host(
            _pins(), lease=BocaJobLease("999", 9, os.getpid(), True), io=io
        )


def test_unrelated_credentials_never_enter_a_receipt(tmp_path: Path) -> None:
    io = _fake(tmp_path)
    assert IPC_ATTEMPT != "TOKEN"
    observed = host.observe_telegram_host(_pins(), lease=_lease(), io=io)
    text = repr(observed)
    for secret in ("TOKEN", "/run/telegram", str(tmp_path), "getUpdates"):
        assert secret not in text
