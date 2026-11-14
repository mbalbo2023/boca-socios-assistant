"""R124: bounded Boca-only linger diagnosis, no Docker or host mutation."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from test_ci_parallel_pytest_contract import assert_required_ci_covers

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import boca_linger_readonly as probe  # noqa: E402 - source-layout script


def test_identity_gate_fails_before_any_host_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(probe.os, "getuid", lambda: 1000)
    with (
        patch.object(probe.pwd, "getpwuid") as account,
        patch.object(probe.subprocess, "run") as command,
        patch.object(probe.os, "open") as read,
    ):
        assert probe.main() == 1
    account.assert_not_called()
    command.assert_not_called()
    read.assert_not_called()


def test_identity_requires_exact_dedicated_account_and_gid(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, group, home in (
        ("other", 10001, "/home/boca-deploy"),
        ("boca-deploy", 10002, "/home/boca-deploy"),
        ("boca-deploy", 10001, "/home/../home"),
        ("boca-deploy", 10001, "/srv/porota"),
        ("boca-deploy", 10001, "/etc"),
        ("boca-deploy", 10001, "/home/boca-deploy-other"),
    ):
        monkeypatch.setattr(probe.os, "getuid", lambda: 10001)
        monkeypatch.setattr(probe.os, "geteuid", lambda: 10001)
        monkeypatch.setattr(probe.os, "getgid", lambda: 10001)
        monkeypatch.setattr(probe.os, "getegid", lambda: 10001)
        with patch.object(
            probe.pwd,
            "getpwuid",
            return_value=SimpleNamespace(pw_name=name, pw_gid=group, pw_dir=home),
        ):
            with pytest.raises(probe.IdentityError):
                probe._dedicated_home()


def test_foreign_home_fails_before_any_metadata_read(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("getuid", "geteuid", "getgid", "getegid"):
        monkeypatch.setattr(probe.os, name, lambda: 10001)
    with (
        patch.object(
            probe.pwd,
            "getpwuid",
            return_value=SimpleNamespace(pw_name="boca-deploy", pw_gid=10001, pw_dir="/srv/porota"),
        ),
        patch.object(probe, "_fixed_metadata") as stat_host,
        patch.object(probe, "_linger") as loginctl,
        patch.object(probe, "_subids") as subids,
    ):
        assert probe.main() == 1
    stat_host.assert_not_called()
    loginctl.assert_not_called()
    subids.assert_not_called()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("yes\n", "YES"),
        ("no\n", "NO"),
        ("YES\n", "UNKNOWN"),
        ("yes\nno\n", "UNKNOWN"),
        ("", "UNKNOWN"),
        ("yes\nsecret-sentinel", "UNKNOWN"),
    ],
)
def test_linger_requires_exact_systemd_answer(raw: str, expected: str) -> None:
    with patch.object(
        probe.subprocess,
        "run",
        return_value=SimpleNamespace(returncode=0, stdout=raw),
    ) as command:
        assert probe._linger() == expected
    args, kwargs = command.call_args
    assert args == (
        (
            "/usr/bin/loginctl",
            "--no-ask-password",
            "show-user",
            "10001",
            "--property=Linger",
            "--value",
        ),
    )
    assert kwargs["timeout"] == 5
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert kwargs["env"] == {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}


def test_linger_failures_are_unknown_without_raw_output() -> None:
    for exception in (OSError("secret-sentinel"), subprocess.TimeoutExpired("loginctl", 5)):
        with patch.object(probe.subprocess, "run", side_effect=exception):
            assert probe._linger() == "UNKNOWN"


def test_linger_denied_reply_is_unknown_without_exposing_stderr() -> None:
    with patch.object(
        probe.subprocess,
        "run",
        return_value=SimpleNamespace(returncode=1, stdout="secret-sentinel\n"),
    ):
        assert probe._linger() == "UNKNOWN"


def test_subordinate_ids_only_accept_one_valid_boca_allocation() -> None:
    assert probe._parse_subids("other:100000:65536\nboca-deploy:175536:65536\n") == "VALID"
    assert probe._parse_subids("10001:175536:65536\nother:250000:65536\n") == "VALID"
    for text in (
        "other:175536:65536\n",
        "boca-deploy:175536:10\n",
        "boca-deploy:175536:65536\n10001:175536:65536\n",
        "boca-deploy:175536:bad\n",
        "boca-deploy:4294967294:65536\n",
        "boca-deploy:-1:65536\n",
        "boca-deploy:10001:65536\n",
    ):
        assert probe._parse_subids(text) == "INVALID"


def test_subid_reader_rejects_untrusted_file_before_read() -> None:
    for mode, owner in ((0o100666, 0), (0o100644, 2000), (0o40755, 0)):
        with (
            patch.object(probe.os, "open", return_value=42) as opening,
            patch.object(
                probe.os,
                "fstat",
                return_value=SimpleNamespace(st_mode=mode, st_uid=owner, st_size=100),
            ),
            patch.object(probe.os, "read") as reading,
            patch.object(probe.os, "close"),
        ):
            assert probe._subids("subuid") == "UNKNOWN"
        opening.assert_called_once_with(
            "/etc/subuid", probe.os.O_RDONLY | probe.os.O_NOFOLLOW | probe.os.O_CLOEXEC
        )
        reading.assert_not_called()


def test_subid_reader_parses_only_dedicated_account_rows() -> None:
    with (
        patch.object(probe.os, "open", return_value=42),
        patch.object(
            probe.os,
            "fstat",
            return_value=SimpleNamespace(st_mode=0o100644, st_uid=0, st_size=50),
        ),
        patch.object(
            probe.os,
            "read",
            return_value=b"other:100000:65536\nboca-deploy:175536:65536\n",
        ) as reading,
        patch.object(probe.os, "close"),
    ):
        assert probe._subids("subgid") == "VALID"
    reading.assert_called_once_with(42, probe.MAX_SUBID_BYTES + 1)
    assert probe._subids("other") == "UNKNOWN"


def test_file_metadata_rejects_symlinks_and_unknown_permissions(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir()
    regular = private / "marker"
    regular.write_text("")
    (private / "link").symlink_to(regular)
    assert probe._fixed_metadata(private / "link").state == "UNSAFE"
    assert probe._fixed_metadata(private / "missing").state == "ABSENT"
    assert probe._fixed_metadata(private / "marker").state == "REGULAR"
    with patch.object(probe.os, "open", side_effect=PermissionError("secret-sentinel")):
        assert probe._fixed_metadata(regular).state == "UNAVAILABLE"


def test_safe_path_blocks_parent_traversal_and_absolute_symlinks(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir()
    (private / "link").symlink_to(tmp_path)
    assert probe._fixed_metadata(private / "link" / "secret").state == "UNSAFE"
    assert probe._fixed_metadata(Path("/home/../etc/passwd")).state == "UNSAFE"


def test_uidmap_binary_is_only_metadata_not_execution() -> None:
    for metadata, permitted, expected in (
        (probe.Metadata("REGULAR", 0, 0, 0o4755), True, "AVAILABLE"),
        (probe.Metadata("REGULAR", 0, 0, 0o777), True, "UNKNOWN"),
        (probe.Metadata("UNSAFE"), True, "UNKNOWN"),
        (probe.Metadata("ABSENT"), False, "UNAVAILABLE"),
    ):
        with (
            patch.object(probe, "_fixed_metadata", return_value=metadata),
            patch.object(probe.os, "access", return_value=permitted),
            patch.object(probe.subprocess, "run") as command,
        ):
            assert probe._binary("newuidmap") == expected
        command.assert_not_called()


def test_user_namespaces_zero_means_disabled() -> None:
    with (
        patch.object(probe.os, "open", return_value=43),
        patch.object(probe.os, "read", return_value=b"0\n"),
        patch.object(probe.os, "close"),
    ):
        assert probe._userns() == "DISABLED"


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        (probe.Metadata("DIRECTORY", 10001, 10001, 0o710), "OWNER_0710"),
        (probe.Metadata("DIRECTORY", 10001, 10001, 0o700), "PRIVATE"),
        (probe.Metadata("DIRECTORY", 10001, 10001, 0o711), "UNSAFE"),
        (probe.Metadata("DIRECTORY", 10001, 10001, 0o750), "UNSAFE"),
        (probe.Metadata("DIRECTORY", 10001, 10001, 0o720), "UNSAFE"),
        (probe.Metadata("DIRECTORY", 10001, 10001, 0o777), "UNSAFE"),
        (probe.Metadata("DIRECTORY", 10001, 166523, 0o710), "UNSAFE"),
        (probe.Metadata("DIRECTORY", 0, 10001, 0o710), "UNSAFE"),
        (probe.Metadata("SOCKET", 10001, 10001, 0o710), "SOCKET"),
        (probe.Metadata("ABSENT"), "ABSENT"),
    ],
)
def test_docker_root_mode_is_not_home_runtime_mode(metadata: probe.Metadata, expected: str) -> None:
    assert probe._docker_root_dir(metadata) == expected


def test_docker_data_root_default_mode_does_not_create_false_unsafe() -> None:
    home = probe.Metadata("DIRECTORY", 10001, 10001, 0o700)
    engine_root = probe.Metadata("DIRECTORY", 10001, 10001, 0o710)
    socket = probe.Metadata("SOCKET", 10001, 166523, 0o660)
    with (
        patch.object(probe, "_dedicated_home", return_value=Path("/home/boca-deploy")),
        patch.object(probe, "_linger", return_value="YES"),
        patch.object(
            probe,
            "_fixed_metadata",
            side_effect=[
                home,
                home,
                socket,
                socket,
                socket,
                probe.Metadata("REGULAR", 0, 0, 0o644),
                engine_root,
                probe.Metadata("REGULAR", 10001, 10001, 0o600),
            ],
        ),
        patch.object(probe, "_subids", side_effect=["VALID", "VALID"]),
        patch.object(probe, "_binary", return_value="AVAILABLE"),
        patch.object(probe, "_userns", return_value="AVAILABLE"),
    ):
        lines, state = probe.collect()
    assert state == "METADATA_CANDIDATE"
    assert "data_root=OWNER_0710" in "\n".join(lines)
    assert "data_mode=0710" in "\n".join(lines)


def test_collect_reports_metadata_only_without_docker_calls() -> None:
    owned = probe.Metadata("DIRECTORY", 10001, 10001, 0o700)
    sock = probe.Metadata("SOCKET", 10001, 166523, 0o660)
    with (
        patch.object(probe, "_dedicated_home", return_value=Path("/home/boca-deploy")),
        patch.object(probe, "_linger", return_value="YES"),
        patch.object(
            probe,
            "_fixed_metadata",
            side_effect=[
                owned,
                owned,
                sock,
                sock,
                sock,
                probe.Metadata("REGULAR", 0, 0, 0o644),
                owned,
                probe.Metadata("REGULAR", 10001, 10001, 0o600),
            ],
        ),
        patch.object(probe, "_subids", side_effect=["VALID", "VALID"]),
        patch.object(probe, "_binary", return_value="AVAILABLE"),
        patch.object(probe, "_userns", return_value="AVAILABLE"),
        patch.object(probe.subprocess, "run") as command,
    ):
        lines, state = probe.collect()
    command.assert_not_called()
    report = "\n".join(lines)
    assert state == "METADATA_CANDIDATE"
    assert "linger=YES" in report
    assert "docker_socket=OWNED" in report
    assert "docker_gid=166523" in report
    assert "data_root=PRIVATE" in report
    assert "unit=REGULAR" in report
    assert "marker_uid=0" in report
    assert "subuid=VALID subgid=VALID" in report
    assert "docker_queries=0 changes=NONE" in report
    assert "boca-deploy" not in report


def test_linger_no_never_becomes_go_without_host_change() -> None:
    owned = probe.Metadata("DIRECTORY", 10001, 10001, 0o700)
    sock = probe.Metadata("SOCKET", 10001, 166523, 0o660)
    with (
        patch.object(probe, "_dedicated_home", return_value=Path("/home/boca-deploy")),
        patch.object(probe, "_linger", return_value="NO"),
        patch.object(
            probe,
            "_fixed_metadata",
            side_effect=[
                owned,
                owned,
                sock,
                sock,
                sock,
                probe.Metadata("ABSENT"),
                probe.Metadata("ABSENT"),
                probe.Metadata("ABSENT"),
            ],
        ),
        patch.object(probe, "_subids", side_effect=["VALID", "VALID"]),
        patch.object(probe, "_binary", return_value="AVAILABLE"),
        patch.object(probe, "_userns", return_value="AVAILABLE"),
    ):
        lines, state = probe.collect()
    assert state == "PREREQUISITES_UNPROVEN"
    assert "linger=NO" in "\n".join(lines)


def test_public_socket_mode_never_qualifies_as_metadata_candidate() -> None:
    owned = probe.Metadata("DIRECTORY", 10001, 10001, 0o700)
    private_socket = probe.Metadata("SOCKET", 10001, 166523, 0o660)
    public_socket = probe.Metadata("SOCKET", 10001, 166523, 0o777)
    assert probe._socket(public_socket) == "OPEN_MODE"
    with (
        patch.object(probe, "_dedicated_home", return_value=Path("/home/boca-deploy")),
        patch.object(probe, "_linger", return_value="YES"),
        patch.object(
            probe,
            "_fixed_metadata",
            side_effect=[
                owned,
                owned,
                private_socket,
                private_socket,
                public_socket,
                probe.Metadata("REGULAR", 0, 0, 0o644),
                owned,
                probe.Metadata("REGULAR", 10001, 10001, 0o600),
            ],
        ),
        patch.object(probe, "_subids", side_effect=["VALID", "VALID"]),
        patch.object(probe, "_binary", return_value="AVAILABLE"),
        patch.object(probe, "_userns", return_value="AVAILABLE"),
    ):
        lines, state = probe.collect()
    assert state == "PREREQUISITES_UNPROVEN"
    assert "docker_socket=OPEN_MODE" in "\n".join(lines)


def test_systemd_default_0666_is_informational_with_private_runtime() -> None:
    owned = probe.Metadata("DIRECTORY", 10001, 10001, 0o700)
    systemd_bus = probe.Metadata("SOCKET", 10001, 10001, 0o666)
    docker = probe.Metadata("SOCKET", 10001, 166523, 0o660)
    with (
        patch.object(probe, "_dedicated_home", return_value=Path("/home/boca-deploy")),
        patch.object(probe, "_linger", return_value="YES"),
        patch.object(
            probe,
            "_fixed_metadata",
            side_effect=[
                owned,
                owned,
                systemd_bus,
                systemd_bus,
                docker,
                probe.Metadata("REGULAR", 0, 0, 0o644),
                owned,
                probe.Metadata("REGULAR", 10001, 10001, 0o600),
            ],
        ),
        patch.object(probe, "_subids", side_effect=["VALID", "VALID"]),
        patch.object(probe, "_binary", return_value="AVAILABLE"),
        patch.object(probe, "_userns", return_value="AVAILABLE"),
    ):
        lines, state = probe.collect()
    assert state == "METADATA_CANDIDATE"
    assert "manager=SYSTEMD_DEFAULT" in "\n".join(lines)
    assert "bus=SYSTEMD_DEFAULT" in "\n".join(lines)


def test_systemd_default_0666_does_not_mask_unsafe_runtime() -> None:
    owned = probe.Metadata("DIRECTORY", 10001, 10001, 0o700)
    bad_runtime = probe.Metadata("DIRECTORY", 10001, 10001, 0o755)
    systemd_bus = probe.Metadata("SOCKET", 10001, 10001, 0o666)
    docker = probe.Metadata("SOCKET", 10001, 166523, 0o660)
    with (
        patch.object(probe, "_dedicated_home", return_value=Path("/home/boca-deploy")),
        patch.object(probe, "_linger", return_value="YES"),
        patch.object(
            probe,
            "_fixed_metadata",
            side_effect=[
                owned,
                bad_runtime,
                systemd_bus,
                systemd_bus,
                docker,
                probe.Metadata("REGULAR", 0, 0, 0o644),
                owned,
                probe.Metadata("REGULAR", 10001, 10001, 0o600),
            ],
        ),
        patch.object(probe, "_subids", side_effect=["VALID", "VALID"]),
        patch.object(probe, "_binary", return_value="AVAILABLE"),
        patch.object(probe, "_userns", return_value="AVAILABLE"),
    ):
        lines, state = probe.collect()
    assert state == "PREREQUISITES_UNPROVEN"
    assert "runtime=UNSAFE" in "\n".join(lines)


def test_owner_without_socket_write_permission_is_not_candidate() -> None:
    assert probe._socket(probe.Metadata("SOCKET", 10001, 10001, 0o400)) == "NO_OWNER_WRITE"


def test_workflow_uses_only_existing_readonly_selector() -> None:
    workflow = Path(".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    header = workflow.split("      - name: Inspect Boca linger metadata without Docker", 1)
    assert len(header) == 2
    step = header[1].split("      - name:", 1)[0]
    assert "inputs.operation == 'inspect-prerequisites'" in step
    assert "id: boca_linger_metadata" in step
    assert "< scripts/boca_linger_readonly.py" in step
    assert "timeout --signal=TERM --kill-after=5s 30s ssh" in step
    assert "ulimit -f 16 && timeout" in step
    assert "python3 -I -S -" in step
    assert "verify_boca_linger_receipt.py" in step
    assert ' > "$receipt" 2>/dev/null' in step
    assert workflow.index("Inspect Boca linger metadata without Docker") < workflow.index(
        "Inspect dedicated user prerequisites without Docker"
    )
    inspector = workflow.split(
        "      - name: Inspect dedicated user prerequisites without Docker", 1
    )[1]
    inspector = inspector.split("      - name:", 1)[0]
    assert "steps.boca_linger_metadata.outcome == 'success'" in inspector
    assert "steps.boca_linger_metadata.outputs.candidate" in workflow
    assert_required_ci_covers(
        "tests/test_r124_linger_readonly.py",
        "tests/test_r124_linger_receipt_verify.py",
    )
    assert not any(
        word in step
        for word in ("sudo ", "docker ", "enable-linger", "systemctl --user start", "compose up")
    )
