"""R186 one-off deploy contract isolated from the failed full APPLY."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/boca-first-deploy.yml"


def test_one_shot_finalizer_reuses_existing_exclusive_manual_boca_host_path() -> None:
    raw = WORKFLOW.read_text(encoding="utf-8")
    assert "concurrency:\n  group: ${{ github.event_name == 'pull_request'" in raw
    assert "environment: boca-first-deploy" in raw
    assert "boca-postcommit-finalize" in raw.split("options: [", 1)[1].split("]", 1)[0]
    assert "--postcommit-finalize" in raw
    assert "host_boca_pair_postcommit_finalize verify" in raw
    assert "if: inputs.operation == 'boca-postcommit-finalize'" in raw
    assert "checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in raw
    assert "GITHUB_RUN_ATTEMPT" in raw
    assert "refs/heads/main" in raw
    assert "BOCA_DEPLOY_KNOWN_HOSTS" in raw
    assert "BOCA_DEPLOY_SSH_KEY" in raw
    assert "gh api" in raw and "/pulls?state=open" in raw
    assert "43229793525" in raw and "43230212167" in raw
    assert "BOCA_POSTCOMMIT_FINALIZE" in raw
    # A PR's successful checks do not prove the distinct postmerge main SHA.
    assert "boca-r186-main-checks.json" in raw
    assert ".github/workflows/ci.yml" in raw
    assert ".github/workflows/image-security.yml" in raw
    assert '"event":"push"' in raw or '.event == "push"' in raw
