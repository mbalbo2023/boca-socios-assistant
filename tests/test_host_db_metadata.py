"""Fixed candidate metadata never opens a database or follows a symlink."""

import errno
import io
import os
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from boca_socios import host_first_deploy as host

CHECKS = TestCase()


def _owned_fstat(fd: int) -> SimpleNamespace:
    return SimpleNamespace(st_uid=10001, st_mode=0o40700)


def test_candidate_presence_reads_only_file_metadata_and_closes_descriptors() -> None:
    with TemporaryDirectory() as root:
        anchor = Path(root)
        database = anchor / "boca.sqlite3"
        database.write_bytes(b"private-content-must-not-be-read")
        actual_open = os.open
        actual_close = os.close
        with (
            patch.object(host.os, "fstat", side_effect=_owned_fstat),
            patch.object(host.os, "open", wraps=actual_open) as opened,
            patch.object(host.os, "close", wraps=actual_close) as closed,
            patch.object(Path, "read_bytes", side_effect=AssertionError("content read")),
            patch.object(Path, "read_text", side_effect=AssertionError("content read")),
            patch.object(host.subprocess, "run", side_effect=AssertionError("subprocess")),
        ):
            assert host._candidate_file_metadata(database, anchor) == (
                "candidate-present",
                database.stat().st_size,
            )
        assert opened.call_count == closed.call_count
        for call in opened.call_args_list:
            assert call.args[0] != "boca.sqlite3"
            assert call.args[1] & os.O_PATH
            assert call.args[1] & os.O_NOFOLLOW
            assert call.args[1] & os.O_DIRECTORY
            assert not call.args[1] & (os.O_CREAT | os.O_WRONLY | os.O_RDWR)


def test_candidate_absence_and_permission_error_are_distinct() -> None:
    with TemporaryDirectory() as root:
        anchor = Path(root)
        with patch.object(host.os, "fstat", side_effect=_owned_fstat):
            assert host._candidate_file_metadata(anchor / "missing", anchor) == (
                "candidate-absent",
                None,
            )
        for error, expected in (
            (PermissionError(errno.EACCES, "private-path"), "inaccessible"),
            (OSError(errno.EIO, "private-path"), "unavailable"),
        ):
            with patch.object(host.os, "open", side_effect=error):
                assert host._candidate_file_metadata(anchor / "missing", anchor) == (
                    expected,
                    None,
                )


def test_candidate_rejects_symlink_in_every_parent_and_at_leaf() -> None:
    with TemporaryDirectory() as root:
        base = Path(root)
        real = base / "real"
        real.mkdir()
        (real / "boca.sqlite3").write_bytes(b"private")
        alias = base / "alias"
        alias.symlink_to(real, target_is_directory=True)
        with patch.object(host.os, "fstat", side_effect=_owned_fstat):
            for anchor in (base, alias):
                assert host._candidate_file_metadata(alias / "boca.sqlite3", anchor) == (
                    "unsafe-path",
                    None,
                )
            (real / "linked.sqlite3").symlink_to(real / "boca.sqlite3")
            assert host._candidate_file_metadata(real / "linked.sqlite3", real) == (
                "unsafe-path",
                None,
            )
            assert host._candidate_file_metadata(real, base) == ("not-regular", None)


def test_candidate_refuses_foreign_or_writable_anchor_and_path_escape() -> None:
    with TemporaryDirectory() as root:
        anchor = Path(root)
        for uid, mode in ((10002, 0o40700), (10001, 0o40777)):
            with patch.object(
                host.os, "fstat", return_value=SimpleNamespace(st_uid=uid, st_mode=mode)
            ):
                assert host._candidate_file_metadata(anchor / "boca.sqlite3", anchor) == (
                    "unsafe-path",
                    None,
                )
        with patch.object(host.os, "open") as opened:
            for candidate in (Path("relative"), anchor / ".." / "foreign", Path("/elsewhere")):
                assert host._candidate_file_metadata(candidate, anchor) == ("unsafe-path", None)
        opened.assert_not_called()


def test_candidate_rejects_directory_replaced_by_symlink_without_following() -> None:
    with TemporaryDirectory() as root:
        anchor = Path(root)
        (anchor / "parent").mkdir()
        actual_open = os.open

        def swapped_open(path: str, flags: int, *, dir_fd: int | None = None) -> int:
            if path == "parent":
                (anchor / "parent").rmdir()
                (anchor / "parent").symlink_to("/", target_is_directory=True)
            return actual_open(path, flags, dir_fd=dir_fd)

        with (
            patch.object(host.os, "open", side_effect=swapped_open),
            patch.object(host.os, "fstat", side_effect=_owned_fstat),
        ):
            assert host._candidate_file_metadata(anchor / "parent" / "boca.sqlite3", anchor) == (
                "unsafe-path",
                None,
            )


def test_db_receipt_is_fixed_bounded_and_never_claims_global_absence() -> None:
    with (
        patch.object(host, "_require_dedicated_identity", return_value=10001),
        patch.object(host.pwd, "getpwuid", return_value=SimpleNamespace(pw_dir="/home/private")),
        patch.object(
            host, "_candidate_file_metadata", return_value=("candidate-absent", None)
        ) as probe,
    ):
        receipt = host._database_candidate_metadata()
    assert receipt.startswith("BOCA_DB_CANDIDATES location=UNVERIFIED scope=fixed_paths_only")
    assert len(receipt) < 1500
    assert "/home/private" not in receipt
    assert probe.call_count == 9
    expected = (
        Path("/home/private/.local/share/docker/volumes/boca-socios_boca_data/_data/boca.sqlite3"),
        Path("/srv/boca-socios/boca.sqlite3"),
        Path("/srv/boca-socios/data/boca.sqlite3"),
    )
    assert [call.args[0] for call in probe.call_args_list] == [
        Path(str(path) + suffix) for path in expected for suffix in ("", "-wal", "-shm")
    ]
    assert receipt.count("candidate-absent") == 9


def test_db_metadata_validates_identity_before_any_path_probe() -> None:
    with (
        patch.object(host, "_require_dedicated_identity", side_effect=host.PreflightError("uid")),
        patch.object(host.pwd, "getpwuid") as account,
        patch.object(host, "_candidate_file_metadata") as probe,
    ):
        with CHECKS.assertRaises(host.PreflightError):
            host._database_candidate_metadata()
    account.assert_not_called()
    probe.assert_not_called()


def test_invalid_home_is_redacted_without_probing_arbitrary_location() -> None:
    for home in ("/", "relative", "/home/../foreign", "", None):
        with (
            patch.object(host, "_require_dedicated_identity", return_value=10001),
            patch.object(host.pwd, "getpwuid", return_value=SimpleNamespace(pw_dir=home)),
            patch.object(host, "_candidate_file_metadata") as probe,
        ):
            receipt = host._database_candidate_metadata()
        assert "location=UNVERIFIED" in receipt
        assert "rootless_default db=unavailable" in receipt
        probe.assert_not_called()


def test_db_receipt_precedes_socket_failure_without_relaxing_readiness() -> None:
    with (
        patch.object(host, "_require_dedicated_identity", return_value=10001),
        patch.object(host, "_safe_dir", return_value=False),
        patch.object(host, "_socket_state", return_value="absent"),
        patch.object(Path, "read_text", return_value="cpu memory pids"),
        patch.object(host, "_rootless_service_metadata", return_value="BOCA_ROOTLESS_SERVICE stub"),
        patch.object(host, "_database_candidate_metadata", return_value="BOCA_DB_CANDIDATES stub"),
        redirect_stdout(io.StringIO()) as output,
    ):
        with CHECKS.assertRaises(host.PreflightError):
            host.inspect_prerequisites()
    assert "state=PREREQUISITES_UNPROVEN" in output.getvalue()
    assert output.getvalue().endswith("BOCA_DB_CANDIDATES stub\n")
