"""Effective commands need typed presence proof, not systemctl's display rows."""

from __future__ import annotations

import io
import json
import runpy
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from boca_socios import host_rootless_setup as rootless

HOME = Path("/home/boca-deploy")
SCALARS = {
    "LoadState": "loaded",
    "NeedDaemonReload": "no",
    "Type": "exec",
    "Restart": "no",
    "Delegate": "yes",
    "KillMode": "mixed",
}
PROPERTIES = (
    "ExecCondition",
    "ExecStartPre",
    "ExecStartPost",
    "ExecStop",
    "ExecStopPost",
    "ExecStart",
)
SIGNATURE = "a(sasbttttuii)"
ARGV = [
    "/usr/bin/env",
    "-i",
    "HOME=/home/boca-deploy",
    "USER=boca-deploy",
    "LOGNAME=boca-deploy",
    "PATH=/usr/bin:/bin:/usr/sbin:/sbin",
    "XDG_RUNTIME_DIR=/run/user/10001",
    "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/10001/bus",
    "/usr/bin/dockerd-rootless.sh",
    "--config-file=/home/boca-deploy/.config/docker/daemon.json",
]


def _exec_row() -> list[object]:
    return ["/usr/bin/env", ARGV.copy(), False, 0, 0, 0, 0, 0, 0, 0]


def _typed_commands(row: list[object] | None = None) -> str:
    return "\n".join(
        json.dumps(
            {
                "type": SIGNATURE,
                "data": [row if row is not None else _exec_row()] if name == "ExecStart" else [],
            }
        )
        for name in PROPERTIES
    )


def _systemctl_display(command: tuple[str, ...]) -> str:
    # Official v255 renderer emits no rows for empty Exec* arrays, even --all.
    requested = command[-1].removeprefix("--property=").split(",")
    fields = SCALARS | {
        "ExecStart": "{ path=/usr/bin/env ; argv[]="
        + " ".join(ARGV)
        + " ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; "
        "pid=0 ; code=(null) ; status=0/0 }"
    }
    return "\n".join(f"{name}={fields[name]}" for name in requested if name in fields)


_ASSERT = unittest.TestCase()


def _check(*, scalar: str | None = None, typed: str | None = None) -> None:
    scalar = scalar if scalar is not None else "\n".join(f"{k}={v}" for k, v in SCALARS.items())
    typed = typed if typed is not None else _typed_commands()
    with patch.object(rootless, "_command", side_effect=[scalar, typed]):
        rootless._preflight_effective_unit(HOME)


def test_effective_unit_accepts_official_omitted_empty_hooks_with_typed_presence() -> None:
    commands: list[tuple[str, ...]] = []

    def command(home: Path, *args: str) -> str:
        _ASSERT.assertEqual(home, HOME)
        commands.append(args)
        if args[0] == "/usr/bin/systemctl":
            return _systemctl_display(args)
        if args[0] == "/usr/bin/busctl":
            return _typed_commands()
        _ASSERT.fail("unreviewed command")

    with patch.object(rootless, "_command", command):
        rootless._preflight_effective_unit(HOME)
    _ASSERT.assertEqual(len(commands), 2)
    _ASSERT.assertEqual(
        commands[0],
        (
            "/usr/bin/systemctl",
            "--user",
            "show",
            "--all",
            "docker.service",
            "--property=" + ",".join(SCALARS),
        ),
    )
    _ASSERT.assertEqual(
        commands[1],
        (
            "/usr/bin/busctl",
            "--user",
            "--no-pager",
            "--json=short",
            "get-property",
            "org.freedesktop.systemd1",
            "/org/freedesktop/systemd1/unit/docker_2eservice",
            "org.freedesktop.systemd1.Service",
            *PROPERTIES,
        ),
    )


def test_effective_unit_accepts_prior_runtime_metadata_with_exact_typed_bounds() -> None:
    for runtime in (
        [0, 0, 0, 0, 0, 0, 0],
        [1_793_613_600_000_000, 2000, 0, 0, 123, 0, 0],
        [1_793_613_600_000_000, 2000, 1_793_613_660_000_000, 3000, 123, 2, 15],
        [2**64 - 1] * 4 + [2**32 - 1, -(2**31), 2**31 - 1],
    ):
        with _ASSERT.subTest(runtime=runtime):
            _check(typed=_typed_commands(_exec_row()[:3] + runtime))


def test_effective_unit_rejects_every_nonempty_hook() -> None:
    for index, name in enumerate(PROPERTIES[:-1]):
        with _ASSERT.subTest(property=name):
            lines = _typed_commands().splitlines()
            lines[index] = json.dumps({"type": SIGNATURE, "data": [_exec_row()]})
            with _ASSERT.assertRaisesRegex(
                rootless.SetupError, "^effective_preflight_unit_changed$"
            ):
                _check(typed="\n".join(lines))


def test_effective_unit_rejects_loaded_scalar_drift() -> None:
    for key in SCALARS:
        with _ASSERT.subTest(property=key):
            fields = SCALARS | {key: "unexpected"}
            with _ASSERT.assertRaisesRegex(
                rootless.SetupError, "^effective_preflight_unit_changed$"
            ):
                _check(scalar="\n".join(f"{k}={v}" for k, v in fields.items()))


def test_effective_unit_requires_exact_scalar_presence() -> None:
    lines = [f"{k}={v}" for k, v in SCALARS.items()]
    for raw in (
        "\n".join(lines[:-1]),
        "\n".join(lines + ["Extra=no"]),
        "\n".join(lines + [lines[0]]),
        "\n".join(lines[:-1] + [lines[0]]),
        "\n".join(lines[:-1] + ["malformed"]),
        "\n".join(lines[:-1] + ["=mixed"]),
        "\n".join(lines[:-1] + ["KillMode=mixed=extra"]),
        "\n".join(lines) + "x" * 16_384,
    ):
        with _ASSERT.subTest(raw=raw[:40]), _ASSERT.assertRaises(rootless.SetupError):
            _check(scalar=raw)


def test_effective_unit_requires_six_complete_typed_property_results() -> None:
    lines = _typed_commands().splitlines()
    for raw in (
        "",
        "\n".join(lines[:-1]),
        "\n".join(lines[1:]),
        "\n".join(lines + [lines[0]]),
        "\n".join(lines + ["", ""]),
        "\n".join(lines[:2] + [""] + lines[2:]),
        "\n".join(lines) + "x" * 16_384,
    ):
        with _ASSERT.subTest(length=len(raw)), _ASSERT.assertRaises(rootless.SetupError):
            _check(typed=raw)


def test_effective_unit_rejects_malformed_or_ambiguous_json_envelopes() -> None:
    for malformed in (
        "{",
        "null",
        "[]",
        "{}",
        '{"type":"a(sasbttttuii)"}',
        '{"data":[]}',
        '{"type":"a(sasbttttuii)","data":[],"extra":0}',
        '{"type":"a(sasbttttuii)","type":"a(sasbttttuii)","data":[]}',
        '{"type":"a(sasbttttuii)","data":[],"data":[]}',
        '{"type":"as","data":[]}',
        '{"type":"a(sasbttttuii)","data":null}',
        '{"type":"a(sasbttttuii)","data":{}}',
        '{"type":"a(sasbttttuii)","data":[]}{}',
        '{"type":"a(sasbttttuii)","data":NaN}',
        '{"type":"a(sasbttttuii)","data":Infinity}',
        '{"type":"a(sasbttttuii)","data":' + "[" * 1500 + "]" * 1500 + "}",
    ):
        with _ASSERT.subTest(malformed=malformed[:50]):
            lines = _typed_commands().splitlines()
            lines[0] = malformed
            with _ASSERT.assertRaisesRegex(
                rootless.SetupError, "^effective_preflight_unit_(unverified|changed)$"
            ):
                _check(typed="\n".join(lines))


def test_effective_unit_requires_one_complete_execstart_structure() -> None:
    for data in (
        [],
        [_exec_row(), _exec_row()],
        [None],
        [{}],
        [_exec_row()[:-1]],
        [_exec_row() + [0]],
    ):
        with _ASSERT.subTest(data=data):
            lines = _typed_commands().splitlines()
            lines[-1] = json.dumps({"type": SIGNATURE, "data": data})
            with _ASSERT.assertRaisesRegex(
                rootless.SetupError, "^effective_preflight_command_changed$"
            ):
                _check(typed="\n".join(lines))


def test_effective_unit_json_recursion_failure_remains_a_fixed_reason() -> None:
    with (
        patch.object(rootless.json, "loads", side_effect=RecursionError("sentinel-private")),
        _ASSERT.assertRaisesRegex(rootless.SetupError, "^effective_preflight_unit_unverified$"),
    ):
        _check()


def test_effective_unit_rejects_command_identity_and_argument_boundary_changes() -> None:
    for index, value in (
        (0, "/bin/other"),
        (0, None),
        (1, " ".join(ARGV)),
        (1, ARGV[:-1]),
        (1, ARGV + ["--extra"]),
        (1, [" ".join(ARGV[:2]), *ARGV[2:]]),
        (1, ARGV[:-1] + ["--config-file=/other/daemon.json"]),
        (1, ARGV[:-1] + ["--config-file=%h/.config/docker/daemon.json"]),
        (2, True),
        (2, 0),
        (2, "false"),
    ):
        with _ASSERT.subTest(index=index, value=value):
            row = _exec_row()
            row[index] = value
            with _ASSERT.assertRaisesRegex(
                rootless.SetupError, "^effective_preflight_command_changed$"
            ):
                _check(typed=_typed_commands(row))


def test_effective_unit_rejects_invalid_typed_runtime_metadata() -> None:
    for index in range(3, 10):
        lower, upper = (
            (0, 2**64 - 1)
            if index < 7
            else ((0, 2**32 - 1) if index == 7 else (-(2**31), 2**31 - 1))
        )
        for value in (
            False,
            True,
            None,
            "0",
            0.0,
            float("nan"),
            float("inf"),
            lower - 1,
            upper + 1,
        ):
            with _ASSERT.subTest(index=index, value=value):
                row = _exec_row()
                row[index] = value
                with _ASSERT.assertRaisesRegex(
                    rootless.SetupError, "^effective_preflight_command_changed$"
                ):
                    _check(typed=_typed_commands(row))


def test_effective_unit_rejection_cannot_reach_daemon_start() -> None:
    start, runtime, containers = Mock(), Mock(), Mock()
    scalar = "\n".join(f"{k}={v}" for k, v in SCALARS.items())
    with (
        patch.object(rootless, "_existing_daemon_boundary", return_value=(HOME, "inactive")),
        patch.object(rootless, "_command", side_effect=[scalar, ""]),
        patch.object(rootless, "_require_stopped_runtime", runtime),
        patch.object(rootless, "_preflight_empty_containers", containers),
        patch.object(rootless, "_start_stopped_daemon", start),
        _ASSERT.assertRaises(rootless.SetupError),
    ):
        rootless.infrastructure_start("a" * 40)
    start.assert_not_called()
    runtime.assert_not_called()
    containers.assert_not_called()


def test_effective_unit_busctl_failures_keep_fixed_diagnostics_without_raw_output() -> None:
    scalar = "\n".join(f"{k}={v}" for k, v in SCALARS.items())
    classify = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "scripts/check_infrastructure_diagnostic.py")
    )["classify"]
    for failure, reason in (
        (
            subprocess.CalledProcessError(1, ["sentinel-private"], output="sentinel-private"),
            "user_service_metadata_failed_exit_1",
        ),
        (
            subprocess.TimeoutExpired("sentinel-private", 15),
            "user_service_metadata_failed_timeout",
        ),
        (FileNotFoundError("sentinel-private"), "user_service_metadata_failed_unavailable"),
    ):
        with _ASSERT.subTest(reason=reason):
            output, error = io.StringIO(), io.StringIO()
            with (
                patch.object(
                    rootless, "_existing_daemon_boundary", return_value=(HOME, "inactive")
                ),
                patch.object(
                    rootless.subprocess,
                    "run",
                    side_effect=[subprocess.CompletedProcess([], 0, stdout=scalar), failure],
                ) as run,
                patch.object(
                    sys, "argv", ["host_rootless_setup.py", "infrastructure-check", "a" * 40]
                ),
                redirect_stdout(output),
                redirect_stderr(error),
            ):
                _ASSERT.assertEqual(rootless.main(), 1)
            _ASSERT.assertEqual(run.call_count, 2)
            _ASSERT.assertEqual(run.call_args.args[0][0], "/usr/bin/busctl")
            _ASSERT.assertEqual(run.call_args.kwargs["timeout"], 15)
            _ASSERT.assertEqual(run.call_args.kwargs["env"], rootless._environment(HOME))
            _ASSERT.assertEqual(run.call_args.kwargs["stderr"], subprocess.DEVNULL)
            _ASSERT.assertNotIn("sentinel-private", output.getvalue() + error.getvalue())
            rc, receipt = classify(
                "a" * 40, 1, output.getvalue().encode(), error.getvalue().encode()
            )
            _ASSERT.assertEqual(rc, 1)
            _ASSERT.assertIn(
                f"state=NO_GO source_sha={'a' * 40} rc=1 transport=confirmed reason={reason}",
                receipt,
            )
            _ASSERT.assertIn("start_attempted=no", receipt)


if __name__ == "__main__":
    suite = unittest.TestSuite(
        unittest.FunctionTestCase(test)
        for name, test in sorted(globals().items())
        if name.startswith("test_") and callable(test)
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
