"""Protected BETA installation must preserve custody and host loopback isolation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host

SHA = "a" * 40
IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64
ORIGIN = "https://boca.example.test:8443"
OWNER = "synthetic-owner"


def _snapshot() -> host.HostSnapshot:
    return host.HostSnapshot(
        arch="x86_64",
        uid=10001,
        available_memory_kib=853288,
        available_disk_bytes=8 * 1024**3,
        available_inodes=100000,
        docker_disk_bytes=8 * 1024**3,
        docker_inodes=100000,
        root_ready=True,
        boca_containers=False,
        boca_volume=True,
        boca_network=False,
        cpu_headroom=1.0,
    )


def test_beta_preflight_only_accepts_owner_volume_and_empty_app_namespace() -> None:
    host.validate_beta_snapshot(_snapshot(), {host.OWNER_VOLUME}, expected={host.OWNER_VOLUME})
    for volumes in (
        set(),
        {host.OWNER_VOLUME, host.KEY_VOLUME},
        {host.OWNER_VOLUME, "boca-socios_boca_data"},
        {"boca-socios_other"},
    ):
        with pytest.raises(host.PreflightError):
            host.validate_beta_snapshot(_snapshot(), volumes, expected={host.OWNER_VOLUME})
    for changed in ("boca_containers", "boca_network"):
        with pytest.raises(host.PreflightError):
            host.validate_beta_snapshot(
                replace(_snapshot(), **{changed: True}),
                {host.OWNER_VOLUME},
                expected={host.OWNER_VOLUME},
            )


def test_beta_context_rejects_untrusted_origin_and_subject() -> None:
    host._validate_beta_context(ORIGIN, OWNER)
    for origin, owner in (
        ("http://boca.example.test:8443", OWNER),
        ("https://boca.example.test:8443/path", OWNER),
        ("https://user@boca.example.test:8443", OWNER),
        ("https://boca.example.test:99999", OWNER),
        (ORIGIN, ""),
        (ORIGIN, "owner;id"),
    ):
        with pytest.raises(host.PreflightError):
            host._validate_beta_context(origin, owner)


def test_beta_preflight_containers_are_network_free_and_do_not_mount_data() -> None:
    owner = host._beta_check_container(IMAGE, ORIGIN, OWNER, "check-beta-owner")
    assert owner[:5] == ("docker", "run", "--rm", "--pull", "never")
    assert owner[owner.index("--user") + 1] == "10001:10001"
    assert owner[owner.index("--network") + 1] == "none"
    assert owner[owner.index("--cap-drop") + 1] == "ALL"
    assert "--read-only" in owner and "docker.sock" not in " ".join(owner)
    assert f"type=volume,source={host.OWNER_VOLUME},target=/run/owner,volume-nocopy,readonly" in owner
    assert host.KEY_VOLUME not in " ".join(owner)
    assert "boca-socios_boca_data" not in " ".join(owner)
    assert "BOCA_HEALTH_CA_FILE=/run/owner/health-ca.pem" in owner
    assert owner[-4:] == ("python", "-m", "boca_socios.runtime", "check-beta-owner")
    full = host._beta_check_container(IMAGE, ORIGIN, OWNER, "check-beta-config")
    assert f"type=volume,source={host.KEY_VOLUME},target=/run/secrets,volume-nocopy,readonly" in full
    assert "boca-socios_boca_data" not in " ".join(full)
    assert full[-1] == "check-beta-config"


def test_new_only_beta_initializer_uses_private_key_and_data_with_fixed_limits() -> None:
    command = host._beta_init_container(IMAGE)
    assert command[command.index("--user") + 1] == "10001:10001"
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--memory") + 1] == "256m"
    assert command[command.index("--cpus") + 1] == "0.50"
    assert f"type=volume,source={host.KEY_VOLUME},target=/run/secrets,volume-nocopy,readonly" in command
    assert "type=volume,source=boca-socios_boca_data,target=/data" in command
    assert host.OWNER_VOLUME not in " ".join(command)
    assert command[-4:] == ("python", "-m", "boca_socios.runtime", "init-beta")


def test_beta_workflow_has_separate_marker_release_and_main_gates() -> None:
    workflow = Path(".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    assert "beta-install" in workflow
    assert 'test "$BOCA_BETA_ENV_READY" = ready' in workflow
    assert "BOCA_BETA_PANEL_ORIGIN: ${{ secrets.BOCA_BETA_PANEL_ORIGIN }}" in workflow
    assert "BOCA_BETA_OWNER_SUBJECT: ${{ secrets.BOCA_BETA_OWNER_SUBJECT }}" in workflow
    assert "python scripts/check_release_run.py" in workflow
    assert "python scripts/check_beta_deploy_contract.py" in workflow
    assert workflow.index("Recheck current main before BETA install") < workflow.index(
        "Initialize new-only BETA and start isolated controller"
    )
    assert "BOCA_SITE_ENVELOPE" in workflow
    assert "BOCA_BETA_TOKEN" not in workflow


def test_dormant_and_site_phases_cannot_take_beta_context_before_host_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host, "_validate_docker_boundary", lambda: pytest.fail("host probed"))
    for phase in ("observe", "apply", "site-prepare"):
        with pytest.raises(host.PreflightError):
            host.phase(phase, "" if phase == "observe" else IMAGE, SHA, "d" * 64, ORIGIN, OWNER)
