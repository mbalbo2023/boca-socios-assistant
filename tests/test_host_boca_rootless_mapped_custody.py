"""R255: prove rootless subuid ownership with read-only Boca metadata."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_rootless_mapped_custody as custody

UID_MAP = b"         0      10001          1\n         1     231072      65536\n"
GID_MAP = b"         0      10001          1\n         1     296608      65536\n"


def test_maps_the_exact_container_user_not_the_host_daemon_user() -> None:
    assert custody.map_container_id(UID_MAP, 10001) == 241072
    assert custody.map_container_id(GID_MAP, 10001) == 306608


@pytest.mark.parametrize(
    "bad",
    [
        b"0 10001 1\n",  # the host daemon's rootless map says nothing about user 10001
        b"0 10001 1\n1 231072 100\n",  # user 10001 isn't mapped
        b"0 10001 1\n1 231072 65536\n1 123456 65536\n",  # overlap
        b"0 10001 1\n1 231072 65536\n5000 900000 10000\n",  # same child twice
        b"0 10001 1\n1 10001 65536\n",  # host overlap
        b"0 10001 1\n1 4294967290 65536\n",  # host overflow
        b"0 10001 1\n1 231072 0\n",  # zero range
        b"0 10001 1\n1 231072 65536\nextra\n",  # unbounded or malformed
        b"0 10001 1\n1 231072 65536\x00\n",  # binary bytes
        b"0 10001 1\n1 231072 65536",  # truncated proc line
        b"0 10001 1\n1 231072 65536\n" + b" " * 500,
        b"0 99999 1\n1 231072 65536\n",  # foreign root owner
    ],
)
def test_refuses_ambiguous_invalid_or_non_boca_uid_maps(bad: bytes) -> None:
    with pytest.raises(custody.MappedCustodyNoGo):
        custody.map_container_id(bad, 10001)


def test_reads_only_two_pinned_proc_maps_and_refuses_symlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "12345"
    directory.mkdir()
    (directory / "uid_map").write_bytes(UID_MAP)
    (directory / "gid_map").write_bytes(GID_MAP)
    monkeypatch.setattr(custody, "_PROC_ROOT", tmp_path)
    assert custody.read_proc_mapped_owner(12345) == custody.MappedOwner(241072, 306608)

    (directory / "uid_map").rename(directory / "old-uid-map")
    (directory / "uid_map").symlink_to("old-uid-map")
    with pytest.raises(custody.MappedCustodyNoGo):
        custody.read_proc_mapped_owner(12345)


def _volume(tmp_path: Path) -> tuple[Path, tuple[tuple[str, str], ...]]:
    root = tmp_path / "docker"
    entries = (
        ("boca-socios_boca_data", "boca.sqlite3"),
        ("boca-socios_boca_key", "boca_master_key"),
        ("boca-socios_boca_owner", "boca_owner_session.sqlite3"),
    )
    for volume, filename in entries:
        directory = root / "volumes" / volume / "_data"
        directory.mkdir(parents=True)
        directory.chmod(0o700)
        (directory / filename).write_bytes(b"private, never read by custody")
        (directory / filename).chmod(0o400 if volume.endswith("_key") else 0o600)
        (directory.parent).chmod(0o700)
    (root / "volumes").chmod(0o700)
    root.chmod(0o700)
    return root, entries


def test_attests_real_file_inodes_without_reading_contents(tmp_path: Path) -> None:
    root, _ = _volume(tmp_path)
    owner = custody.MappedOwner(os.geteuid(), os.getegid())
    first = custody.capture_mapped_custody(root, owner, trusted_root=root)
    assert len(first) == 3
    assert first == custody.capture_mapped_custody(root, owner, trusted_root=root)
    assert "private" not in repr(first)


@pytest.mark.parametrize("defect", ["owner", "symlink", "hardlink", "mode", "redirect"])
def test_refuses_unmapped_relinked_or_redirected_boca_file(tmp_path: Path, defect: str) -> None:
    root, entries = _volume(tmp_path)
    filename = root / "volumes" / entries[0][0] / "_data" / entries[0][1]
    owner = custody.MappedOwner(os.geteuid(), os.getegid())
    if defect == "owner":
        owner = custody.MappedOwner(os.geteuid() + 1, os.getegid())
    elif defect == "symlink":
        filename.rename(filename.with_name("other"))
        filename.symlink_to("other")
    elif defect == "hardlink":
        os.link(filename, filename.with_name("other"))
    elif defect == "mode":
        filename.chmod(0o644)
    else:
        original = filename.parent
        original.rename(original.with_name("real"))
        original.symlink_to("real", target_is_directory=True)
    with pytest.raises(custody.MappedCustodyNoGo):
        custody.capture_mapped_custody(root, owner, trusted_root=root)


def test_same_lease_observer_rechecks_pair_mapping_volumes_and_all_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = _volume(tmp_path)
    events: list[str] = []
    expected = SimpleNamespace(plan=SimpleNamespace(attempt_id="555"), controller_id="a" * 64)
    lease = cleanup.BocaJobLease("555", -1, os.getpid(), True)
    owner = custody.MappedOwner(os.geteuid(), os.getegid())
    monkeypatch.setattr(custody.runtime, "_ROOT", root)
    monkeypatch.setattr(custody.runtime, "_attest_live_pair", lambda *_: events.append("pair"))
    monkeypatch.setattr(
        custody.cleanup, "verify_protected_boca_job_lease", lambda *_: events.append("lease")
    )
    monkeypatch.setattr(
        custody, "read_controller_mapped_owner", lambda *_: events.append("map") or owner
    )

    def volume_attestor() -> None:
        events.append("volume")

    assert (
        custody.observe_boca_mapped_file_custody(expected, lease, volume_attestor)
        == "VERIFIED_MAPPED"
    )
    assert events == ["lease", "pair", "map", "volume", "volume", "map", "volume", "pair", "lease"]


def test_inode_changes_during_observation_never_produce_verified_mapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, entries = _volume(tmp_path)
    database = root / "volumes" / entries[0][0] / "_data" / entries[0][1]
    expected = SimpleNamespace(plan=SimpleNamespace(attempt_id="555"), controller_id="a" * 64)
    lease = cleanup.BocaJobLease("555", -1, os.getpid(), True)
    monkeypatch.setattr(custody.runtime, "_ROOT", root)
    monkeypatch.setattr(custody.runtime, "_attest_live_pair", lambda *_: None)
    monkeypatch.setattr(custody.cleanup, "verify_protected_boca_job_lease", lambda *_: None)
    monkeypatch.setattr(
        custody,
        "read_controller_mapped_owner",
        lambda *_: custody.MappedOwner(os.geteuid(), os.getegid()),
    )
    calls = 0

    def volume_attestor() -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            replacement = database.with_name("replacement")
            replacement.write_bytes(b"new-private-content")
            replacement.chmod(0o600)
            replacement.replace(database)

    assert custody.observe_boca_mapped_file_custody(expected, lease, volume_attestor) == "NO_GO"


def test_controller_pid_read_must_be_proven_twice_and_never_mutates_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    expected = SimpleNamespace(plan=SimpleNamespace(attempt_id="555"), controller_id="a" * 64)
    lease = cleanup.BocaJobLease("555", -1, os.getpid(), True)
    monkeypatch.setattr(custody.runtime, "_attest_live_pair", lambda *_: None)
    monkeypatch.setattr(custody.cleanup, "verify_protected_boca_job_lease", lambda *_: None)
    monkeypatch.setattr(
        custody, "read_proc_mapped_owner", lambda pid: custody.MappedOwner(241072, 306608)
    )

    def docker(*args: str) -> str:
        calls.append(args)
        return "12345\n"

    monkeypatch.setattr(custody.cleanup, "_docker", docker)
    assert custody.read_controller_mapped_owner(expected, lease) == custody.MappedOwner(
        241072, 306608
    )
    assert calls == [
        ("inspect", "--format", "{{json .State.Pid}}", "a" * 64),
        ("inspect", "--format", "{{json .State.Pid}}", "a" * 64),
    ]
