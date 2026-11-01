"""Rootless service preparation is exclusive, bounded and never application install."""

import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from boca_socios import host_rootless_setup as setup

CHECKS = TestCase()
SHA = "a" * 40


def test_subordinate_ids_require_one_sufficient_dedicated_range() -> None:
    assert setup._subordinate_ids("other:1:10\nboca-deploy:100000:65536\n") == (100000, 65536)
    for raw in ("", "boca-deploy:100000:1", "boca-deploy:10001:65536", "10001:x:65536",
                "boca-deploy:100000:65536\n10001:200000:65536"):
        with CHECKS.assertRaises(setup.SetupError):
            setup._subordinate_ids(raw)


def test_reviewed_unit_has_fixed_scope_no_retries_and_clean_environment() -> None:
    unit = setup._unit()
    assert "ExecStart=/usr/bin/env -i " in unit
    assert "/usr/bin/dockerd-rootless.sh --config-file=%h/.config/docker/daemon.json" in unit
    assert "Restart=no" in unit and "Delegate=yes" in unit
    assert "WantedBy=default.target" in unit
    assert "sudo" not in unit and "Requires=" not in unit
    assert "unix:path=/run/user/10001/bus" in unit
    config = json.loads(setup._config(Path("/home/boca-deploy")))
    assert config["hosts"] == ["unix:///run/user/10001/docker.sock"]
    assert config["data-root"] == "/home/boca-deploy/.local/share/docker"
    assert config["features"] == {"containerd-snapshotter": False}


def test_directory_walk_rejects_symlinks_double_root_and_foreign_owner() -> None:
    with TemporaryDirectory() as root:
        home = Path(root)
        (home / "link").symlink_to("/", target_is_directory=True)
        def owned(fd: int) -> SimpleNamespace:
            resolved = Path(os.readlink(f"/proc/self/fd/{fd}"))
            uid = 10001 if resolved == home or resolved.is_relative_to(home) else 0
            return SimpleNamespace(st_uid=uid, st_mode=0o40700)

        with patch.object(setup.os, "fstat", side_effect=owned):
            with CHECKS.assertRaisesRegex(setup.SetupError, "inaccessible_or_redirected"):
                setup._directory(home, ("link",), create=False)
        with patch.object(setup.os, "open") as opened:
            with CHECKS.assertRaises(setup.SetupError):
                setup._directory(Path("/" + root), (), create=False)
        opened.assert_not_called()


def test_foreign_anchor_is_rejected_and_all_acquired_descriptors_close() -> None:
    with TemporaryDirectory() as root:
        home = Path(root)
        original_open, original_close = os.open, os.close

        def foreign_anchor(fd: int) -> SimpleNamespace:
            resolved = Path(os.readlink(f"/proc/self/fd/{fd}"))
            return SimpleNamespace(st_uid=10002 if resolved == home else 0, st_mode=0o40700)

        with (
            patch.object(setup.os, "fstat", side_effect=foreign_anchor),
            patch.object(setup.os, "open", wraps=original_open) as opened,
            patch.object(setup.os, "close", wraps=original_close) as closed,
        ):
            with CHECKS.assertRaisesRegex(setup.SetupError, "owner_or_mode"):
                setup._directory(home, (), create=False)
        assert opened.call_count == closed.call_count


def test_write_exclusive_preserves_existing_configuration() -> None:
    with TemporaryDirectory() as root:
        parent = Path(root)
        target = parent / "daemon.json"
        target.write_text("preserve-existing")
        fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        with patch.object(setup, "_directory", return_value=fd):
            with CHECKS.assertRaises(FileExistsError):
                setup._write_new(parent, ("daemon.json",), "replacement")
        assert target.read_text() == "preserve-existing"


def test_readonly_check_cannot_write_start_enable_or_probe_database() -> None:
    with (
        patch.object(setup, "_preflight", return_value=Path("/home/boca-deploy")),
        patch.object(setup, "_namespace_smoke") as smoke,
        patch.object(setup, "_write_new") as write,
        patch.object(setup, "_enable_new") as enable,
        patch.object(setup, "_command") as command,
        redirect_stdout(io.StringIO()) as output,
    ):
        setup.prepare("check", SHA)
    write.assert_not_called()
    enable.assert_not_called()
    command.assert_not_called()
    smoke.assert_not_called()
    assert "state=PREPARED_FOR_REVIEW" in output.getvalue()


def test_failed_preflight_has_no_effectful_action() -> None:
    with (
        patch.object(setup, "_preflight", side_effect=setup.SetupError("linger_required")),
        patch.object(setup, "_write_new") as write,
        patch.object(setup, "_command") as command,
    ):
        with CHECKS.assertRaises(setup.SetupError):
            setup.prepare("apply", SHA)
    write.assert_not_called()
    command.assert_not_called()


def test_unit_effective_override_blocks_before_service_start() -> None:
    with (
        patch.object(setup, "_preflight", return_value=Path("/home/boca-deploy")),
        patch.object(setup, "_namespace_smoke"),
        patch.object(setup, "_write_new"),
        patch.object(setup, "_command", return_value="DropInPaths=unexpected") as command,
        patch.object(setup, "_enable_new") as enable,
    ):
        with CHECKS.assertRaises(setup.SetupError):
            setup.prepare("apply", SHA)
    enable.assert_not_called()
    assert not any("start" in call.args for call in command.call_args_list)


def test_apply_starts_only_own_unit_then_requires_strict_postflight() -> None:
    home = Path("/home/boca-deploy")
    effective = f"FragmentPath={home}/.config/systemd/user/docker.service\nDropInPaths=\n"
    with (
        patch.object(setup, "_preflight", return_value=home),
        patch.object(setup, "_namespace_smoke"),
        patch.object(setup, "_write_new") as write,
        patch.object(setup, "_command", return_value=effective) as command,
        patch.object(setup, "_enable_new") as enable,
        patch.object(setup, "_postflight") as postflight,
        redirect_stdout(io.StringIO()) as output,
    ):
        setup.prepare("apply", SHA)
    assert write.call_count == 2
    enable.assert_called_once_with(home)
    postflight.assert_called_once_with(home)
    assert [call.args[1:] for call in command.call_args_list] == [
        ("/usr/bin/dockerd", "--validate", f"--config-file={home}/.config/docker/daemon.json"),
        ("/usr/bin/systemctl", "--user", "daemon-reload"),
        ("/usr/bin/systemctl", "--user", "show", "docker.service", "--property=FragmentPath,DropInPaths"),
        ("/usr/bin/systemctl", "--user", "start", "docker.service"),
    ]
    assert "state=SERVICE_READY" in output.getvalue()


def test_postflight_rejects_malformed_rootless_and_container_count_evidence() -> None:
    home = Path("/home/boca-deploy")
    valid = {
        "SecurityOptions": ["name=rootless"], "CgroupVersion": "2", "CgroupDriver": "systemd",
        "Driver": "overlay2", "DockerRootDir": str(home.joinpath(*setup.DATA)), "Containers": 0,
    }
    for changes in ({"SecurityOptions": "name=rootless"}, {"SecurityOptions": ["name=rootless", 1]}, {"Containers": False}):
        with (
            patch.object(setup, "_socket"),
            patch.object(setup.os, "access", return_value=False),
            patch.object(setup, "_command", side_effect=["ActiveState=active\nSubState=running", json.dumps({**valid, **changes})]),
        ):
            with CHECKS.assertRaisesRegex(setup.SetupError, "boundary_unproven"):
                setup._postflight(home)


def test_postflight_failure_stops_only_new_service_and_preserves_files() -> None:
    home = Path("/home/boca-deploy")
    effective = f"FragmentPath={home}/.config/systemd/user/docker.service\nDropInPaths=\n"
    with (
        patch.object(setup, "_preflight", return_value=home),
        patch.object(setup, "_namespace_smoke"),
        patch.object(setup, "_write_new"),
        patch.object(setup, "_enable_new"),
        patch.object(setup, "_command", return_value=effective) as command,
        patch.object(setup, "_postflight", side_effect=setup.SetupError("rootless_unproven")),
        patch.object(setup.os, "unlink") as unlink,
    ):
        with CHECKS.assertRaises(setup.SetupError):
            setup.prepare("apply", SHA)
    assert command.call_args.args[1:] == ("/usr/bin/systemctl", "--user", "stop", "docker.service")
    unlink.assert_not_called()


def test_workflow_setup_has_existing_mutation_gate_and_final_main_recheck() -> None:
    workflow = Path(".github/workflows/boca-first-deploy.yml").read_text()
    assert "prepare-rootless)" in workflow
    branch = workflow.split("prepare-rootless)", 1)[1].split(";;", 1)[0]
    assert 'test "$BOCA_DEPLOY_ENV_READY" = ready' in branch
    assert 'test -z "$BOCA_IMAGE_REF"' in branch
    assert "BOCA_ROOTLESS_SETUP_ENV_READY" not in workflow
    assert "Recheck current main before preparing dedicated rootless service" in workflow
    assert "host_rootless_setup.py" in workflow
