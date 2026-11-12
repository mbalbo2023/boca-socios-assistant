"""R244: exercise the real two-image CI build shell without Docker/network."""

from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github/workflows/ci.yml"
SOURCE_SHA = "c" * 40
STEP_NAME = "Build both isolated images concurrently without deploying"


def _build_body() -> str:
    source = CI.read_text(encoding="utf-8")
    marker = f"      - name: {STEP_NAME}\n"
    assert marker in source, "required concurrent build step is absent"
    step = source.split(marker, 1)[1].split("      - name:", 1)[0]
    assert "        run: |\n" in step
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


def _run_pair(tmp_path: Path, failures: str = "") -> subprocess.CompletedProcess[str]:
    """Substitute only the slow Docker boundary; execute the actual Bash body."""
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys, time\n"
        "args = sys.argv[1:]\n"
        "assert args[0] == 'build', args\n"
        "role = 'browser' if 'Dockerfile.browser' in args else 'controller'\n"
        "other = 'controller' if role == 'browser' else 'browser'\n"
        "root = pathlib.Path(os.environ['DOCKER_FIXTURE_DIR'])\n"
        "(root / (role + '.args')).write_text(json.dumps(args))\n"
        "(root / (role + '.started')).touch()\n"
        "deadline = time.monotonic() + 4\n"
        "while not (root / (other + '.started')).exists() and time.monotonic() < deadline:\n"
        "    time.sleep(.01)\n"
        "if not (root / (other + '.started')).exists():\n"
        "    print('SECOND_BUILD_NEVER_STARTED', flush=True)\n"
        "    sys.exit(93)\n"
        "time.sleep(.12 if role == 'controller' else .23)\n"
        "(root / (role + '.finished')).touch()\n"
        "print('FIXTURE_BUILD role=' + role, flush=True)\n"
        "if role in os.environ['DOCKER_FIXTURE_FAILURES'].split(','):\n"
        "    sys.exit(23 if role == 'controller' else 29)\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o700)
    env = os.environ | {
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "SOURCE_SHA": SOURCE_SHA,
        "GITHUB_SHA": SOURCE_SHA,
        "GITHUB_RUN_ID": "12345",
        "GITHUB_RUN_ATTEMPT": "1",
        "CONTROLLER_IMAGE": f"boca-socios-ci:{SOURCE_SHA}",
        "BROWSER_IMAGE": f"boca-browser-ci:{SOURCE_SHA}",
        "RUNNER_TEMP": str(tmp_path),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
        "DOCKER_FIXTURE_DIR": str(tmp_path),
        "DOCKER_FIXTURE_FAILURES": failures,
    }
    return subprocess.run(  # noqa: S603 - reviewed Bash body with synthetic Docker only
        ["/usr/bin/bash", "-e", "-c", _build_body()],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=12,
    )


def test_exact_role_labels_and_aliases_are_built_concurrently(tmp_path: Path) -> None:
    result = _run_pair(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    for role, image, aliases in (
        ("controller", f"boca-socios-ci:{SOURCE_SHA}", [f"boca-release-validation:{SOURCE_SHA}"]),
        (
            "browser",
            f"boca-browser-ci:{SOURCE_SHA}",
            [f"boca-browser-release-validation:{SOURCE_SHA}", f"boca-observer:{SOURCE_SHA}"],
        ),
    ):
        assert (tmp_path / f"{role}.finished").exists()
        args = json.loads((tmp_path / f"{role}.args").read_text())
        assert args[0] == "build"
        assert args[-1] == "."
        assert args.count("--label") == (3 if role == "browser" else 2)
        assert (
            "org.opencontainers.image.source=https://github.com/mbalbo2023/boca-socios-assistant"
            in args
        )
        assert f"org.opencontainers.image.revision={SOURCE_SHA}" in args
        tags = [args[i + 1] for i, arg in enumerate(args) if arg == "--tag"]
        assert tags == [image, *aliases]
        if role == "browser":
            assert args[args.index("--file") + 1] == "Dockerfile.browser"
            assert "org.boca.public-image=12345-1" in args
        else:
            assert "--file" not in args

    assert re.search(
        r"BOCA_CI_BUILD_PAIR result=PASS source_sha=c{40} wall_seconds=\d+", result.stdout
    )
    assert "BOCA_CI_BUILD role=controller result=PASS" in result.stdout
    assert "BOCA_CI_BUILD role=browser result=PASS" in result.stdout
    assert "BOCA_CI_BUILD_PAIR result=PASS" in (tmp_path / "summary").read_text()


@pytest.mark.parametrize(
    ("failures", "controller_exit", "browser_exit"),
    [
        ("controller", 23, 0),
        ("browser", 0, 29),
        ("controller,browser", 23, 29),
    ],
)
def test_either_build_failure_waits_for_both_and_fails_closed(
    tmp_path: Path, failures: str, controller_exit: int, browser_exit: int
) -> None:
    result = _run_pair(tmp_path, failures)
    assert result.returncode != 0
    assert all((tmp_path / f"{role}.finished").exists() for role in ("controller", "browser"))
    assert "FIXTURE_BUILD role=controller" in result.stdout
    assert "FIXTURE_BUILD role=browser" in result.stdout
    assert "BOCA_CI_BUILD_PAIR result=NO_GO" in result.stderr
    assert f"controller_exit={controller_exit}" in result.stderr
    assert f"browser_exit={browser_exit}" in result.stderr


def test_both_security_scans_still_depend_on_successful_build_step() -> None:
    source = CI.read_text(encoding="utf-8")
    image = source.split("  image:\n", 1)[1]
    build_at = image.index(f"      - name: {STEP_NAME}")
    controller_scan_at = image.index("      - name: Scan before any image publication")
    browser_scan_at = image.index("      - name: Scan browser image before any publication")
    assert build_at < controller_scan_at < browser_scan_at
    for scan_at in (controller_scan_at, browser_scan_at):
        step = image[scan_at + len("      - name:") :].split("      - name:", 1)[0]
        assert "        if: always()" not in step
        assert "run: bash scripts/trivy_scan_image.sh" in step
    assert image.count("docker build") == 2
    assert "docker buildx" not in image
    assert "cache-from" not in image and "cache-to" not in image


def test_pair_duration_ends_at_both_waits_before_log_replay() -> None:
    body = _build_body()
    assert body.index('wait "$controller_pid"') < body.index('wait "$browser_pid"')
    assert body.index('wait "$browser_pid"') < body.index("pair_wall=$((SECONDS - pair_started))")
    assert body.index("pair_wall=$((SECONDS - pair_started))") < body.index(
        'cat "$controller_log" "$browser_log"'
    )
    assert body.count('"$pair_wall"') == 2
