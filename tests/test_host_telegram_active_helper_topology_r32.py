"""Offline-only R32 active-helper topology witness; no real Docker/Bot API."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_telegram_active_helper_topology as topology
from boca_socios import host_telegram_egress_helper as helper
from boca_socios import host_telegram_postcutover as stopped
from boca_socios.host_boca_cleanup import Container
from test_host_telegram_egress_helper_r30 import _HELPER, _attested_reader, _coordinates
from test_host_telegram_postcutover import _lease, _pins


@pytest.fixture(autouse=True)
def _fake_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    def verify(lease, attempt: str) -> None:
        assert lease.active is True and lease.attempt_id == attempt

    for module in (topology, stopped, helper):
        monkeypatch.setattr(module, "verify_protected_boca_job_lease", verify)
    monkeypatch.setattr(helper, "_run_helper", lambda *_args: _HELPER)
    monkeypatch.setattr(helper, "_remove_helper", lambda _ident: None)
    monkeypatch.setattr(
        helper, "_private_exec", lambda *_args: pytest.fail("no Telegram GET in topology test")
    )


def _observe(reader, phase: str = "BEFORE_API"):
    with helper.protected_ephemeral_get_session(
        _pins(), _coordinates(), lease=_lease(), reader=reader
    ) as session:
        return session.attest_topology(phase)


def test_active_helper_topology_remains_explicit_no_go(tmp_path: Path) -> None:
    reader = _attested_reader(tmp_path)
    witness = _observe(reader)
    assert type(witness) is topology.TelegramActiveHelperTopologyWitness
    assert witness.attempt_id == _pins().attempt_id
    assert witness.source_sha == _pins().source_sha
    assert witness.phase == "BEFORE_API"
    assert witness.state == "ACTIVE_HELPER_STOPPED_TOPOLOGY_OBSERVED_NO_GO"
    assert witness.sender_state == "OFF"
    assert witness.host_go is False
    assert witness.custody_state == "UNVERIFIED"
    assert witness.human_receipt == "UNVERIFIED"
    assert _HELPER not in repr(witness)
    assert reader.effects == []


def test_competing_poller_refused_even_if_expected_helper_present(tmp_path: Path) -> None:
    reader = _attested_reader(tmp_path)
    networks = tuple(
        replace(network, attached_ids=(_HELPER, "c" * 64))
        if network.name == helper._EGRESS
        else network
        for network in reader.inventory_value.networks
    )
    reader.inventory_value = replace(reader.inventory_value, networks=networks)
    with pytest.raises(helper.TelegramPhysicalNoGo):
        _observe(reader)


def test_unreviewed_container_not_hidden_by_projection(tmp_path: Path) -> None:
    reader = _attested_reader(tmp_path)
    foreign = Container("9" * 64, "/foreign", "sha256:" + "8" * 64, False, ())
    reader.inventory_value = replace(
        reader.inventory_value,
        containers=reader.inventory_value.containers + (foreign,),
    )
    with pytest.raises(helper.TelegramPhysicalNoGo, match="topology"):
        _observe(reader)


def test_active_topology_rejects_stopped_release_drift(tmp_path: Path) -> None:
    reader = _attested_reader(tmp_path)
    original = reader.inventory_value.containers
    reader.inventory_value = replace(
        reader.inventory_value,
        containers=(replace(original[0], running=True), *original[1:]),
    )
    with pytest.raises(helper.TelegramPhysicalNoGo, match="topology"):
        _observe(reader)


def test_reader_inventory_graph_changed_during_observation_no_go(tmp_path: Path) -> None:
    reader = _attested_reader(tmp_path)
    original_inventory = reader.inventory
    calls = 0

    def changing_inventory():
        nonlocal calls
        calls += 1
        original = original_inventory()
        if calls >= 4:
            return replace(original, volumes=original.volumes[:-1])
        return original

    reader.inventory = changing_inventory  # type: ignore[method-assign]
    with pytest.raises(helper.TelegramPhysicalNoGo, match="topology"):
        _observe(reader)


def test_closed_helper_cannot_be_used_for_later_topology(tmp_path: Path) -> None:
    reader = _attested_reader(tmp_path)
    with helper.protected_ephemeral_get_session(
        _pins(), _coordinates(), lease=_lease(), reader=reader
    ) as session:
        assert session.attest_topology("AFTER_READS").phase == "AFTER_READS"
    with pytest.raises(helper.TelegramPhysicalNoGo):
        session.attest_topology("BEFORE_COMMIT")


def test_nonallowlisted_phase_cannot_produce_topology_witness(tmp_path: Path) -> None:
    reader = _attested_reader(tmp_path)
    with pytest.raises(helper.TelegramPhysicalNoGo):
        _observe(reader, phase="SEND_MESSAGE")


def test_direct_observer_cannot_claim_topology_for_unattested_helper(tmp_path: Path) -> None:
    reader = _attested_reader(tmp_path)
    reader.fields[("container", _HELPER, "Config.Env")].append("BOT_TOKEN=exposed")
    with pytest.raises(topology.TelegramActiveTopologyNoGo):
        topology.observe_active_helper_topology(
            _pins(),
            _coordinates(),
            phase="BEFORE_API",
            lease=_lease(),
            reader=reader,
            helper_id=_HELPER,
        )
