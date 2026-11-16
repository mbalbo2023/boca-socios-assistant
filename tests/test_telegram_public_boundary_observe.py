"""R311: literal installed program observes only metadata, never document bytes."""

from __future__ import annotations

import errno
import os

import pytest

from boca_socios import host_telegram_status as status
from test_r309_telegram_prepare_diagnose import ADMIN, PUBLIC, ProgramFS, execute_program


def _sample(fs, monkeypatch):
    value, raw = execute_program(status, "BOUNDARY_OBSERVE_PROGRAM", fs, monkeypatch)
    assert b"secret" not in raw and b"key" not in raw.lower()
    assert all(name not in fs.opens for name in (PUBLIC, ADMIN))
    assert not fs.secret_reads and not fs.scan_counts
    return value


def test_parent_invalid_never_attempts_either_leaf(tmp_path, monkeypatch):
    fs = ProgramFS(tmp_path)
    fs.data.chmod(0o755)
    fs.stat_fault = lambda name: pytest.fail("a leaf was reached") if name in (PUBLIC, ADMIN) else None
    value = _sample(fs, monkeypatch)
    assert value["parent"]["state"] == "INVALID"
    assert value["parent"]["checks"]["mode"] == "FAIL"
    assert {value[name]["state"] for name in ("recipient", "admin")} == {"NOT_ATTEMPTED"}
    assert fs.opens == ["/"]


def test_valid_metadata_does_not_claim_valid_parsing(tmp_path, monkeypatch):
    fs = ProgramFS(tmp_path)
    fs.write(PUBLIC, b"secret-invalid-json", mode=0o400)
    fs.write(ADMIN, b"secret-invalid-json", mode=0o600)
    value = _sample(fs, monkeypatch)
    assert value["parent"]["state"] == "VALID"
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
    fs.stat_fault = (
        lambda name: (_ for _ in ()).throw(OSError(fault, "private"))
        if name == PUBLIC else None
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
    for forbidden in ("sqlite", "_read(", "_document(", "parse_telegram", "listdir(", "scandir(", "send(", "subprocess"):
        assert forbidden not in program
    assert "'data'" in program and "follow_symlinks=False" in program
