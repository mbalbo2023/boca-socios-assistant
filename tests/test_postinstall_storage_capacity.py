"""Owner-approved post-pull residual is scoped to Boca BETA, never pre-pull.

All observations and Docker calls are synthetic. Nothing reaches a host.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from boca_socios import host_first_deploy as host
from test_host_beta_install import IMAGE, _snapshot
from test_host_first_deploy import safe_storage

GIB = 1024**3


@pytest.mark.parametrize("minimum", [0, -1, True, GIB // 2, 2 * GIB, 4 * GIB + 1])
def test_only_two_reviewed_storage_policy_thresholds_are_accepted(minimum: int) -> None:
    with pytest.raises(host.PreflightError, match="invalid Boca storage capacity policy"):
        host._validate_storage_capacity(safe_storage(), min_free_bytes=minimum)
    with pytest.raises(host.PreflightError, match="invalid Boca storage capacity policy"):
        host.validate_snapshot(_snapshot(), min_free_bytes=minimum)
    with pytest.raises(host.PreflightError, match="invalid Boca storage capacity policy"):
        host._validate_storage_continuity(
            safe_storage(), safe_storage(), require_capacity=False, min_free_bytes=minimum
        )


@pytest.mark.parametrize("field", ["stage_free_bytes", "docker_free_bytes"])
def test_dual_pull_preflight_still_rejects_below_four_gib(field: str) -> None:
    before = replace(safe_storage(), **{field: 4 * GIB - 1})
    with pytest.raises(host.PreflightError, match="insufficient Boca"):
        host._validate_storage_capacity(before)


@pytest.mark.parametrize("field", ["stage_free_bytes", "docker_free_bytes"])
def test_postpull_residual_admits_one_gib_but_not_one_byte_less(field: str) -> None:
    before = safe_storage()
    at_limit = replace(before, **{field: GIB})
    host._validate_storage_continuity(
        before, at_limit, min_free_bytes=host.POSTINSTALL_STORAGE_MIN_BYTES
    )
    with pytest.raises(host.PreflightError, match="insufficient Boca"):
        host._validate_storage_continuity(
            before,
            replace(at_limit, **{field: GIB - 1}),
            min_free_bytes=host.POSTINSTALL_STORAGE_MIN_BYTES,
        )


@pytest.mark.parametrize("field", ["stage_inodes", "docker_inodes"])
def test_postpull_residual_preserves_fifty_thousand_free_inodes(field: str) -> None:
    before = safe_storage()
    after = replace(
        before,
        stage_free_bytes=GIB,
        docker_free_bytes=GIB,
        **{field: 49_999},
    )
    with pytest.raises(host.PreflightError, match="insufficient Boca"):
        host._validate_storage_continuity(
            before, after, min_free_bytes=host.POSTINSTALL_STORAGE_MIN_BYTES
        )


def test_postpull_residual_still_blocks_docker_root_inode_drift() -> None:
    before = safe_storage()
    after = replace(before, docker_inode=before.docker_inode + 1, docker_free_bytes=GIB)
    with pytest.raises(host.PreflightError, match="storage topology changed"):
        host._validate_storage_continuity(
            before, after, min_free_bytes=host.POSTINSTALL_STORAGE_MIN_BYTES
        )


def test_beta_inventory_threshold_is_only_relaxed_when_explicitly_selected() -> None:
    observed = replace(_snapshot(), available_disk_bytes=GIB, docker_disk_bytes=GIB)
    with pytest.raises(host.PreflightError, match="storage"):
        host.validate_beta_snapshot(observed, {host.OWNER_VOLUME}, expected={host.OWNER_VOLUME})
    host.validate_beta_snapshot(
        observed,
        {host.OWNER_VOLUME},
        expected={host.OWNER_VOLUME},
        min_free_bytes=host.POSTINSTALL_STORAGE_MIN_BYTES,
    )


def test_beta_apply_keeps_pre_pull_floor_and_uses_postpull_floor_before_owner_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    floors: list[int] = []
    events: list[str] = []
    monkeypatch.setattr(host, "_verify_beta_compose", lambda *_args: None)

    def inventory(
        *,
        staged: bool,
        expected: set[str],
        min_free_bytes: int = host.PREFLIGHT_STORAGE_MIN_BYTES,
    ) -> host.HostSnapshot:
        assert staged and expected == {host.OWNER_VOLUME}
        floors.append(min_free_bytes)
        return _snapshot()

    monkeypatch.setattr(host, "_beta_inventory", inventory)
    monkeypatch.setattr(host, "_beta_pull", lambda *_args: events.append("pull"))
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: events.append("check") or "{}")
    monkeypatch.setattr(host, "_create_key", lambda *_args: pytest.fail("key created"))

    with pytest.raises(host.PreflightError, match="preflight did not confirm"):
        host._beta_phase(
            "beta-apply",
            IMAGE,
            "a" * 40,
            "b" * 64,
            "http://localhost:8443",
            "synthetic-owner",
        )
    assert floors == [host.PREFLIGHT_STORAGE_MIN_BYTES, host.POSTINSTALL_STORAGE_MIN_BYTES]
    assert events[0] == "check" and "pull" in events


def test_dual_pull_uses_four_gib_before_first_and_one_gib_between_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = safe_storage()
    after_controller = replace(before, stage_free_bytes=4 * GIB - 1, docker_free_bytes=4 * GIB - 1)
    after_browser = replace(before, stage_free_bytes=GIB, docker_free_bytes=GIB)
    observed = iter((before, after_controller, after_browser))
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(host, "_storage_snapshot", lambda: next(observed))
    monkeypatch.setattr(host, "_browser_validate_image", lambda *_args: None)
    monkeypatch.setattr(host, "_run", lambda *args: commands.append(args) or "")

    host._browser_pull_both("controller-digest", "browser-digest", "a" * 40)
    assert commands == [
        ("docker", "pull", "controller-digest"),
        ("docker", "pull", "browser-digest"),
    ]


def test_dual_pull_aborts_on_low_residual_before_other_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = safe_storage()
    after_controller = replace(before, stage_free_bytes=GIB - 1, docker_free_bytes=GIB - 1)
    observed = iter((before, after_controller))
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(host, "_storage_snapshot", lambda: next(observed))
    monkeypatch.setattr(host, "_browser_validate_image", lambda *_args: None)
    monkeypatch.setattr(host, "_run", lambda *args: commands.append(args) or "")

    with pytest.raises(host.PreflightError, match="insufficient Boca"):
        host._browser_pull_both("controller-digest", "browser-digest", "a" * 40)
    assert commands == [("docker", "pull", "controller-digest")]


def test_dual_pull_uses_residual_only_after_pull_and_completes_two_images(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = safe_storage()
    after_controller = replace(before, stage_free_bytes=4 * GIB, docker_free_bytes=4 * GIB)
    after_browser = replace(before, stage_free_bytes=GIB, docker_free_bytes=GIB)
    observed = iter((before, after_controller, after_browser))
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(host, "_storage_snapshot", lambda: next(observed))
    monkeypatch.setattr(host, "_browser_validate_image", lambda *_args: None)
    monkeypatch.setattr(host, "_run", lambda *args: commands.append(args) or "")

    host._browser_pull_both("controller-digest", "browser-digest", "a" * 40)
    assert commands == [
        ("docker", "pull", "controller-digest"),
        ("docker", "pull", "browser-digest"),
    ]
