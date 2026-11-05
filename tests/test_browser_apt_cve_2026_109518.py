"""Regression for Ubuntu Noble APT hardlink/retry vulnerability USN-8996-1."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APT_FIXED = "2.8.4ubuntu0.1"


def test_browser_image_pins_both_fixed_apt_binary_packages_before_other_installs() -> None:
    dockerfile = (ROOT / "Dockerfile.browser").read_text(encoding="utf-8")
    initial_apt_step = dockerfile.split("WORKDIR /app\n", 1)[1].split(
        "# Exact fixed versions from #241", 1
    )[0]

    assert "apt-get update -o Acquire::Retries=0" in initial_apt_step
    assert "apt-get -o Acquire::Retries=0 install --yes --no-install-recommends" in (
        initial_apt_step
    )
    assert f"apt={APT_FIXED}" in initial_apt_step
    assert f"libapt-pkg6.0t64={APT_FIXED}" in initial_apt_step
    assert (
        initial_apt_step.index("apt-get update -o Acquire::Retries=0")
        < initial_apt_step.index(f"apt={APT_FIXED}")
        < initial_apt_step.index("libbrotli1=1.1.0-2ubuntu0.1")
    )
    assert "for pkg in apt libapt-pkg6.0t64; do" in initial_apt_step
    assert "dpkg-query -W -f='${Version}' \"$pkg\"" in initial_apt_step
    assert f'"{APT_FIXED}"' in initial_apt_step
    assert "apt-get upgrade" not in dockerfile
    assert "apt-get dist-upgrade" not in dockerfile


def test_playwright_install_must_leave_both_apt_packages_at_patched_versions() -> None:
    dockerfile = (ROOT / "Dockerfile.browser").read_text(encoding="utf-8")
    install_step = dockerfile.split(
        "/app/.venv/bin/python -m playwright install --with-deps chromium", 1
    )[1].split("\n\n", 1)[0]

    assert "for pkg in apt libapt-pkg6.0t64; do" in install_step
    assert "dpkg-query -W -f='${Version}' \"$pkg\"" in install_step
    assert f'"{APT_FIXED}"' in install_step
    assert "apt-get clean" in install_step


def test_security_scan_remains_blocking_for_high_and_critical_image_findings() -> None:
    scan = (ROOT / "scripts/trivy_scan_image.sh").read_text(encoding="utf-8")
    security_workflow = (ROOT / ".github/workflows/image-security.yml").read_text(encoding="utf-8")
    assert "HIGH,CRITICAL" in scan
    assert "--exit-code 1" in scan
    assert security_workflow.count("run: bash scripts/trivy_scan_image.sh") == 2
