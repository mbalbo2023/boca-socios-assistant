"""R311: literal installed program observes only metadata, never document bytes."""

from __future__ import annotations

import errno
import os

import pytest

from boca_socios import host_telegram_status as status
from test_r309_telegram_prepare_diagnose import ADMIN, PUBLIC, ProgramFS, execute_program


def _sample(fs, monkeypatch):
    value, raw = execute_program(status, "BOUNDARY_OBSERVE_PROGRAM", fs, monkeypatch)
    status._boundary_check_sample(value)
    assert b"secret" not in raw and b"key" not in raw.lower()
    assert all(name not in fs.opens for name in (PUBLIC, ADMIN))
    assert not fs.secret_reads and not fs.scan_counts
    return value


def test_parent_invalid_never_attempts_either_leaf(tmp_path, monkeypatch):
    fs = ProgramFS(tmp_path)
    fs.data.chmod(0o755)
    fs.stat_fault = lambda name: (
        pytest.fail("a leaf was reached") if name in (PUBLIC, ADMIN) else None
    )
    value = _sample(fs, monkeypatch)
    assert value["parent"]["state"] == "INVALID"
    assert value["parent"]["checks"]["mode"] == "FAIL"
    assert value["parent"]["mode_octal"] == "0755"
    assert {value[name]["state"] for name in ("recipient", "admin")} == {"NOT_ATTEMPTED"}
    assert fs.opens == ["/"]


def test_parent_absent_still_skips_leaves_without_false_leaf_absence(tmp_path, monkeypatch):
    fs = ProgramFS(tmp_path)
    fs.data.rmdir()
    value = _sample(fs, monkeypatch)
    assert value["parent"]["state"] == "ABSENT"
    assert value["parent"]["witness"] is None
    assert value["parent"]["mode_octal"] is None
    assert value["parent"]["controller_search"] == "NOT_READ"
    assert value["recipient"]["state"] == value["admin"]["state"] == "NOT_ATTEMPTED"
    assert fs.opens == ["/"]


def test_valid_metadata_does_not_claim_valid_parsing(tmp_path, monkeypatch):
    fs = ProgramFS(tmp_path)
    fs.write(PUBLIC, b"secret-invalid-json", mode=0o400)
    fs.write(ADMIN, b"secret-invalid-json", mode=0o600)
    value = _sample(fs, monkeypatch)
    assert value["parent"]["state"] == "VALID"
    assert value["parent"]["mode_octal"] == "0700"
    for name in ("recipient", "admin"):
        assert value[name]["state"] == "METADATA_VALID_PARSE_UNVERIFIED"
        assert set(value[name]["checks"].values()) == {"PASS"}
        assert len(value[name]["witness"]) == 64
    assert fs.opens == ["/", "data"]


@pytest.mark.parametrize("damage", ["mode", "size-zero", "size-oversize", "symlink", "hardlink"])
def test_leaf_invalid_flags_without_opening_document(tmp_path, monkeypatch, damage):
    fs = ProgramFS(tmp_path)
    leaf = fs.write(PUBLIC, b"secret", mode=0o400)
    if damage == "mode":
        leaf.chmod(0o600)
    elif damage == "size-zero":
        leaf.chmod(0o600)
        leaf.write_bytes(b"")
        leaf.chmod(0o400)
    elif damage == "size-oversize":
        leaf.chmod(0o600)
        leaf.write_bytes(b"x" * 1025)
        leaf.chmod(0o400)
    elif damage == "symlink":
        leaf.unlink()
        leaf.symlink_to("another")
    else:
        os.link(leaf, fs.data / "second")
    value = _sample(fs, monkeypatch)
    assert value["parent"]["state"] == "VALID"
    assert value["recipient"]["state"] == "INVALID"
    failed = {
        "mode": "mode",
        "size-zero": "size",
        "size-oversize": "size",
        "symlink": "type",
        "hardlink": "nlink",
    }[damage]
    assert value["recipient"]["checks"][failed] == "FAIL"


@pytest.mark.parametrize("name,kind", [(PUBLIC, "recipient"), (ADMIN, "admin")])
def test_enoent_alone_is_absent_under_valid_parent(tmp_path, monkeypatch, name, kind):
    fs = ProgramFS(tmp_path)
    value = _sample(fs, monkeypatch)
    assert value["parent"]["state"] == "VALID"
    assert value[kind]["state"] == "ABSENT"
    assert len(value[kind]["witness"]) == 64


@pytest.mark.parametrize("fault", [errno.EACCES, errno.EIO, errno.ELOOP])
def test_leaf_operating_error_is_not_absent(tmp_path, monkeypatch, fault):
    fs = ProgramFS(tmp_path)
    fs.write(PUBLIC, b"secret", mode=0o400)
    fs.stat_fault = lambda name: (
        (_ for _ in ()).throw(OSError(fault, "private")) if name == PUBLIC else None
    )
    value = _sample(fs, monkeypatch)
    assert value["parent"]["state"] == "VALID"
    assert value["recipient"]["state"] in {"NOT_READ", "CHANGED"}
    assert value["recipient"]["state"] != "ABSENT"


def test_fd_and_name_parent_mismatch_aborts_leaf(tmp_path, monkeypatch):
    fs = ProgramFS(tmp_path)
    fs.write(PUBLIC, b"secret", mode=0o400)
    changed = False

    def mutate_on_directory_open(name, _flags):
        nonlocal changed
        if name == "data" and not changed:
            changed = True
            fs.data.chmod(0o750)

    fs.open_fault = mutate_on_directory_open
    value = _sample(fs, monkeypatch)
    assert value["parent"]["state"] == "CHANGED"
    assert value["parent"]["mode_octal"] is None
    assert value["parent"]["controller_search"] == "NOT_READ"
    assert value["recipient"]["state"] == "NOT_ATTEMPTED"


def test_leaf_identity_changed_within_one_snapshot(tmp_path, monkeypatch):
    fs = ProgramFS(tmp_path)
    leaf = fs.write(PUBLIC, b"secret", mode=0o400)
    count = 0

    def mutate_on_second_stat(name):
        nonlocal count
        if name == PUBLIC:
            count += 1
            if count == 2:
                leaf.chmod(0o600)
                leaf.write_bytes(b"changed")
                leaf.chmod(0o400)

    fs.stat_fault = mutate_on_second_stat
    value = _sample(fs, monkeypatch)
    assert value["recipient"]["state"] == "CHANGED"
    assert value["recipient"]["witness"] is None


def test_no_private_io_expressions_in_literal():
    program = status.BOUNDARY_OBSERVE_PROGRAM
    for forbidden in (
        "sqlite",
        "_read(",
        "_document(",
        "parse_telegram",
        "listdir(",
        "scandir(",
        "send(",
        "subprocess",
    ):
        assert forbidden not in program
    assert "'data'" in program and "follow_symlinks=False" in program


@pytest.mark.parametrize(
    "mode,search_ok,supported,expected",
    [
        (0o700, True, True, "PASS"),
        (0o755, True, True, "PASS"),
        (0o755, False, True, "FAIL"),
        (0o755, True, False, "NOT_READ"),
    ],
)
def test_r313_effective_search_is_literal_root_fd_and_supported_only(
    tmp_path, monkeypatch, mode, search_ok, supported, expected
):
    fs = ProgramFS(tmp_path)
    fs.data.chmod(mode)
    calls = []

    def access(name, requested, *, dir_fd=None, effective_ids=False, follow_symlinks=True):
        calls.append((name, requested, dir_fd, effective_ids, follow_symlinks))
        return search_ok

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "access", access)
        for marker in ("supports_dir_fd", "supports_effective_ids", "supports_follow_symlinks"):
            items = set(getattr(os, marker))
            if supported:
                items.add(access)
            scoped.setattr(os, marker, items)
        value = _sample(fs, scoped)
    parent = value["parent"]
    assert parent["mode_octal"] == f"{mode:04o}"
    assert parent["checks"]["mode"] == ("PASS" if mode == 0o700 else "FAIL")
    assert parent["controller_search"] == expected
    if supported:
        assert len(calls) == 1
        assert calls[0][0:2] == ("data", os.X_OK)
        assert isinstance(calls[0][2], int)
        assert calls[0][3:] == (True, False)
    else:
        assert calls == []
    if mode != 0o700:
        assert parent["state"] == "INVALID"
        assert value["recipient"]["state"] == "NOT_ATTEMPTED"


def test_r313_symlink_parent_never_tests_search_or_leaves(tmp_path, monkeypatch):
    fs = ProgramFS(tmp_path)
    fs.data.rmdir()
    fs.data.symlink_to("another")

    def forbidden(*_args, **_kwargs):
        pytest.fail("ineligible parent must not test search")

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "access", forbidden)
        value = _sample(fs, scoped)
    assert value["parent"]["checks"]["type"] == "FAIL"
    assert value["parent"]["controller_search"] == "NOT_READ"
    assert value["recipient"]["state"] == value["admin"]["state"] == "NOT_ATTEMPTED"


@pytest.mark.parametrize(
    "missing_capability",
    ["supports_dir_fd", "supports_effective_ids", "supports_follow_symlinks"],
)
def test_r313_each_missing_access_capability_is_not_read(tmp_path, monkeypatch, missing_capability):
    fs = ProgramFS(tmp_path)

    def forbidden(*_args, **_kwargs):
        pytest.fail("unsupported access must not be invoked")

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "access", forbidden)
        for name in ("supports_dir_fd", "supports_effective_ids", "supports_follow_symlinks"):
            supported = set(getattr(os, name))
            if name != missing_capability:
                supported.add(forbidden)
            scoped.setattr(os, name, supported)
        value = _sample(fs, scoped)
    assert value["parent"]["mode_octal"] == "0700"
    assert value["parent"]["controller_search"] == "NOT_READ"


def test_r313_access_error_is_not_read_without_leaf_reads(tmp_path, monkeypatch):
    fs = ProgramFS(tmp_path)

    def broken(*_args, **_kwargs):
        raise OSError(errno.EACCES, "access denied")

    with monkeypatch.context() as scoped:
        scoped.setattr(os, "access", broken)
        for name in ("supports_dir_fd", "supports_effective_ids", "supports_follow_symlinks"):
            scoped.setattr(os, name, set(getattr(os, name)) | {broken})
        value = _sample(fs, scoped)
    assert value["parent"]["state"] == "VALID"
    assert value["parent"]["controller_search"] == "NOT_READ"
    assert PUBLIC not in fs.opens and ADMIN not in fs.opens
