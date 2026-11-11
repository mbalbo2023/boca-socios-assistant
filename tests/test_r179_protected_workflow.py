"""R179 GitHub Actions admits read-only SQLite and exact Boca-only dual APPLY."""

from __future__ import annotations

from pathlib import Path

FLOW = (Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml").read_text()


def _step(name: str) -> str:
    heading = f"      - name: {name}\n"
    assert FLOW.count(heading) == 1
    return FLOW.split(heading, 1)[1].split("      - name:", 1)[0]


def _case(name: str) -> str:
    admission = _step("Require verified protected environment and matching main commit")
    return admission.split(f"            {name})\n", 1)[1].split("              ;;", 1)[0]


def test_r179_operation_choices_and_admission_are_exact():
    operations = FLOW.split("      operation:\n", 1)[1].split("      source_sha:", 1)[0]
    assert "boca-sqlite-inode-observe" in operations
    assert "boca-pair-upgrade-apply" in operations
    observer = _case("boca-sqlite-inode-observe")
    for required in (
        'test "$BOCA_HOST_READONLY_ENV_READY" = ready',
        'test "$BOCA_DEPLOY_ENV_READY" = ready',
        'test "$BOCA_SOURCE_SHA" = "$GITHUB_SHA"',
        'test "$BOCA_BUDGET" = 1.5cpu-1024m-192pids',
        '"$BOCA_IMAGE_REF"',
        '"$BOCA_BROWSER_IMAGE_REF"',
        '"$BOCA_RELEASE_RUN_ID"',
        '"$BOCA_PROTECTED_ACTION_CONTEXT"',
        'test -z "$unexpected"',
    ):
        assert required in observer
    apply = _case("boca-pair-upgrade-apply")
    for required in (
        'test "$BOCA_DEPLOY_ENV_READY" = ready',
        'test "$BOCA_SOURCE_SHA" = "$GITHUB_SHA"',
        'test "$BOCA_BUDGET" = 1.5cpu-1024m-192pids',
        '"$BOCA_LEGACY_CONTROLLER_ID"',
        '"$BOCA_PROTECTED_ACTION_CONTEXT"',
        '"$BOCA_SITE_ENVELOPE"',
        '"$BOCA_TELEGRAM_ENVELOPE"',
        'test -z "$unexpected"',
    ):
        assert required in apply


def test_r179_readonly_witness_has_no_host_writes_or_caller_pins():
    body = _step("Observe Boca SQLite inode identity READ_ONLY")
    for needed in (
        "if: inputs.operation == 'boca-sqlite-inode-observe'",
        "scripts/build_protected_boca_bundle.py --sqlite-observe",
        "scripts/boca_protected_memfd_bootstrap.py",
        '"boca-sqlite-inode-observe"',
        '"$GITHUB_RUN_ID"',
        "check_main_ref.py",
        "sha256sum",
        "boca-target",
        "host_boca_pair_upgrade_cli verify-sqlite",
        "GITHUB_STEP_SUMMARY",
        "cutover=NO_GO",
        '"state":"VERIFIED_STABLE"',
    ):
        assert needed in body
    for forbidden in (
        "docker start",
        "docker stop",
        "docker rm",
        "docker exec",
        "docker compose",
        "sudo",
        "cutover-a-apply",
        "boca-pair-upgrade-apply",
        "protected_boca_job_lease",
    ):
        assert forbidden not in body


def test_r179_dual_apply_requires_verified_release_and_bounded_memfd():
    release_step = _step("Require same-run immutable browser companion release manifest")
    assert "inputs.operation == 'boca-pair-upgrade-apply'" in release_step
    review = _step("Validate immutable inputs and successful matching release")
    assert "inputs.operation == 'boca-pair-upgrade-apply'" in review
    body = _step("Upgrade Boca-only rootless pair under one lease")
    for needed in (
        "if: inputs.operation == 'boca-pair-upgrade-apply'",
        "scripts/build_protected_boca_bundle.py --pair-upgrade",
        "scripts/boca_protected_memfd_bootstrap.py",
        '"boca-pair-upgrade-apply"',
        '"$GITHUB_RUN_ID"',
        '"$BOCA_IMAGE_REF"',
        '"$BOCA_BROWSER_IMAGE_REF"',
        '"$BOCA_RELEASE_RUN_ID"',
        "sha256sum",
        "boca-target",
        "host_boca_pair_upgrade_cli verify-upgrade",
        "GITHUB_STEP_SUMMARY",
        '"state":"ACCEPTED"',
        "READ_ONLY_RCA_NO_AUTOMATIC_RETRY",
    ):
        assert needed in body
    for forbidden in (
        "docker system prune",
        "docker rm -f $(",
        "docker compose down",
        "sudo docker",
    ):
        assert forbidden not in body


def test_r179_qa_in_workflow_before_any_ssh():
    body = _step("Validate Boca installed pair observer offline only")
    for name in (
        "test_r179_protected_bundles.py",
        "test_r179_protected_workflow.py",
        "test_host_boca_sqlite_identity.py",
        "test_host_boca_pair_upgrade.py",
        "test_host_on_demand_replace.py",
    ):
        assert name in body
