"""R258 bounded Boca-only rootless mapping witness Actions contract (offline)."""

from __future__ import annotations

from pathlib import Path

WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
).read_text(encoding="utf-8")
OPERATION = "boca-rootless-mapping-observe"


def _step(name: str) -> str:
    marker = f"      - name: {name}\n"
    assert WORKFLOW.count(marker) == 1
    return WORKFLOW.split(marker, 1)[1].split("      - name:", 1)[0]


def test_rootless_mapping_observer_is_owner_main_only_and_fixes_cpu_budget() -> None:
    choices = WORKFLOW.split("      operation:\n", 1)[1].split("      source_sha:", 1)[0]
    assert choices.count(f"{OPERATION},") == 1
    assert "github.event_name == 'workflow_dispatch'" in WORKFLOW
    assert "github.repository == 'mbalbo2023/boca-socios-assistant'" in WORKFLOW
    assert "github.ref == 'refs/heads/main'" in WORKFLOW
    assert "github.actor == 'mbalbo2023'" in WORKFLOW
    assert "environment: boca-first-deploy" in WORKFLOW
    assert "'boca-first-deploy'" in WORKFLOW.split("concurrency:", 1)[1].split("jobs:", 1)[0]
    source = WORKFLOW.split("BOCA_SOURCE_SHA:", 1)[1].split("BOCA_SOURCE_SHA_SUBMITTED:", 1)[0]
    assert "inputs.operation == 'boca-rootless-mapping-observe'" in source
    budget = WORKFLOW.split("BOCA_BUDGET:", 1)[1].split("BOCA_RELEASE_RUN_ID:", 1)[0]
    assert "inputs.operation == 'boca-rootless-mapping-observe'" in budget
    assert "'1.5cpu-1024m-192pids'" in budget


def test_rootless_mapping_admission_rejects_all_caller_supplied_pins_and_secrets() -> None:
    block = _step("Require verified protected environment and matching main commit")
    case = block.split(f"            {OPERATION})\n", 1)[1].split("              ;;", 1)[0]
    for required in (
        'test "$BOCA_HOST_READONLY_ENV_READY" = ready',
        'test "$BOCA_DEPLOY_ENV_READY" = ready',
        'test "$BOCA_SOURCE_SHA" = "$GITHUB_SHA"',
        'test "$BOCA_BUDGET" = 1.5cpu-1024m-192pids',
        '"$BOCA_SOURCE_SHA_SUBMITTED"',
        '"$BOCA_PROTECTED_ACTION_CONTEXT"',
        '"$BOCA_IMAGE_REF"',
        '"$BOCA_BROWSER_IMAGE_REF"',
        '"$BOCA_RELEASE_RUN_ID"',
        '"$BOCA_LEGACY_CONTROLLER_ID"',
        '"$BOCA_SITE_ENVELOPE"',
        '"$BOCA_TELEGRAM_ENVELOPE"',
        '"$BOCA_OWNER_ENVELOPE"',
        '"$BOCA_OWNER_CAPABILITY_SHA256"',
        '"$BOCA_OFFICIAL_NEWS_JSONL_SHA256"',
        '"$BOCA_OFFICIAL_NEWS_OBSERVED_AT_UTC"',
        'test -z "$unexpected"',
    ):
        assert required in case
    # Read-only observes metadata, not user passkey enrollment or owner approval.
    assert 'test "$BOCA_BETA_ENV_READY" = ready' not in case
    assert 'test "$BOCA_BROWSER_ENV_READY" = ready' not in case


def test_rootless_mapping_uses_exact_single_readonly_ssh_and_verified_receipt() -> None:
    body = _step("Observe Boca rootless mapped inode custody READ_ONLY")
    for required in (
        "if: inputs.operation == 'boca-rootless-mapping-observe'",
        "scripts/build_protected_boca_bundle.py --rootless-mapped-observe",
        "scripts/boca_protected_memfd_bootstrap.py",
        '"boca-rootless-mapping-observe"',
        '"$GITHUB_RUN_ID"',
        "host_boca_rootless_mapping_cli.py",
        "check_main_ref.py",
        "sha256sum",
        "canonical_receipt_sha256=",
        '"$RUNNER_TEMP/boca-ssh/config"',
        "boca-target",
        "timeout --signal=TERM --kill-after=5s 180s ssh",
        "ulimit -f 4",
        "host_boca_rootless_mapping_cli verify",
        "BOCA_ROOTLESS_MAPPING state=NO_GO",
        '"state":"PRELIMINARY_PREDEPLOY"',
        '"lease_verified":true',
        "GITHUB_STEP_SUMMARY",
        "cutover=NO_GO",
    ):
        assert required in body
    assert body.count(" boca-target ") == 1
    assert body.count(" ssh ") == 1
    assert body.index("host_boca_rootless_mapping_cli verify") < body.index(
        "canonical_receipt_sha256="
    )
    assert body.index('"$remote_rc" -ne 0') < body.index(
        'printf \'%s\\n\' "$verified" >> "$GITHUB_STEP_SUMMARY"'
    )
    assert '"state":"VERIFIED_MAPPED"' not in body
    assert "postflight=UNVERIFIED" in body
    assert body.index("check_main_ref.py") < body.index(" ssh ")
    assert body.index("test -f src/boca_socios/host_boca_rootless_mapping_cli.py") < body.index(
        " ssh "
    )
    assert 'cat "$receipt_dir/receipt" >> "$GITHUB_STEP_SUMMARY"' not in body
    for forbidden in (
        "docker compose",
        "docker exec",
        "docker start",
        "docker stop",
        "docker rm",
        "sudo",
        "gh workflow run",
        "cutover-a-apply",
        "boca-pair-upgrade-apply",
        "--pair-upgrade",
        "cleanup-allow",
    ):
        assert forbidden not in body


def test_rootless_mapping_workflow_offline_qa_is_pr_readonly() -> None:
    step = _step("Validate Boca installed pair observer offline only")
    assert "tests/test_r258_rootless_mapping_workflow.py" in step
    assert "test_host_boca_rootless_mapped_custody.py" in step
    assert "if: inputs.operation" not in step
