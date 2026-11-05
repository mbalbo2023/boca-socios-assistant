"""R34 redacted dual source: workflow-only fix does not require OCI rebuild."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_telegram_release_lineage as lineage  # noqa: E402

IMAGE_SHA = "a" * 40
WORKFLOW_SHA = "b" * 40


def _response(
    *, status: str = "ahead", ahead_by: int = 2, behind_by: int = 0, **fields: object
) -> bytes:
    value = {
        "status": status,
        "ahead_by": ahead_by,
        "behind_by": behind_by,
        "base_sha": IMAGE_SHA,
        "merge_base_sha": IMAGE_SHA,
    } | fields
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def test_future_workflow_source_may_be_descendant_of_original_image_without_rebuild() -> None:
    result = lineage.verify_dual_source_lineage(
        image_source_sha=IMAGE_SHA, workflow_sha=WORKFLOW_SHA, compare_json=_response()
    )
    assert result.image_source_sha == IMAGE_SHA
    assert result.workflow_sha == WORKFLOW_SHA
    assert result.state == "ANCESTRY_OBSERVED_NO_GO"
    assert result.independent_go_b is False
    assert result.host_effects is False
    assert result.sender_state == "OFF"


def test_same_sha_is_valid_for_first_integrated_release() -> None:
    result = lineage.verify_dual_source_lineage(
        image_source_sha=IMAGE_SHA,
        workflow_sha=IMAGE_SHA,
        compare_json=_response(status="identical", ahead_by=0),
    )
    assert result.workflow_sha == result.image_source_sha == IMAGE_SHA


@pytest.mark.parametrize(
    "field_changes",
    (
        {"status": "diverged"},
        {"status": "behind"},
        {"status": "identical", "ahead_by": 0},
        {"ahead_by": 0},
        {"ahead_by": -1},
        {"ahead_by": 100_001},
        {"behind_by": 1},
        {"behind_by": -1},
        {"base_sha": WORKFLOW_SHA},
        {"merge_base_sha": WORKFLOW_SHA},
        {"extra_go": "ready"},
    ),
)
def test_unproven_ancestry_or_extra_authority_fails_closed(
    field_changes: dict[str, object],
) -> None:
    with pytest.raises(lineage.TelegramLineageNoGo, match="unverified"):
        lineage.verify_dual_source_lineage(
            image_source_sha=IMAGE_SHA,
            workflow_sha=WORKFLOW_SHA,
            compare_json=_response(**field_changes),
        )


@pytest.mark.parametrize(
    "raw",
    (
        b"",
        b'{"status":"ahead","status":"ahead"}',
        b'{"status":"ahead","ahead_by":NaN}',
        b'{"status":"ahead","ahead_by":true}',
        b"x" * 513,
        _response() + b"\n",
    ),
)
def test_malformed_or_noncanonical_json_rejected(raw: bytes) -> None:
    with pytest.raises(lineage.TelegramLineageNoGo):
        lineage.verify_dual_source_lineage(
            image_source_sha=IMAGE_SHA, workflow_sha=WORKFLOW_SHA, compare_json=raw
        )


def test_source_sha_binding_never_coerces_or_accepts_unknown_hash() -> None:
    for source, workflow in (
        ("", WORKFLOW_SHA),
        (IMAGE_SHA.upper(), WORKFLOW_SHA),
        (IMAGE_SHA, "x"),
    ):
        with pytest.raises(lineage.TelegramLineageNoGo):
            lineage.verify_dual_source_lineage(
                image_source_sha=source, workflow_sha=workflow, compare_json=_response()
            )


def test_cli_only_offline_and_outputs_redacted_nongo(tmp_path: Path) -> None:
    proof = tmp_path / "public-compare.json"
    proof.write_bytes(_response() + b"\n")  # `jq -cS` runner framing
    result = subprocess.run(  # noqa: S603 - local fixed Python, no host
        [
            sys.executable,
            str(ROOT / "scripts" / "check_telegram_release_lineage.py"),
            IMAGE_SHA,
            WORKFLOW_SHA,
            str(proof),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == (
        "BOCA_TELEGRAM_LINEAGE state=ANCESTRY_OBSERVED_NO_GO host=untouched sender=OFF"
    )
    assert result.stderr == ""
    proof.write_bytes(_response(behind_by=1))
    rejected = subprocess.run(  # noqa: S603 - local fixed Python, no host
        [
            sys.executable,
            str(ROOT / "scripts" / "check_telegram_release_lineage.py"),
            IMAGE_SHA,
            WORKFLOW_SHA,
            str(proof),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert rejected.returncode == 1
    assert rejected.stdout.strip() == (
        "BOCA_TELEGRAM_LINEAGE state=NO_GO reason=unverified sender=OFF"
    )


def test_untrusted_optional_inputs_and_symlink_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "real-compare.json"
    source.write_bytes(_response())
    link = tmp_path / "link-compare.json"
    link.symlink_to(source)
    assert lineage.main([IMAGE_SHA, WORKFLOW_SHA, str(link)]) == 1
    assert lineage.main([IMAGE_SHA, WORKFLOW_SHA]) == 2


def test_protected_workflow_keeps_telegram_two_sha_review_before_any_host_transport() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    gate = workflow.split("      - name: Require verified protected environment", 1)[1].split(
        "      - name: Reject legacy install routes", 1
    )[0]
    main_check = workflow.split("      - name: Confirm current main HEAD before host access", 1)[
        1
    ].split("      - name:", 1)[0]
    source = workflow.split(
        "      - name: Prove Telegram dual-source release ancestry CODE_ONLY then reject physical activation\n",
        1,
    )[1].split("      - name:", 1)[0]
    assert 'if [[ "$BOCA_OPERATION" = telegram-activate ]]; then' in gate
    assert 'test "$BOCA_SOURCE_SHA" = "$GITHUB_SHA"' in gate
    assert "telegram-activate)" in gate
    assert "host_same_lease_backend_unverified" not in gate
    assert (
        'if [[ "$BOCA_OPERATION" = telegram-activate ]]; then verified_main="$GITHUB_SHA"; fi'
        in (main_check)
    )
    assert "if: inputs.operation == 'telegram-activate'" in source
    assert "compare/$BOCA_SOURCE_SHA...$GITHUB_SHA" in source
    assert "jq -cS" in source
    assert "check_telegram_release_lineage.py" in source
    assert "build_protected_telegram_bundle.py" in source
    assert "state=NO_GO reason=host_same_lease_backend_unverified host=untouched sender=OFF" in (
        source
    )
    assert "exit 1" in source
    assert "ssh " not in source and "docker " not in source
    assert workflow.index(
        "      - name: Prove Telegram dual-source release ancestry CODE_ONLY"
    ) < workflow.index("      - name: Configure pinned SSH host key and dedicated identity")
    assert (
        workflow.count("      - name: Prove Telegram dual-source release ancestry CODE_ONLY") == 1
    )
