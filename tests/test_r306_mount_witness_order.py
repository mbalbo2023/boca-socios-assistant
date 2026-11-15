"""Mount permutations preserve evidence; actual drift still fences recovery effects."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

import test_r305_telegram_initializer_recovery as previous


def boundary(monkeypatch, turns, *, fault="", at=2):
    from boca_socios import host_boca_cleanup as cleanup

    original = cleanup._docker
    counts = {previous.CONTROLLER: 0, previous.WORKER: 0}
    supplied = {cid: [] for cid in counts}

    def docker(*args):
        raw = original(*args)
        if args[:3] != ("inspect", "--format", "{{json .Mounts}}") or args[-1] not in counts:
            return raw
        cid = args[-1]
        counts[cid] += 1
        records = json.loads(raw)
        for record in records:
            record["Mode"] = "rw" if record["RW"] else "ro"
            record["ObservedExtra"] = {"destination": record["Destination"], "values": [1, 2]}
        if cid == previous.CONTROLLER and counts[cid] >= at:
            data = next(record for record in records if record["Destination"] == "/data")
            if fault == "source":
                data["Source"] = previous.ROOT + "other/_data"
            elif fault == "rw":
                data["RW"] = False
            elif fault == "mode":
                data["Mode"] = "changed"
            elif fault == "field":
                data["ObservedExtra"]["values"].append(3)
            elif fault == "driver":
                data["Driver"] = "other"
            elif fault == "duplicate":
                records[-1] = deepcopy(data)
            elif fault == "extra":
                records.append({**data, "Name": "other", "Destination": "/extra"})
        offset = turns[min(counts[cid] - 1, len(turns) - 1)] % len(records)
        records = records[offset:] + records[:offset]
        supplied[cid].append(deepcopy(records))
        return json.dumps(records)

    monkeypatch.setattr(cleanup, "_docker", docker)
    if fault in {"inode", "alias-data", "alias-control"}:
        original_lstat = Path.lstat
        target = (
            previous.CONTROL
            if fault == "alias-control"
            else previous.ROOT + "boca-socios_boca_data/_data"
        )

        def lstat(path, *args, **kwargs):
            result = original_lstat(path, *args, **kwargs)
            if str(path) == target and counts[previous.CONTROLLER] >= at:
                values = list(result)
                values[1] = result.st_ino + 100 if fault == "inode" else 55
                return os.stat_result(values)
            return result

        monkeypatch.setattr(Path, "lstat", lstat)
    return counts, supplied


@pytest.mark.parametrize(
    "turns",
    [
        pytest.param((0, 1, 0, 0, 0), id="preflight"),
        pytest.param((0, 0, 1, 1, 1), id="after-init"),
        pytest.param((0, 0, 0, 1, 0), id="before-rm"),
        pytest.param((0, 0, 0, 0, 1), id="postflight"),
        pytest.param((0, 1, 2, 3, 4), id="every-snapshot"),
    ],
)
def test_r306_mount_order_is_irrelevant_through_real_recovery(monkeypatch, tmp_path, turns):
    recovery, commands, state, clients = previous.fixture(monkeypatch, tmp_path)
    counts, supplied = boundary(monkeypatch, turns)
    value = previous.decoded(recovery, recovery.recover(previous.RUN, previous.WORKFLOW))
    assert value == previous.accepted(), value
    assert [cmd for cmd in commands if cmd[0] in {"start", "rm", "stop", "create"}] == [
        ("start", previous.HELPER),
        ("rm", previous.HELPER),
    ]
    assert not state["exists"] and len(clients) == 1 and clients[0].poll() == 0
    assert counts == {previous.CONTROLLER: 5, previous.WORKER: 5}
    assert any(
        records != supplied[previous.CONTROLLER][0] for records in supplied[previous.CONTROLLER]
    )


@pytest.mark.parametrize(
    "fault",
    [
        "source",
        "rw",
        "mode",
        "field",
        "driver",
        "duplicate",
        "extra",
        "inode",
        "alias-data",
        "alias-control",
    ],
)
@pytest.mark.parametrize(
    "at,phase,initialization,retirement,effects",
    [
        (2, "PREFLIGHT", "NOT_ATTEMPTED", "NOT_ATTEMPTED", []),
        (3, "VERIFY_INITIALIZATION", "INDETERMINATE", "NOT_ATTEMPTED", ["start"]),
        (4, "RETIRE", "ACCEPTED", "NOT_ATTEMPTED", ["start"]),
        (5, "POSTFLIGHT", "ACCEPTED", "RETIRED", ["start", "rm"]),
    ],
)
def test_r306_mount_drift_is_rejected_despite_permutation(
    monkeypatch, tmp_path, fault, at, phase, initialization, retirement, effects
):
    recovery, commands, state, clients = previous.fixture(monkeypatch, tmp_path)
    boundary(monkeypatch, (0, 1, 2, 3, 4), fault=fault, at=at)
    value = previous.decoded(recovery, recovery.recover(previous.RUN, previous.WORKFLOW))
    assert (value["state"], value["phase"], value["initialization"], value["retirement"]) == (
        "NO_GO",
        phase,
        initialization,
        retirement,
    )
    assert value["sender_state"] == value["pair_state"] == "UNVERIFIED"
    assert [cmd[0] for cmd in commands if cmd[0] in {"start", "rm", "stop", "create"}] == effects
    assert len(clients) == int("start" in effects)
    assert state["exists"] is ("rm" not in effects)


def test_r306_mount_records_and_identities_preserve_all_evidence(monkeypatch, tmp_path):
    recovery, _, _, _ = previous.fixture(monkeypatch, tmp_path)
    _, supplied = boundary(monkeypatch, (2, 3))
    parsed = []
    original_parser = recovery.incident._json

    def observe_parser(raw):
        value = original_parser(raw)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            parsed.append(value)
        return value

    # Call through to the real parser; retain its actual list to detect in-place sorting.
    monkeypatch.setattr(recovery.incident, "_json", observe_parser)
    first, second = recovery._mount_witnesses(), recovery._mount_witnesses()
    assert first == second
    assert len(parsed) == 4
    expected_inodes = {
        "/data": 56,
        "/run/secrets": 57,
        "/run/owner": 58,
        "/run/boca-browser-ipc": 59,
        "/run/boca-site-config": 60,
        "/run/boca-bot-control": 61,
    }
    for index, cid in enumerate((previous.CONTROLLER, previous.WORKER)):
        records, identities = first[cid]
        incoming = supplied[cid][0]
        assert parsed[index] == incoming
        assert parsed[index + 2] == supplied[cid][1]
        assert records is not parsed[index]
        assert len(records) == len(incoming) == len(identities)
        assert {record["Destination"] for record in records} == {
            record["Destination"] for record in incoming
        }
        for record, (source, identity) in zip(records, identities, strict=True):
            original = next(
                item for item in incoming if item["Destination"] == record["Destination"]
            )
            assert record == original
            assert source == original["Source"]
            assert identity == (22, expected_inodes[record["Destination"]])


def test_r306_duplicate_mounts_refused_before_sort(monkeypatch, tmp_path):
    from boca_socios import host_boca_cleanup as cleanup
    from boca_socios.host_lifecycle_rootless_adapter import LifecycleAdapterNoGo

    recovery, commands, _, clients = previous.fixture(monkeypatch, tmp_path)
    original = cleanup._docker

    def duplicate(*args):
        raw = original(*args)
        if args == ("inspect", "--format", "{{json .Mounts}}", previous.WORKER):
            records = json.loads(raw)
            return json.dumps([records[1], records[0], records[1]])
        return raw

    monkeypatch.setattr(cleanup, "_docker", duplicate)
    with pytest.raises(LifecycleAdapterNoGo, match="duplicate service mount"):
        recovery._mount_witnesses()
    assert not clients and not any(cmd[0] in {"start", "rm", "stop", "create"} for cmd in commands)
