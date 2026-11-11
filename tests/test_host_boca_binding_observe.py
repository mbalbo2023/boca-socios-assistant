"""R178 protected observation: exact systemd binding, no host effects or GO."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from boca_socios import host_boca_binding_observe as binding
from boca_socios.host_lifecycle_rootless_adapter import ReviewedInstalledPair
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation
from test_host_boca_pair_upgrade_plan import OLD_ATTEMPT, OLD_SHA, RUN, _receipt


def _installed() -> OnDemandInstallation:
    previous = json.loads(_receipt().split(b" ", 1)[1])
    controller, worker = previous["services"]
    return OnDemandInstallation(
        installation_run_id=OLD_ATTEMPT,
        source_sha=OLD_SHA,
        controller_id=controller["container_id"],
        controller_image=controller["image_ref"],
        worker_id=worker["container_id"],
        worker_image=worker["image_ref"],
        database_path=binding.CANONICAL_DATABASE,
        pair=ReviewedInstalledPair(
            original_browser_attempt=OLD_ATTEMPT,
            controller_config_hash=controller["config_hash"],
            worker_config_hash=worker["config_hash"],
        ),
    )


def _run(*, pair=None, installed=None, uid=10001, gid=10001):
    raw = _receipt() if pair is None else pair
    current = _installed() if installed is None else installed
    reads = []

    def pair_reader(run_id):
        reads.append("pair")
        assert run_id == RUN
        return raw

    def binding_reader():
        reads.append("binding")
        return current

    result = binding.observe(
        RUN,
        pair_reader=pair_reader,
        binding_reader=binding_reader,
        effective_uid=uid,
        effective_gid=gid,
    )
    return result, reads


def test_observer_double_reads_binding_and_pair_and_never_grants_apply():
    receipt, reads = _run()
    assert reads == ["pair", "binding", "binding", "pair"]
    assert binding.verify(receipt, RUN) == receipt
    decoded = json.loads(receipt.removeprefix(binding.PREFIX))
    assert decoded == {
        "schema": 1,
        "state": "OBSERVED_NO_GO",
        "observation_run_id": RUN,
        "source_sha": OLD_SHA,
        "installation_run_id": OLD_ATTEMPT,
        "controller_id": _installed().controller_id,
        "worker_id": _installed().worker_id,
        "binding_systemd": "VERIFIED_LISTENING",
        "binding_archive": "VERIFIED_SHA256",
        "binding_pair": "MATCHED_EXACT",
        "sqlite_inode": "UNVERIFIED",
        "worker_exit_code": 1,
        "observer_writes": 0,
        "foreign_resources_touched": 0,
        "apply_authorized": False,
    }


@pytest.mark.parametrize(
    "change",
    [
        lambda item: replace(item, worker_id="f" * 64),
        lambda item: replace(item, source_sha="f" * 40),
        lambda item: replace(item, controller_image=item.worker_image),
        lambda item: replace(item, pair=replace(item.pair, worker_config_hash="e" * 64)),
        lambda item: replace(item, installation_run_id="43000000000"),
        lambda item: replace(item, database_path=item.database_path.parent / "wrong.db"),
        lambda item: replace(item, pair=replace(item.pair, sender_id="f" * 64)),
    ],
)
def test_binding_drift_denied_before_claim(change):
    with pytest.raises(binding.BindingNoGo):
        _run(installed=change(_installed()))


def test_uid_or_gid_mismatch_denied_without_reader_calls():
    for uid, gid in [(0, 0), (10001, 0), (10000, 10001)]:
        with pytest.raises(binding.BindingNoGo):
            _run(uid=uid, gid=gid)


def test_second_binding_change_denied_even_when_pair_unchanged():
    values = iter((_installed(), replace(_installed(), worker_id="f" * 64)))
    with pytest.raises(binding.BindingNoGo):
        binding.observe(
            RUN,
            pair_reader=lambda _: _receipt(),
            binding_reader=lambda: next(values),
            effective_uid=10001,
            effective_gid=10001,
        )


def test_second_pair_change_denied_after_binding_attestation():
    first = _receipt()
    altered = json.loads(first.split(b" ", 1)[1])
    altered["services"][1]["exit_code"] = 0
    second = binding.pair._canonical(altered)
    pairs = iter((first, second))
    with pytest.raises(binding.BindingNoGo):
        binding.observe(
            RUN,
            pair_reader=lambda _: next(pairs),
            binding_reader=_installed,
            effective_uid=10001,
            effective_gid=10001,
        )


@pytest.mark.parametrize(
    "key,value",
    [
        ("apply_authorized", True),
        ("observer_writes", 1),
        ("binding_systemd", "UNKNOWN"),
        ("sqlite_inode", "VERIFIED"),
        ("injected", "secret"),
    ],
)
def test_runner_strictly_rejects_any_receipt_overclaim(key, value):
    valid, _ = _run()
    payload = json.loads(valid.removeprefix(binding.PREFIX))
    payload[key] = value
    forged = (
        binding.PREFIX + json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    with pytest.raises(binding.BindingNoGo):
        binding.verify(forged, RUN)


def test_hostname_or_database_path_never_emitted():
    valid, _ = _run()
    assert b"/home/" not in valid
    assert b".sqlite3" not in valid
    assert b"Env" not in valid
