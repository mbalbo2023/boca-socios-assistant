"""Disposable PR image-size evidence; never a host or publishing operation."""

import ast
import textwrap
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


def test_pr_only_three_browser_launch_is_real_offline_and_bounded() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    preview = workflow.split("  pr-validation:\n", 1)[1].split("  publish:\n", 1)[0]
    marker = "      - name: Launch all three Playwright browsers offline without blackbox\n"
    assert preview.count(marker) == 1
    assert preview.index("Verify isolated Chromium launch offline") < preview.index(marker)
    assert preview.index(marker) < preview.index("Scan before any image publication")
    step = preview.split(marker, 1)[1].split("      - name:", 1)[0]
    assert "IMAGE: boca-browser-release-validation:${{ github.sha }}" in step
    assert 'for name in ("chromium", "firefox", "webkit"):' in step
    assert "browser_type.launch(" in step
    assert 'page.goto("about:blank"' in step
    assert "BOCA_FULL_PLAYWRIGHT_LAUNCH" in step
    source = step.split('--entrypoint python "$IMAGE" -c \'\n', 1)[1].split("\n          '\n", 1)[0]
    ast.parse(textwrap.dedent(source))
    assert "BOCA_BROWSER_HOME_CHECK" in step
    assert "home_stat.st_uid == 10002" in step
    assert "os.access(home, os.W_OK)" in step
    assert "tempfile.TemporaryFile()" in step
    assert "os.dup2(probe.fileno(), 2)" in step
    assert "categories={categories}" in step
    assert "exit_code={code}" in step
    assert "phase={phase}" in step
    for guard in (
        "timeout 120s docker run --rm",
        "--network none",
        "--user 10002:10002",
        "--read-only",
        "--cap-drop ALL --cap-add SYS_CHROOT",
        "--security-opt no-new-privileges:true",
        '"seccomp=$GITHUB_WORKSPACE/docker/seccomp_profile.json"',
        "--pids-limit 128 --memory 768m --cpus 1.0",
        "--tmpfs /tmp:rw,noexec,nosuid,size=32m",
        "--env DEBUG=pw:browser",
    ):
        assert guard in step
    for forbidden in (
        "synthetic.py",
        "ipc_worker.py",
        "https://",
        "http://",
        "docker push",
        "docker pull",
        "docker login",
        "ssh ",
        "print(error)",
        "print(captured)",
    ):
        assert forbidden not in step
    assert marker not in workflow.split("  publish:\n", 1)[1]
