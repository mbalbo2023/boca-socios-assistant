"""Disposable PR image-size evidence; never a host or publishing operation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/release-image.yml"


def _measurement_step() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    preview = workflow.split("  pr-validation:\n", 1)[1].split("  publish:\n", 1)[0]
    marker = "      - name: Measure disposable dual-image logical and archive bytes\n"
    assert preview.count(marker) == 1
    assert preview.index("Verify browser source revision label") < preview.index(marker)
    assert preview.index(marker) < preview.index("Scan browser image before any publication")
    return preview.split(marker, 1)[1].split("      - name:", 1)[0]


def test_pr_only_size_step_reads_exact_local_images_with_no_host_or_publish() -> None:
    step = _measurement_step()
    assert "CONTROLLER_IMAGE: boca-release-validation:${{ github.sha }}" in step
    assert "BROWSER_IMAGE: boca-browser-release-validation:${{ github.sha }}" in step
    assert "docker image inspect --format '{{.Size}}' \"$CONTROLLER_IMAGE\"" in step
    assert "docker image inspect --format '{{.Size}}' \"$BROWSER_IMAGE\"" in step
    assert 'docker image save "$CONTROLLER_IMAGE" "$BROWSER_IMAGE"' in step
    assert "set -euo pipefail" in step
    assert "GITHUB_STEP_SUMMARY" in step
    assert "host_delta=UNVERIFIED" in step
    assert "runner=DISPOSABLE" in step
    assert "logical" in step.lower()
    for forbidden in (
        "docker pull",
        "docker push",
        "docker login",
        "docker image rm",
        "docker rmi",
        "docker prune",
        "docker run",
        "ssh ",
        "Config.Env",
    ):
        assert forbidden not in step


def test_size_step_remains_outside_protected_publisher() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    publisher = workflow.split("  publish:\n", 1)[1]
    assert "Measure disposable dual-image logical and archive bytes" not in publisher
    assert "packages: write" in publisher
    assert "github.event_name == 'workflow_dispatch'" in publisher


def test_full_browser_image_proves_chromium_firefox_webkit_without_blackbox() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    preview = workflow.split("  pr-validation:\n", 1)[1].split("  publish:\n", 1)[0]
    marker = "      - name: Verify all full Playwright browser bundles without blackbox execution\n"
    assert preview.count(marker) == 1
    verify = preview.split(marker, 1)[1].split("      - name:", 1)[0]
    assert 'for name in ("chromium", "firefox", "webkit"):' in verify
    assert "executable_path).is_file()" in verify
    assert "BOCA_FULL_PLAYWRIGHT_BUNDLES" in verify
    assert "--network none" in verify
    assert "--user 10002:10002" in verify
    assert "--read-only" in verify
    assert "blackbox=UNTOUCHED" in verify
    assert "synthetic.py" not in verify
    assert "ipc_worker.py" not in verify
    assert marker not in workflow.split("  publish:\n", 1)[1]
