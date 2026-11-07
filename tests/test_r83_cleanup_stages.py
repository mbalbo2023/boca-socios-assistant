"""R83 TDD RED: preserve primary failure and exact cleanup stage without secrets.

Only the subprocess/host boundaries are simulated; the real preflight
``execute`` and cleanup state machine are exercised without Docker or SSH.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from scripts import host_cutover_worker_preflight as probe  # noqa: E402

CID = "f" * 64
PRIVATE = "PRIVATE_DOCKER_ERROR_RAW_NEVER_LOG_807"
PROFILE = b'{"defaultAction":"SCMP_ACT_ERRNO"}'


def _coordinates() -> probe.Coordinates:
    return probe.Coordinates(
        attempt="42341290485",
        source="a" * 40,
        controller="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64,
        browser="ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "b" * 64,
        legacy_source="c" * 40,
        legacy_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "c" * 64,
        legacy_id="d" * 64,
    )


def _full_probe(coords: probe.Coordinates, *, running: bool) -> dict[str, Any]:
    return {
        "Id": CID,
        "Name": f"/{probe.PREFIX}{coords.attempt}",
        "Config": {
            "Image": coords.browser,
            "User": "10002:10002",
            "Cmd": ["python", "-c", "import time; time.sleep(90)"],
            "Labels": {
                probe.LABEL: coords.attempt,
                "com.docker.compose.project": "boca-socios",
                "org.opencontainers.image.revision": coords.source,
            },
        },
        "HostConfig": {
            "NetworkMode": "none",
            "IpcMode": "private",
            "CgroupnsMode": "private",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "Init": True,
            "NanoCpus": 1_000_000_000,
            "Memory": 805_306_368,
            "PidsLimit": 128,
            "CapDrop": ["ALL"],
            "CapAdd": ["SYS_CHROOT"],
            "PortBindings": None,
            "SecurityOpt": ["no-new-privileges:true", "seccomp=reviewed"],
        },
        "State": {"Running": running},
        "Mounts": [],
        "NetworkSettings": {"Ports": None, "Networks": {"none": {}}},
    }


class CleanupRig:
    """Probe created once; fail only during cleanup after boundary attempt."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        failure: str = "NONE",
        primary_failure: bool = False,
    ) -> None:
        self.coords = _coordinates()
        self.failure = failure
        self.primary_failure = primary_failure
        self.calls: list[tuple[str, ...]] = []
        self.present = False
        self.running = False
        self.boundary_done = False
        self.rm_attempts = 0
        self.stop_attempts = 0
        self.legacy_reads = 0

        monkeypatch.setattr(probe, "protected_boca_job_lease", lambda _attempt: nullcontext())
        monkeypatch.setattr(probe, "_require_clean_namespace", lambda _name: None)
        monkeypatch.setattr(probe, "_temporary_seccomp", self.seccomp_context)
        monkeypatch.setattr(probe.host, "_cutover_legacy_record", self.legacy)
        monkeypatch.setattr(probe.host, "_browser_engine_version", lambda: "28.0.1")
        monkeypatch.setattr(probe.host, "_storage_snapshot", lambda: object())
        monkeypatch.setattr(probe.host, "_browser_pull_both", lambda *_pins: None)
        monkeypatch.setattr(probe.host, "_browser_inspect_record", self.inspect)
        monkeypatch.setattr(
            probe.host, "_browser_effective_seccomp_options", lambda *_a, **_k: None
        )
        monkeypatch.setattr(probe.host, "_run", self.docker)

    @contextmanager
    def seccomp_context(self, _attempt: str, _profile: bytes):
        yield Path("/run/user/10001/reviewed-seccomp-fixture.json")
        if self.failure == "TEMP_SECCOMP":
            raise probe.TempSeccompCleanupError(PRIVATE)

    def legacy(self, *_args: Any, **_kwargs: Any) -> None:
        self.legacy_reads += 1
        if self.failure == "LEGACY" and self.legacy_reads == 2:
            raise probe.host.PreflightError(PRIVATE)

    def inspect(self, _cid: str) -> dict[str, Any]:
        assert _cid == CID
        if self.failure == "INSPECT" and self.boundary_done:
            raise probe.host.PreflightError(PRIVATE)
        record = _full_probe(self.coords, running=self.running)
        if self.failure == "OWNERSHIP" and self.boundary_done:
            record["Config"]["Labels"][probe.LABEL] = "foreign"  # type: ignore[index]
        return record

    def docker(self, *args: str, **_kwargs: Any) -> str:
        self.calls.append(args)
        assert args[0] == "docker"
        action = args[1]
        if action == "ps":
            assert args[2:5] == ("-a", "-q", "--no-trunc")
            assert args[5:] == ("--filter", f"name=^/{probe.PREFIX}{self.coords.attempt}$")
            if self.failure == "PS" and self.boundary_done:
                raise probe.host.PreflightError(PRIVATE)
            if self.failure == "POST_ID" and self.rm_attempts:
                return CID
            return CID if self.present else ""
        if action == "create":
            assert not self.present
            self.present = True
            return CID
        if action == "start":
            assert self.present and args == ("docker", "start", CID)
            self.running = True
            return CID
        if action == "exec":
            assert self.running and args[4] == CID
            self.boundary_done = True
            if self.primary_failure:
                raise probe.host.PreflightError(PRIVATE)
            return "BOCA_CUTOVER_WORKER_BOUNDARY_PASS"
        if action == "stop":
            self.stop_attempts += 1
            assert self.present and self.running
            assert args == ("docker", "stop", "--time", "5", CID)
            if self.failure == "STOP":
                raise probe.host.PreflightError(PRIVATE)
            self.running = False
            return CID
        if action == "rm":
            self.rm_attempts += 1
            assert self.present and not self.running and args == ("docker", "rm", CID)
            if self.failure == "RM":
                raise probe.host.PreflightError(PRIVATE)
            self.present = False
            return CID
        raise AssertionError(f"Unexpected synthetic Docker operation {action}")


@pytest.mark.parametrize(
    "stage",
    ["PS", "INSPECT", "OWNERSHIP", "STOP", "RM", "POST_ID", "TEMP_SECCOMP", "LEGACY"],
)
def test_cleanup_failure_preserves_exact_stage_without_fabricating_primary_failure(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """No cleanup stage may collapse into undifferentiated CLEANUP."""
    rig = CleanupRig(monkeypatch, failure=stage)
    with pytest.raises(probe.PreflightFailure) as captured:
        probe.execute(rig.coords, PROFILE)
    failure = captured.value
    assert failure.phase == "CLEANUP"  # Preserve old consumer behavior.
    assert failure.cleanup == "INDETERMINATE"
    assert failure.primary_failed_phase == "NONE"
    assert failure.cleanup_failed_stage == stage
    assert PRIVATE not in str(failure)
    assert rig.rm_attempts <= 1 and rig.stop_attempts <= 1
    assert rig.calls.count(("docker", "rm", CID)) <= 1
    assert rig.calls.count(("docker", "stop", "--time", "5", CID)) <= 1
    if stage in {"PS", "INSPECT", "OWNERSHIP", "STOP"}:
        assert rig.rm_attempts == 0


def test_original_boundary_failure_survives_later_rm_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cleanup failure must not overwrite the first failed operational phase."""
    rig = CleanupRig(monkeypatch, failure="RM", primary_failure=True)
    with pytest.raises(probe.PreflightFailure) as captured:
        probe.execute(rig.coords, PROFILE)
    failure = captured.value
    assert failure.phase == "CLEANUP"
    assert failure.cleanup == "INDETERMINATE"
    assert failure.primary_failed_phase == "WORKER_BOUNDARY"
    assert failure.cleanup_failed_stage == "RM"
    assert rig.stop_attempts == rig.rm_attempts == 1
    assert PRIVATE not in str(failure)


def test_primary_failure_without_cleanup_error_keeps_cleanup_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = CleanupRig(monkeypatch, primary_failure=True)
    with pytest.raises(probe.PreflightFailure) as captured:
        probe.execute(rig.coords, PROFILE)
    failure = captured.value
    assert failure.phase == "WORKER_BOUNDARY"
    assert failure.cleanup == "VERIFIED"
    assert failure.primary_failed_phase == "WORKER_BOUNDARY"
    assert failure.cleanup_failed_stage == "NONE"
    assert rig.rm_attempts == 1
    assert not rig.present


def test_success_keeps_existing_one_stop_one_rm_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = CleanupRig(monkeypatch)
    assert probe.execute(rig.coords, PROFILE) == ("WORKER_BOUNDARY", "VERIFIED")
    assert rig.stop_attempts == rig.rm_attempts == 1
    assert not rig.present
    assert rig.legacy_reads == 2


def test_cli_receipt_exposes_only_bounded_sanitized_stage_enums(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = CleanupRig(monkeypatch, failure="RM", primary_failure=True)
    monkeypatch.setattr(probe, "_reviewed_seccomp", lambda: PROFILE)
    command = ["host", *rig.coords.__dict__.values()]
    assert probe.main(command) == 3
    captured = capsys.readouterr()
    assert captured.err == ""
    assert PRIVATE not in captured.out
    assert len(captured.out.encode("ascii")) <= 240
    assert captured.out.count("\n") == 1
    assert "state=NO_GO" in captured.out
    assert "primary_failed_phase=WORKER_BOUNDARY" in captured.out
    assert "cleanup_failed_stage=RM" in captured.out
    assert rig.rm_attempts == 1
