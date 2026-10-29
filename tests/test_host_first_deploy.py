"""Host preflight fails before mutation on unsafe capacity or Boca state."""

from dataclasses import replace

import pytest

from boca_socios.host_first_deploy import HostSnapshot, PreflightError, validate_snapshot


def safe_snapshot() -> HostSnapshot:
    return HostSnapshot(
        arch="x86_64",
        uid=10001,
        available_memory_kib=1024 * 1024,
        available_disk_bytes=8 * 1024**3,
        available_inodes=100_000,
        root_ready=True,
        boca_containers=False,
        boca_volume=False,
        boca_network=False,
    )


def test_first_deploy_preflight_passes_only_with_free_boca_namespace() -> None:
    validate_snapshot(safe_snapshot())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("arch", "aarch64"),
        ("uid", 0),
        ("available_memory_kib", 400_000),
        ("available_disk_bytes", 2 * 1024**3),
        ("available_inodes", 1_000),
        ("root_ready", False),
        ("boca_containers", True),
        ("boca_volume", True),
        ("boca_network", True),
    ],
)
def test_unsafe_host_snapshot_is_no_go(field: str, value: object) -> None:
    with pytest.raises(PreflightError):
        validate_snapshot(replace(safe_snapshot(), **{field: value}))
