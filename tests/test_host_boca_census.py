"""Boca-only current Docker census: redacted categories, no host effects."""

from __future__ import annotations

import json
from importlib import import_module

import pytest

from boca_socios import host_boca_cleanup as cleanup


def _census():
    return import_module("boca_socios.host_boca_census")


def _container(index: int, service: str, name: str, *, running: bool = True, attempt: bool = False):
    labels = [
        ("com.docker.compose.project", "boca-socios"),
        ("com.docker.compose.service", service),
    ]
    if attempt:
        labels.append(("boca.socios.browser-ipc-attempt", "42912586832"))
    return cleanup.Container(
        f"{index:064x}",
        name,
        f"{index + 10:064x}",
        running,
        tuple(labels),
    )


def _inventory(*containers):
    return _census().CensusSnapshot(
        tuple(_census().CensusContainer(c.ident, c.name, c.running, c.labels) for c in containers),
        frozenset(),
        frozenset(),
        (123, 456),
    )


def _observe(*snapshots):
    readings = iter(snapshots)
    raw = _census().observe(
        "42912586832",
        inventory_reader=lambda: next(readings),
        effective_uid=10001,
        effective_gid=10001,
    )
    return json.loads(raw.removeprefix(b"BOCA_CURRENT_CENSUS "))


@pytest.mark.parametrize(
    ("containers", "expected"),
    [
        ((), ("0", "0", "0", "0", "ABSENT")),
        (
            (_container(1, "controller", "/boca-socios-controller-1"),),
            ("1", "1", "0", "0", "APPEARS_RUNNING"),
        ),
        (
            (_container(1, "controller", "/boca-socios-controller-1", running=False),),
            ("1", "1", "0", "0", "APPEARS_STOPPED"),
        ),
        (
            (
                _container(1, "controller", "/boca-socios-controller-1"),
                _container(2, "browser-worker", "/boca-socios-browser-worker-1", running=False),
            ),
            ("2_PLUS", "1", "1", "0", "APPEARS_RUNNING"),
        ),
        (
            (
                _container(1, "controller", "/boca-socios-controller-1", attempt=True),
                _container(2, "controller", "/boca-socios-controller-legacy-42912586832"),
                _container(3, "browser-worker", "/boca-socios-browser-worker-1", running=False),
                _container(4, "telegram", "/boca-socios-telegram-1"),
            ),
            ("2_PLUS", "2_PLUS", "1", "1", "ABSENT"),
        ),
    ],
)
def test_current_census_distinguishes_empty_legacy_and_ambiguous_boca_topology(
    containers, expected
):
    snapshot = _inventory(*containers)
    result = _observe(snapshot, snapshot)
    total, controller, worker, other, legacy_shape = expected
    assert result == {
        "schema": 1,
        "state": "READY",
        "observation_run_id": "42912586832",
        "total": total,
        "controllers": controller,
        "workers": worker,
        "other_boca": other,
        "legacy_shape": legacy_shape,
        "observer_writes": 0,
        "foreign_resources_touched": 0,
        "cutover_authorized": False,
    }


def test_current_census_requires_two_identical_snapshots_and_no_implicit_retry():
    legacy = _container(1, "controller", "/boca-socios-controller-1")
    old = _inventory(legacy)
    changed = _inventory(legacy, _container(2, "browser-worker", "/boca-socios-browser-worker-1"))
    with pytest.raises(_census().CensusNoGo, match="unstable"):
        _observe(old, changed)


def test_current_census_reads_only_two_proven_boca_snapshots(monkeypatch):
    calls = []
    snapshot = _inventory()
    monkeypatch.setattr(
        _census(), "capture_container_census", lambda: calls.append("census") or snapshot
    )
    monkeypatch.setattr(cleanup, "capture_inventory", lambda: pytest.fail("image reader invoked"))
    monkeypatch.setattr(cleanup, "protected_boca_job_lease", lambda *_: pytest.fail("lease write"))
    monkeypatch.setattr(_census().os, "geteuid", lambda: 10001)
    monkeypatch.setattr(_census().os, "getegid", lambda: 10001)
    _census().observe("42912586832")
    assert calls == ["census", "census"]


def test_current_census_real_empty_inventory_issues_only_readonly_docker_verbs(monkeypatch):
    calls = []
    monkeypatch.setattr(cleanup, "_docker", lambda *args: calls.append(args) or "")
    monkeypatch.setattr(cleanup, "_disk_inodes", lambda: pytest.fail("storage reader invoked"))
    result = _observe_via_default_reader(monkeypatch)
    assert result["total"] == "0"
    assert len(calls) == 2 * 7  # seven graph ID/name listing reads per snapshot
    assert {args[0] for args in calls} == {"ps", "network", "volume"}
    assert all(args[1] == "ls" for args in calls if args[0] in {"network", "volume"})


def test_current_census_attests_private_rootless_daemon_before_each_resource_listing(monkeypatch):
    calls = []

    def attest():
        calls.append(("rootless_attest",))
        return (100, 20, 123, 456)

    monkeypatch.setattr(cleanup, "_docker", lambda *args: calls.append(args) or "")
    result = _observe_via_default_reader(monkeypatch, rootless_attestor=attest)
    assert result["total"] == "0"
    assert len(calls) == 2 * 8
    assert calls[0] == calls[8] == ("rootless_attest",)
    assert calls[1] == calls[9] == ("ps", "-a", "-q", "--no-trunc")
    assert {args[0] for args in calls if args[0] != "rootless_attest"} == {
        "ps",
        "network",
        "volume",
    }


def test_current_census_rootless_attestation_failure_aborts_before_all_docker_listing(monkeypatch):
    def untrusted():
        raise cleanup.CleanupError("UNTRUSTED_DOCKER_ROOT=/secret/root")

    monkeypatch.setattr(
        cleanup, "_docker", lambda *_: pytest.fail("Docker listed before root proof")
    )
    with pytest.raises(cleanup.CleanupError, match="UNTRUSTED_DOCKER_ROOT"):
        _observe_via_default_reader(monkeypatch, rootless_attestor=untrusted)


def test_current_census_rootless_attestation_failure_has_only_fixed_redacted_no_go(
    monkeypatch, capsys
):
    def untrusted():
        raise cleanup.CleanupError("DockerRootDir=/private/path")

    monkeypatch.setattr(cleanup, "_rootless_docker_disk_inodes", untrusted)
    monkeypatch.setattr(cleanup, "_docker", lambda *_: pytest.fail("Docker listed after NO_GO"))
    monkeypatch.setattr(_census().os, "geteuid", lambda: 10001)
    monkeypatch.setattr(_census().os, "getegid", lambda: 10001)
    assert _census().main(["host", "42912586832"]) == 3
    output = capsys.readouterr()
    assert output.out == "BOCA_CURRENT_CENSUS state=NO_GO reason=UNVERIFIED observer_writes=0\n"
    assert output.err == ""


def test_current_census_allows_free_space_drift_when_rootless_inode_remains_same(monkeypatch):
    readings = iter(((100, 20, 123, 456), (99, 19, 123, 456)))
    monkeypatch.setattr(cleanup, "_docker", lambda *args: "")
    result = _observe_via_default_reader(monkeypatch, rootless_attestor=lambda: next(readings))
    assert result["total"] == "0"


def test_current_census_never_reads_images_even_with_spoofed_boca_oci_label(monkeypatch):
    calls = []

    def fake_docker(*args):
        calls.append(args)
        if args[0] == "image":
            pytest.fail("global OCI image listing or inspect forbidden")
        return ""

    monkeypatch.setattr(cleanup, "_docker", fake_docker)
    monkeypatch.setattr(cleanup, "_disk_inodes", lambda: pytest.fail("storage reader invoked"))
    result = _observe_via_default_reader(monkeypatch)
    assert result["total"] == "0"
    assert {args[0] for args in calls} == {"ps", "network", "volume"}


def test_current_census_only_inspects_proven_boca_container_fields(monkeypatch):
    ident = "a" * 64
    calls = []

    def docker(*args):
        assert args[0] in ("ps", "network", "volume")
        if args[0] == "ps":
            return ident + "\n"
        return ""

    fields = {
        "Id": ident,
        "Name": "/boca-socios-controller-1",
        "State.Running": True,
        "Config.Labels": {
            "com.docker.compose.project": "boca-socios",
            "com.docker.compose.service": "controller",
        },
    }

    def inspect(kind, target, field):
        calls.append((kind, target, field))
        assert kind == "container" and target == ident
        return fields[field]

    monkeypatch.setattr(cleanup, "_docker", docker)
    monkeypatch.setattr(cleanup, "_inspect_field", inspect)
    result = _observe_via_default_reader(monkeypatch)
    assert result["total"] == "1"
    assert result["legacy_shape"] == "APPEARS_RUNNING"
    assert calls == [
        ("container", ident, field)
        for _ in range(2)
        for field in ("Id", "Name", "State.Running", "Config.Labels")
    ]


@pytest.mark.parametrize("foreign_kind", ["network", "volume"])
def test_current_census_refuses_foreign_resource_before_any_container_inspect(
    monkeypatch, foreign_kind
):
    calls = []

    def docker(*args):
        calls.append(args)
        if args[0] == foreign_kind and "--filter" not in args:
            return ("a" * 64 if foreign_kind == "network" else "foreign_service_data") + "\n"
        return ""

    monkeypatch.setattr(cleanup, "_docker", docker)
    monkeypatch.setattr(
        cleanup, "_inspect_field", lambda *_: pytest.fail("inspect before foreign exclusion")
    )
    with pytest.raises(_census().CensusNoGo, match=f"foreign {foreign_kind}"):
        _observe_via_default_reader(monkeypatch)
    assert all(args[0] in ("ps", "network", "volume") for args in calls)


def test_current_census_rejects_network_topology_drift_between_container_reads():
    first = _inventory()
    after = _census().CensusSnapshot((), frozenset({"a" * 64}), frozenset(), (123, 456))
    with pytest.raises(_census().CensusNoGo, match="unstable"):
        _observe(first, after)


def test_current_census_rejects_rootless_storage_inode_swap_between_reads():
    first = _inventory()
    after = _census().CensusSnapshot((), frozenset(), frozenset(), (123, 457))
    with pytest.raises(_census().CensusNoGo, match="unstable"):
        _observe(first, after)


def _observe_via_default_reader(monkeypatch, *, rootless_attestor=None):
    if rootless_attestor is None:

        def rootless_attestor():
            return (100, 20, 123, 456)

    monkeypatch.setattr(cleanup, "_rootless_docker_disk_inodes", rootless_attestor)
    monkeypatch.setattr(_census().os, "geteuid", lambda: 10001)
    monkeypatch.setattr(_census().os, "getegid", lambda: 10001)
    return json.loads(_census().observe("42912586832").removeprefix(b"BOCA_CURRENT_CENSUS "))


def test_current_census_foreign_id_only_probe_aborts_before_inspect(monkeypatch):
    calls = []

    def fake_docker(*args):
        calls.append(args)
        if args == ("ps", "-a", "-q", "--no-trunc"):
            return "a" * 64 + "\n"
        return ""

    monkeypatch.setattr(cleanup, "_docker", fake_docker)
    monkeypatch.setattr(
        cleanup, "_inspect_field", lambda *args: pytest.fail("foreign inspect attempted")
    )
    with pytest.raises(_census().CensusNoGo, match="foreign container"):
        _observe_via_default_reader(monkeypatch)
    assert calls == [
        ("ps", "-a", "-q", "--no-trunc"),
        (
            "ps",
            "-a",
            "-q",
            "--no-trunc",
            "--filter",
            "label=com.docker.compose.project=boca-socios",
        ),
    ]


@pytest.mark.parametrize("run_id", ["", "0", "01", "7;docker rm", "a" * 60])
def test_current_census_rejects_unpinned_observation_run(run_id):
    with pytest.raises(_census().CensusNoGo):
        _census().observe(
            run_id,
            inventory_reader=lambda: pytest.fail("read without identity"),
            effective_uid=10001,
            effective_gid=10001,
        )


def test_current_census_fails_closed_before_docker_if_not_boca_uid():
    with pytest.raises(_census().CensusNoGo):
        _census().observe(
            "42912586832",
            inventory_reader=lambda: pytest.fail("read on foreign UID"),
            effective_uid=0,
            effective_gid=0,
        )


def test_current_census_never_prints_foreign_inventory_or_exception_details(monkeypatch, capsys):
    def foreign():
        raise cleanup.CleanupError("FOREIGN_PATH=/var/private/sensitive")

    monkeypatch.setattr(_census(), "capture_container_census", foreign)
    monkeypatch.setattr(_census().os, "geteuid", lambda: 10001)
    monkeypatch.setattr(_census().os, "getegid", lambda: 10001)
    assert _census().main(["host", "42912586832"]) == 3
    output = capsys.readouterr()
    assert output.out == "BOCA_CURRENT_CENSUS state=NO_GO reason=UNVERIFIED observer_writes=0\n"
    assert output.err == ""


def test_current_census_runner_rejects_wrong_run_or_noncanonical_host_receipt():
    snapshot = _inventory()
    raw = _census().observe(
        "42912586832",
        inventory_reader=lambda: snapshot,
        effective_uid=10001,
        effective_gid=10001,
    )
    assert _census().verify(raw, "42912586832") == raw
    for corrupt in (
        raw + b"OTHER\n",
        raw.replace(b"42912586832", b"42912586833"),
        raw.replace(b'"observer_writes":0', b'"observer_writes":1'),
        raw.replace(b'"cutover_authorized":false', b'"cutover_authorized":true'),
        raw.replace(b'"total":"0"', b'"total":"2_PLUS"'),
        b"{" + b"X" * 1000,
        raw.replace(b'"legacy_shape":"ABSENT"', b'"legacy_shape":[]'),
        raw.replace(b'"controllers":"0"', b'"controllers":[]'),
    ):
        with pytest.raises(_census().CensusNoGo):
            _census().verify(corrupt, "42912586832")
