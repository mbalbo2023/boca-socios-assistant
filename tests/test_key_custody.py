"""Owner-only key creation and inspection without third-party traffic."""

import base64
import os
import stat
from pathlib import Path

import pytest

from boca_socios.security import key_custody


def _test_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    # The production container requires its volume root to be namespace UID 0;
    # a pytest temp directory belongs to the unprivileged runner instead.
    monkeypatch.setattr(
        key_custody,
        "_directory",
        lambda path: os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW),
    )


def test_initialization_creates_one_0400_key_and_never_replaces_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _test_directory(monkeypatch)
    monkeypatch.setattr(key_custody.os, "geteuid", lambda: 0)
    owners: list[tuple[int, int]] = []
    monkeypatch.setattr(key_custody.os, "fchown", lambda _fd, uid, gid: owners.append((uid, gid)))
    key = tmp_path / "boca_master_key"
    key_custody.initialize(key)
    first = key.read_bytes()
    assert len(base64.b64decode(first.strip(), validate=True)) == 32
    assert stat.S_IMODE(key.stat().st_mode) == 0o400
    assert owners == [(10001, 10001)]
    with pytest.raises(ValueError, match="not empty"):
        key_custody.initialize(key)
    assert key.read_bytes() == first


def test_initialization_rejects_symlink_without_touching_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _test_directory(monkeypatch)
    monkeypatch.setattr(key_custody.os, "geteuid", lambda: 0)
    target = tmp_path / "target"
    target.write_text("unchanged")
    (tmp_path / "boca_master_key").symlink_to(target)
    with pytest.raises(ValueError, match="not empty"):
        key_custody.initialize(tmp_path / "boca_master_key")
    assert target.read_text() == "unchanged"


def test_initialization_rejects_nonempty_key_volume(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _test_directory(monkeypatch)
    monkeypatch.setattr(key_custody.os, "geteuid", lambda: 0)
    (tmp_path / "unexpected").write_text("keep")
    with pytest.raises(ValueError, match="not empty"):
        key_custody.initialize(tmp_path / "boca_master_key")
    assert not (tmp_path / "boca_master_key").exists()


def test_inspection_rejects_unowned_key_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _test_directory(monkeypatch)
    monkeypatch.setattr(key_custody.os, "geteuid", lambda: 10001)
    key = tmp_path / "boca_master_key"
    key.write_bytes(base64.b64encode(os.urandom(32)) + b"\n")
    key.chmod(0o444)
    with pytest.raises(ValueError, match="metadata"):
        key_custody.inspect(key)


def test_key_errors_do_not_print_key_or_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["key_custody", "init"])
    monkeypatch.setattr(
        key_custody, "initialize", lambda: (_ for _ in ()).throw(ValueError("secret-value"))
    )
    assert key_custody.main() == 1
    output = capsys.readouterr()
    assert "secret-value" not in output.err
    assert output.out == ""
