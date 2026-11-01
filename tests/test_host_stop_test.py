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
IMAGE_ID = "sha256:" + "c" * 64
IMAGE_REF = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64


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


def _telegram_inspect(container_id: str, *, running: bool = True) -> dict[str, object]:
    record = json.loads(_inspect(container_id, service="telegram", running=running))
    record["Image"] = IMAGE_ID
    record["Config"]["Image"] = IMAGE_REF
    record["Config"]["Cmd"] = ["python", "-m", "boca_socios.notify.telegram_worker", "serve"]
    record["Config"]["User"] = "10001:10001"
    record["Config"]["Labels"]["org.opencontainers.image.revision"] = SHA
    return record


def _telegram_image() -> dict[str, object]:
    return {
        "Id": IMAGE_ID,
        "RepoDigests": [IMAGE_REF],
        "Config": {"Labels": {"org.opencontainers.image.revision": SHA}, "Env": []},
    }


def _telegram_test_inspect(container_id: str, *, running: bool = True) -> dict[str, object]:
    record = _telegram_inspect(container_id, running=running)
    record["Name"] = "/boca-socios-telegram-test-1"
    record["Config"]["Labels"]["com.docker.compose.service"] = "telegram-test"
    record["Config"]["Cmd"] = [
        "python",
        "-m",
        "boca_socios.telegram_one_shot",
        "test",
        SHA,
        "12345",
        "e" * 64,
    ]
    record["Config"]["Entrypoint"] = None
    record["Config"]["WorkingDir"] = "/app"
    record["Config"]["Env"] = [
        "BOCA_ENVIRONMENT=staging",
        "BOCA_RUNTIME_MODE=simulation",
        "BOCA_ENGINE_MODE=off",
        "BOCA_TELEGRAM_DISPATCH_MODE=explicit",
    ]
    record["Config"]["Healthcheck"] = {
        "Test": ["NONE"],
        "Interval": 30_000_000_000,
        "Timeout": 5_000_000_000,
        "StartPeriod": 15_000_000_000,
        "Retries": 3,
    }
    record["HostConfig"] = {
        "NanoCpus": 250_000_000,
        "Memory": 134_217_728,
        "PidsLimit": 32,
        "ReadonlyRootfs": True,
        "Privileged": False,
        "PublishAllPorts": False,
        "PortBindings": {},
        "NetworkMode": host.TELEGRAM_TEST_NETWORK,
        "CapDrop": ["ALL"],
        "CapAdd": None,
        "SecurityOpt": ["no-new-privileges"],
        "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=8m"},  # noqa: S108 - private container
    }
    record["Mounts"] = [
        {"Type": kind, "Name": name, "Destination": dest, "RW": writable, "Driver": driver}
        for kind, name, dest, writable, driver in host.TELEGRAM_TEST_MOUNTS
    ]
    record["NetworkSettings"] = {
        "Ports": {},
        "Networks": {host.TELEGRAM_TEST_NETWORK: {}} if running else {},
    }
    return record


def _telegram_test_network(container_id: str) -> str:
    return json.dumps(
        {
            "Name": host.TELEGRAM_TEST_NETWORK,
            "Driver": "bridge",
            "Scope": "local",
            "Internal": False,
            "Attachable": False,
            "Ingress": False,
            "Labels": {
                "com.docker.compose.project": "boca-socios",
                "com.docker.compose.network": "telegram_egress",
            },
            "Containers": {container_id: {}},
        }
    )


def test_known_disposable_telegram_test_can_be_stopped_after_cli_timeout() -> None:
    with patch.object(
        host,
        "_command",
        side_effect=[
            _info(2),
            f"{CONTAINER}\n{UNKNOWN}",
            _inspect(CONTAINER),
            json.dumps(_telegram_test_inspect(UNKNOWN)),
            _telegram_test_network(UNKNOWN),
            json.dumps(_telegram_image()),
            CONTAINER,
            UNKNOWN,
            _inspect(CONTAINER, running=False),
            json.dumps(_telegram_test_inspect(UNKNOWN, running=False)),
            _info(2),
            f"{CONTAINER}\n{UNKNOWN}",
        ],
    ) as command:
        assert host._stop_test_containers(HOME) == 2
    assert [call.args[-1] for call in command.call_args_list if call.args[3] == "stop"] == [
        CONTAINER,
        UNKNOWN,
    ]


def test_unreviewed_one_shot_command_cannot_stop_any_container() -> None:
    for changed in (
        ["python", "-m", "boca_socios.telegram_one_shot", "test", SHA, "12345", "bad"],
        ["python", "-m", "boca_socios.telegram_one_shot", "test", "f" * 40, "12345", "e" * 64],
        ["sh", "-c", "send another message"],
    ):
        record = _telegram_test_inspect(UNKNOWN)
        record["Config"]["Cmd"] = changed
        with patch.object(
            host,
            "_command",
            side_effect=[
                _info(2),
                f"{CONTAINER}\n{UNKNOWN}",
                _inspect(CONTAINER),
                json.dumps(record),
            ],
        ) as command:
            with CHECKS.assertRaisesRegex(host.SetupError, "unknown_container_preserved_no_stop"):
                host._stop_test_containers(HOME)
        assert all("stop" not in invocation.args for invocation in command.call_args_list)


def test_one_shot_foreign_mount_network_or_budget_blocks_every_stop() -> None:
    for location, key, value in (
        ("Mounts", None, [{"Type": "bind", "Source": "/unrelated"}]),
        ("HostConfig", "NetworkMode", "host"),
        ("HostConfig", "NanoCpus", 2_000_000_000),
        ("HostConfig", "PortBindings", {"80/tcp": [{"HostIp": "0.0.0.0"}]}),  # noqa: S104 - rejected
        ("HostConfig", "CapAdd", ["SYS_ADMIN"]),
        ("HostConfig", "SecurityOpt", []),
        ("Config", "Healthcheck", {"Test": ["CMD", "unrelated"]}),
        ("Config", "Entrypoint", ["sh", "-c"]),
        ("Config", "WorkingDir", "/data"),
    ):
        record = _telegram_test_inspect(UNKNOWN)
        if key is None:
            record[location] = value
        else:
            record[location][key] = value
        with patch.object(
            host,
            "_command",
            side_effect=[
                _info(2),
                f"{CONTAINER}\n{UNKNOWN}",
                _inspect(CONTAINER),
                json.dumps(record),
            ],
        ) as command:
            with CHECKS.assertRaisesRegex(host.SetupError, "unknown_container_preserved_no_stop"):
                host._stop_test_containers(HOME)
        assert all("stop" not in invocation.args for invocation in command.call_args_list)

    with patch.object(
        host,
        "_command",
        side_effect=[
            _info(2),
            f"{CONTAINER}\n{UNKNOWN}",
            _inspect(CONTAINER),
            json.dumps(_telegram_test_inspect(UNKNOWN)),
            _telegram_test_network("f" * 64),
        ],
    ) as command:
        with CHECKS.assertRaisesRegex(host.SetupError, "unknown_container_preserved_no_stop"):
            host._stop_test_containers(HOME)
    assert all("stop" not in invocation.args for invocation in command.call_args_list)

    record = _telegram_test_inspect(UNKNOWN)
    record["Config"]["Env"].append("PYTHONPATH=/data")
    with patch.object(
        host,
        "_command",
        side_effect=[
            _info(2),
            f"{CONTAINER}\n{UNKNOWN}",
            _inspect(CONTAINER),
            json.dumps(record),
            _telegram_test_network(UNKNOWN),
            json.dumps(_telegram_image()),
        ],
    ) as command:
        with CHECKS.assertRaisesRegex(host.SetupError, "unknown_container_preserved_no_stop"):
            host._stop_test_containers(HOME)
    assert all("stop" not in invocation.args for invocation in command.call_args_list)


def test_verified_telegram_and_controller_stop_only_after_complete_inventory() -> None:
    with patch.object(
        host,
        "_command",
        side_effect=[
            _info(2),
            f"{CONTAINER}\n{UNKNOWN}",
            _inspect(CONTAINER),
            json.dumps(_telegram_inspect(UNKNOWN)),
            json.dumps(_telegram_image()),
            CONTAINER,
            UNKNOWN,
            _inspect(CONTAINER, running=False),
            json.dumps(_telegram_inspect(UNKNOWN, running=False)),
            _info(2),
            f"{CONTAINER}\n{UNKNOWN}",
        ],
    ) as command:
        assert host._stop_test_containers(HOME) == 2
    stops = [call.args[-1] for call in command.call_args_list if call.args[3] == "stop"]
    assert stops == [CONTAINER, UNKNOWN]
    assert command.call_args_list[4].args[3:5] == ("image", "inspect")
    assert command.call_args_list[5].args[3] == "stop"


def test_telegram_identity_and_image_mismatch_block_even_known_controller_stop() -> None:
    def wrong_project(container: dict, _image: dict) -> None:
        container["Config"]["Labels"]["com.docker.compose.project"] = "other"

    def wrong_service(container: dict, _image: dict) -> None:
        container["Config"]["Labels"]["com.docker.compose.service"] = "proxy"

    def wrong_number(container: dict, _image: dict) -> None:
        container["Config"]["Labels"]["com.docker.compose.container-number"] = "2"

    def wrong_name(container: dict, _image: dict) -> None:
        container["Name"] = "/boca-socios-telegram-2"

    def wrong_user(container: dict, _image: dict) -> None:
        container["Config"]["User"] = "0:0"

    def wrong_command(container: dict, _image: dict) -> None:
        container["Config"]["Cmd"] = ["sh", "-c", "sleep 100"]

    def wrong_ref(container: dict, _image: dict) -> None:
        container["Config"]["Image"] = "unreviewed:latest"

    def wrong_id(container: dict, _image: dict) -> None:
        container["Image"] = "sha256:" + "e" * 64

    def wrong_digest(_container: dict, image: dict) -> None:
        image["RepoDigests"] = ["ghcr.io/other/project@sha256:" + "d" * 64]

    def wrong_image_identity(_container: dict, image: dict) -> None:
        image["Id"] = "sha256:" + "e" * 64

    def wrong_revision(container: dict, _image: dict) -> None:
        container["Config"]["Labels"]["org.opencontainers.image.revision"] = "f" * 40

    def wrong_image_revision(_container: dict, image: dict) -> None:
        image["Config"]["Labels"]["org.opencontainers.image.revision"] = "f" * 40

    for mutate in (
        wrong_project,
        wrong_service,
        wrong_number,
        wrong_name,
        wrong_user,
        wrong_command,
        wrong_ref,
        wrong_id,
        wrong_digest,
        wrong_image_identity,
        wrong_revision,
        wrong_image_revision,
    ):
        telegram = _telegram_inspect(UNKNOWN)
        image = _telegram_image()
        mutate(telegram, image)
        with patch.object(
            host,
            "_command",
            side_effect=[
                _info(2),
                f"{CONTAINER}\n{UNKNOWN}",
                _inspect(CONTAINER),
                json.dumps(telegram),
                json.dumps(image),
            ],
        ) as command:
            with CHECKS.assertRaisesRegex(host.SetupError, "unknown_container_preserved_no_stop"):
                host._stop_test_containers(HOME)
        assert all(call.args[3] != "stop" for call in command.call_args_list)


def test_unknown_after_verified_telegram_blocks_every_stop() -> None:
    other = "e" * 64
    with patch.object(
        host,
        "_command",
        side_effect=[
            _info(2),
            f"{CONTAINER}\n{other}",
            json.dumps(_telegram_inspect(CONTAINER)),
            json.dumps(_telegram_image()),
            _inspect(other, service="other"),
        ],
    ) as command:
        with CHECKS.assertRaisesRegex(host.SetupError, "unknown_container_preserved_no_stop"):
            host._stop_test_containers(HOME)
    assert all(call.args[3] != "stop" for call in command.call_args_list)


def test_telegram_image_lookup_failure_blocks_inventory_without_stop() -> None:
    for result in (host.SetupError("private_daemon_metadata_failed_exit_1"), "not json"):
        with patch.object(
            host,
            "_command",
            side_effect=[_info(1), CONTAINER, json.dumps(_telegram_inspect(CONTAINER)), result],
        ) as command:
            with CHECKS.assertRaisesRegex(host.SetupError, "unknown_container_preserved_no_stop"):
                host._stop_test_containers(HOME)
        assert all(call.args[3] != "stop" for call in command.call_args_list)


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
