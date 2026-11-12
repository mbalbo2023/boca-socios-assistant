"""Disposable PR image-size evidence; never a host or publishing operation."""

import ast
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/release-image.yml"
CI = WORKFLOW.with_name("ci.yml")
DIAGNOSTIC = ROOT / ".github/workflows/boca-playwright-offline-diagnostic.yml"


def _measurement_step() -> str:
    preview = CI.read_text(encoding="utf-8").split("  image:\n", 1)[1]
    marker = "      - name: Measure disposable dual-image logical and archive bytes\n"
    assert preview.count(marker) == 1
    assert preview.index("Verify browser source revision label") < preview.index(marker)
    assert preview.index(marker) < preview.index("Scan browser image before any publication")
    return preview.split(marker, 1)[1].split("      - name:", 1)[0]


def test_pr_only_size_step_reads_exact_local_images_with_no_host_or_publish() -> None:
    step = _measurement_step()
    assert "CONTROLLER_IMAGE: boca-socios-ci:${{ github.sha }}" in step
    assert "BROWSER_IMAGE: boca-browser-ci:${{ github.sha }}" in step
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
    preview = CI.read_text(encoding="utf-8").split("  image:\n", 1)[1]
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


def test_three_engine_launches_are_independent_opt_in_offline_containers() -> None:
    workflow = DIAGNOSTIC.read_text(encoding="utf-8")
    assert "  workflow_dispatch:\n" in workflow
    assert "  pull_request:\n" not in workflow
    assert "  contents: read\n" in workflow
    assert "packages: write" not in workflow
    assert "secrets." not in workflow
    assert "ghcr.io" not in workflow
    assert "actions/upload-artifact" not in workflow
    marker = "      - name: Probe each Playwright engine in a separate offline process\n"
    assert workflow.count(marker) == 1
    assert workflow.index("Build one disposable full Playwright worker image") < workflow.index(
        marker
    )
    step = workflow.split(marker, 1)[1].split("      - name:", 1)[0]

    # The #402 failure followed Chromium in a shared Python/PID1 process.
    # One reviewed image but a fresh, bounded, disposable process per engine.
    assert "for engine in chromium firefox webkit; do" in step
    assert '--env BOCA_PLAYWRIGHT_ENGINE="$engine"' in step
    assert 'name = os.environ["BOCA_PLAYWRIGHT_ENGINE"]' in step
    assert 'for name in ("chromium", "firefox", "webkit"):' not in step
    assert "failures=$((failures + 1))" in step
    assert 'test "$failures" -eq 0' in step
    assert "--rm --init --network none" in step
    for guard in (
        "timeout 50s docker run",
        "--user 10002:10002 --read-only",
        "--cap-drop ALL --cap-add SYS_CHROOT",
        "--security-opt no-new-privileges:true",
        '"seccomp=$GITHUB_WORKSPACE/docker/seccomp_profile.json"',
        "--cgroupns private --ipc private",
        "--pids-limit 128 --memory 768m --cpus 1.0 --shm-size 64m",
        "--tmpfs /tmp:rw,noexec,nosuid,size=32m",
        "--tmpfs /home/boca-browser:rw,noexec,nosuid,size=16m,uid=10002,gid=10002,mode=0700",
        "browser_type.launch(headless=True, timeout=20000, **options)",
        'page.goto("about:blank", timeout=10000)',
        "BOCA_FULL_PLAYWRIGHT_LAUNCH",
    ):
        assert guard in step

    source = step.split('--entrypoint python "$IMAGE" -c \'\n', 1)[1].split(
        "\n          ' ; then\n", 1
    )[0]
    ast.parse(textwrap.dedent(source))
    for forbidden in (
        "synthetic.py",
        "ipc_worker.py",
        "https://",
        "http://",
        "docker pull",
        "docker push",
        "docker login",
        "ssh ",
        "print(error)",
        "print(captured)",
    ):
        assert forbidden not in step


def test_diagnostic_is_not_a_release_or_cutover_gate() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Probe each Playwright engine in a separate offline process" not in workflow
    assert "Verify isolated Chromium launch offline" in CI.read_text(encoding="utf-8")
    assert "Verify all full Playwright browser bundles" in CI.read_text(encoding="utf-8")
    assert "publish-reviewed-image" in workflow
    diagnostic = DIAGNOSTIC.read_text(encoding="utf-8")
    assert "--tmpfs /home/boca-browser:rw,noexec,nosuid,size=16m,uid=10002,gid=10002,mode=0700" in (
        diagnostic
    )
    for forbidden in (
        "boca-first-deploy",
        "cutover-a-apply",
        "docker push",
        "docker login",
        "ssh ",
    ):
        assert forbidden not in diagnostic
