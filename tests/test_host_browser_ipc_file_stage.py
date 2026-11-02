"""Offline adversarial checks for the Boca-only, atomic browser IPC upload."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from boca_socios import host_browser_file_stage as stage

SOURCE = "c" * 40
ATTEMPT = "424242"
CONTROLLER = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64
WORKER = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "b" * 64
PAYLOADS = {
    "base": b"name: boca-socios\nservices: {}\n",
    "overlay": b"services:\n  browser-worker:\n    network_mode: none\n",
    "seccomp": b'{"defaultAction":"SCMP_ACT_ERRNO"}\n',
}
FIELDS = {
    "base": ("compose.beta.yaml", "beta_compose_sha"),
    "overlay": ("compose.beta.browser.yaml", "overlay_compose_sha"),
    "seccomp": ("seccomp_profile.json", "seccomp_sha"),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def private_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "boca-private"
    root.mkdir(mode=0o700)
    marker: dict[str, object] = {
        "version": "browser-ipc-new-only-v2",
        "attempt_id": ATTEMPT,
        "source_sha": SOURCE,
        "controller_digest": CONTROLLER,
        "browser_digest": WORKER,
        "controller_image_absent": True,
        "browser_image_absent": False,
        "bridge_absent": True,
        "ipc_volume_absent": True,
        **{field: _sha(PAYLOADS[slot]) for slot, (_, field) in FIELDS.items()},
    }
    metadata = root / stage.MARKER
    metadata.write_text(json.dumps(marker, sort_keys=True, separators=(",", ":")), encoding="ascii")
    metadata.chmod(0o600)
    monkeypatch.setattr(stage, "ROOT", root)
    return root, marker


def _as_dedicated_boca(
    callback: Callable[[], object],
    *,
    uid: int = 10001,
    uid_by_name: dict[str, int] | None = None,
) -> object:
    """Exercise real inode, hardlink, and no-follow syscalls without host UID10001."""
    real_fstat = os.fstat

    def verified_fstat(fd: int) -> os.stat_result:
        actual = list(real_fstat(fd))
        name = Path(os.readlink(f"/proc/self/fd/{fd}")).name
        actual[4] = (uid_by_name or {}).get(name, 10001)
        return os.stat_result(actual)

    with (
        patch.object(stage.os, "geteuid", return_value=uid),
        patch.object(stage.os, "fstat", side_effect=verified_fstat),
    ):
        return callback()


def _stage(slot: str, payload: bytes | None = None, **coordinates: str) -> None:
    expected_payload = PAYLOADS.get(slot, PAYLOADS["base"])
    data = expected_payload if payload is None else payload
    stage.stage_file(
        slot,
        coordinates.get("sha", _sha(expected_payload)),
        coordinates.get("attempt", ATTEMPT),
        coordinates.get("source", SOURCE),
        coordinates.get("controller", CONTROLLER),
        coordinates.get("worker", WORKER),
        io.BytesIO(data),
    )


def test_each_reviewed_file_is_installed_atomically_without_temp_residue(
    private_stage: tuple[Path, dict[str, object]],
) -> None:
    root, marker = private_stage
    for slot, (filename, _) in FIELDS.items():
        _as_dedicated_boca(lambda slot=slot: _stage(slot))
        installed = root / filename
        assert installed.read_bytes() == PAYLOADS[slot]
        assert stat.S_IMODE(installed.stat().st_mode) == 0o600
        assert not (root / f".browser-ipc-{slot}-{ATTEMPT}.part").exists()
    assert json.loads((root / stage.MARKER).read_text()) == marker
    assert sorted(path.name for path in root.iterdir()) == sorted(
        [stage.MARKER, *(name for name, _ in FIELDS.values())]
    )


@pytest.mark.parametrize(
    "tamper",
    ["symlink", "wrong-hash", "mode", "uid", "hardlink", "fifo", "directory"],
)
def test_other_slots_preexisting_final_must_be_exact_verified_regular_inode(
    private_stage: tuple[Path, dict[str, object]], tmp_path: Path, tamper: str
) -> None:
    root, _ = private_stage
    previous = root / FIELDS["base"][0]
    wrong_owner: dict[str, int] = {}
    if tamper == "symlink":
        previous.symlink_to(root / stage.MARKER)
    elif tamper == "wrong-hash":
        previous.write_bytes(b"different bytes")
        previous.chmod(0o600)
    elif tamper == "fifo":
        os.mkfifo(previous, 0o600)
    elif tamper == "directory":
        previous.mkdir(mode=0o700)
    else:
        previous.write_bytes(PAYLOADS["base"])
        previous.chmod(0o600)
        if tamper == "mode":
            previous.chmod(0o640)
        elif tamper == "uid":
            wrong_owner[previous.name] = 10002
        elif tamper == "hardlink":
            os.link(previous, tmp_path / "foreign-hardlink")
    with pytest.raises(stage.StageError):
        _as_dedicated_boca(lambda: _stage("overlay"), uid_by_name=wrong_owner)
    assert not (root / FIELDS["overlay"][0]).exists()
    assert not (root / f".browser-ipc-overlay-{ATTEMPT}.part").exists()


def test_other_slot_partial_blocks_staging_without_touching_rollback_residue(
    private_stage: tuple[Path, dict[str, object]],
) -> None:
    root, _ = private_stage
    residue = root / f".browser-ipc-base-{ATTEMPT}.part"
    residue.write_bytes(b"interrupted base upload")
    residue.chmod(0o600)
    with pytest.raises(stage.StageError):
        _as_dedicated_boca(lambda: _stage("overlay"))
    assert residue.read_bytes() == b"interrupted base upload"
    assert not (root / FIELDS["overlay"][0]).exists()
    assert not (root / f".browser-ipc-overlay-{ATTEMPT}.part").exists()


def test_fifo_marker_without_writer_fails_without_hanging(
    private_stage: tuple[Path, dict[str, object]],
) -> None:
    root, _ = private_stage
    marker = root / stage.MARKER
    marker.unlink()
    os.mkfifo(marker, 0o600)
    # The unpatched O_RDONLY open would wait forever for a FIFO writer.
    # Probe the actual standalone helper in a killable, bounded child.
    script = """
import os
import sys
from boca_socios import host_browser_file_stage as stage

dirfd = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    stage._read_marker_coordinates(dirfd, {"version": "browser-ipc-new-only-v2"}, "beta_compose_sha", "a" * 64)
except stage.StageError:
    raise SystemExit(0)
finally:
    os.close(dirfd)
raise SystemExit(1)
"""
    result = subprocess.run(  # noqa: S603 - fixed interpreter, local synthetic FIFO only
        [sys.executable, "-c", script, str(root)],
        capture_output=True,
        text=True,
        check=False,
        timeout=1,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)


@pytest.mark.parametrize("payload", [b"", b"changed", b"x" * 32_769, b"partial\x00"])
def test_bad_bytes_are_rejected_before_creating_a_file(
    private_stage: tuple[Path, dict[str, object]], payload: bytes
) -> None:
    root, _ = private_stage
    with pytest.raises(stage.StageError, match="payload"):
        _as_dedicated_boca(lambda: _stage("base", payload))
    assert {path.name for path in root.iterdir()} == {stage.MARKER}


@pytest.mark.parametrize(
    "coordinates",
    [
        {"slot": "foreign"},
        {"sha": "0" * 64},
        {"sha": "A" * 64},
        {"attempt": "0"},
        {"attempt": "001"},
        {"attempt": "1" * 21},
        {"source": "0" * 39},
        {"controller": "other-project@sha256:" + "0" * 64},
        {"controller": CONTROLLER.replace("@sha256:", ":latest-")},
        {"worker": CONTROLLER},
    ],
)
def test_invalid_host_coordinates_never_create_files(
    private_stage: tuple[Path, dict[str, object]], coordinates: dict[str, str]
) -> None:
    root, _ = private_stage
    with pytest.raises(stage.StageError):
        _as_dedicated_boca(
            lambda: _stage(
                coordinates.get("slot", "base"),
                **{key: value for key, value in coordinates.items() if key != "slot"},
            )
        )
    assert {path.name for path in root.iterdir()} == {stage.MARKER}


def test_wrong_local_uid_is_rejected_before_opening_private_directory(
    private_stage: tuple[Path, dict[str, object]],
) -> None:
    root, _ = private_stage
    with pytest.raises(stage.StageError, match="coordinates"):
        _as_dedicated_boca(lambda: _stage("base"), uid=10002)
    assert {path.name for path in root.iterdir()} == {stage.MARKER}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("version", "other-version"),
        ("attempt_id", "424243"),
        ("source_sha", "d" * 40),
        ("controller_digest", WORKER),
        ("browser_digest", CONTROLLER),
        ("beta_compose_sha", "f" * 64),
        ("overlay_compose_sha", "f" * 64),
        ("seccomp_sha", "f" * 64),
        ("controller_image_absent", 1),
        ("browser_image_absent", "false"),
        ("bridge_absent", False),
        ("ipc_volume_absent", False),
    ],
)
def test_marker_field_tampering_fails_closed(
    private_stage: tuple[Path, dict[str, object]], key: str, value: object
) -> None:
    root, marker = private_stage
    marker[key] = value
    (root / stage.MARKER).write_text(json.dumps(marker), encoding="ascii")
    # Each invocation receives only its chosen artifact hash. The other two
    # hashes are syntactically checked, then compared by their own stage calls.
    slot = next((slot for slot, (_, field) in FIELDS.items() if field == key), "base")
    with pytest.raises(stage.StageError):
        _as_dedicated_boca(lambda: _stage(slot))
    assert not (root / FIELDS[slot][0]).exists()


@pytest.mark.parametrize(
    ("slot", "other_hash"),
    [
        ("base", "seccomp_sha"),
        ("overlay", "beta_compose_sha"),
        ("seccomp", "overlay_compose_sha"),
    ],
)
def test_nonselected_hash_must_be_a_string_not_a_64_digit_json_integer(
    private_stage: tuple[Path, dict[str, object]], slot: str, other_hash: str
) -> None:
    root, marker = private_stage
    marker[other_hash] = int("1" * 64)
    (root / stage.MARKER).write_text(json.dumps(marker), encoding="ascii")
    with pytest.raises(stage.StageError, match="marker"):
        _as_dedicated_boca(lambda: _stage(slot))
    assert not (root / FIELDS[slot][0]).exists()


@pytest.mark.parametrize("malformed", ["{bad json", '{"version":1,"version":2}', "[]"])
def test_malformed_or_duplicate_marker_rejected(
    private_stage: tuple[Path, dict[str, object]], malformed: str
) -> None:
    root, _ = private_stage
    (root / stage.MARKER).write_text(malformed, encoding="ascii")
    with pytest.raises(stage.StageError):
        _as_dedicated_boca(lambda: _stage("base"))


def test_unexpected_marker_field_rejected(
    private_stage: tuple[Path, dict[str, object]],
) -> None:
    root, marker = private_stage
    marker["extra"] = "surprise"
    (root / stage.MARKER).write_text(json.dumps(marker), encoding="ascii")
    with pytest.raises(stage.StageError):
        _as_dedicated_boca(lambda: _stage("base"))


@pytest.mark.parametrize(
    "unsafe",
    ["marker-symlink", "marker-mode", "marker-uid", "root-mode", "root-uid", "root-symlink"],
)
def test_unsafe_marker_or_root_never_creates_target(
    private_stage: tuple[Path, dict[str, object]],
    unsafe: str,
    tmp_path: Path,
) -> None:
    root, _ = private_stage
    marker = root / stage.MARKER
    original = marker.read_bytes()
    uid_by_name: dict[str, int] = {}
    if unsafe == "marker-symlink":
        marker.unlink()
        other = tmp_path / "foreign"
        other.write_bytes(original)
        marker.symlink_to(other)
    elif unsafe == "marker-mode":
        marker.chmod(0o644)
    elif unsafe == "marker-uid":
        uid_by_name[stage.MARKER] = 10002
    elif unsafe == "root-mode":
        root.chmod(0o755)
    elif unsafe == "root-uid":
        uid_by_name[root.name] = 10002
    else:
        replacement = tmp_path / "replacement"
        root.rename(replacement)
        root.symlink_to(replacement, target_is_directory=True)
    with pytest.raises((stage.StageError, OSError)):
        _as_dedicated_boca(lambda: _stage("base"), uid_by_name=uid_by_name)
    assert not (root / FIELDS["base"][0]).exists()


@pytest.mark.parametrize(
    "kind", ["foreign", "preexisting-final", "final-symlink", "preexisting-part", "part-symlink"]
)
def test_foreign_or_existing_inode_cannot_be_overwritten(
    private_stage: tuple[Path, dict[str, object]], kind: str
) -> None:
    root, _ = private_stage
    final = root / FIELDS["base"][0]
    partial = root / f".browser-ipc-base-{ATTEMPT}.part"
    outsider = root / "unrelated"
    if kind == "foreign":
        outsider.write_text("foreign")
    elif kind == "preexisting-final":
        final.write_text("original")
    elif kind == "final-symlink":
        final.symlink_to(root / stage.MARKER)
    elif kind == "preexisting-part":
        partial.write_text("original")
    else:
        partial.symlink_to(root / stage.MARKER)
    with pytest.raises(stage.StageError):
        _as_dedicated_boca(lambda: _stage("base"))
    if kind == "preexisting-final":
        assert final.read_text() == "original"
    elif kind == "final-symlink":
        assert final.is_symlink()
    elif kind == "preexisting-part":
        assert partial.read_text() == "original"
    elif kind == "part-symlink":
        assert partial.is_symlink()
    else:
        assert outsider.read_text() == "foreign"


def test_interrupted_hardlink_retains_only_same_attempt_partial_for_rollback(
    private_stage: tuple[Path, dict[str, object]], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = private_stage

    def fail_link(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(stage.os, "link", fail_link)
    with pytest.raises(stage.StageError, match="atomic"):
        _as_dedicated_boca(lambda: _stage("base"))
    partial = root / f".browser-ipc-base-{ATTEMPT}.part"
    assert partial.read_bytes() == PAYLOADS["base"]
    assert stat.S_IMODE(partial.stat().st_mode) == 0o600
    assert not (root / FIELDS["base"][0]).exists()


def test_payload_file_fsync_precedes_atomic_link_and_directory_fsync_follows(
    private_stage: tuple[Path, dict[str, object]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, _ = private_stage
    events: list[str] = []
    real_fsync, real_link, real_unlink = os.fsync, os.link, os.unlink

    def fsync(fd: int) -> None:
        events.append("fsync-directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "fsync-file")
        real_fsync(fd)

    def link(*args: object, **kwargs: object) -> None:
        events.append("link")
        real_link(*args, **kwargs)

    def unlink(*args: object, **kwargs: object) -> None:
        events.append("unlink")
        real_unlink(*args, **kwargs)

    monkeypatch.setattr(stage.os, "fsync", fsync)
    monkeypatch.setattr(stage.os, "link", link)
    monkeypatch.setattr(stage.os, "unlink", unlink)
    _as_dedicated_boca(lambda: _stage("base"))
    assert events == ["fsync-file", "link", "unlink", "fsync-directory"]


def test_standalone_cli_emits_only_fixed_receipts(
    private_stage: tuple[Path, dict[str, object]], capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        _as_dedicated_boca(
            lambda: stage.main(
                ["base", _sha(PAYLOADS["base"]), ATTEMPT, SOURCE, CONTROLLER, WORKER],
                io.BytesIO(PAYLOADS["base"]),
            )
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.out == "BOCA_BROWSER_FILE_STAGE_PASS slot=base\n"
    assert captured.err == ""

    assert _as_dedicated_boca(lambda: stage.main(["invalid"], io.BytesIO(b"secret"))) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "BOCA_BROWSER_FILE_STAGE_NO_GO\n"
