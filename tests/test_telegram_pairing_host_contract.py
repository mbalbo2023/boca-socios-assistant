"""Fail-closed source-only Telegram pairing gate shape; never remote host proof."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios.telegram_pairing_host_contract import (
    INTEGRATION_SEQUENCE,
    HostContractError,
    UntrustedHostClaims,
    review_untrusted_host_claims,
)

SHA = "a" * 40
IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64
FP = "c" * 64
NOW = 1_790_000_000
WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/boca-telegram-pairing.yml"


def _synthetic_claims() -> UntrustedHostClaims:
    return UntrustedHostClaims(
        source_sha=SHA,
        installed_source_sha=SHA,
        image_digest=IMAGE,
        installed_image_digest=IMAGE,
        release_run_id=123,
        observed_at=NOW,
        owner_authenticated=True,
        owner_subject_verified=True,
        rootless_uid=10001,
        daemon_inventory_singleton=True,
        daemon_installed_stopped=True,
        controller_service="controller",
        controller_engine_mode="off",
        sender_off=True,
        browser_worker_absent=True,
        origin="http://localhost:8443",
        volume_inventory_verified=True,
        data_schema_0007_verified=True,
        recipient_fingerprint=FP,
        recipient_custody_verified=True,
        dedicated_egress_verified=True,
        no_competing_bot_poller_verified=True,
        host_lease_exclusive=True,
        unrelated_workloads_untouched=True,
    )


def _review(claims: UntrustedHostClaims, **overrides: object) -> object:
    kwargs: dict[str, object] = {
        "expected_source_sha": SHA,
        "expected_image_digest": IMAGE,
        "trusted_now": NOW,
    }
    kwargs.update(overrides)
    return review_untrusted_host_claims(claims, **kwargs)  # type: ignore[arg-type]


def test_even_entirely_positive_claims_never_authorize_or_execute() -> None:
    result = _review(_synthetic_claims())
    assert result.state == "EVIDENCE_SHAPE_ONLY"  # type: ignore[attr-defined]
    assert result.authorized is False  # type: ignore[attr-defined]
    assert result.executable is False  # type: ignore[attr-defined]
    assert result.human_receipt == "UNVERIFIED"  # type: ignore[attr-defined]
    assert result.source_sha == SHA  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "field",
    [
        "owner_authenticated",
        "owner_subject_verified",
        "daemon_inventory_singleton",
        "daemon_installed_stopped",
        "sender_off",
        "browser_worker_absent",
        "volume_inventory_verified",
        "data_schema_0007_verified",
        "recipient_custody_verified",
        "dedicated_egress_verified",
        "no_competing_bot_poller_verified",
        "host_lease_exclusive",
        "unrelated_workloads_untouched",
    ],
)
@pytest.mark.parametrize("bad", [False, None, "true", 1])
def test_every_boolean_gate_is_fail_closed(field: str, bad: object) -> None:
    with pytest.raises(HostContractError, match="host_protection_claims_unverified"):
        _review(replace(_synthetic_claims(), **{field: bad}))


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("source_sha", "d" * 40),
        ("installed_source_sha", "d" * 40),
        ("image_digest", "other@sha256:" + "b" * 64),
        ("installed_image_digest", IMAGE.replace("b", "c")),
        ("release_run_id", 0),
        ("release_run_id", True),
        ("observed_at", NOW - 31),
        ("observed_at", NOW + 31),
        ("observed_at", "recent"),
        ("controller_service", "browser"),
        ("controller_engine_mode", "ipc"),
        ("rootless_uid", 0),
        ("rootless_uid", True),
        ("origin", "https://localhost:8443"),
        ("origin", "http://127.0.0.1:8444"),
        ("recipient_fingerprint", "not-pinned"),
    ],
)
def test_identity_or_freshness_mismatch_is_rejected(field: str, bad: object) -> None:
    with pytest.raises(HostContractError, match="host_identity_claims_unverified"):
        _review(replace(_synthetic_claims(), **{field: bad}))


def test_bad_trusted_expected_values_are_rejected_without_host_effects() -> None:
    for override in (
        {"expected_source_sha": ""},
        {"expected_image_digest": "untrusted"},
        {"trusted_now": False},
        {"trusted_now": 0},
    ):
        with pytest.raises(HostContractError, match="untrusted_host_claims_invalid"):
            _review(_synthetic_claims(), **override)


def test_source_only_pr_workflow_has_no_remote_operation_entrypoint() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "  pull_request:" in workflow
    assert "permissions:\n  contents: read\n" in workflow
    assert "persist-credentials: false" in workflow
    assert "if: github.event_name == 'pull_request'" in workflow
    for forbidden in (
        "workflow_dispatch:",
        "workflow_call:",
        "repository_dispatch:",
        "schedule:",
        "environment:",
        "pull_request_target:",
        "secrets.",
        "ssh ",
        "docker ",
        "api.telegram.org",
        "actions/upload-artifact",
    ):
        assert forbidden not in workflow
    assert "TELEGRAM_V2_HOST_AUTHORIZED=false" in workflow
    assert "TELEGRAM_V2_SENDER=OFF" in workflow


def test_contract_sequence_requires_stopped_recheck_before_install_and_sender_gate() -> None:
    assert INTEGRATION_SEQUENCE.index(
        "owner_and_daemon_stopped_inventory"
    ) < INTEGRATION_SEQUENCE.index("controller_resumed_for_authenticated_chrome_pairing")
    assert INTEGRATION_SEQUENCE.index(
        "controller_stopped_again_with_exact_identity"
    ) < INTEGRATION_SEQUENCE.index("restricted_telegram_tls_get_me_webhook_updates_get_chat")
    assert INTEGRATION_SEQUENCE.index(
        "verify_v2_custody_before_any_sender"
    ) < INTEGRATION_SEQUENCE.index("separately_governed_sender_activation")
