"""R247: disposable BuildKit cache must never become Boca release provenance."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
SETUP = "docker/setup-buildx-action@e468171a9de216ec08956ac3ada2f0791b6bd435"
BUILD = "docker/build-push-action@263435318d21b8e681c14492fe198d362a7d2c83"


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _job(name: str, ident: str) -> str:
    body = _workflow(name).split(f"  {ident}:\n", 1)[1]
    return re.split(r"\n  (?=[a-z][a-z0-9_-]*:\n)", body, maxsplit=1)[0]


def _build_steps(job: str) -> list[str]:
    return [block for block in job.split("      - name: ")[1:] if f"uses: {BUILD}" in block]


def test_ci_keeps_controller_cache_and_one_native_browser_build() -> None:
    image = _job("ci.yml", "image")
    assert image.count(f"uses: {SETUP}") == 1
    assert "id: setup_buildx" in image
    builds = _build_steps(image)
    assert len(builds) == 1
    assert all("load: true" in step and "push: false" in step for step in builds)
    for step, role in zip(builds, ("controller",), strict=True):
        assert "context: ." in step
        assert f"cache-from: type=gha,scope=boca-main-{role}-r247" in step
        assert "github.event_name == 'push'" in step.split("cache-to:", 1)[1]
        assert (
            "github.repository == 'mbalbo2023/boca-socios-assistant'"
            in step.split("cache-to:", 1)[1]
        )
        assert "github.ref == 'refs/heads/main'" in step.split("cache-to:", 1)[1]
        assert f"scope=boca-main-{role}-r247" in step.split("cache-to:", 1)[1]
        assert "ignore-error=true" in step
        assert "org.opencontainers.image.revision=${{ github.sha }}" in step
        assert (
            "org.opencontainers.image.source=https://github.com/mbalbo2023/boca-socios-assistant"
            in step
        )
        assert "${{ github.sha }}" in step
    browser = image.split("      - name: Build isolated Chromium worker without deploying\n", 1)[
        1
    ].split("      - name:", 1)[0]
    assert "if: steps.docs_pr_scope.outputs.docs_only != 'true'\n" in browser
    assert "continue-on-error" not in browser
    assert "SOURCE_SHA: ${{ github.sha }}" in browser
    assert "docker build --builder default --file Dockerfile.browser" in browser
    assert 'org.opencontainers.image.revision=$SOURCE_SHA"' in browser
    assert (
        "org.opencontainers.image.source=https://github.com/mbalbo2023/boca-socios-assistant"
        in browser
    )
    for tag in ("boca-browser-ci", "boca-browser-release-validation", "boca-observer"):
        assert f'--tag "{tag}:$SOURCE_SHA"' in browser
    assert 'org.boca.public-image=${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"' in browser
    assert "boca-main-browser-r247" not in image
    assert "steps.setup_buildx.outcome == 'failure'" in image
    assert "steps.cached_controller_build.outcome == 'failure'" in image
    assert "cached_browser_build" not in image
    assert image.count("docker build ") == 2  # controller fallback + primary browser


def test_independent_main_security_still_builds_and_scans_both_images_from_read_only_cache() -> (
    None
):
    security = _workflow("image-security.yml")
    for job, role in (("controller-scan", "controller"), ("browser-scan", "browser")):
        body = _job("image-security.yml", job)
        assert "cache-mode:" not in body  # invalid job keyword in Actions
        assert body.count(f"uses: {SETUP}") == 1
        assert "id: setup_buildx" in body
        builds = _build_steps(body)
        assert len(builds) == 1
        assert "load: true" in builds[0] and "push: false" in builds[0]
        assert f"cache-from: type=gha,scope=boca-main-{role}-r247" in builds[0]
        assert "cache-to:" not in builds[0]
        assert "${{ github.sha }}" in builds[0]
        assert body.count("scripts/trivy_scan_image.sh") == 1
        assert "steps.setup_buildx.outcome == 'failure'" in body
        assert f"steps.cached_{role}_build.outcome == 'failure'" in body
        assert body.count("docker build ") == 1  # cold fallback only
    assert "  pull_request:" not in security
    assert "name: image-security-scan" in security


def test_protected_release_remains_cold_exact_sha_and_independently_scanned() -> None:
    publish = _job("release-image.yml", "publish")
    assert "cache-mode:" not in publish  # release explicitly avoids every cache input
    assert publish.count("docker build ") == 2
    assert publish.count("scripts/trivy_scan_image.sh") == 2
    assert "docker/build-push-action" not in publish
    assert "cache-from" not in publish
    assert "environment: boca-image-release" in publish
