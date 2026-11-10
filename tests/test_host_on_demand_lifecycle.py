"""Owner one-touch actions with the real existing SQLite ledger and inert Docker IO."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from boca_socios import host_lifecycle_rootless_adapter as adapter
from boca_socios import host_on_demand_lifecycle as demand
from boca_socios.host_boca_cleanup import BocaJobLease
from boca_socios.integration.engine_socket import EngineReceipt
from test_host_lifecycle_rootless_adapter import (
    CONTROLLER,
    CONTROLLER_REF,
    INSTALLED,
    SOURCE,
    WORKER,
    WORKER_REF,
    FakeIO,
    _binding,
    _request_with_real_ledger,
)


def test_real_docker_boundary_limits_fields_and_accepts_one_cli_newline(monkeypatch):
    def docker(*argv):
        if argv == ("inspect", "--format", "{{json .HostConfig.ReadonlyRootfs}}", WORKER):
            return "true\n"
        if argv == ("inspect", "--format", "{{json .State.Running}}", WORKER):
            return "false\n"
        assert argv == ("stop", "--time", "8", WORKER)
        return WORKER + "\n"

    monkeypatch.setattr(adapter.cleanup, "_docker", docker)
    io = adapter.ProductionRootlessDockerIO()
    assert io.field("container", WORKER, "HostConfig.ReadonlyRootfs") is True
    io.worker_action(WORKER, "stop")
    for field in ["Config.Env", "State.Error", "State.Health.Log", "HostConfig.Binds"]:
        with pytest.raises(adapter.LifecycleAdapterNoGo):
            io.field("container", WORKER, field)
    with pytest.raises(adapter.LifecycleAdapterNoGo):
        io.field("container", "other-name", "State.Running")


class InertDemandIO:
    def __init__(self, database):
        self.path = database.parent
        self.running = False
        self.healthy = False
        self.engine = False
        self.state = "created"
        self.events = []
        self.after_start = lambda: None
        self.failure = None
        self.stop_epoch = 0
        self.snap = adapter.RootlessLifecycleProbe(
            _binding(), FakeIO(self.path, worker_running=False)
        )

    def observe(self, coordinates, lease):
        return replace(
            self.snap.observe(coordinates, lease),
            worker_running=self.running, worker_healthy=self.healthy,
            bot_engine_running=self.engine,
        )

    def worker_state(self, worker_id):
        assert worker_id == WORKER
        return self.state

    def stopped_token(self, worker_id):
        assert worker_id == WORKER and self.state == "exited"
        return f"{self.stop_epoch:064x}"

    def start_worker(self, installation, state, before_start):
        assert installation.worker_id == WORKER and state == self.state
        self.events.append("attach")
        before_start()
        self.events.append("worker-start")
        self.state = "running"
        self.running = self.healthy = True
        self.after_start()
        if self.failure:
            self.running = self.healthy = False
            self.state = "exited"
            raise self.failure

    def verify_peer(self, controller_id):
        assert controller_id == CONTROLLER and self.running
        self.events.append("peer")

    def engine_request(self, controller_id, operation):
        assert controller_id == CONTROLLER
        self.events.append("motor-" + operation)
        self.engine = operation == "start"
        return EngineReceipt("RUNNING" if self.engine else "STOPPED", True, 22)

    def stop_worker(self, worker_id):
        assert worker_id == WORKER and not self.engine
        self.events.append("worker-stop")
        self.state = "exited"
        self.running = self.healthy = False
        self.stop_epoch += 1


@pytest.fixture
def setup_demand(tmp_path, monkeypatch):
    path = tmp_path / "boca.sqlite3"
    coords, ledger = _request_with_real_ledger(path, "bot", "start")
    install = demand.OnDemandInstallation(INSTALLED, SOURCE, CONTROLLER, CONTROLLER_REF, WORKER,
                                         WORKER_REF, path, _binding())
    io = InertDemandIO(path)

    @contextmanager
    def held(attempt):
        assert attempt == INSTALLED
        yield BocaJobLease(attempt, 100, 100, True)

    def validate(lease, attempt):
        assert lease.active and attempt == INSTALLED == lease.attempt_id

    monkeypatch.setattr(demand, "verify_protected_boca_job_lease", validate)
    monkeypatch.setattr(adapter, "verify_protected_boca_job_lease", validate)
    monkeypatch.setattr(demand, "verify_controller_peer", lambda c: io.verify_peer(c))

    def apply(operation):
        return demand.apply_panel_request(operation, install, io=io, lease_factory=held)

    return coords.request_id, ledger, io, apply


def test_start_stop_restart_and_no_replay(setup_demand):
    start, ledger, io, apply = setup_demand
    assert apply(start).status == "APPLIED"
    assert io.events == ["attach", "worker-start", "peer", "motor-start"]
    assert apply(start).status == "APPLIED"
    assert io.events == ["attach", "worker-start", "peer", "motor-start"]
    stop = str(uuid4())
    ledger.request("bot", "stop", stop)
    assert apply(stop).status == "APPLIED"
    assert io.events[-2:] == ["motor-stop", "worker-stop"]
    second = str(uuid4())
    ledger.request("bot", "start", second)
    assert apply(second).status == "APPLIED"
    assert io.events[-4:] == ["attach", "worker-start", "peer", "motor-start"]


def test_exited_worker_without_prior_owned_stop_is_refused(setup_demand):
    start, ledger, io, apply = setup_demand
    io.state = "exited"
    assert apply(start).status == "REFUSED"
    assert ledger.current().status == "REFUSED" and not io.events


def test_capture_category_and_exit_preserved_without_restarting(setup_demand):
    start, ledger, io, apply = setup_demand
    io.failure = demand.WorkerStartFailure("MODULE_NOT_FOUND_ERROR", exit_code=1, oom=False)
    result = apply(start)
    assert result.status == ledger.current().status == "FAILED"
    assert result.cause == "MODULE_NOT_FOUND_ERROR" and result.exit_code == 1
    assert apply(start) == result
    assert io.events == ["attach", "worker-start"]


def test_stop_preempts_inflight_start_before_enabling_motor(setup_demand):
    start, ledger, io, apply = setup_demand
    stop = str(uuid4())
    io.after_start = lambda: ledger.request("bot", "stop", stop)
    assert apply(start).status == "FAILED"
    assert "motor-start" not in io.events and io.events[-1] == "worker-stop"
    assert apply(stop).status == "APPLIED"
    assert apply(start).status == "FAILED"
    assert not io.running and not io.engine


def test_unrelated_uuid_does_not_start(setup_demand):
    _start, _ledger, io, apply = setup_demand
    with pytest.raises(demand.OnDemandUnavailable):
        apply(str(uuid4()))
    assert io.events == []
