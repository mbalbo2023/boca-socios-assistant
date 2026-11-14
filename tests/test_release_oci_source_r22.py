"""Offline regression for Boca's exact OCI image-source provenance at release.

Docker image cleanup recognizes a Boca image only when its OCI source label
equals BOCA_SOURCE. Both publish and pull-request builds must exercise the
same build and inspect contract. This never invokes Docker or a real host.
"""

from __future__ import annotations

import re
from pathlib import Path

from boca_socios.host_boca_cleanup import BOCA_SOURCE

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/release-image.yml"
CI = WORKFLOW.with_name("ci.yml")
CANONICAL_SOURCE = "https://github.com/mbalbo2023/boca-socios-assistant"
STEP = re.compile(
    r"^      - name: (?P<name>[^\n]+)\n(?P<body>.*?)(?=^      - name: |\Z)",
    re.MULTILINE | re.DOTALL,
)
SOURCE_BUILD_LABEL = re.compile(
    r'(?:--label "|^\s+)org\.opencontainers\.image\.source=([^"\n]+)',
    re.MULTILINE,
)


def _all_steps() -> list[tuple[str, str]]:
    return [
        (step["name"], step["body"])
        for step in STEP.finditer(WORKFLOW.read_text() + CI.read_text())
    ]


def test_canonical_label_matches_exact_cleanup_provenance() -> None:
    assert BOCA_SOURCE == CANONICAL_SOURCE


def test_both_roles_are_labeled_in_pr_and_publish_builds() -> None:
    steps = _all_steps()
    expected = {
        "Build one local controller image": 1,
        "Build isolated image without deploying": 1,
        "Build one local browser worker image": 1,
        "Build isolated Chromium worker without deploying": 1,
    }
    for step_name, count in expected.items():
        matches = [body for name, body in steps if name == step_name]
        assert len(matches) == count
        for body in matches:
            if step_name == "Build isolated image without deploying":
                assert "uses: docker/build-push-action@" in body
                assert f"org.opencontainers.image.source={CANONICAL_SOURCE}" in body
                assert "org.opencontainers.image.revision=${{ github.sha }}" in body
                assert "load: true" in body and "push: false" in body
                assert "${{ github.sha }}" in body
                assert "file: ./Dockerfile\n" in body
            else:
                assert "docker build" in body
                assert f'--label "org.opencontainers.image.source={CANONICAL_SOURCE}"' in body
                assert '--label "org.opencontainers.image.revision=$SOURCE_SHA"' in body
                if "Chromium" in step_name:
                    assert "SOURCE_SHA: ${{ github.sha }}" in body
                    assert '--tag "boca-browser-ci:$SOURCE_SHA"' in body
                    assert "--builder default" in body
                else:
                    assert '--tag "$IMAGE"' in body
                if "browser" in step_name or "Chromium" in step_name:
                    assert "--file Dockerfile.browser" in body
                else:
                    assert "--file Dockerfile.browser" not in body
    labels = SOURCE_BUILD_LABEL.findall(WORKFLOW.read_text() + CI.read_text())
    # Release pair + primary PR pair + controller-only cold fallback.
    assert labels == [CANONICAL_SOURCE] * 5


def test_both_roles_verify_exact_published_oci_source_label() -> None:
    steps = _all_steps()
    for step_name in ("Verify source revision label", "Verify browser source revision label"):
        matches = [body for name, body in steps if name == step_name]
        assert len(matches) == 2
        for body in matches:
            assert 'index .Config.Labels "org.opencontainers.image.source"' in body
            assert f'= "{CANONICAL_SOURCE}"' in body
            assert 'index .Config.Labels "org.opencontainers.image.revision"' in body
            assert '= "$SOURCE_SHA"' in body
    # No weaker alternative, foreign repository or unverified image source in
    # any release build or verification branch.
    assert (WORKFLOW.read_text() + CI.read_text()).count(
        'index .Config.Labels "org.opencontainers.image.source"'
    ) == 4
