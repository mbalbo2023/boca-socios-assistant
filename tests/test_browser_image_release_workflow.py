"""One protected release produces both scoped OCI digests, never a CI deploy."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/release-image.yml"


def test_release_candidate_contains_the_merged_ipc_worker_entrypoint() -> None:
    dockerfile = (ROOT / "Dockerfile.browser").read_text(encoding="utf-8")
    assert 'CMD ["python", "-m", "boca_socios.browser.ipc_worker"]' in dockerfile
    assert 'CMD ["python", "scripts/verify_chromium_worker.py"]' not in dockerfile


def test_browser_pr_validation_builds_scans_but_never_publishes() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "on:\n  pull_request:\n  workflow_dispatch:" in workflow
    assert "  push:" not in workflow
    assert "permissions:\n  contents: read" in workflow
    preview = workflow.split("  pr-validation:\n", 1)[1].split("  publish:\n", 1)[0]
    assert "github.event_name == 'pull_request'" in preview
    assert "Build one local controller image" in preview
    assert "Build one local browser worker image" in preview
    assert "docker build --file Dockerfile.browser" in preview
    assert "Verify browser source revision label" in preview
    assert "org.opencontainers.image.revision=$SOURCE_SHA" in preview
    assert "Require the reviewed browser IPC worker command" in preview
    assert '["python","-m","boca_socios.browser.ipc_worker"]' in preview
    assert (
        preview.index("Verify browser source revision label")
        < preview.index("Require the reviewed browser IPC worker command")
        < preview.index("Scan browser image before any publication")
    )
    assert "Scan browser image before any publication" in preview
    assert preview.count("uses: aquasecurity/trivy-action@") == 2
    assert "docker push" not in preview
    assert "docker login" not in preview
    assert "packages: write" not in preview


def test_protected_main_release_scans_both_before_any_ghcr_auth_or_push() -> None:
    publish = WORKFLOW.read_text(encoding="utf-8").split("  publish:\n", 1)[1]
    assert "github.event_name == 'workflow_dispatch'" in publish
    assert "github.ref == 'refs/heads/main'" in publish
    assert "github.repository == 'mbalbo2023/boca-socios-assistant'" in publish
    assert "github.actor == 'mbalbo2023'" in publish
    assert "environment: boca-image-release" in publish
    assert "packages: write" in publish and "actions: read" in publish
    assert "id-token: write" not in publish and "attestations: write" not in publish
    first_attempt = publish.index('test "$GITHUB_RUN_ATTEMPT" = 1')
    controller_build = publish.index("Build one local controller image")
    browser_build = publish.index("Build one local browser worker image")
    controller_scan = publish.index("Scan the image that will be published")
    browser_scan = publish.index("Scan browser image before any publication")
    recheck = publish.index("Recheck current main source before publication")
    unique = publish.index("Recheck unique dispatch before registry login")
    login = publish.index("Log in only after successful scan")
    push = publish.index("Publish both scanned images and record immutable digests")
    assert first_attempt < controller_build < browser_build < controller_scan < browser_scan
    assert browser_scan < recheck < unique < login < push
    assert publish.count("python scripts/check_main_ref.py") == 2
    assert publish.count("python scripts/check_release_dispatch.py") == 2
    assert publish.count("uses: aquasecurity/trivy-action@") == 2
    assert "ghcr.io/mbalbo2023/boca-socios-assistant:sha-${{ github.sha }}" in publish
    assert "ghcr.io/mbalbo2023/boca-socios-assistant-browser:sha-${{ github.sha }}" in publish
    assert "Verify browser source revision label" in publish
    assert "org.opencontainers.image.revision=$SOURCE_SHA" in publish
    assert "Require the reviewed browser IPC worker command" in publish
    assert '["python","-m","boca_socios.browser.ipc_worker"]' in publish
    assert (
        publish.index("Verify browser source revision label")
        < publish.index("Require the reviewed browser IPC worker command")
        < controller_scan
    )
    assert "--role browser" in publish
    assert "--role controller" in publish
    assert 'docker push "$BROWSER_IMAGE"' in publish
    assert 'docker push "$CONTROLLER_IMAGE"' in publish
    assert ":latest" not in publish


def test_controller_v1_manifest_preserved_and_browser_companion_uploaded_only_after_push() -> None:
    publish = WORKFLOW.read_text(encoding="utf-8").split("  publish:\n", 1)[1]
    pushed = publish.index("Publish both scanned images and record immutable digests")
    legacy_writer = publish.index("python -m boca_socios.release_manifest write")
    companion_writer = publish.index("python -m boca_socios.browser_release_manifest write")
    legacy_upload = publish.index("name: boca-release-manifest")
    companion_upload = publish.index("name: boca-browser-release-manifest")
    assert pushed < legacy_writer < companion_writer < legacy_upload < companion_upload
    assert "boca-release-manifest.json" in publish
    assert "boca-browser-release-manifest.json" in publish
    assert publish.count("uses: actions/upload-artifact@") == 2
    assert publish.count("if-no-files-found: error") == 2
    assert publish.count("overwrite: false") == 2
    assert publish.count("retention-days: 30") == 2
    assert "github.sha" in publish and "GITHUB_RUN_ID" in publish
    assert publish.index('docker push "$BROWSER_IMAGE"') < publish.index(
        'docker push "$CONTROLLER_IMAGE"'
    )
    assert publish.index('docker push "$CONTROLLER_IMAGE"') < legacy_writer
    assert "set -euo pipefail" in publish[pushed:legacy_writer]


def test_every_release_image_scan_blocks_high_critical_vulnerabilities() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    preview = workflow.split("  pr-validation:\n", 1)[1].split("  publish:\n", 1)[0]
    publish = workflow.split("  publish:\n", 1)[1]
    for section, controller_name in (
        (preview, "Scan before any image publication"),
        (publish, "Scan the image that will be published"),
    ):
        for name in (controller_name, "Scan browser image before any publication"):
            scan = section.split(f"      - name: {name}\n", 1)[1].split("      - name:", 1)[0]
            assert (
                "uses: aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25" in scan
            )
            for guard in (
                "scanners: vuln",
                "vuln-type: os,library",
                "severity: HIGH,CRITICAL",
                'ignore-unfixed: "false"',
                'exit-code: "1"',
            ):
                assert guard in scan
