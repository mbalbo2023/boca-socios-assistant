"""Dedicated rootless metadata cannot become a daemon operation."""

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from boca_socios import host_first_deploy as host


def test_service_metadata_distinguishes_missing_inactive_failed_and_running() -> None:
    for load, active, sub, result in (
        ("not-found", "inactive", "dead", "success"),
        ("loaded", "inactive", "dead", "success"),
        ("loaded", "failed", "failed", "exit-code"),
        ("loaded", "active", "running", "success"),
    ):
        raw = f"LoadState={load}\nActiveState={active}\nSubState={sub}\nResult={result}\n"
        assert host._parse_service_properties(raw) == (load, active, sub, result)


def test_service_metadata_redacts_malformed_or_unrecognized_values() -> None:
    good = "LoadState=loaded\nActiveState=active\nSubState=running\nResult=success\n"
    for raw in (
        "",
        good + "LoadState=loaded\n",
        good + "Environment=secret-sentinel\n",
        good.replace("active", "secret-sentinel"),
        good.replace("Result=success\n", ""),
        "x" * 1025,
    ):
        assert host._parse_service_properties(raw) == ("unavailable",) * 4


def test_service_probe_uses_only_fixed_user_unit_and_private_bus() -> None:
    raw = "LoadState=loaded\nActiveState=failed\nSubState=failed\nResult=exit-code\n"
    with (
        patch.object(host, "_require_dedicated_identity", return_value=10001),
        patch.object(host, "_binary_presence", return_value="available"),
        patch.object(host.subprocess, "run", return_value=SimpleNamespace(stdout=raw)) as run,
    ):
        report = host._rootless_service_metadata(True)
    assert "load=loaded active=failed sub=failed result=exit-code" in report
    assert "docker=available dockerd=available wrapper=available setup=available" in report
    args, kwargs = run.call_args
    assert args == ((
        "/usr/bin/systemctl", "--user", "--no-pager", "show", "docker.service",
        "--property=LoadState,ActiveState,SubState,Result",
    ),)
    assert kwargs["timeout"] == 5
    assert kwargs["check"] is True
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert kwargs["env"] == {
        "PATH": "/usr/bin:/bin", "LC_ALL": "C", "XDG_RUNTIME_DIR": "/run/user/10001",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/10001/bus",
    }


def test_service_probe_failure_is_unknown_without_leaking_stderr() -> None:
    for error in (
        OSError("secret-sentinel"),
        subprocess.TimeoutExpired("systemctl", 5, output="secret-sentinel"),
        subprocess.CalledProcessError(1, "systemctl", output="secret-sentinel"),
    ):
        with (
            patch.object(host, "_require_dedicated_identity", return_value=10001),
            patch.object(host, "_binary_presence", return_value="not_found_in_search_path"),
            patch.object(host.subprocess, "run", side_effect=error),
        ):
            report = host._rootless_service_metadata(True)
        assert "load=unavailable active=unavailable sub=unavailable result=unavailable" in report
        assert "secret-sentinel" not in report
        assert "not_found_in_search_path" in report


def test_service_probe_does_not_connect_when_private_runtime_is_unproven() -> None:
    with (
        patch.object(host, "_require_dedicated_identity", return_value=10001),
        patch.object(host, "_binary_presence", return_value="available"),
        patch.object(host.subprocess, "run") as run,
    ):
        report = host._rootless_service_metadata(False)
    run.assert_not_called()
    assert "load=not_checked active=not_checked sub=not_checked result=not_checked" in report


def test_service_probe_checks_identity_before_executable_or_bus_metadata() -> None:
    with (
        patch.object(host, "_require_dedicated_identity", side_effect=host.PreflightError("uid")),
        patch.object(host, "_binary_presence") as binary,
        patch.object(host.subprocess, "run") as run,
    ):
        try:
            host._rootless_service_metadata(True)
        except host.PreflightError:
            pass
        else:
            raise AssertionError("wrong identity accepted")
    binary.assert_not_called()
    run.assert_not_called()


def test_binary_presence_only_reports_fixed_search_lookup_without_execution() -> None:
    with (
        patch.object(host.pwd, "getpwuid", return_value=SimpleNamespace(pw_dir="/home/boca-deploy")),
        patch.object(host.shutil, "which", return_value="/usr/bin/docker") as which,
        patch.object(host.subprocess, "run") as run,
    ):
        assert host._binary_presence("docker") == "available"
    assert which.call_args.kwargs["path"].startswith("/home/boca-deploy/bin:")
    run.assert_not_called()
