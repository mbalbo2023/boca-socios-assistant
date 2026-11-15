"""Resolute image keeps the APT fix before other package operations."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APT_FIXED = "3.2.1ubuntu0.1"
FIXED_PACKAGES = {
    "apt": APT_FIXED,
    "libapt-pkg7.0": APT_FIXED,
    "libbrotli1": "1.2.0-3ubuntu0.1",
    "gstreamer1.0-plugins-bad": "1.28.2-1ubuntu1.2",
    "libgstreamer-plugins-bad1.0-0": "1.28.2-1ubuntu1.2",
}


def _initial_apt_step() -> str:
    dockerfile = (ROOT / "Dockerfile.browser").read_text(encoding="utf-8")
    return next(
        line.removeprefix("RUN ")
        for line in dockerfile.replace("\\\n", "").splitlines()
        if line.startswith("RUN ") and "apt-get update" in line
    )


def test_browser_image_pins_both_fixed_apt_binary_packages_before_other_installs() -> None:
    dockerfile = (ROOT / "Dockerfile.browser").read_text(encoding="utf-8")
    initial_apt_step = _initial_apt_step()

    assert "apt-get update -o Acquire::Retries=0" in initial_apt_step
    assert "apt-get -o Acquire::Retries=0 install --yes --no-install-recommends" in (
        initial_apt_step
    )
    assert f"apt={APT_FIXED}" in initial_apt_step
    assert f"libapt-pkg7.0={APT_FIXED}" in initial_apt_step
    assert (
        initial_apt_step.index("apt-get update -o Acquire::Retries=0")
        < initial_apt_step.index(f"apt={APT_FIXED}")
        < initial_apt_step.index("libbrotli1=1.2.0-3ubuntu0.1")
    )
    assert "for pkg in apt libapt-pkg7.0; do" in initial_apt_step
    assert "dpkg-query -W -f='${Version}' \"$pkg\"" in initial_apt_step
    assert f'"{APT_FIXED}"' in initial_apt_step
    assert "apt-get upgrade" not in dockerfile
    assert "apt-get dist-upgrade" not in dockerfile


def test_browser_image_fails_apt_update_on_unresolved_security_mirror() -> None:
    """Unreachable mirrors must not silently fall through to stale APT indexes."""
    first_run = _initial_apt_step()
    update = "apt-get update -o Acquire::Retries=0 --error-on=any"
    assert first_run.count(update) == 2
    assert f"if {update}; then" in first_run
    assert (
        first_run.index("else ")
        < first_run.index("python /tmp/boca_browser_apt_mirror.py")
        < first_run.index("fi &&")
    )


def test_browser_image_uses_separately_hosted_signed_resolute_mirror() -> None:
    """Official Ubuntu key and security pocket must survive mirror substitution."""
    dockerfile = (ROOT / "Dockerfile.browser").read_text(encoding="utf-8")
    initial = _initial_apt_step()

    # Require attestation of the source file's known structure before rewriting.
    assert (
        "--mount=type=bind,source=scripts/browser_ubuntu_apt_mirror.py,"
        "target=/tmp/boca_browser_apt_mirror.py,readonly"
    ) in initial
    assert "python /tmp/boca_browser_apt_mirror.py --suite resolute" in initial
    assert (
        initial.index("if apt-get update")
        < initial.index("python /tmp/boca_browser_apt_mirror.py")
        < initial.index("apt-get -o Acquire::Retries=0 install")
    )
    assert "COPY scripts/browser_ubuntu_apt_mirror.py" not in dockerfile
    assert "--allow-unauthenticated" not in dockerfile
    assert "AllowInsecureRepositories=true" not in dockerfile
    assert "trusted=yes" not in dockerfile
    assert "--network=host" not in dockerfile


def test_playwright_install_must_leave_both_apt_packages_at_patched_versions() -> None:
    dockerfile = (ROOT / "Dockerfile.browser").read_text(encoding="utf-8")
    install_step = dockerfile.split(
        "/app/.venv/bin/python -m playwright install --with-deps chromium firefox webkit", 1
    )[1].split("\n\n", 1)[0]

    assert "for pkg in apt libapt-pkg7.0; do" in install_step
    assert "dpkg-query -W -f='${Version}' \"$pkg\"" in install_step
    assert f'"{APT_FIXED}"' in install_step
    assert "apt-get clean" in install_step


@pytest.mark.parametrize("stale_package", [None, *FIXED_PACKAGES])
def test_actual_package_postchecks_reject_each_stale_binary(
    tmp_path: Path, stale_package: str | None
) -> None:
    """Run the real initial shell gate with inert APT/dpkg boundaries only."""
    versions = dict(FIXED_PACKAGES)
    if stale_package is not None:
        versions[stale_package] = "0.0-stale"
    events = tmp_path / "apt-events.jsonl"
    apt = tmp_path / "apt-get"
    apt.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "with open(os.environ['APT_EVENTS'], 'a') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n",
        encoding="utf-8",
    )
    apt.chmod(0o700)
    dpkg = tmp_path / "dpkg-query"
    dpkg.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "print(json.loads(os.environ['PACKAGE_VERSIONS']).get(sys.argv[-1], 'MISSING'))\n",
        encoding="utf-8",
    )
    dpkg.chmod(0o700)
    command = re.sub(r"^(?:--mount=\S+\s+)+", "", _initial_apt_step())
    # The reviewed repository shell gate can resolve only the two inert fixture commands.
    result = subprocess.run(  # noqa: S603
        ["/bin/sh", "-eu", "-c", command],
        env={
            "PATH": str(tmp_path),
            "PACKAGE_VERSIONS": json.dumps(versions),
            "APT_EVENTS": str(events),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is (stale_package is None), result.stderr
    calls = [json.loads(line) for line in events.read_text().splitlines()]
    assert calls[0] == ["update", "-o", "Acquire::Retries=0", "--error-on=any"]
    assert calls[1][-2:] == [f"apt={APT_FIXED}", f"libapt-pkg7.0={APT_FIXED}"]
    if stale_package in ("apt", "libapt-pkg7.0"):
        assert len(calls) == 2, "stale APT must stop before any other package operation"


def test_security_scan_remains_blocking_for_high_and_critical_image_findings() -> None:
    scan = (ROOT / "scripts/trivy_scan_image.sh").read_text(encoding="utf-8")
    security_workflow = (ROOT / ".github/workflows/image-security.yml").read_text(encoding="utf-8")
    assert "HIGH,CRITICAL" in scan
    assert "--exit-code 1" in scan
    assert security_workflow.count("run: bash scripts/trivy_scan_image.sh") == 2
