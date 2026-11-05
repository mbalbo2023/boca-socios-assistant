"""Host attestation is exercised using inert JSON Docker records, never Docker."""

from __future__ import annotations

import base64
import fcntl
import json
import os
import sqlite3
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any

import pytest

from boca_socios.config import Settings
from boca_socios.panel import owner_session_host_attestor as host
from boca_socios.panel import owner_session_upgrade as upgrade
from boca_socios.runtime import initialize_beta

_ORIGINAL = "a" * 64
_SHA = "b" * 40
_IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "c" * 64
_OTHER = "d" * 64


@pytest.fixture
def docker_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, dict[str, Any], list[tuple[str, ...]]]:
    key = tmp_path / "synthetic.key"
    key.write_bytes(base64.b64encode(b"k" * 32))
    key.chmod(0o400)
    mountpoint = tmp_path / "volumes" / host.DATA_VOLUME / "_data"
    mountpoint.mkdir(parents=True)
    db = mountpoint / "boca.sqlite3"
    initialize_beta(Settings("staging", "simulation", db, key))
    monkeypatch.setattr(host, "_UID", os.getuid())
    monkeypatch.setattr(host, "_LOCK", tmp_path / "boca-socios-0008.lock")
    monkeypatch.setattr(upgrade, "_BOCA_UID", os.getuid())
    monkeypatch.setattr(upgrade, "_BOCA_GID", os.getgid())
    records: dict[str, Any] = {
        "rootless": True,
        "volume": {
            "Name": "boca-socios_boca_data",
            "Driver": "local",
            "Mountpoint": str(mountpoint),
            "Labels": {
                "com.docker.compose.project": "boca-socios",
                "com.docker.compose.volume": "boca_data",
            },
        },
        "controllers": [_ORIGINAL],
        "users": [_ORIGINAL],
        "original": {
            "Name": "/boca-socios-controller-legacy-1234",
            "Config.Labels": {
                "com.docker.compose.project": "boca-socios",
                "com.docker.compose.service": "controller",
                "com.docker.compose.container-number": "1",
                "org.opencontainers.image.revision": _SHA,
            },
            "Config.Image": _IMAGE,
            "HostConfig.RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
            "State": {"Running": False, "Status": "exited", "Restarting": False},
            "Mounts": [
                {
                    "Type": "volume",
                    "Driver": "local",
                    "Name": "boca-socios_boca_data",
                    "Destination": "/data",
                    "RW": True,
                    "Source": str(mountpoint),
                },
                {
                    "Type": "volume",
                    "Driver": "local",
                    "Name": "boca-socios_boca_key",
                    "Destination": "/run/secrets",
                    "RW": False,
                },
                {
                    "Type": "volume",
                    "Driver": "local",
                    "Name": "boca-socios_boca_owner",
                    "Destination": "/run/owner",
                    "RW": False,
                },
            ],
        },
        "other": {
            "State": {"Running": False, "Status": "exited"},
            "Mounts": [
                {"Name": "boca-socios_boca_data", "Destination": "/data", "RW": True},
            ],
        },
    }
    calls: list[tuple[str, ...]] = []

    def fake_docker(*args: str) -> str:
        calls.append(args)
        if args[0] == "info":
            return json.dumps(["name=rootless"] if records["rootless"] else ["name=seccomp"])
        if args[:2] == ("volume", "inspect"):
            return json.dumps(records["volume"])
        if args[0] == "ps":
            key_name = (
                "controllers" if "label=com.docker.compose.service=controller" in args else "users"
            )
            return "\n".join(records[key_name])
        if args[0] == "inspect":
            identifier = args[-1]
            record = records["original"] if identifier == _ORIGINAL else records["other"]
            key_name = args[2].removeprefix("{{json .").removesuffix("}}")
            return json.dumps(record[key_name])
        raise AssertionError(f"unsupported read-only Docker call: {args}")

    monkeypatch.setattr(host, "_docker", fake_docker)
    return db, records, calls


def _evidence() -> host.DockerStoppedControllerEvidence:
    return host.DockerStoppedControllerEvidence(
        original_id=_ORIGINAL, attempt_id="1234", legacy_sha=_SHA, legacy_image=_IMAGE
    )


def _versions(path: Path) -> list[int]:
    with sqlite3.connect(path) as conn:
        return [
            version
            for (version,) in conn.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]


def test_trusted_host_attestor_applies_only_0008_under_exclusive_lease(
    docker_fixture: tuple[Path, dict[str, Any], list[tuple[str, ...]]],
) -> None:
    db, _, calls = docker_fixture
    attestor = _evidence()
    assert attestor.host_database_path() == db
    assert (
        upgrade.upgrade_existing_owner_schema_0008(attestor, path=db)
        is upgrade.UpgradeResult.APPLIED
    )
    assert _versions(db) == [1, 2, 3, 5, 6, 8]
    assert (
        upgrade.upgrade_existing_owner_schema_0008(attestor, path=db)
        is upgrade.UpgradeResult.ALREADY_APPLIED
    )
    assert len([call for call in calls if call[0] == "info"]) == 4
    assert all(call[0] in {"info", "ps", "inspect", "volume"} for call in calls)


@pytest.mark.parametrize(
    "tamper",
    [
        "running",
        "restart",
        "wrong_name",
        "bad_revision",
        "no_rootless",
        "extra_controller",
        "other_running_writer",
        "volume_swap",
        "volume_bind",
        "mount_source_swap",
        "missing_owner_mount",
    ],
)
def test_fails_closed_without_writing_0008_for_host_identity_drift(
    docker_fixture: tuple[Path, dict[str, Any], list[tuple[str, ...]]],
    tamper: str,
) -> None:
    db, records, _ = docker_fixture
    original = records["original"]
    if tamper == "running":
        original["State"]["Running"] = True
    elif tamper == "restart":
        original["HostConfig.RestartPolicy"]["Name"] = "unless-stopped"
    elif tamper == "wrong_name":
        original["Name"] = "/boca-socios-controller-1"
    elif tamper == "bad_revision":
        original["Config.Labels"]["org.opencontainers.image.revision"] = "f" * 40
    elif tamper == "no_rootless":
        records["rootless"] = False
    elif tamper == "extra_controller":
        records["controllers"].append(_OTHER)
    elif tamper == "other_running_writer":
        records["users"].append(_OTHER)
        records["other"]["State"]["Running"] = True
    elif tamper == "volume_swap":
        records["volume"]["Mountpoint"] = "/invalid-unowned"
    elif tamper == "volume_bind":
        records["volume"]["Options"] = {"device": "/outside", "o": "bind"}
    elif tamper == "mount_source_swap":
        original["Mounts"][0]["Source"] = "/outside"
    elif tamper == "missing_owner_mount":
        original["Mounts"].pop()
    with pytest.raises(upgrade.OwnerSessionUpgradeUnavailable):
        upgrade.upgrade_existing_owner_schema_0008(_evidence(), path=db)
    assert _versions(db) == [1, 2, 3, 5, 6]


def test_leased_stop_is_mutually_exclusive(
    docker_fixture: tuple[Path, dict[str, Any], list[tuple[str, ...]]],
) -> None:
    db, _, _ = docker_fixture
    meta = db.stat()
    first, second = _evidence(), _evidence()
    with pytest.raises(FrozenInstanceError):
        first.original_id = _OTHER  # type: ignore[misc]
    with first.exclusive_stop(database_path=db, device=meta.st_dev, inode=meta.st_ino):
        with pytest.raises(upgrade.OwnerSessionUpgradeUnavailable):
            with second.exclusive_stop(database_path=db, device=meta.st_dev, inode=meta.st_ino):
                raise AssertionError("unreachable")
    assert _versions(db) == [1, 2, 3, 5, 6]


def test_borrowed_canonical_boca_job_lease_is_reentrant_and_remains_owned(
    docker_fixture: tuple[Path, dict[str, Any], list[tuple[str, ...]]],
) -> None:
    db, _, _ = docker_fixture
    identity = db.stat()
    fd = os.open(host._LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        guard = replace(_evidence(), borrowed_lease_fd=fd)
        with guard.exclusive_stop(database_path=db, device=identity.st_dev, inode=identity.st_ino):
            assert _versions(db) == [1, 2, 3, 5, 6]
        # Closing the attestor's duplicate cannot release the outer lease.
        competitor = os.open(host._LOCK, os.O_RDWR | os.O_NOFOLLOW)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(competitor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(competitor)
    finally:
        os.close(fd)
    assert _versions(db) == [1, 2, 3, 5, 6]


@pytest.mark.parametrize("failure", ["unlocked", "wrong_inode", "other_lease_holder"])
def test_borrowed_fd_must_itself_hold_canonical_boca_lease(
    docker_fixture: tuple[Path, dict[str, Any], list[tuple[str, ...]]],
    tmp_path: Path,
    failure: str,
) -> None:
    db, _, _ = docker_fixture
    identity = db.stat()
    canonical = os.open(host._LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    borrowed = canonical
    try:
        if failure == "wrong_inode":
            borrowed = os.open(tmp_path / "foreign-borrowed.lock", os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(borrowed, fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif failure == "other_lease_holder":
            fcntl.flock(canonical, fcntl.LOCK_EX | fcntl.LOCK_NB)
            borrowed = os.open(host._LOCK, os.O_RDWR | os.O_NOFOLLOW)
        with pytest.raises(upgrade.OwnerSessionUpgradeUnavailable):
            with replace(_evidence(), borrowed_lease_fd=borrowed).exclusive_stop(
                database_path=db, device=identity.st_dev, inode=identity.st_ino
            ):
                raise AssertionError("unreachable")
    finally:
        if borrowed != canonical:
            os.close(borrowed)
        os.close(canonical)
    assert _versions(db) == [1, 2, 3, 5, 6]


def test_foreign_path_and_public_stopped_flag_cannot_trigger_upgrade(
    docker_fixture: tuple[Path, dict[str, Any], list[tuple[str, ...]]], tmp_path: Path
) -> None:
    db, _, _ = docker_fixture
    with pytest.raises(upgrade.OwnerSessionUpgradeUnavailable, match="scope"):
        upgrade.upgrade_existing_owner_schema_0008(_evidence(), path=tmp_path / "other.db")
    with pytest.raises(upgrade.OwnerSessionUpgradeUnavailable, match="evidence"):
        upgrade.upgrade_existing_owner_schema_0008(True, path=db)  # type: ignore[arg-type]
    assert _versions(db) == [1, 2, 3, 5, 6]
