"""R83 RED: independent primary and cleanup diagnosis with no host/BLACKBOX effects."""

from __future__ import annotations

import sys
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from scripts import host_cutover_worker_preflight as preflight  # noqa: E402 - src layout

CID = "f" * 64
SOURCE = "a" * 40
BROWSER = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "b" * 64
LEGACY = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "c" * 64


def _pins() -> preflight.Coordinates:
    return preflight.Coordinates(
        attempt="42341290485",
        source=SOURCE,
        controller="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64,
        browser=BROWSER,
        legacy_source="c" * 40,
        legacy_image=LEGACY,
        legacy_id="d" * 64,
    )


class Scenario:
    """Real preflight state machine, only external OS/Docker boundaries faked."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        primary: str = "NONE",
        cleanup_stage: str = "NONE",
        fail_initial_legacy: bool = False,
        fail_legacy_postflight: bool = False,
    ) -> None:
        self.primary = primary
        self.cleanup_stage = cleanup_stage
        self.fail_initial_legacy = fail_initial_legacy
        self.fail_legacy_postflight = fail_legacy_postflight
        self.events: list[str] = []
        self.created = False
        self.running = False
        self.removed = False
        self.in_cleanup = False
        self.legacy_reads = 0
        cleanup_exact = preflight._cleanup_exact

        def attest(*_args: Any, **_kwargs: Any) -> None:
            self.events.append("legacy")
            self.legacy_reads += 1
            if self.fail_initial_legacy and self.legacy_reads == 1:
                raise preflight.host.PreflightError("injected initial legacy attestation failure")
            if self.fail_legacy_postflight and self.legacy_reads == 2:
                raise preflight.host.PreflightError("injected legacy postflight failure")

        def pull(_pins: preflight.Coordinates) -> None:
            self.events.append("pull")
            if self.primary == "GHCR_PULL":
                raise preflight.WorkerPreflightError("injected initial GHCR error")

        def named(_name: str) -> str | None:
            self.events.append("named")
            if self.in_cleanup and self.cleanup_stage == "PS":
                raise preflight.host.PreflightError("injected Docker ps failure")
            if self.in_cleanup and self.cleanup_stage == "POST_ID" and self.removed:
                return CID
            return CID if self.created and not self.removed else None

        def inspect(_cid: str) -> dict[str, Any]:
            assert _cid == CID
            self.events.append("inspect")
            if self.in_cleanup and self.cleanup_stage == "INSPECT":
                raise preflight.host.PreflightError("injected Docker inspect failure")
            return {
                "Id": CID,
                "Name": f"/{preflight.PREFIX}{_pins().attempt}",
                "Config": {
                    "Image": BROWSER,
                    "Labels": {
                        preflight.LABEL: _pins().attempt,
                        "com.docker.compose.project": (
                            "foreign"
                            if self.cleanup_stage == "OWNERSHIP"
                            else preflight.host.PROJECT
                        ),
                    },
                },
                "State": {"Running": self.running},
            }

        def run(*argv: str, **_kwargs: Any) -> str:
            assert argv[0] == "docker"
            command = argv[1]
            self.events.append(command)
            if command == "create":
                self.created = True
                if self.primary == "WORKER_CREATE":
                    raise preflight.host.PreflightError("injected ambiguous create ACK")
                return CID
            if command == "start":
                self.running = True
                return CID
            if command == "exec":
                return (
                    "NOT_VERIFIED"
                    if self.primary == "WORKER_BOUNDARY"
                    else "BOCA_CUTOVER_WORKER_BOUNDARY_PASS"
                )
            if command == "stop":
                if self.cleanup_stage == "STOP":
                    raise preflight.host.PreflightError("injected Docker stop error")
                self.running = False
                return CID
            if command == "rm":
                if self.cleanup_stage == "RM":
                    raise preflight.host.PreflightError("injected Docker rm error")
                self.removed = True
                return CID
            raise AssertionError(argv)

        def cleanup(pins: preflight.Coordinates, name: str) -> None:
            self.in_cleanup = True
            return cleanup_exact(pins, name)

        monkeypatch.setattr(preflight, "protected_boca_job_lease", lambda _attempt: nullcontext())
        monkeypatch.setattr(preflight.host, "_cutover_legacy_record", attest)
        monkeypatch.setattr(preflight, "_require_clean_namespace", lambda _name: None)
        monkeypatch.setattr(preflight.host, "_browser_engine_version", lambda: "28.0.1")
        monkeypatch.setattr(preflight.host, "_storage_snapshot", lambda: object())
        monkeypatch.setattr(preflight.host, "_browser_pull_both", lambda *_args: pull(_pins()))
        monkeypatch.setattr(
            preflight,
            "_temporary_seccomp",
            lambda _attempt, _profile: nullcontext(Path("/run/user/10001/mock-seccomp.json")),
        )
        monkeypatch.setattr(preflight, "_named_id", named)
        monkeypatch.setattr(preflight.host, "_browser_inspect_record", inspect)
        monkeypatch.setattr(preflight.host, "_run", run)
        monkeypatch.setattr(preflight, "_inspect_probe", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(preflight, "_cleanup_exact", cleanup)


def _failure() -> preflight.PreflightFailure:
    with pytest.raises(preflight.PreflightFailure) as raised:
        preflight.execute(_pins(), b"{}")
    return raised.value


def test_ghcr_primary_failure_survives_cleanup_ps_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Scenario(monkeypatch, primary="GHCR_PULL", cleanup_stage="PS")
    failure = _failure()
    assert failure.phase == "CLEANUP"
    assert failure.cleanup == "INDETERMINATE"
    assert failure.primary_failed_phase == "GHCR_PULL"
    assert failure.cleanup_failed_stage == "PS"
    assert rig.legacy_reads == 2
    assert "rm" not in rig.events and "stop" not in rig.events


def test_worker_create_error_survives_cleanup_rm_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Scenario(monkeypatch, primary="WORKER_CREATE", cleanup_stage="RM")
    failure = _failure()
    assert failure.phase == "CLEANUP"
    assert failure.cleanup == "INDETERMINATE"
    assert failure.primary_failed_phase == "WORKER_CREATE"
    assert failure.cleanup_failed_stage == "RM"
    assert rig.events.count("rm") == 1


def test_boundary_failure_with_verified_cleanup_stays_no_go(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Scenario(monkeypatch, primary="WORKER_BOUNDARY")
    failure = _failure()
    assert failure.phase == "WORKER_BOUNDARY"
    assert failure.cleanup == "VERIFIED"
    assert failure.primary_failed_phase == "WORKER_BOUNDARY"
    assert failure.cleanup_failed_stage == "NONE"
    assert rig.removed is True
    assert rig.legacy_reads == 2


def test_legacy_postflight_failure_is_not_misattributed_to_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Scenario(monkeypatch, fail_legacy_postflight=True)
    failure = _failure()
    assert failure.phase == "CLEANUP"
    assert failure.cleanup == "INDETERMINATE"
    assert failure.primary_failed_phase == "NONE"
    assert failure.cleanup_failed_stage == "LEGACY"
    assert rig.removed is True
    assert rig.legacy_reads == 2


def test_initial_legacy_validation_failure_is_primary_attest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Scenario(monkeypatch, fail_initial_legacy=True)
    failure = _failure()
    assert failure.phase == "ATTEST"
    assert failure.cleanup == "VERIFIED"
    assert failure.primary_failed_phase == "ATTEST"
    assert failure.cleanup_failed_stage == "NONE"
    assert rig.legacy_reads == 2
    assert "rm" not in rig.events


@pytest.mark.parametrize("stage", ["PS", "INSPECT", "OWNERSHIP", "STOP", "RM", "POST_ID"])
def test_each_cleanup_stage_is_diagnosed_independently(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    rig = Scenario(monkeypatch, cleanup_stage=stage)
    failure = _failure()
    assert failure.phase == "CLEANUP"
    assert failure.cleanup == "INDETERMINATE"
    assert failure.primary_failed_phase == "NONE"
    assert failure.cleanup_failed_stage == stage
    assert rig.legacy_reads == 2
    if stage in {"PS", "INSPECT", "OWNERSHIP", "STOP"}:
        assert "rm" not in rig.events
    else:
        assert rig.events.count("rm") == 1


def test_earliest_cleanup_stage_survives_subsequent_legacy_postflight_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Scenario(monkeypatch, cleanup_stage="STOP", fail_legacy_postflight=True)
    failure = _failure()
    assert failure.phase == "CLEANUP"
    assert failure.cleanup == "INDETERMINATE"
    assert failure.primary_failed_phase == "NONE"
    assert failure.cleanup_failed_stage == "STOP"
    assert rig.legacy_reads == 2
    assert "rm" not in rig.events


def test_boundary_and_stop_failure_keep_two_distinct_causal_phases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Scenario(monkeypatch, primary="WORKER_BOUNDARY", cleanup_stage="STOP")
    failure = _failure()
    assert failure.phase == "CLEANUP"
    assert failure.cleanup == "INDETERMINATE"
    assert failure.primary_failed_phase == "WORKER_BOUNDARY"
    assert failure.cleanup_failed_stage == "STOP"
    assert "rm" not in rig.events


def test_ghcr_primary_failure_survives_independent_late_legacy_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Scenario(monkeypatch, primary="GHCR_PULL", fail_legacy_postflight=True)
    failure = _failure()
    assert failure.phase == "CLEANUP"
    assert failure.cleanup == "INDETERMINATE"
    assert failure.primary_failed_phase == "GHCR_PULL"
    assert failure.cleanup_failed_stage == "LEGACY"
    assert rig.legacy_reads == 2


def test_temp_seccomp_failure_is_separate_from_probe_and_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Scenario(monkeypatch)

    @contextmanager
    def failed_temp(_attempt: str, _profile: bytes):
        raise preflight.TempSeccompCleanupError("injected inode failure")
        yield Path("/run/user/10001/not-reached")

    monkeypatch.setattr(preflight, "_temporary_seccomp", failed_temp)
    failure = _failure()
    assert failure.phase == "CLEANUP"
    assert failure.cleanup == "INDETERMINATE"
    assert failure.primary_failed_phase == "SECCOMP_ENTER"
    assert failure.cleanup_failed_stage == "TEMP_SECCOMP"
    assert "create" not in rig.events
    assert "stop" not in rig.events and "rm" not in rig.events


def test_seccomp_enter_worker_error_is_not_attributed_to_completed_pull(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Scenario(monkeypatch)

    @contextmanager
    def broken_enter(_attempt: str, _profile: bytes):
        raise preflight.WorkerPreflightError("injected seccomp setup error")
        yield Path("/run/user/10001/not-reached")

    monkeypatch.setattr(preflight, "_temporary_seccomp", broken_enter)
    failure = _failure()
    assert failure.phase == "SECCOMP_ENTER"
    assert failure.cleanup == "VERIFIED"
    assert failure.primary_failed_phase == "SECCOMP_ENTER"
    assert failure.cleanup_failed_stage == "NONE"
    assert rig.events.count("pull") == 1
    assert "create" not in rig.events
    assert "stop" not in rig.events and "rm" not in rig.events


def test_seccomp_exit_failure_after_success_does_not_invent_primary_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Scenario(monkeypatch)

    @contextmanager
    def broken_exit(_attempt: str, _profile: bytes):
        try:
            yield Path("/run/user/10001/mock-seccomp.json")
        finally:
            raise preflight.TempSeccompCleanupError("injected seccomp __exit__ failure")

    monkeypatch.setattr(preflight, "_temporary_seccomp", broken_exit)
    failure = _failure()
    assert failure.phase == "CLEANUP"
    assert failure.cleanup == "INDETERMINATE"
    assert failure.primary_failed_phase == "NONE"
    assert failure.cleanup_failed_stage == "TEMP_SECCOMP"
    assert rig.removed is True
    assert rig.legacy_reads == 2


def test_worker_primary_survives_simultaneous_temp_seccomp_exit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Scenario(monkeypatch, primary="WORKER_BOUNDARY")

    @contextmanager
    def broken_exit(_attempt: str, _profile: bytes):
        try:
            yield Path("/run/user/10001/mock-seccomp.json")
        finally:
            raise preflight.TempSeccompCleanupError("injected seccomp __exit__ failure")

    monkeypatch.setattr(preflight, "_temporary_seccomp", broken_exit)
    failure = _failure()
    assert failure.phase == "CLEANUP"
    assert failure.cleanup == "INDETERMINATE"
    assert failure.primary_failed_phase == "WORKER_BOUNDARY"
    assert failure.cleanup_failed_stage == "TEMP_SECCOMP"
    assert rig.removed is True
    assert rig.legacy_reads == 2


def test_host_no_go_receipt_has_only_bounded_categorical_primary_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    Scenario(monkeypatch, primary="GHCR_PULL", cleanup_stage="PS")
    monkeypatch.setattr(preflight, "_reviewed_seccomp", lambda: b"{}")
    coords = _pins()
    rc = preflight.main(
        [
            "host",
            coords.attempt,
            coords.source,
            coords.controller,
            coords.browser,
            coords.legacy_source,
            coords.legacy_image,
            coords.legacy_id,
        ]
    )
    captured = capsys.readouterr()
    assert rc == 3
    assert captured.err == ""
    assert captured.out == (
        "BOCA_CUTOVER_WORKER_PREFLIGHT state=NO_GO failed_phase=CLEANUP "
        "cleanup=INDETERMINATE primary_failed_phase=GHCR_PULL cleanup_failed_stage=PS\n"
    )
    assert "injected" not in captured.out
