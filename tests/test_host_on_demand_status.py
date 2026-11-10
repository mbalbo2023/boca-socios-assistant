"""Read-only physical observation, same-run projection and no raw output."""

import copy
import io
import json
import os
from contextlib import contextmanager
from dataclasses import replace

import pytest

import test_host_lifecycle_rootless_adapter as fixture
from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_lifecycle_rootless_adapter as adapter
from boca_socios import host_on_demand_status as status
from boca_socios.host_boca_cleanup import BocaJobLease
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation, PanelStatus
from test_on_demand_end_to_end import WorkerFixture

PINS = (fixture.SOURCE, fixture.CONTROLLER_REF, fixture.WORKER_REF, fixture.RUN)
OP = "a3b563c5-0a43-4d31-85d3-364467d684f7"
FAILED = PanelStatus(OP, "start", "FAILED", "MODULE_NOT_FOUND_ERROR", 1, False, None)


def test_host_attestor_reads_only_status_and_pid_of_the_installed_worker(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(cleanup, "LEASE_DIR", tmp_path)
    monkeypatch.setattr(adapter, "panel_control_mount", lambda: str(tmp_path / "control"))
    physical = WorkerFixture(tmp_path)
    monkeypatch.setattr(status, "ProductionRootlessDockerIO", lambda: physical)
    install = OnDemandInstallation(
        fixture.INSTALLED,
        fixture.SOURCE,
        fixture.CONTROLLER,
        fixture.CONTROLLER_REF,
        fixture.WORKER,
        fixture.WORKER_REF,
        tmp_path / "boca.sqlite3",
        fixture._binding(),
    )
    coords = replace(install.coordinates(OP), attempt_id=fixture.RUN)
    with cleanup.protected_boca_job_lease(fixture.RUN) as lease:
        for phase, pid, motor in (
            ("created", 0, False),
            ("running", 27, True),
            ("exited", 0, False),
        ):
            physical.fields["container", fixture.WORKER, "State.Status"] = phase
            physical.fields["container", fixture.WORKER, "State.Pid"] = pid
            physical.set_state(fixture.WORKER, pid > 0)
            physical.engine_running = motor
            assert status._physical(install, coords, lease) == (phase, pid, pid > 0, motor)
        physical.fields["container", fixture.WORKER, "State.Pid"] = 23
        with pytest.raises(status.StatusUnavailable):
            status._physical(install, coords, lease)
    assert physical.effects == []


@pytest.fixture
def host(tmp_path, monkeypatch):
    installation = OnDemandInstallation(
        fixture.INSTALLED,
        fixture.SOURCE,
        fixture.CONTROLLER,
        fixture.CONTROLLER_REF,
        fixture.WORKER,
        fixture.WORKER_REF,
        tmp_path / "boca.sqlite3",
        fixture._binding(),
    )
    lease = BocaJobLease(fixture.RUN, 1, 1, True)
    events = []
    state = {"state": "exited", "pid": 0, "healthy": False, "engine": False, "operation": FAILED}

    @contextmanager
    def held(run):
        assert run == fixture.RUN
        events.append("lease")
        yield lease
        events.append("released")

    def binding(given_lease):
        assert given_lease is lease
        events.append("binding")
        return installation

    def physical(item, coords, given_lease):
        assert item == installation and coords.attempt_id == fixture.RUN and given_lease is lease
        assert (coords.controller_id, coords.worker_id) == (fixture.CONTROLLER, fixture.WORKER)
        assert (coords.target, coords.component) == ("stop", "bot")
        events.append("physical")
        return state["state"], state["pid"], state["healthy"], state["engine"]

    def read(item):
        assert item == installation
        events.append("read")
        return state["operation"]

    monkeypatch.setattr(status, "protected_boca_job_lease", held)
    monkeypatch.setattr(status, "read_installed_binding", binding)
    monkeypatch.setattr(status, "_physical", physical)
    monkeypatch.setattr(status, "read_panel_status", read)
    return state, events


def verify(monkeypatch, data, pins=PINS):
    monkeypatch.setattr(status.sys, "stdin", io.TextIOWrapper(io.BytesIO(data)))
    return status.main(["verify", *pins])


def test_failed_worker_is_a_successful_independent_read(host, monkeypatch, capsys):
    state, events = host
    assert status.main(["host", *PINS]) == 0
    out = capsys.readouterr()
    assert not out.err and len(out.out.splitlines()) == 1
    assert events == ["lease", "binding", "physical", "read", "physical", "read", "released"]
    assert verify(monkeypatch, out.out.encode()) == 0
    assert capsys.readouterr().out == out.out
    data = json.loads(out.out.removeprefix(status.PREFIX))
    assert (data["panel"], data["engine"], data["worker_state"], data["worker_pid"]) == (
        "HEALTHY",
        "STOPPED",
        "exited",
        0,
    )
    assert data["operation"]["status"] == "FAILED" and data["operation"]["cause"] == FAILED.cause
    assert data["installation_run_id"] != data["observation_run_id"]
    state.update(state="created", operation=None)
    assert status.main(["host", *PINS]) == 0
    data = json.loads(capsys.readouterr().out.removeprefix(status.PREFIX))
    assert data["operation"] is None and data["worker_state"] == "created"


def test_cli_preserves_a_past_ack_separately_from_live_worker_state(host, capsys):
    state, _ = host
    state.update(
        operation=PanelStatus(OP, "start", "APPLIED", "NONE", None, None, None), engine=True
    )
    assert status.main(["host", *PINS]) == 0
    data = json.loads(capsys.readouterr().out.removeprefix(status.PREFIX))
    assert data["worker_state"] == "exited" and data["worker_pid"] == 0
    assert data["engine"] == "RUNNING" and data["operation"]["status"] == "APPLIED"


def test_refuses_wrong_release_before_physical_probe(host, capsys):
    _, events = host
    assert status.main(["host", "f" * 40, *PINS[1:]]) == 3
    assert events == ["lease", "binding"]
    assert capsys.readouterr().out == status.NO_GO + "\n"


@pytest.mark.parametrize("changed", ["physical", "read"])
def test_racing_observation_suppresses_partial_receipt(host, monkeypatch, capsys, changed):
    state, events = host
    func = "_physical" if changed == "physical" else "read_panel_status"
    original = getattr(status, func)

    def racing(*args):
        result = original(*args)
        if events.count(changed) == 1:
            if changed == "physical":
                state["engine"] = True
            else:
                state["operation"] = replace(FAILED, cause="MEMORY_ERROR")
        return result

    monkeypatch.setattr(status, func, racing)
    assert status.main(["host", *PINS]) == 3
    assert capsys.readouterr().out == status.NO_GO + "\n"


def test_verifier_rejects_single_field_substitutions_noise_and_cross_run(host, monkeypatch, capsys):
    assert status.main(["host", *PINS]) == 0
    raw = capsys.readouterr().out
    doc = json.loads(raw.removeprefix(status.PREFIX))
    for key, value in (
        ("controller_id", doc["worker_id"]),
        ("observation_run_id", "9"),
        ("engine", "untrusted-sentinel"),
        ("worker_state", "running"),
        ("worker_pid", False),
        ("worker_healthy", 1),
        ("operation", {**doc["operation"], "cause": "untrusted-sentinel"}),
        ("operation", {**doc["operation"], "exit_code": True}),
        ("operation", {**doc["operation"], "extra": "untrusted-sentinel"}),
    ):
        amended = copy.deepcopy(doc)
        amended[key] = value
        data = status.PREFIX + json.dumps(amended, separators=(",", ":"), sort_keys=True) + "\n"
        assert verify(monkeypatch, data.encode()) == 3
        assert capsys.readouterr().out == status.NO_GO + "\n"
    for payload in (raw + raw, raw.rstrip(), raw.replace("{", '{"schema":1,', 1), "x" * 4097):
        assert verify(monkeypatch, payload.encode()) == 3
        assert capsys.readouterr().out == status.NO_GO + "\n"
