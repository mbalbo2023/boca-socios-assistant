"""A guarded test shutdown may stop Boca containers, never an unknown workload."""

from __future__ import annotations

import io
import json
import os
import subprocess
import textwrap
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from boca_socios import host_rootless_setup as host

CHECKS = TestCase()
HOME = Path("/home/boca-deploy")
SHA = "a" * 40
CONTAINER = "a" * 64
UNKNOWN = "b" * 64


def _info(count: int) -> str:
    return json.dumps(
        {
            "SecurityOptions": ["name=rootless"],
            "DockerRootDir": str(HOME.joinpath(*host.DATA)),
            "CgroupVersion": "2",
            "CgroupDriver": "systemd",
            "Driver": "overlay2",
            "Containers": count,
        }
    )


def _inspect(container_id: str, *, service: str = "controller", running: bool = True) -> str:
    return json.dumps(
        {
            "Id": container_id,
            "Name": f"/boca-socios-{service}-1",
            "Config": {
                "Labels": {
                    "com.docker.compose.project": "boca-socios",
                    "com.docker.compose.service": service,
                    "com.docker.compose.container-number": "1",
                }
            },
            "State": {"Running": running},
        }
    )


def test_unknown_container_fails_before_any_stop() -> None:
    with patch.object(
        host,
        "_command",
        side_effect=[
            _info(2),
            f"{CONTAINER}\n{UNKNOWN}",
            _inspect(CONTAINER),
            _inspect(UNKNOWN, service="other"),
        ],
    ) as command:
        with CHECKS.assertRaisesRegex(host.SetupError, "unknown_container_preserved_no_stop"):
            host._stop_test_containers(HOME)
    assert all("stop" not in call.args for call in command.call_args_list)


def test_inventory_count_mismatch_or_nonrootless_metadata_fails_closed() -> None:
    for responses in (
        [_info(2), CONTAINER],
        [json.dumps({"SecurityOptions": "name=rootless", "Containers": 0})],
    ):
        with patch.object(host, "_command", side_effect=responses) as command:
            with CHECKS.assertRaises(host.SetupError):
                host._stop_test_containers(HOME)
        assert all("stop" not in call.args for call in command.call_args_list)


def test_only_validated_running_container_is_stopped_and_verified() -> None:
    with patch.object(
        host,
        "_command",
        side_effect=[
            _info(2),
            f"{CONTAINER}\n{UNKNOWN}",
            _inspect(CONTAINER),
            _inspect(UNKNOWN, service="browser", running=False),
            CONTAINER,
            _inspect(CONTAINER, running=False),
            _inspect(UNKNOWN, service="browser", running=False),
            _info(2),
            f"{CONTAINER}\n{UNKNOWN}",
        ],
    ) as command:
        assert host._stop_test_containers(HOME) == 1
    stops = [call.args for call in command.call_args_list if "stop" in call.args]
    assert stops == [
        (
            HOME,
            "/usr/bin/docker",
            "--host=unix:///run/user/10001/docker.sock",
            "stop",
            "--time",
            "10",
            CONTAINER,
        )
    ]


def test_new_container_after_stops_blocks_daemon_stop() -> None:
    with patch.object(
        host,
        "_command",
        side_effect=[
            _info(1),
            CONTAINER,
            _inspect(CONTAINER),
            CONTAINER,
            _inspect(CONTAINER, running=False),
            _info(2),
            f"{CONTAINER}\n{UNKNOWN}",
        ],
    ) as command:
        with CHECKS.assertRaisesRegex(host.SetupError, "inventory_changed_no_daemon_stop"):
            host._stop_test_containers(HOME)
    assert [call.args[3] for call in command.call_args_list if "stop" in call.args] == ["stop"]


def test_failed_container_stop_never_reports_success() -> None:
    with patch.object(
        host,
        "_command",
        side_effect=[
            _info(1),
            CONTAINER,
            _inspect(CONTAINER),
            host.SetupError("private_daemon_metadata_failed_exit_1"),
        ],
    ):
        with CHECKS.assertRaises(host.SetupError):
            host._stop_test_containers(HOME)


def test_stopped_service_is_idempotent_and_does_not_start_daemon() -> None:
    with (
        patch.object(host, "_identity", return_value=HOME),
        patch.object(
            host,
            "_directory",
            side_effect=[os.open("/dev/null", os.O_RDONLY), os.open("/dev/null", os.O_RDONLY)],
        ),
        patch.object(host, "_socket"),
        patch.object(host.os, "access", return_value=False),
        patch.object(host, "_read_private"),
        patch.object(host, "_stop_service_state", return_value="inactive"),
        patch.object(host, "_entry", return_value=None),
        patch.object(host, "_stop_test_containers") as containers,
        patch.object(host, "_command") as command,
        redirect_stdout(io.StringIO()) as output,
    ):
        host.stop_test(SHA)
    containers.assert_not_called()
    command.assert_not_called()
    assert f"state=ALREADY_STOPPED source_sha={SHA}" in output.getvalue()


def test_daemon_only_state_stops_verified_service_and_preserves_data() -> None:
    with (
        patch.object(host, "_identity", return_value=HOME),
        patch.object(
            host,
            "_directory",
            side_effect=[os.open("/dev/null", os.O_RDONLY), os.open("/dev/null", os.O_RDONLY)],
        ),
        patch.object(host, "_socket"),
        patch.object(host.os, "access", return_value=False),
        patch.object(host, "_read_private") as private,
        patch.object(host, "_stop_service_state", side_effect=["active", "inactive"]),
        patch.object(host, "_entry", return_value=None),
        patch.object(host, "_stop_test_containers", return_value=0) as containers,
        patch.object(host, "_command") as command,
        redirect_stdout(io.StringIO()) as output,
    ):
        host.stop_test(SHA)
    assert private.call_count == 2
    containers.assert_called_once_with(HOME)
    command.assert_called_once_with(
        HOME, "/usr/bin/systemctl", "--user", "stop", "docker.service", timeout=35
    )
    assert f"state=STOPPED source_sha={SHA} containers=0 data=preserved" in output.getvalue()


def test_daemon_stop_failure_has_no_success_receipt() -> None:
    with (
        patch.object(host, "_identity", return_value=HOME),
        patch.object(
            host,
            "_directory",
            side_effect=[os.open("/dev/null", os.O_RDONLY), os.open("/dev/null", os.O_RDONLY)],
        ),
        patch.object(host, "_socket"),
        patch.object(host.os, "access", return_value=False),
        patch.object(host, "_read_private"),
        patch.object(host, "_stop_service_state", return_value="active"),
        patch.object(host, "_stop_test_containers", return_value=0),
        patch.object(
            host, "_command", side_effect=host.SetupError("user_service_stop_failed_exit_1")
        ),
        redirect_stdout(io.StringIO()) as output,
    ):
        with CHECKS.assertRaises(host.SetupError):
            host.stop_test(SHA)
    assert "state=STOPPED" not in output.getvalue()


def test_private_config_symlink_is_rejected_without_reading_target() -> None:
    with TemporaryDirectory() as root:
        parent = Path(root)
        (parent / "docker.service").symlink_to("/etc/passwd")
        with patch.object(
            host,
            "_directory",
            side_effect=lambda *_args, **_kwargs: os.open(parent, os.O_RDONLY | os.O_DIRECTORY),
        ):
            with CHECKS.assertRaisesRegex(host.SetupError, "configuration_unavailable"):
                host._read_private(parent, ("docker.service",), "expected")


def test_stop_workflow_has_same_protected_mutex_and_blank_release_coordinates() -> None:
    workflow = Path(".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    gate = workflow.split(
        "      - name: Require verified protected environment and matching main commit\n", 1
    )[1].split("      - name:", 1)[0]
    script = textwrap.dedent(gate.split("        run: |\n", 1)[1])
    env = {
        "PATH": "/usr/bin:/bin",
        "GITHUB_RUN_ATTEMPT": "1",
        "BOCA_SOURCE_SHA": SHA,
        "GITHUB_SHA": SHA,
        "BOCA_SERVICE": "controller",
        "BOCA_BUDGET": "0.5cpu-256m-64pids",
        "BOCA_OPERATION": "stop-test",
        "BOCA_HOST_READONLY_ENV_READY": "",
        "BOCA_DEPLOY_ENV_READY": "ready",
        "BOCA_IMAGE_REF": "",
        "BOCA_RELEASE_RUN_ID": "",
    }

    def run() -> int:
        return subprocess.run(
            ["/usr/bin/bash", "-e", "-o", "pipefail"],
            input=script,
            text=True,
            capture_output=True,
            env=env,
            timeout=3,
            check=False,
        ).returncode  # noqa: S603

    assert run() == 0
    env["BOCA_IMAGE_REF"] = "digest"
    assert run() != 0
    env["BOCA_IMAGE_REF"] = ""
    env["BOCA_DEPLOY_ENV_READY"] = ""
    env["BOCA_HOST_READONLY_ENV_READY"] = "ready"
    assert run() != 0
    assert "|| 'boca-first-deploy'" in workflow
    assert "Recheck current main before stopping Boca tests" in workflow
    assert "python3 - stop-test" in workflow
