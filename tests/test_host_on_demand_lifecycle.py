"""Owner one-touch actions with the real existing SQLite ledger and inert Docker IO."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
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
        if argv == ("stop", "--time", "8", WORKER):
            return "Flag --time has been deprecated, use --timeout instead\n" + WORKER + "\n"
        assert argv == ("stop", "-t", "8", WORKER)
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
            worker_running=self.running,
            worker_healthy=self.healthy,
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
    old, ledger = _request_with_real_ledger(path, "bot", "start")
    operation = str(uuid4())
    assert ledger.request("bot", "start", operation, on_demand=True).operation_id == operation
    assert old.request_id != operation
    install = demand.OnDemandInstallation(
        INSTALLED, SOURCE, CONTROLLER, CONTROLLER_REF, WORKER, WORKER_REF, path, _binding()
    )
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

    return operation, ledger, io, apply


def test_start_stop_restart_and_no_replay(setup_demand):
    start, ledger, io, apply = setup_demand
    assert apply(start).status == "APPLIED"
    assert io.events == ["attach", "worker-start", "peer", "motor-start"]
    assert apply(start).status == "APPLIED"
    assert io.events == ["attach", "worker-start", "peer", "motor-start"]
    stop = str(uuid4())
    ledger.request("bot", "stop", stop, on_demand=True)
    assert apply(stop).status == "APPLIED"
    assert io.events[-2:] == ["motor-stop", "worker-stop"]
    second = str(uuid4())
    ledger.request("bot", "start", second, on_demand=True)
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
    io.after_start = lambda: ledger.request("bot", "stop", stop, on_demand=True)
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


def test_stop_wake_waits_on_real_flock_without_repeating_start(tmp_path, monkeypatch):
    import os
    import time
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from boca_socios import host_boca_cleanup as cleanup

    path = tmp_path / "boca.sqlite3"
    _, ledger = _request_with_real_ledger(path, "bot", "start")
    start = str(uuid4())
    assert ledger.request("bot", "start", start, on_demand=True).operation_id == start
    install = demand.OnDemandInstallation(
        INSTALLED, SOURCE, CONTROLLER, CONTROLLER_REF, WORKER, WORKER_REF, path, _binding()
    )
    io = InertDemandIO(path)
    entered, contention, release = Event(), Event(), Event()
    locks = tmp_path / "boca-lease"
    locks.mkdir(mode=0o700)
    monkeypatch.setattr(cleanup, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(cleanup, "LEASE_DIR", locks)

    def wait_for_stop():
        entered.set()
        assert release.wait(4)

    def wait_for_free_lock(_seconds):
        contention.set()
        time.sleep(0.01)

    io.after_start = wait_for_stop
    monkeypatch.setattr(demand, "sleep", wait_for_free_lock)
    stop = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        starting = pool.submit(demand.apply_panel_request, start, install, io=io)
        assert entered.wait(4)
        assert ledger.request("bot", "stop", stop, on_demand=True).operation_id == stop
        stopping = pool.submit(demand.apply_panel_request, stop, install, io=io)
        try:
            assert contention.wait(4) and not stopping.done()
        finally:
            release.set()
        assert starting.result(timeout=5).cause == "CANCELLED"
        assert stopping.result(timeout=5).status == "APPLIED"
    assert io.events == ["attach", "worker-start", "worker-stop"]
    assert ledger.current().operation_id == stop and ledger.current().status == "APPLIED"


def test_start_ack_lost_after_commit_is_observed_without_compensation(setup_demand, monkeypatch):
    start, _, io, apply = setup_demand
    transact = demand._Transaction.transact

    def lose_one_reply(self, phase, arg="-"):
        result = transact(self, phase, arg)
        if phase == "APPLIED":
            raise OSError("lost public response")
        return result

    monkeypatch.setattr(demand._Transaction, "transact", lose_one_reply)
    assert apply(start).status == "APPLIED"
    assert io.engine and io.running and "worker-stop" not in io.events


@pytest.mark.parametrize("lost_ack", [False, True])
def test_capture_arm_precedes_docker_and_classifies_exit_inside_attach(
    monkeypatch, tmp_path, lost_ack
):
    install = demand.OnDemandInstallation(
        INSTALLED,
        SOURCE,
        CONTROLLER,
        CONTROLLER_REF,
        WORKER,
        WORKER_REF,
        tmp_path / "boca.sqlite3",
        _binding(),
    )
    trace = []

    @contextmanager
    def attach(path, worker):
        assert path == demand.deploy.ROOTLESS_SOCKET and worker == WORKER
        trace.append("attached")

        class Capture:
            def finish(self):
                trace.append("classify")
                return demand.CaptureResult.MODULE_NOT_FOUND_ERROR

        yield Capture()
        trace.append("detached")

    def preflight(cid, image, sha, run, conf, *, expected_state, on_demand):
        assert (cid, image, sha, run, conf, expected_state, on_demand) == (
            WORKER,
            WORKER_REF,
            SOURCE,
            INSTALLED,
            _binding().worker_config_hash,
            "exited",
            True,
        )
        trace.append("verified")

    def docker(*args, timeout):
        assert args == ("docker", "start", WORKER) and timeout == 30
        trace.append("start")
        if lost_ack:
            raise demand.deploy.PreflightError("transport failure")
        return WORKER

    def health(cid):
        assert cid == WORKER
        trace.append("exited")
        raise demand.deploy.WorkerHealthPhaseError(
            "HEALTH_EXITED",
            exit_code=1,
            oom_killed=False,
            exit_signature="EMPTY.EXITED.EARLY_LT_5S.NOT_RUN",
        )

    monkeypatch.setattr(demand.deploy, "_cutover_capture_preflight", preflight)
    monkeypatch.setattr(demand, "attach_output", attach)
    monkeypatch.setattr(demand.deploy, "_run", docker)
    monkeypatch.setattr(demand.deploy, "_browser_wait_healthy", health)
    monkeypatch.setattr(demand._RootlessIO, "worker_state", lambda self, cid: "exited")
    with pytest.raises(demand.WorkerStartFailure) as error:
        demand._RootlessIO(install).start_worker(install, "exited", lambda: trace.append("claimed"))
    assert trace == ["verified", "attached", "claimed", "start", "exited", "classify"]
    assert error.value.encode() == "MODULE_NOT_FOUND_ERROR|1|0|EMPTY.EXITED.EARLY_LT_5S.NOT_RUN"


def test_status_reads_only_exact_controller_private_ledger(setup_demand, monkeypatch):
    start, _, io, apply = setup_demand
    assert apply(start).status == "APPLIED"
    path = io.path / "boca.sqlite3"
    install = demand.OnDemandInstallation(
        INSTALLED, SOURCE, CONTROLLER, CONTROLLER_REF, WORKER, WORKER_REF, path, _binding()
    )
    with demand.lifecycle._controller_ledger(path, readonly=True) as db:
        count = db.execute("SELECT COUNT(*) FROM audit_events").fetchone()
        assert db.execute("PRAGMA query_only").fetchone() == (1,)

    def docker(*args):
        assert args == (
            "exec",
            "--user",
            "10001:10001",
            CONTROLLER,
            "/app/.venv/bin/python",
            "-I",
            "-B",
            "-m",
            "boca_socios.host_on_demand_lifecycle",
            "status",
            install.fingerprint(),
        )
        return demand._status_wire(path, install.fingerprint()) + "\n"

    monkeypatch.setattr(demand.cleanup, "_docker", docker)
    status = demand.read_panel_status(install)
    assert status.operation_id == start and status.status == "APPLIED"
    with demand.lifecycle._controller_ledger(path, readonly=True) as db:
        assert db.execute("SELECT COUNT(*) FROM audit_events").fetchone() == count


def test_recovered_claim_blocks_replay_and_unknown_installation(setup_demand):
    start, ledger, io, apply = setup_demand
    path = io.path / "boca.sqlite3"
    install = demand.OnDemandInstallation(
        INSTALLED, SOURCE, CONTROLLER, CONTROLLER_REF, WORKER, WORKER_REF, path, _binding()
    )
    fp = install.fingerprint()
    assert demand._transact(path, start, fp, "claim").status == "CLAIMED"
    receipt = apply(start)
    assert receipt.status == "UNCERTAIN" and receipt.cause == "CLAIM_INTERRUPTED"
    assert apply(start) == receipt and not io.events and ledger.current().status == "UNCERTAIN"
    with pytest.raises(demand.OnDemandUnavailable):
        demand._transact(path, start, "7" * 64, "read")


@pytest.mark.parametrize(
    "mutation",
    [
        "none",
        "control_rw",
        "other_source",
        "worker_ip",
        "worker_restart",
        "wrong_controller_restart",
    ],
)
def test_on_demand_topology_only_controller_survives_reboot(tmp_path, monkeypatch, mutation):
    from test_host_lifecycle_rootless_adapter import _coordinates

    coords = _coordinates(tmp_path / "boca.sqlite3", "bot", "stop")
    io = FakeIO(tmp_path, worker_running=False)
    mount = {
        "Type": "bind",
        "Source": adapter.panel_control_mount(),
        "Destination": "/run/boca-bot-control",
        "RW": False,
        "Propagation": "rprivate",
    }
    io.fields[("container", CONTROLLER, "Mounts")].append(mount)
    io.fields[("container", CONTROLLER, "HostConfig.RestartPolicy")]["Name"] = "unless-stopped"
    io.fields[("container", CONTROLLER, "RestartCount")] = 2
    io.fields[("container", WORKER, "HostConfig.PortBindings")] = {}
    io.fields[("container", WORKER, "NetworkSettings.Ports")] = None
    io.fields[("container", WORKER, "NetworkSettings.Networks")] = {
        "none": {"IPAddress": "", "GlobalIPv6Address": ""}
    }
    if mutation == "control_rw":
        mount["RW"] = True
    elif mutation == "other_source":
        mount["Source"] = "/other/socket"
    elif mutation == "worker_ip":
        io.fields[("container", WORKER, "NetworkSettings.Networks")]["none"]["IPAddress"] = (
            "192.0.2.1"
        )
    elif mutation == "worker_restart":
        io.fields[("container", WORKER, "HostConfig.RestartPolicy")]["Name"] = "always"
    elif mutation == "wrong_controller_restart":
        io.fields[("container", CONTROLLER, "HostConfig.RestartPolicy")]["Name"] = "always"
    monkeypatch.setattr(adapter, "verify_protected_boca_job_lease", lambda lease, attempt: None)
    lease = BocaJobLease(coords.attempt_id, 1, 1, True)
    probe = adapter.RootlessLifecycleProbe(_binding(), io, on_demand=True)
    if mutation == "none":
        observed = probe.observe(coords, lease)
        assert observed.controller_healthy and not observed.worker_running
        with pytest.raises(adapter.LifecycleAdapterNoGo):
            adapter.RootlessLifecycleProbe(_binding(), io).observe(coords, lease)
    else:
        with pytest.raises(adapter.LifecycleAdapterNoGo):
            probe.observe(coords, lease)


def test_legacy_request_cannot_demand_worker_or_supply_new_install_receipt(tmp_path):
    path = tmp_path / "boca.sqlite3"
    legacy, _ = _request_with_real_ledger(path, "bot", "start")
    fp = "a" * 64
    assert demand._status_wire(path, fp) == "NONE"
    with pytest.raises(demand.OnDemandUnavailable):
        demand._transact(path, legacy.request_id, fp, "claim")
    with demand.lifecycle._controller_ledger(path) as connection, connection:
        connection.execute(
            "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
            demand.host_marker(legacy.request_id, "bot", "start", "CLAIMED"),
        )
    with pytest.raises(demand.OnDemandUnavailable):
        demand._status_wire(path, fp)


def test_delayed_wakeup_cannot_claim_start_already_superseded_by_stop(setup_demand):
    start, ledger, io, apply = setup_demand
    stop = str(uuid4())
    ledger.request("bot", "stop", stop, on_demand=True)
    with pytest.raises(demand.OnDemandUnavailable):
        apply(start)
    with demand.lifecycle._controller_ledger(io.path / "boca.sqlite3", readonly=True) as sql:
        assert demand.LifecycleIntentStore.for_operation(sql, start).status == "REQUESTED"
    assert apply(stop).status == "APPLIED"
    assert io.events == []
