"""Single existing protected selector authenticates real dual ZIPs on the runner."""

from pathlib import Path

FLOW = (Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml").read_text()


def _apply() -> str:
    heading = "      - name: Upgrade Boca-only rootless pair under one lease\n"
    assert FLOW.count(heading) == 1
    return FLOW.split(heading, 1)[1].split("      - name:", 1)[0]


def test_existing_apply_authenticates_dual_release_before_any_remote_command() -> None:
    body = _apply()
    assert body.count("gh run download") == 2
    auth = body.index("python3 -m boca_socios.host_boca_upgrade_release_bridge")
    first = body.index("--name boca-release-manifest")
    second = body.index("--name boca-browser-release-manifest")
    build = body.index("scripts/build_protected_boca_bundle.py --pair-upgrade")
    remote = body.index("timeout --signal=TERM")
    assert first < second < auth < build < remote
    assert '--pair-upgrade-release-dir "$release_dir"' in body
    assert '"$BOCA_SOURCE_SHA" "$BOCA_RELEASE_RUN_ID"' in body
    assert '"$BOCA_IMAGE_REF" "$BOCA_BROWSER_IMAGE_REF"' in body
    assert "BOCA_RELEASE_AUTH state=VERIFIED host_authorized=false" in body
    assert "GITHUB_RUN_ATTEMPT" in body


def test_release_bearer_is_never_a_remote_argument_and_old_selector_is_reused() -> None:
    body = _apply()
    remote = body[body.index("remote_command=") : body.index("receipt_dir=")]
    assert "GH_TOKEN" not in remote
    assert "GITHUB_TOKEN" not in remote
    assert "legacy" not in remote
    assert '"boca-pair-upgrade-apply"' in remote
    assert "boca-pair-upgrade-v2" not in FLOW
    assert FLOW.count("if: inputs.operation == 'boca-pair-upgrade-apply'") == 1
