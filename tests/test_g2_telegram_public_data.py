"""G2: DATA public recipient policy only; no host, Docker or provider I/O."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from boca_socios import host_telegram_status as status
from boca_socios import telegram_bootstrap as bootstrap
from boca_socios.panel import telegram_recipient as recipient_module
from boca_socios.panel.telegram_recipient import (
    FILENAME,
    publish_prepared_recipient,
    read_prepared_recipient,
)
from test_r309_telegram_prepare_diagnose import (
    ADMIN,
    FINGERPRINT,
    PUBLIC,
    ProgramFS,
    admin_document,
    canonical,
    execute_program,
    public_document,
)

SOURCE = "a" * 40
INSTALLATION = "b" * 64


def _prepared_data(tmp_path, monkeypatch, *, mode: int):
    data = tmp_path / "data"
    data.mkdir()
    data.chmod(mode)
    monkeypatch.setattr(bootstrap, "UID", os.geteuid())
    monkeypatch.setattr(recipient_module, "PUBLIC_DATA_DIR", data, raising=False)
    recipient = bootstrap._receipt(b"\x11" * 32, "PREPARED")
    return data, recipient


@pytest.mark.parametrize("mode", [0o700, 0o755])
def test_recipient_public_data_read_write_idempotent_with_exact_modes(tmp_path, monkeypatch, mode):
    data, recipient = _prepared_data(tmp_path, monkeypatch, mode=mode)
    for _ in range(2):
        publish_prepared_recipient(
            data, recipient, source_sha=SOURCE, installation_fingerprint=INSTALLATION
        )
    assert read_prepared_recipient(data, expected_source_sha=SOURCE) == recipient
    assert (data / FILENAME).stat().st_mode & 0o777 == 0o400


@pytest.mark.parametrize("mode", [0o750, 0o777])
def test_public_data_rejects_nonallowlisted_parent_mode(tmp_path, monkeypatch, mode):
    data, recipient = _prepared_data(tmp_path, monkeypatch, mode=mode)
    with pytest.raises(bootstrap.BootstrapError, match="telegram_directory_unsafe"):
        publish_prepared_recipient(
            data, recipient, source_sha=SOURCE, installation_fingerprint=INSTALLATION
        )
    assert not (data / FILENAME).exists()


@pytest.mark.parametrize("candidate", ["custody", "foreign"])
def test_public_data_rejects_other_absolute_paths_before_any_io(tmp_path, monkeypatch, candidate):
    data, recipient = _prepared_data(tmp_path, monkeypatch, mode=0o755)
    forbidden = tmp_path / "other" if candidate == "foreign" else Path("/run/telegram")
    if candidate == "foreign":
        forbidden.mkdir(mode=0o755)
        forbidden.chmod(0o755)

    def forbidden_io(*args, **kwargs):
        pytest.fail("no file descriptor, read or write may precede DATA path rejection")

    with monkeypatch.context() as scope:
        for name in ("open", "read", "write"):
            scope.setattr(os, name, forbidden_io)
        scope.setattr(bootstrap, "_read", forbidden_io)
        scope.setattr(bootstrap, "_write_new", forbidden_io)
        with pytest.raises(bootstrap.BootstrapError, match="telegram_directory_unsafe"):
            read_prepared_recipient(forbidden, expected_source_sha=SOURCE)
        with pytest.raises(bootstrap.BootstrapError, match="telegram_directory_unsafe"):
            publish_prepared_recipient(
                forbidden,
                recipient,
                source_sha=SOURCE,
                installation_fingerprint=INSTALLATION,
            )
    assert not (data / FILENAME).exists()


def test_public_data_rejects_wrong_owner_and_unmapped_host_actor(tmp_path, monkeypatch):
    data, recipient = _prepared_data(tmp_path, monkeypatch, mode=0o755)
    monkeypatch.setattr(bootstrap, "UID", os.geteuid() + 1)
    with pytest.raises(bootstrap.BootstrapError, match="dedicated_identity_required"):
        publish_prepared_recipient(
            data, recipient, source_sha=SOURCE, installation_fingerprint=INSTALLATION
        )
    with monkeypatch.context() as scope:
        scope.setattr(bootstrap, "_identity", lambda uid: None)
        with pytest.raises(bootstrap.BootstrapError, match="telegram_directory_unsafe"):
            publish_prepared_recipient(
                data, recipient, source_sha=SOURCE, installation_fingerprint=INSTALLATION
            )


def test_public_data_rejects_parent_symlink_and_stat_drift(tmp_path, monkeypatch):
    data, recipient = _prepared_data(tmp_path, monkeypatch, mode=0o755)
    real_stat = os.stat
    observations = 0

    def drift(path, *args, **kwargs):
        nonlocal observations
        result = real_stat(path, *args, **kwargs)
        if path == "data" and kwargs.get("dir_fd") is not None:
            observations += 1
            if observations == 1:
                data.chmod(0o777)
        return result

    with monkeypatch.context() as scope:
        scope.setattr(os, "stat", drift)
        with pytest.raises(bootstrap.BootstrapError, match="telegram_directory_unsafe"):
            publish_prepared_recipient(
                data, recipient, source_sha=SOURCE, installation_fingerprint=INSTALLATION
            )
    assert observations >= 2
    data.chmod(0o755)
    data.rmdir()
    data.symlink_to(tmp_path)
    with pytest.raises(bootstrap.BootstrapError, match="telegram_directory_unsafe"):
        publish_prepared_recipient(
            data, recipient, source_sha=SOURCE, installation_fingerprint=INSTALLATION
        )


@pytest.mark.parametrize("damage", ["mode", "link", "nlink", "size", "parse", "conflict"])
def test_public_data_preserves_strict_leaf_and_conflict_contract(tmp_path, monkeypatch, damage):
    data, recipient = _prepared_data(tmp_path, monkeypatch, mode=0o755)
    publish_prepared_recipient(
        data, recipient, source_sha=SOURCE, installation_fingerprint=INSTALLATION
    )
    path = data / FILENAME
    if damage == "mode":
        path.chmod(0o600)
    elif damage == "link":
        path.unlink()
        path.symlink_to("never-read-target")
    elif damage == "nlink":
        os.link(path, data / "same-inode")
    elif damage == "size":
        path.chmod(0o600)
        path.write_bytes(b"x" * 1025)
        path.chmod(0o400)
    elif damage == "parse":
        path.chmod(0o600)
        path.write_bytes(b'{"version":2,"version":2}')
        path.chmod(0o400)
    elif damage == "conflict":
        another = bootstrap._receipt(b"\x22" * 32, "PREPARED")
        with pytest.raises(ValueError, match="telegram_public_recipient_conflict"):
            publish_prepared_recipient(
                data, another, source_sha=SOURCE, installation_fingerprint=INSTALLATION
            )
        assert read_prepared_recipient(data, expected_source_sha=SOURCE) == recipient
        return
    with pytest.raises((ValueError, bootstrap.BootstrapError)):
        read_prepared_recipient(data, expected_source_sha=SOURCE)


def test_installed_public_observer_reads_0755_without_touching_private_custody(
    tmp_path, monkeypatch
):
    fs = ProgramFS(tmp_path)
    fs.data.chmod(0o755)
    fs.write(PUBLIC, canonical(public_document()))
    fs.write(ADMIN, canonical(admin_document()) + b"\n")
    observed, raw = execute_program(status, "PUBLIC_OBSERVE_PROGRAM", fs, monkeypatch)
    assert observed["recipient"]["state"] == observed["admin"]["state"] == "VALID"
    assert observed["recipient"]["fingerprint"] == FINGERPRINT
    assert fs.secret_reads == [] and b"bot_token" not in raw


@pytest.mark.parametrize("mode", [0o750, 0o777])
def test_installed_public_observer_rejects_unsafe_data_modes(tmp_path, monkeypatch, mode):
    fs = ProgramFS(tmp_path)
    fs.data.chmod(mode)
    fs.write(PUBLIC, canonical(public_document()))
    observed, _ = execute_program(status, "PUBLIC_OBSERVE_PROGRAM", fs, monkeypatch)
    assert observed["recipient"]["state"] == "INVALID"
    assert PUBLIC not in fs.opens


def test_installed_public_observer_rejects_host_actor_even_if_metadata_mapped(
    tmp_path, monkeypatch
):
    fs = ProgramFS(tmp_path)
    fs.data.chmod(0o755)
    fs.write(PUBLIC, canonical(public_document()))
    output = io.BytesIO()
    with monkeypatch.context() as scope:
        fs.install(scope)  # stat/fstat expose mapped UID/GID=10001
        for name in ("getuid", "geteuid", "getgid", "getegid"):
            scope.setattr(os, name, lambda: 1000)
        scope.setattr(sys, "stdout", SimpleNamespace(buffer=output))
        exec(  # noqa: S102 - same isolated, fixed image literal as existing R309 tests
            compile(status.PUBLIC_OBSERVE_PROGRAM, "<fixed-installed-public-program>", "exec"),
            {"__name__": "__main__"},
        )
    assert __import__("json").loads(output.getvalue())["recipient"]["state"] == "NOT_READ"
    assert PUBLIC not in fs.opens
