"""Code-only lifecycle observation: Docker/SQLite fakes, no host writes."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from boca_socios import host_lifecycle_observe as observer
from boca_socios import host_lifecycle_rootless_adapter as adapter
from boca_socios.host_boca_cleanup import BocaJobLease
from boca_socios.panel import lifecycle_intents as panel
from test_host_lifecycle_rootless_adapter import (
    CONFIG_CONTROLLER,
    CONFIG_WORKER,
    CONTROLLER,
    CONTROLLER_REF,
    SOURCE,
    WORKER,
    WORKER_REF,
    FakeIO,
    _request_with_real_ledger,
)

RELEASE = observer.ReviewedObserveRelease(
    source_sha=SOURCE,
    controller_image=CONTROLLER_REF,
    worker_image=WORKER_REF,
    release_run_id="1000001",
    observe_run_id="1000002",
)


@pytest.fixture(autouse=True)
def no_host_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    def held(lease: BocaJobLease, attempt: str) -> None:
        assert lease.attempt_id == attempt == RELEASE.observe_run_id

    monkeypatch.setattr(observer, "verify_protected_boca_job_lease", held)
    monkeypatch.setattr(adapter, "verify_protected_boca_job_lease", held)
    monkeypatch.setattr(adapter.lifecycle, "verify_protected_boca_job_lease", held)


def _lease() -> BocaJobLease:
    return BocaJobLease(RELEASE.observe_run_id, 12, 1, True)


def _encoded(**overrides: str) -> str:
    body = {
        "version": "boca-lifecycle-observe-v1",
        "source_sha": SOURCE,
        "controller_image": CONTROLLER_REF,
        "worker_image": WORKER_REF,
        "release_run_id": RELEASE.release_run_id,
        "observe_run_id": RELEASE.observe_run_id,
    }
    body.update(overrides)
    return (
        base64.urlsafe_b64encode(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("ascii")
        )
        .decode("ascii")
        .rstrip("=")
    )


@pytest.mark.parametrize(
    ("component", "target", "engine", "worker_running"),
    [
        ("bot", "start", False, True),
        ("bot", "stop", True, True),
        ("chromium", "start", False, False),
        ("chromium", "stop", False, True),
    ],
)
def test_observe_four_owner_scopes_without_mutation_or_manual_pins(
    tmp_path: Path, component: str, target: str, engine: bool, worker_running: bool
) -> None:
    coords, ledger = _request_with_real_ledger(tmp_path / "boca.sqlite3", component, target)
    assert ledger.current().operation_id == coords.request_id
    database = tmp_path / "boca.sqlite3"
    before_hash = hashlib.sha256(database.read_bytes()).hexdigest()
    before_stat = database.stat()
    io = FakeIO(tmp_path, engine=engine, worker_running=worker_running)
    public = observer.observe_pending_lifecycle(RELEASE, lease=_lease(), io=io)
    assert public == {
        "version": "boca-protected-action-v1",
        "kind": "lifecycle",
        "source_sha": SOURCE,
        "controller_id": CONTROLLER,
        "controller_image": CONTROLLER_REF,
        "worker_id": WORKER,
        "worker_image": WORKER_REF,
        "browser_attempt": "12345678",
        "controller_config_hash": CONFIG_CONTROLLER,
        "worker_config_hash": CONFIG_WORKER,
        "data_mountpoint": str(tmp_path),
        "expected_component": component,
        "expected_target": target,
        "expected_request_id": coords.request_id,
    }
    assert io.effects == []
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before_hash
    assert database.stat().st_size == before_stat.st_size
    assert ledger.current().status == "REQUESTED"
    assert "attempt_id" not in public and "prepare_run_id" not in public
    assert "token" not in public and "password" not in public


@pytest.mark.parametrize("sender_running", [True, False])
def test_observe_sender_optional_exact_binding_with_no_sender_effects(
    tmp_path: Path, sender_running: bool
) -> None:
    _request_with_real_ledger(tmp_path / "boca.sqlite3")
    io = FakeIO(tmp_path, sender_running=sender_running)
    public = observer.observe_pending_lifecycle(RELEASE, lease=_lease(), io=io)
    assert public["sender_id"] == "8" * 64
    assert public["sender_config_hash"] == "9" * 64
    assert public["sender_attempt_id"] == "777777"
    assert public["sender_state"] == ("on" if sender_running else "off")
    assert io.effects == []


def test_unhealthy_chromium_stop_can_still_be_observed_without_starting(
    tmp_path: Path,
) -> None:
    _request_with_real_ledger(tmp_path / "boca.sqlite3", "chromium", "stop")
    io = FakeIO(tmp_path, engine=False, worker_running=True)
    io.fields[("container", WORKER, "State.Health.Status")] = "unhealthy"
    public = observer.observe_pending_lifecycle(RELEASE, lease=_lease(), io=io)
    assert public["expected_component"] == "chromium"
    assert public["expected_target"] == "stop"
    assert io.effects == []


def test_unhealthy_chromium_start_does_not_receive_prepared_context(tmp_path: Path) -> None:
    _, ledger = _request_with_real_ledger(tmp_path / "boca.sqlite3", "chromium", "start")
    io = FakeIO(tmp_path, engine=False, worker_running=True)
    io.fields[("container", WORKER, "State.Health.Status")] = "unhealthy"
    with pytest.raises(observer.LifecycleObservationNoGo):
        observer.observe_pending_lifecycle(RELEASE, lease=_lease(), io=io)
    assert io.effects == [] and ledger.current().status == "REQUESTED"


@pytest.mark.parametrize("unsafe", ["source", "image", "foreign", "config", "controller_health"])
def test_wrong_rootless_host_or_release_fails_without_effect(tmp_path: Path, unsafe: str) -> None:
    _request_with_real_ledger(tmp_path / "boca.sqlite3")
    io = FakeIO(tmp_path)
    release = RELEASE
    if unsafe == "source":
        release = replace(release, source_sha="f" * 40)
    elif unsafe == "image":
        release = replace(
            release,
            worker_image="ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "0" * 64,
        )
    elif unsafe == "foreign":
        io.inventory_value = replace(
            io.inventory_value,
            containers=io.inventory_value.containers + (io.inventory_value.containers[0],),
        )
    elif unsafe == "config":
        first = io.inventory_value.containers[0]
        io.inventory_value = replace(
            io.inventory_value,
            containers=(
                replace(
                    first,
                    labels=tuple(
                        (key, "bad-config" if key == "com.docker.compose.config-hash" else value)
                        for key, value in first.labels
                    ),
                ),
                io.inventory_value.containers[1],
            ),
        )
    else:
        io.fields[("container", CONTROLLER, "State.Health.Status")] = "unhealthy"
    with pytest.raises(observer.LifecycleObservationNoGo):
        observer.observe_pending_lifecycle(release, lease=_lease(), io=io)
    assert io.effects == []


def test_two_unresolved_intents_are_rejected_without_observation_token(
    tmp_path: Path,
) -> None:
    first, _ = _request_with_real_ledger(tmp_path / "boca.sqlite3")
    second_uuid = str(uuid4())
    second_action = panel._REQUEST_ACTIONS[("chromium", "stop")]  # noqa: SLF001
    with sqlite3.connect(tmp_path / "boca.sqlite3") as connection:
        connection.execute(
            "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
            (second_uuid, second_action),
        )
    io = FakeIO(tmp_path)
    with pytest.raises(observer.LifecycleObservationNoGo, match="more than one"):
        observer.observe_pending_lifecycle(RELEASE, lease=_lease(), io=io)
    assert first.request_id != second_uuid
    assert io.effects == []


def test_absent_or_completed_current_intent_never_observed(tmp_path: Path) -> None:
    _, ledger = _request_with_real_ledger(tmp_path / "boca.sqlite3")
    io = FakeIO(tmp_path)
    with sqlite3.connect(tmp_path / "boca.sqlite3") as connection:
        connection.execute("DELETE FROM audit_events")
    with pytest.raises(observer.LifecycleObservationNoGo, match="REQUESTED"):
        observer.observe_pending_lifecycle(RELEASE, lease=_lease(), io=io)
    assert ledger.current() is None and io.effects == []


def test_legacy_schema_0008_is_never_adopted_or_migrated(tmp_path: Path) -> None:
    _request_with_real_ledger(tmp_path / "boca.sqlite3")
    with sqlite3.connect(tmp_path / "boca.sqlite3") as connection:
        connection.execute("CREATE TABLE owner_browser_session(id TEXT)")
    io = FakeIO(tmp_path)
    with pytest.raises(observer.LifecycleObservationNoGo, match="schema"):
        observer.observe_pending_lifecycle(RELEASE, lease=_lease(), io=io)
    assert io.effects == []


def test_synthetic_docker_volume_outside_bound_database_cannot_be_created(
    tmp_path: Path,
) -> None:
    _request_with_real_ledger(tmp_path / "boca.sqlite3")
    io = FakeIO(tmp_path)
    foreign = tmp_path / "does-not-exist"
    io.fields[("volume", "boca-socios_boca_data", "Mountpoint")] = str(foreign)
    with pytest.raises(observer.LifecycleObservationNoGo):
        observer.observe_pending_lifecycle(RELEASE, lease=_lease(), io=io)
    assert not foreign.exists()
    assert io.effects == []


@pytest.mark.parametrize("invalid", ["0", "1000001", "bad", "-5", "111111111111111111111"])
def test_observer_rejects_invalid_or_same_run_lease_before_inventory(invalid: str) -> None:
    with pytest.raises(observer.LifecycleObservationNoGo):
        observer.decode_observe_input(_encoded(observe_run_id=invalid))


def test_observer_rejects_unknown_keys_padding_and_duplication() -> None:
    with pytest.raises(observer.LifecycleObservationNoGo):
        observer.decode_observe_input(_encoded(token="forbidden"))
    with pytest.raises(observer.LifecycleObservationNoGo):
        observer.decode_observe_input(_encoded() + "=")
    payload = json.loads(base64.urlsafe_b64decode(_encoded() + "=" * (-len(_encoded()) % 4)))
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).replace(
        '"version":', '"version":"duplicate", "version":'
    )
    with pytest.raises(observer.LifecycleObservationNoGo):
        observer.decode_observe_input(
            base64.urlsafe_b64encode(raw.encode("ascii")).decode().rstrip("=")
        )


def test_observer_cli_no_context_is_inert(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert observer.main([]) == 3
    output = capsys.readouterr()
    assert output.out == ""
    assert "NO_GO" in output.err


def test_observer_memfd_selftest_has_no_host_effect(capsys: pytest.CaptureFixture[str]) -> None:
    assert observer.selftest_main() == 0
    assert capsys.readouterr().out == (
        "BOCA_LIFECYCLE_OBSERVE_MEMFD state=PASS host=untouched blackbox=excluded\n"
    )
