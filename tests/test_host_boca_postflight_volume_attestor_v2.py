"""R253 Boca-only same-lease volume custody; synthetic fixtures, no host Docker."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_postflight_volume_attestor_v2 as witness
from boca_socios import host_boca_upgrade_postflight_runtime as runtime

VOLUMES = (
    "boca-socios_boca_data",
    "boca-socios_boca_key",
    "boca-socios_boca_owner",
)


def _fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[object, cleanup.BocaJobLease, list[str], dict[str, object]]:
    root = tmp_path / "docker"
    root.mkdir(mode=0o700)
    for name in VOLUMES:
        (root / "volumes" / name / "_data").mkdir(parents=True)
    monkeypatch.setattr(runtime, "_ROOT", root)
    events: list[str] = []
    expected = SimpleNamespace(plan=SimpleNamespace(attempt_id="279"))
    lease = cleanup.BocaJobLease("279", -1, os.getpid(), True)
    monkeypatch.setattr(runtime, "_attest_live_pair", lambda *_: events.append("pair"))
    monkeypatch.setattr(
        cleanup, "verify_protected_boca_job_lease", lambda *_: events.append("lease")
    )
    monkeypatch.setattr(
        runtime,
        "_read_rootless_identity",
        lambda: (cleanup.EXPECTED_UID, cleanup.EXPECTED_GID),
    )
    root_stat = root.stat()
    labels = {
        name: (
            ("com.docker.compose.project", "boca-socios"),
            ("com.docker.compose.volume", name.removeprefix("boca-socios_")),
        )
        for name in VOLUMES
    }
    inventory = SimpleNamespace(
        volumes=tuple(cleanup.Volume(name, labels[name]) for name in VOLUMES),
        disk=SimpleNamespace(docker_device=root_stat.st_dev, docker_inode=root_stat.st_ino),
    )
    monkeypatch.setattr(
        cleanup, "capture_inventory", lambda: events.append("inventory") or inventory
    )
    fields: dict[str, object] = {}

    def docker(*args: str) -> str:
        if args == ("info", "--format", "{{json .DockerRootDir}}"):
            events.append("docker-root")
            return json.dumps(str(root))
        assert args[:4] == ("volume", "inspect", "--format", "{{json .}}")
        assert args[4] in VOLUMES
        events.append(args[4])
        name = args[4]
        volume = {
            "Name": name,
            "Driver": "local",
            "Scope": "local",
            "Options": None,
            "Mountpoint": str(root / "volumes" / name / "_data"),
            "Labels": dict(labels[name]),
        }
        volume.update(fields)
        return json.dumps(volume)

    monkeypatch.setattr(cleanup, "_docker", docker)
    return expected, lease, events, fields


def test_exact_data_key_owner_proof_requires_live_pair_lease_and_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected, lease, events, _ = _fixture(tmp_path, monkeypatch)
    attestor = witness.ProductionBocaVolumeAttestor(expected, lease)
    assert attestor() is None
    assert events == [
        "lease",
        "pair",
        "inventory",
        "docker-root",
        *VOLUMES,
        "pair",
        "lease",
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Driver", "local2"),
        ("Scope", "global"),
        ("Options", {"device": "/foreign"}),
        ("Name", "foreign-volume"),
        ("Mountpoint", "/foreign/sensitive"),
        ("Labels", {"com.docker.compose.project": "foreign"}),
    ],
)
def test_refuses_nonlocal_unlabeled_redirected_or_foreign_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    expected, lease, _, fields = _fixture(tmp_path, monkeypatch)
    fields[field] = value
    with pytest.raises(witness.BocaVolumeAttestorNoGo, match="NO_GO"):
        witness.ProductionBocaVolumeAttestor(expected, lease)()


def test_refuses_docker_root_symlink_without_following_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected, lease, _, _ = _fixture(tmp_path, monkeypatch)
    root = runtime._ROOT
    assert root.is_dir()
    root.rename(tmp_path / "real-docker")
    root.symlink_to(tmp_path / "real-docker", target_is_directory=True)
    with pytest.raises(witness.BocaVolumeAttestorNoGo, match="NO_GO"):
        witness.ProductionBocaVolumeAttestor(expected, lease)()


def test_refuses_redirected_data_mount_even_with_matching_docker_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected, lease, _, _ = _fixture(tmp_path, monkeypatch)
    root = runtime._ROOT
    original = root / "volumes" / VOLUMES[0] / "_data"
    original.rename(root / "volumes" / VOLUMES[0] / "safe-original")
    original.symlink_to(root / "volumes" / VOLUMES[0] / "safe-original", target_is_directory=True)
    with pytest.raises(witness.BocaVolumeAttestorNoGo, match="NO_GO"):
        witness.ProductionBocaVolumeAttestor(expected, lease)()


def test_foreign_inventory_fails_before_any_volume_inspect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected, lease, events, _ = _fixture(tmp_path, monkeypatch)

    def fail_foreign() -> None:
        raise cleanup.CleanupError("foreign volume; no inspect")

    monkeypatch.setattr(cleanup, "capture_inventory", fail_foreign)
    with pytest.raises(witness.BocaVolumeAttestorNoGo, match="NO_GO"):
        witness.ProductionBocaVolumeAttestor(expected, lease)()
    assert events == ["lease", "pair"]


def test_no_rootless_or_pair_proof_means_no_docker_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected, lease, events, _ = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "_read_rootless_identity", lambda: (0, 0))
    with pytest.raises(witness.BocaVolumeAttestorNoGo, match="NO_GO"):
        witness.ProductionBocaVolumeAttestor(expected, lease)()
    assert events == ["lease", "pair"]
