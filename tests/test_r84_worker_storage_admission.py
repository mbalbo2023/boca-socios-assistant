"""R84 regression: worker probe must use the reviewed two-image storage gate.

All host/Docker calls are synthetic. This module never connects to a daemon.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from pathlib import Path

import pytest

from test_host_first_deploy import safe_storage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from scripts import host_cutover_worker_preflight as probe  # noqa: E402

from test_cutover_worker_preflight import pins  # noqa: E402

GIB = 1024**3


def _run_storage_probe(
    monkeypatch: pytest.MonkeyPatch,
    before: probe.host.StorageSnapshot,
    after_controller: probe.host.StorageSnapshot | None = None,
    after_browser: probe.host.StorageSnapshot | None = None,
) -> tuple[probe.PreflightFailure, list[tuple[str, ...]]]:
    """Run real storage validators inside the real preflight error state machine."""
    observations = iter(
        (before, before, after_controller or before, after_browser or before, before)
    )
    commands: list[tuple[str, ...]] = []
    legacy: list[str] = []
    cleanup: list[str] = []
    monkeypatch.setattr(probe, "protected_boca_job_lease", lambda _id: nullcontext())
    monkeypatch.setattr(probe.host, "_cutover_legacy_record", lambda *a, **k: legacy.append("ok"))
    monkeypatch.setattr(probe, "_require_clean_namespace", lambda _name: None)
    monkeypatch.setattr(probe.host, "_browser_engine_version", lambda: "28.0.1")
    monkeypatch.setattr(probe.host, "_storage_snapshot", lambda: next(observations))
    monkeypatch.setattr(probe.host, "_browser_validate_image", lambda *a: None)
    monkeypatch.setattr(probe, "_cleanup_exact", lambda *_args: cleanup.append("verified"))

    def run(*args: str, **_kwargs: object) -> str:
        commands.append(args)
        assert args[:2] == ("docker", "pull"), "only the reviewed pair may be pulled"
        return ""

    monkeypatch.setattr(probe.host, "_run", run)

    @contextmanager
    def stop_after_pulls(_attempt: str, _profile: bytes):
        raise probe.WorkerPreflightError("synthetic boundary: no worker creation")
        yield Path("/run/user/10001/unreachable")

    monkeypatch.setattr(probe, "_temporary_seccomp", stop_after_pulls)
    with pytest.raises(probe.PreflightFailure) as caught:
        probe.execute(pins(), b"{}")
    assert legacy == ["ok", "ok"]
    assert cleanup == ["verified"]
    assert caught.value.cleanup == "VERIFIED"
    assert caught.value.cleanup_failed_stage == "NONE"
    return caught.value, commands


@pytest.mark.parametrize(
    "field,below",
    [
        ("stage_free_bytes", 4 * GIB - 1),
        ("docker_free_bytes", 4 * GIB - 1),
        ("stage_inodes", 49_999),
        ("docker_inodes", 49_999),
    ],
)
def test_worker_preflight_rejects_below_initial_floor_before_any_pull(
    monkeypatch: pytest.MonkeyPatch, field: str, below: int
) -> None:
    initial = replace(safe_storage(), **{field: below})
    failure, commands = _run_storage_probe(monkeypatch, initial)
    assert failure.phase == failure.primary_failed_phase == "GHCR_PULL"
    assert commands == []


@pytest.mark.parametrize(
    "field,below",
    [
        ("stage_free_bytes", GIB - 1),
        ("docker_free_bytes", GIB - 1),
        ("stage_inodes", 49_999),
        ("docker_inodes", 49_999),
    ],
)
def test_worker_preflight_blocks_second_pull_on_low_controller_residual(
    monkeypatch: pytest.MonkeyPatch, field: str, below: int
) -> None:
    initial = safe_storage()
    residual = replace(initial, **{field: below})
    failure, commands = _run_storage_probe(monkeypatch, initial, residual)
    assert failure.phase == failure.primary_failed_phase == "GHCR_PULL"
    assert commands == [("docker", "pull", pins().controller)]


@pytest.mark.parametrize(
    "field,below",
    [("stage_free_bytes", GIB - 1), ("docker_inodes", 49_999), ("docker_inode", 999_999)],
)
def test_worker_preflight_rejects_bad_post_browser_storage_without_creating_worker(
    monkeypatch: pytest.MonkeyPatch, field: str, below: int
) -> None:
    initial = safe_storage()
    bad_final = replace(initial, **{field: below})
    failure, commands = _run_storage_probe(monkeypatch, initial, initial, bad_final)
    assert failure.phase == failure.primary_failed_phase == "GHCR_PULL"
    assert commands == [
        ("docker", "pull", pins().controller),
        ("docker", "pull", pins().browser),
    ]


def test_worker_preflight_accepts_inclusive_floors_without_extra_pull(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = replace(safe_storage(), stage_free_bytes=4 * GIB, docker_free_bytes=4 * GIB)
    residual = replace(
        initial,
        stage_free_bytes=GIB,
        docker_free_bytes=GIB,
        stage_inodes=50_000,
        docker_inodes=50_000,
    )
    failure, commands = _run_storage_probe(monkeypatch, initial, residual, residual)
    assert failure.phase == failure.primary_failed_phase == "SECCOMP_ENTER"
    assert commands == [
        ("docker", "pull", pins().controller),
        ("docker", "pull", pins().browser),
    ]
