"""Single existing protected selector authenticates real dual ZIPs on the runner."""

from pathlib import Path

FLOW = (Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml").read_text()


def _apply() -> str:
    heading = "      - name: Upgrade Boca-only rootless pair under one lease\n"
    assert FLOW.count(heading) == 1
    return FLOW.split(heading, 1)[1].split("      - name:", 1)[0]


def test_existing_apply_authenticates_dual_release_before_any_remote_command() -> None:
    body = _apply()
    assert body.count("gh run download") == 2  # Dual release only; observations via REST ZIP.
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


def test_observation_is_a_separate_authenticated_run_before_memfd_or_ssh() -> None:
    body = _apply()
    auth = body.index("python3 -m boca_socios.host_boca_upgrade_observation_bridge")
    build = body.index("scripts/build_protected_boca_bundle.py --pair-upgrade")
    remote = body.index("timeout --signal=TERM")
    assert auth < build < remote
    assert "--name boca-installed-pair-observation" not in body
    assert '"$BOCA_PROTECTED_ACTION_CONTEXT"' in body
    assert '"$GITHUB_RUN_ID" "$BOCA_RELEASE_RUN_ID"' in body
    assert "BOCA_OBSERVATION_AUTH state=VERIFIED host_authorized=false" in body
    assert "observation-proof.json" in body
    assert "boca-pair-observation.receipt" in body
    admission = FLOW.split("            boca-pair-upgrade-apply)\n", 1)[1].split(
        "              ;;", 1
    )[0]
    assert '[[ "$BOCA_PROTECTED_ACTION_CONTEXT" =~ ^[1-9][0-9]{0,19}$ ]]' in admission
    assert 'test "$BOCA_PROTECTED_ACTION_CONTEXT" != "$GITHUB_RUN_ID"' in admission
    assert 'test "$BOCA_PROTECTED_ACTION_CONTEXT" != "$BOCA_RELEASE_RUN_ID"' in admission
    assert '"$BOCA_PROTECTED_ACTION_CONTEXT" "$BOCA_LEGACY_SOURCE_SHA"' not in admission
    assert "actions: read" in FLOW.split("  deploy:\n", 1)[1].split("    steps:\n", 1)[0]
    assert "actions: write" not in FLOW


def test_two_readonly_observers_are_authenticated_in_memory_before_any_host_zip() -> None:
    body = _apply()
    pair = body.index("python3 -m boca_socios.host_boca_upgrade_observation_bridge")
    retained = body.index("python3 -m boca_socios.host_boca_upgrade_retained_bridge")
    builder = body.index("scripts/build_protected_boca_bundle.py --pair-upgrade")
    assert pair < retained < builder
    assert 'gh run download "$BOCA_PROTECTED_ACTION_CONTEXT"' not in body
    assert 'gh run download "$BOCA_RETAINED_OBSERVATION_RUN_ID"' not in body
    assert "boca-retained-observation.receipt" in body
    assert "retained-proof.json" in body
    assert "BOCA_RETAINED_AUTH state=VERIFIED host_authorized=false" in body
    assert '"$BOCA_RETAINED_OBSERVATION_RUN_ID"' in body
    assert "retained_observation_run_id:" not in FLOW
    assert (
        "BOCA_RETAINED_OBSERVATION_RUN_ID: ${{ inputs.operation == 'boca-pair-upgrade-apply' "
        "&& inputs.official_news_run_id || '' }}"
    ) in FLOW
    assert (
        "BOCA_OFFICIAL_NEWS_RUN_ID: ${{ inputs.operation != 'boca-pair-upgrade-apply' "
        "&& inputs.official_news_run_id || '' }}"
    ) in FLOW
    assert 'test -z "${BOCA_RETAINED_OBSERVATION_RUN_ID:-}"' in FLOW
    admission = FLOW.split("            boca-pair-upgrade-apply)\n", 1)[1].split(
        "              ;;", 1
    )[0]
    assert '[[ "$BOCA_RETAINED_OBSERVATION_RUN_ID" =~ ^[1-9][0-9]{0,19}$ ]]' in admission
    assert (
        'test "$BOCA_RETAINED_OBSERVATION_RUN_ID" != "$BOCA_PROTECTED_ACTION_CONTEXT"' in admission
    )


def test_release_bearer_is_never_a_remote_argument_and_old_selector_is_reused() -> None:
    body = _apply()
    remote = body[body.index("remote_command=") : body.index("receipt_dir=")]
    assert "GH_TOKEN" not in remote
    assert "GITHUB_TOKEN" not in remote
    assert "legacy" not in remote
    assert '"boca-pair-upgrade-apply"' in remote
    assert "boca-pair-upgrade-v2" not in FLOW
    assert FLOW.count("if: inputs.operation == 'boca-pair-upgrade-apply'") == 1
