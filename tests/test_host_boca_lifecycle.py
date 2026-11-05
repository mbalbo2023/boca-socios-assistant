"""Code-only Boca lifecycle host claim/ACK; no Docker, SSH or real browser."""

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from boca_socios import host_boca_lifecycle as host
from boca_socios.host_boca_cleanup import BocaJobLease, CleanupError
from boca_socios.panel.lifecycle_intents import LifecycleIntentStore
from boca_socios.storage.database import Database

RUN = "3456789012"
SOURCE = "a" * 40
CONTROLLER = "b" * 64
WORKER = "c" * 64
CONTROLLER_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64
WORKER_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "e" * 64
_UNBOUND_DATA_MOUNT = Path("test_unbound_data_mount")


class FakeBocaAttestor:
    """Fake snapshots are safe ONLY because these tests have no host adapter."""

    def __init__(self, snapshot: host.LifecycleHostSnapshot) -> None:
        self.snapshot = snapshot
        self.observations = 0

    def observe(
        self, coordinates: host.LifecycleHostCoordinates, lease: BocaJobLease
    ) -> host.LifecycleHostSnapshot:
        self.observations += 1
        if self.snapshot.controller_data_mountpoint == _UNBOUND_DATA_MOUNT:
            return replace(
                self.snapshot, controller_data_mountpoint=coordinates.database_path.parent
            )
        return self.snapshot


def _snapshot(
    *, engine: bool | None = False, worker: bool = False, database_parent: Path | None = None
) -> host.LifecycleHostSnapshot:
    return host.LifecycleHostSnapshot(
        controller_id=CONTROLLER,
        controller_project="boca-socios",
        controller_service="controller",
        controller_image=CONTROLLER_IMAGE,
        controller_sha=SOURCE,
        worker_id=WORKER,
        worker_project="boca-socios",
        worker_service="browser-worker",
        worker_image=WORKER_IMAGE,
        worker_sha=SOURCE,
        controller_running=True,
        controller_healthy=True,
        worker_running=worker,
        worker_healthy=worker,
        bot_engine_running=engine,
        worker_network_mode="none",
        published_controller_port="127.0.0.1:8443",
        rootless_uid=10001,
        controller_data_volume="boca-socios_boca_data",
        controller_data_mountpoint=database_parent or _UNBOUND_DATA_MOUNT,
        controller_data_volume_exclusive=True,
        single_boca_project_verified=True,
        rootless_boca_uid_verified=True,
    )


def _setup(
    path: Path, component: host.Component, target: host.Target
) -> tuple[host.LifecycleHostCoordinates, LifecycleIntentStore, BocaJobLease]:
    db = Database(path)
    db.migrate()
    panel = LifecycleIntentStore(db)
    request_id = str(uuid4())
    panel.request(component, target, request_id)
    coordinates = host.LifecycleHostCoordinates(
        attempt_id=RUN,
        request_id=request_id,
        component=component,
        target=target,
        source_sha=SOURCE,
        controller_id=CONTROLLER,
        controller_image=CONTROLLER_IMAGE,
        worker_id=WORKER,
        worker_image=WORKER_IMAGE,
        database_path=path,
    )
    return coordinates, panel, BocaJobLease(RUN, 42, 123, True)


@pytest.fixture(autouse=True)
def no_real_boca_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test a strict lease gate without touching /run/user/10001 or Docker."""

    def verify(lease: BocaJobLease, attempt: str) -> None:
        if not isinstance(lease, BocaJobLease) or not lease.active or lease.attempt_id != attempt:
            raise CleanupError("lease unavailable")

    monkeypatch.setattr(host, "verify_protected_boca_job_lease", verify)


@pytest.mark.parametrize("component", ["bot", "chromium"])
def test_protected_claim_then_ack_applied_is_durable_and_panel_visible(
    tmp_path: Path, component: host.Component
) -> None:
    coordinates, panel, lease = _setup(tmp_path / "boca.sqlite3", component, "start")
    fake = FakeBocaAttestor(_snapshot())
    claim = host.claim_requested(coordinates, lease=lease, probe=fake)
    assert claim.was_running is False
    assert panel.current().status == "CLAIMED"
    assert fake.observations == 1
    if component == "bot":
        fake.snapshot = _snapshot(engine=True)
    else:
        fake.snapshot = _snapshot(worker=True)
    host.acknowledge(claim, lease=lease, probe=fake, result="APPLIED", effect_attempted=True)
    assert panel.current().status == "APPLIED"
    assert fake.observations == 2
    with pytest.raises(host.LifecycleHostUnavailable):
        host.acknowledge(claim, lease=lease, probe=fake, result="APPLIED", effect_attempted=True)


def test_stop_chromium_preserves_running_private_panel(tmp_path: Path) -> None:
    coords, panel, lease = _setup(tmp_path / "boca.sqlite3", "chromium", "stop")
    fake = FakeBocaAttestor(_snapshot(engine=True, worker=True))
    claim = host.claim_requested(coords, lease=lease, probe=fake)
    fake.snapshot = _snapshot(engine=True, worker=False)
    host.acknowledge(claim, lease=lease, probe=fake, result="APPLIED", effect_attempted=True)
    assert panel.current().status == "APPLIED"
    assert fake.snapshot.controller_running and fake.snapshot.controller_healthy


def test_stop_bot_requires_motor_evidence_not_merely_pause_admission(tmp_path: Path) -> None:
    coords, panel, lease = _setup(tmp_path / "boca.sqlite3", "bot", "stop")
    fake = FakeBocaAttestor(_snapshot(engine=None, worker=True))
    with pytest.raises(host.LifecycleHostUnavailable, match="independent state witness"):
        host.claim_requested(coords, lease=lease, probe=fake)
    assert panel.current().status == "REQUESTED"


def test_refused_requires_proof_no_physical_effect(tmp_path: Path) -> None:
    coords, panel, lease = _setup(tmp_path / "boca.sqlite3", "chromium", "start")
    fake = FakeBocaAttestor(_snapshot())
    claim = host.claim_requested(coords, lease=lease, probe=fake)
    with pytest.raises(host.LifecycleHostUnavailable, match="no-effect"):
        host.acknowledge(claim, lease=lease, probe=fake, result="REFUSED", effect_attempted=True)
    assert panel.current().status == "CLAIMED"
    host.acknowledge(claim, lease=lease, probe=fake, result="REFUSED", effect_attempted=False)
    assert panel.current().status == "REFUSED"


def test_uncertain_after_claim_blocks_new_panel_request_but_can_be_resolved(
    tmp_path: Path,
) -> None:
    coords, panel, lease = _setup(tmp_path / "boca.sqlite3", "bot", "start")
    fake = FakeBocaAttestor(_snapshot())
    claim = host.claim_requested(coords, lease=lease, probe=fake)
    host.mark_uncertain(claim, lease=lease)
    assert panel.current().status == "UNCERTAIN"
    with pytest.raises(host.LifecycleHostUnavailable):
        host.mark_uncertain(claim, lease=lease)
    fake.snapshot = _snapshot(engine=True)
    host.acknowledge(claim, lease=lease, probe=fake, result="APPLIED", effect_attempted=True)
    assert panel.current().status == "APPLIED"


@pytest.mark.parametrize(
    "unsafe",
    [
        {"controller_id": "f" * 64},
        {"controller_project": "porota"},
        {"worker_service": "foreign-worker"},
        {"rootless_uid": 10002},
        {"controller_data_volume": "porota_data"},
        {"controller_data_volume_exclusive": False},
        {"controller_data_mountpoint": Path("/foreign-project")},
        {"worker_image": CONTROLLER_IMAGE},
        {"worker_sha": "0" * 40},
        {"worker_network_mode": "bridge"},
        {"published_controller_port": "0.0.0.0:8443"},
        {"single_boca_project_verified": False},
        {"rootless_boca_uid_verified": False},
        {"controller_running": False},
        {"controller_healthy": False},
        {"worker_healthy": True},
    ],
)
def test_mismatched_or_unisolated_boca_host_is_never_claimed(
    tmp_path: Path, unsafe: dict[str, object]
) -> None:
    coords, panel, lease = _setup(tmp_path / "boca.sqlite3", "chromium", "start")
    fake = FakeBocaAttestor(replace(_snapshot(), **unsafe))
    with pytest.raises(host.LifecycleHostUnavailable, match="witness invalid"):
        host.claim_requested(coords, lease=lease, probe=fake)
    assert panel.current().status == "REQUESTED"


def test_foreign_lease_and_request_and_db_identity_cannot_write(tmp_path: Path) -> None:
    coords, panel, lease = _setup(tmp_path / "boca.sqlite3", "bot", "start")
    fake = FakeBocaAttestor(_snapshot())
    with pytest.raises(CleanupError):
        host.claim_requested(coords, lease=replace(lease, attempt_id="9"), probe=fake)
    with pytest.raises(host.LifecycleHostUnavailable):
        host.claim_requested(replace(coords, request_id=str(uuid4())), lease=lease, probe=fake)
    assert panel.current().status == "REQUESTED"
    path = tmp_path / "boca.sqlite3"
    path.chmod(0o644)
    with pytest.raises(host.LifecycleHostUnavailable, match="identity"):
        host.claim_requested(coords, lease=lease, probe=fake)
    path.chmod(0o600)
    assert panel.current().status == "REQUESTED"


def test_missing_controller_db_is_not_created_by_host_contract(tmp_path: Path) -> None:
    path = tmp_path / "boca.sqlite3"
    coords = host.LifecycleHostCoordinates(
        RUN,
        str(uuid4()),
        "bot",
        "start",
        SOURCE,
        CONTROLLER,
        CONTROLLER_IMAGE,
        WORKER,
        WORKER_IMAGE,
        path,
    )
    with pytest.raises(host.LifecycleHostUnavailable):
        host.claim_requested(
            coords, lease=BocaJobLease(RUN, 42, 123, True), probe=FakeBocaAttestor(_snapshot())
        )
    assert not path.exists()


def test_unknown_legacy_owner_schema_0008_is_not_adopted(tmp_path: Path) -> None:
    coords, panel, lease = _setup(tmp_path / "boca.sqlite3", "bot", "start")
    with Database(coords.database_path).connection() as connection, connection:
        connection.execute(
            "INSERT INTO schema_migrations(version,checksum) VALUES(8,?)", ("z" * 64,)
        )
    with pytest.raises(host.LifecycleHostUnavailable, match="legacy lifecycle schema"):
        host.claim_requested(coords, lease=lease, probe=FakeBocaAttestor(_snapshot()))
    assert panel.current().status == "REQUESTED"


def test_untrusted_probe_exception_is_redacted_without_claim(tmp_path: Path) -> None:
    coords, panel, lease = _setup(tmp_path / "boca.sqlite3", "chromium", "start")

    class FailingProbe:
        def observe(
            self, coordinates: host.LifecycleHostCoordinates, held: BocaJobLease
        ) -> host.LifecycleHostSnapshot:
            raise RuntimeError("private-docker-environment-SECRET")

    with pytest.raises(
        host.LifecycleHostUnavailable, match="physical preflight unavailable"
    ) as error:
        host.claim_requested(coords, lease=lease, probe=FailingProbe())
    assert "SECRET" not in str(error.value)
    assert panel.current().status == "REQUESTED"


def test_failed_postflight_stays_claimed_until_explicit_uncertain(tmp_path: Path) -> None:
    coords, panel, lease = _setup(tmp_path / "boca.sqlite3", "bot", "start")
    fake = FakeBocaAttestor(_snapshot())
    claim = host.claim_requested(coords, lease=lease, probe=fake)
    fake.snapshot = _snapshot(engine=False)
    with pytest.raises(host.LifecycleHostUnavailable, match="applied effect unverified"):
        host.acknowledge(claim, lease=lease, probe=fake, result="APPLIED", effect_attempted=True)
    assert panel.current().status == "CLAIMED"
    host.mark_uncertain(claim, lease=lease)
    assert panel.current().status == "UNCERTAIN"


def test_code_only_host_module_has_no_process_or_network_effect_api() -> None:
    import inspect

    source = inspect.getsource(host)
    assert "subprocess" not in source
    assert "socket" not in source
    assert "docker run" not in source
    assert "docker stop" not in source
    assert "ipc_worker" not in source
    assert "browser.synthetic" not in source
