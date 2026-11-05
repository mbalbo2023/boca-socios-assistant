"""No host/SSH/Chrome/BLACKBOX; test the protected lifecycle dispatch bridge."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from boca_socios import host_lifecycle_actions as actions
from boca_socios.host_boca_cleanup import BocaJobLease
from boca_socios.host_boca_lifecycle import LifecycleHostCoordinates
from boca_socios.host_lifecycle_rootless_adapter import ReviewedInstalledPair
from boca_socios.panel.lifecycle_intents import LifecycleIntent

SOURCE = "a" * 40
CONTROLLER = "b" * 64
WORKER = "c" * 64
CONTROLLER_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64
WORKER_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "e" * 64
REQUEST_ID = "00000000-0000-4000-8000-000000000002"


def _reviewed(path: Path) -> actions.ReviewedLifecycleInstallation:
    return actions.ReviewedLifecycleInstallation(
        attempt_id="3456789012",
        prepare_run_id="41999999999",
        source_sha=SOURCE,
        controller_id=CONTROLLER,
        controller_image=CONTROLLER_IMAGE,
        worker_id=WORKER,
        worker_image=WORKER_IMAGE,
        database_path=path / "boca.sqlite3",
        pair=ReviewedInstalledPair("12345", "f" * 64, "1" * 64),
        expected_request_id=REQUEST_ID,
    )


class FakeLedger:
    """A deterministic stand-in, with no SQLite creation or host operations."""

    def __init__(self, state: LifecycleIntent | None):
        self.state = state

    def current(self) -> LifecycleIntent | None:
        return self.state


def _requested(
    component: str = "bot", target: str = "start", operation_id: str = REQUEST_ID
) -> LifecycleIntent:
    return LifecycleIntent(
        operation_id=operation_id,
        component=component,  # type: ignore[arg-type]
        target=target,  # type: ignore[arg-type]
        status="REQUESTED",
        requested_at="2026-11-05 11:00:00",
    )


@pytest.fixture
def verified_io(monkeypatch: pytest.MonkeyPatch) -> tuple[FakeLedger, list[object]]:
    ledger = FakeLedger(_requested())
    effects: list[object] = []
    monkeypatch.setattr(actions, "_read_current", lambda path: ledger.current())
    monkeypatch.setattr(
        actions.adapter.RootlessLifecycleProbe, "observe", lambda self, coordinates, lease: None
    )
    monkeypatch.setattr(actions, "verify_protected_boca_job_lease", lambda lease, attempt: None)

    def execute(coordinates: object, *, binding: object, lease: object, io: object) -> str:
        effects.append(coordinates)
        assert isinstance(coordinates, LifecycleHostCoordinates)
        assert ledger.state is not None
        assert coordinates.request_id == ledger.state.operation_id
        assert isinstance(binding, ReviewedInstalledPair)
        assert isinstance(lease, BocaJobLease)
        assert isinstance(io, actions.adapter.ProductionRootlessDockerIO)
        ledger.state = replace(ledger.state, status="APPLIED")
        return "APPLIED"

    monkeypatch.setattr(actions.adapter, "execute_requested_lifecycle", execute)
    return ledger, effects


def test_one_pending_request_yields_one_verified_redacted_ack(
    tmp_path: Path, verified_io: tuple[FakeLedger, list[object]]
) -> None:
    ledger, effects = verified_io
    lease = BocaJobLease("3456789012", 12, 1, True)
    receipt = actions.apply_latest_owner_request(_reviewed(tmp_path), lease=lease)
    assert receipt.applied and receipt.status == "APPLIED"
    assert receipt.request_id == ledger.state.operation_id
    assert len(effects) == 1
    data = json.loads(receipt.redacted_json())
    assert data["physical_ack"] is True
    assert data["scope"] == "boca-lifecycle"
    assert data["prepare_run_id"] == "41999999999"
    assert data["source_sha"] == SOURCE
    assert "image" not in data and "token" not in data and "password" not in data


@pytest.mark.parametrize(
    ("component", "target"),
    [
        ("bot", "start"),
        ("bot", "stop"),
        ("chromium", "start"),
        ("chromium", "stop"),
    ],
)
def test_exact_action_pins_permit_each_of_four_requested_actions(
    tmp_path: Path,
    verified_io: tuple[FakeLedger, list[object]],
    component: str,
    target: str,
) -> None:
    ledger, effects = verified_io
    ledger.state = _requested(component, target)
    reviewed = replace(_reviewed(tmp_path), expected_component=component, expected_target=target)
    receipt = actions.apply_latest_owner_request(
        reviewed, lease=BocaJobLease("3456789012", 12, 1, True)
    )
    assert receipt.applied and receipt.component == component and receipt.target == target
    assert len(effects) == 1
    coordinates = effects[0]
    assert isinstance(coordinates, LifecycleHostCoordinates)
    assert (coordinates.component, coordinates.target) == (component, target)


@pytest.mark.parametrize("state", [None, "APPLIED", "CLAIMED", "UNCERTAIN", "REFUSED"])
def test_no_fresh_requested_fails_before_adapter_effect(
    tmp_path: Path,
    verified_io: tuple[FakeLedger, list[object]],
    state: str | None,
) -> None:
    ledger, effects = verified_io
    ledger.state = replace(_requested(), status=state) if state else None  # type: ignore[arg-type]
    with pytest.raises(actions.PhysicalAckUnavailable, match="REQUESTED"):
        actions.apply_latest_owner_request(
            _reviewed(tmp_path), lease=BocaJobLease("3456789012", 12, 1, True)
        )
    assert effects == []


def test_wrong_action_pin_refused_before_effect(
    tmp_path: Path, verified_io: tuple[FakeLedger, list[object]]
) -> None:
    _, effects = verified_io
    reviewed = replace(_reviewed(tmp_path), expected_component="chromium", expected_target="stop")
    with pytest.raises(actions.PhysicalAckUnavailable, match="scope"):
        actions.apply_latest_owner_request(reviewed, lease=BocaJobLease("3456789012", 12, 1, True))
    assert effects == []


@pytest.mark.parametrize("wrong", ["source", "image", "pair", "scope"])
def test_invalid_reviewed_coordinates_cannot_reach_effect(
    tmp_path: Path,
    verified_io: tuple[FakeLedger, list[object]],
    wrong: str,
) -> None:
    _, effects = verified_io
    installed = _reviewed(tmp_path)
    if wrong == "source":
        installed = replace(installed, source_sha="unreviewed")
    elif wrong == "image":
        installed = replace(installed, controller_image="porota")
    elif wrong == "pair":
        installed = replace(installed, pair=ReviewedInstalledPair("", "f" * 64, "1" * 64))
    else:
        installed = replace(installed, expected_component="bot")
    with pytest.raises((actions.PhysicalAckUnavailable, actions.adapter.LifecycleAdapterNoGo)):
        actions.apply_latest_owner_request(installed, lease=BocaJobLease("3456789012", 12, 1, True))
    assert effects == []


def test_refused_is_terminal_but_never_physical_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verified_io: tuple[FakeLedger, list[object]],
) -> None:
    ledger, _ = verified_io

    def refused(*args: object, **kwargs: object) -> str:
        ledger.state = replace(ledger.state, status="REFUSED")
        return "REFUSED"

    monkeypatch.setattr(actions.adapter, "execute_requested_lifecycle", refused)
    receipt = actions.apply_latest_owner_request(
        _reviewed(tmp_path), lease=BocaJobLease("3456789012", 12, 1, True)
    )
    assert receipt.status == "REFUSED"
    assert receipt.applied is False
    assert json.loads(receipt.redacted_json())["physical_ack"] is False


def test_return_without_matching_legacy_ack_is_no_go(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verified_io: tuple[FakeLedger, list[object]],
) -> None:
    _, effects = verified_io

    def missing(*args: object, **kwargs: object) -> str:
        effects.append("attempted")
        return "APPLIED"

    monkeypatch.setattr(actions.adapter, "execute_requested_lifecycle", missing)
    with pytest.raises(actions.PhysicalAckUnavailable, match="terminal ACK"):
        actions.apply_latest_owner_request(
            _reviewed(tmp_path), lease=BocaJobLease("3456789012", 12, 1, True)
        )
    assert effects == ["attempted"]


def test_effect_uncertain_does_not_retry_or_forge_ack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verified_io: tuple[FakeLedger, list[object]],
) -> None:
    _, effects = verified_io

    def uncertain(*args: object, **kwargs: object) -> str:
        effects.append("attempted")
        raise actions.adapter.LifecycleEffectUncertain("sensitive host text")

    monkeypatch.setattr(actions.adapter, "execute_requested_lifecycle", uncertain)
    with pytest.raises(actions.PhysicalAckUnavailable, match="uncertain") as exc:
        actions.apply_latest_owner_request(
            _reviewed(tmp_path), lease=BocaJobLease("3456789012", 12, 1, True)
        )
    assert "sensitive" not in str(exc.value)
    assert effects == ["attempted"]


def test_reused_prepare_run_rejected_even_with_later_requested_intent(
    tmp_path: Path,
    verified_io: tuple[FakeLedger, list[object]],
) -> None:
    ledger, effects = verified_io
    installed = _reviewed(tmp_path)
    lease = BocaJobLease("3456789012", 12, 1, True)
    first = actions.apply_latest_owner_request(installed, lease=lease)
    assert first.applied and len(effects) == 1
    marker = tmp_path / ".boca-lifecycle-go" / "prepare-41999999999.used"
    assert marker.is_file()
    assert marker.parent.stat().st_mode & 0o777 == 0o700
    stored = json.loads(marker.read_text(encoding="ascii"))
    assert stored["prepare_run_id"] == installed.prepare_run_id
    assert stored["request_id"] == first.request_id
    assert marker.stat().st_mode & 0o777 == 0o600

    ledger.state = _requested("bot", "stop")
    with pytest.raises(actions.PhysicalAckUnavailable, match="already consumed"):
        actions.apply_latest_owner_request(installed, lease=lease)
    assert len(effects) == 1
    assert ledger.current().status == "REQUESTED"


def test_crash_after_prepare_consumption_never_replays_physical_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verified_io: tuple[FakeLedger, list[object]],
) -> None:
    ledger, effects = verified_io
    lease = BocaJobLease("3456789012", 12, 1, True)

    def crash(*args: object, **kwargs: object) -> str:
        effects.append("may-have-executed")
        raise RuntimeError("crash after durable marker")

    monkeypatch.setattr(actions.adapter, "execute_requested_lifecycle", crash)
    with pytest.raises(RuntimeError, match="crash after durable marker"):
        actions.apply_latest_owner_request(_reviewed(tmp_path), lease=lease)
    marker = tmp_path / ".boca-lifecycle-go" / "prepare-41999999999.used"
    assert marker.is_file()
    assert ledger.current().status == "REQUESTED"
    with pytest.raises(actions.PhysicalAckUnavailable, match="already consumed"):
        actions.apply_latest_owner_request(_reviewed(tmp_path), lease=lease)
    assert effects == ["may-have-executed"]


def test_no_pending_or_invalid_approved_run_creates_no_marker(
    tmp_path: Path,
    verified_io: tuple[FakeLedger, list[object]],
) -> None:
    ledger, effects = verified_io
    ledger.state = None
    with pytest.raises(actions.PhysicalAckUnavailable, match="REQUESTED"):
        actions.apply_latest_owner_request(
            _reviewed(tmp_path), lease=BocaJobLease("3456789012", 12, 1, True)
        )
    assert list(tmp_path.iterdir()) == []
    ledger.state = _requested()
    with pytest.raises(actions.PhysicalAckUnavailable, match="PREPARE run ID"):
        actions.apply_latest_owner_request(
            replace(_reviewed(tmp_path), prepare_run_id="0"),
            lease=BocaJobLease("3456789012", 12, 1, True),
        )
    assert effects == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("unsafe_directory", ["world_readable", "symlink"])
def test_private_prepare_marker_custody_fail_closed_without_foreign_write(
    tmp_path: Path,
    verified_io: tuple[FakeLedger, list[object]],
    unsafe_directory: str,
) -> None:
    _, effects = verified_io
    private_dir = tmp_path / ".boca-lifecycle-go"
    if unsafe_directory == "world_readable":
        private_dir.mkdir(mode=0o755)
    else:
        foreign = tmp_path / "foreign"
        foreign.mkdir()
        private_dir.symlink_to(foreign, target_is_directory=True)
    with pytest.raises(actions.PhysicalAckUnavailable):
        actions.apply_latest_owner_request(
            _reviewed(tmp_path), lease=BocaJobLease("3456789012", 12, 1, True)
        )
    assert effects == []
    assert not (tmp_path / ".boca-lifecycle-go" / "prepare-41999999999.used").exists()


def test_component_stop_passes_through_without_worker_requirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verified_io: tuple[FakeLedger, list[object]]
) -> None:
    ledger, effects = verified_io
    ledger.state = _requested("bot", "stop")
    receipt = actions.apply_latest_owner_request(
        _reviewed(tmp_path), lease=BocaJobLease("3456789012", 12, 1, True)
    )
    assert receipt.component == "bot" and receipt.target == "stop"
    assert len(effects) == 1


def test_no_implicit_migration_or_database_creation(
    tmp_path: Path, verified_io: tuple[FakeLedger, list[object]]
) -> None:
    reviewed = _reviewed(tmp_path)
    actions.apply_latest_owner_request(reviewed, lease=BocaJobLease("3456789012", 12, 1, True))
    assert not reviewed.database_path.exists()


def _context(**overrides: str) -> str:
    import base64

    obj = {
        "version": "boca-protected-action-v1",
        "kind": "lifecycle",
        "attempt_id": "3456789012",
        "prepare_run_id": "41999999999",
        "source_sha": SOURCE,
        "controller_id": CONTROLLER,
        "controller_image": CONTROLLER_IMAGE,
        "worker_id": WORKER,
        "worker_image": WORKER_IMAGE,
        "browser_attempt": "12345",
        "controller_config_hash": "f" * 64,
        "worker_config_hash": "1" * 64,
        "data_mountpoint": "/run/user/10001/docker/volumes/boca-socios_boca_data/_data",
        "expected_component": "bot",
        "expected_target": "stop",
        "expected_request_id": REQUEST_ID,
    }
    obj.update(overrides)
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_rotated_same_action_new_uuid_is_no_go_before_prepare_marker_or_effect(
    tmp_path: Path, verified_io: tuple[FakeLedger, list[object]]
) -> None:
    """The GO reviewed request A cannot authorize a newer request B of same scope."""
    ledger, effects = verified_io
    initial = ledger.current()
    assert initial is not None and initial.operation_id == REQUEST_ID
    successor_id = str(uuid4())
    assert successor_id != initial.operation_id
    ledger.state = _requested("bot", "start", operation_id=successor_id)
    marker = tmp_path / ".boca-lifecycle-go" / "prepare-41999999999.used"
    with pytest.raises(actions.PhysicalAckUnavailable, match="request ID"):
        actions.apply_latest_owner_request(
            _reviewed(tmp_path), lease=BocaJobLease("3456789012", 12, 1, True)
        )
    assert effects == []
    assert ledger.current() == ledger.state and ledger.current().status == "REQUESTED"
    assert not marker.exists()
    assert not marker.parent.exists()


@pytest.mark.parametrize(
    "invalid",
    [
        "",
        "not-a-uuid",
        "00000000-0000-0000-0000-000000000000",
        "00000000-0000-4000-8000-00000000000A",
    ],
)
def test_expected_request_id_requires_exact_nonzero_canonical_uuid(invalid: str) -> None:
    with pytest.raises(actions.PhysicalAckUnavailable):
        actions.decode_lifecycle_context(_context(expected_request_id=invalid))


def test_unpinned_direct_installation_refuses_before_creating_marker(
    tmp_path: Path, verified_io: tuple[FakeLedger, list[object]]
) -> None:
    _, effects = verified_io
    installed = replace(_reviewed(tmp_path), expected_request_id="")
    with pytest.raises(actions.PhysicalAckUnavailable, match="scope"):
        actions.apply_latest_owner_request(installed, lease=BocaJobLease("3456789012", 12, 1, True))
    assert effects == [] and not list(tmp_path.iterdir())


def test_public_context_decodes_canonical_exact_pins() -> None:
    decoded = actions.decode_lifecycle_context(_context())
    assert decoded.attempt_id == "3456789012"
    assert decoded.expected_component == "bot"
    assert decoded.expected_target == "stop"
    assert decoded.expected_request_id == REQUEST_ID
    assert decoded.database_path.name == "boca.sqlite3"


@pytest.mark.parametrize("extra", ["unknown", "token", "password"])
def test_unknown_context_keys_rejected(extra: str) -> None:
    with pytest.raises(actions.PhysicalAckUnavailable):
        actions.decode_lifecycle_context(_context(**{extra: "never accepted"}))


@pytest.mark.parametrize("invalid", ["", "0", "-1", "000012", "1" * 21, "123abc"])
def test_prepare_run_id_requires_single_positive_immutable_run(invalid: str) -> None:
    with pytest.raises(actions.PhysicalAckUnavailable):
        actions.decode_lifecycle_context(_context(prepare_run_id=invalid))


def test_wrong_context_sha_rejected() -> None:
    with pytest.raises(actions.PhysicalAckUnavailable):
        actions.decode_lifecycle_context(_context(source_sha="0"))


def test_canonical_context_cannot_have_padding_or_oversize() -> None:
    with pytest.raises(actions.PhysicalAckUnavailable):
        actions.decode_lifecycle_context(_context() + "=")
    with pytest.raises(actions.PhysicalAckUnavailable):
        actions.decode_lifecycle_context("A" * 2751)


def test_cli_missing_context_has_no_effect(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert actions.main([]) == 3
    assert json.loads(capsys.readouterr().out)["status"] == "NO_GO"


def test_zip_import_selftest_has_no_host_effect(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert actions.selftest_main() == 0
    assert capsys.readouterr().out == (
        "BOCA_LIFECYCLE_MEMFD state=PASS host=untouched blackbox=excluded\n"
    )
