"""NON-AUTHORIZING review contract for a future protected Telegram V2 host gate.

This intentionally performs no SSH, Docker, network, filesystem writes or
runtime dispatch. Its input is a *claim*, not observed proof. Even a fully
well-formed positive claim returns ``authorized=False``. A standalone manual
workflow must NOT use this parser as permission to act; the existing canonical
host gate must be extended under its own writer and exact-SHA review.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE = re.compile(r"ghcr[.]io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")

INTEGRATION_SEQUENCE = (
    "pinned_main_and_release_manifest",
    "owner_and_daemon_stopped_inventory",
    "isolated_schema_0007_migration",
    "recipient_key_prepared",
    "controller_resumed_for_authenticated_chrome_pairing",
    "controller_stopped_again_with_exact_identity",
    "restricted_telegram_tls_get_me_webhook_updates_get_chat",
    "exclusive_volume_v1_install_and_v2_commit_marker",
    "verify_v2_custody_before_any_sender",
    "controller_resumed_engine_off_sender_off",
    "single_synthetic_api_acceptance",
    "independent_human_notification_receipt",
    "separately_governed_sender_activation",
)


class HostContractError(ValueError):
    """Only generic, nonsecret claims errors may be surfaced."""


@dataclass(frozen=True, slots=True)
class UntrustedHostClaims:
    """Untrusted snapshot shape for integration tests, never authorization."""

    source_sha: str
    image_digest: str
    installed_source_sha: str
    installed_image_digest: str
    release_run_id: int
    observed_at: int
    owner_authenticated: bool
    owner_subject_verified: bool
    rootless_uid: int
    daemon_inventory_singleton: bool
    daemon_installed_stopped: bool
    controller_service: str
    controller_engine_mode: str
    sender_off: bool
    browser_worker_absent: bool
    origin: str
    volume_inventory_verified: bool
    data_schema_0007_verified: bool
    recipient_fingerprint: str
    recipient_custody_verified: bool
    dedicated_egress_verified: bool
    no_competing_bot_poller_verified: bool
    host_lease_exclusive: bool
    unrelated_workloads_untouched: bool


@dataclass(frozen=True, slots=True)
class HostContractReview:
    """No booleans that could be confused with host authorizations."""

    source_sha: str
    image_digest: str
    release_run_id: int
    recipient_fingerprint: str
    state: str = "EVIDENCE_SHAPE_ONLY"
    authorized: bool = False
    executable: bool = False
    human_receipt: str = "UNVERIFIED"


def review_untrusted_host_claims(
    claims: UntrustedHostClaims,
    *,
    expected_source_sha: str,
    expected_image_digest: str,
    trusted_now: int,
) -> HostContractReview:
    """Validate formatting/consistency ONLY; always forbid host effects.

    This function is useful for fixture/adapter negotiation with the cutover
    writer. It is not a cryptographic attestation or an authorization boundary.
    It may NEVER be consumed as ``go`` by a GitHub Actions dispatch job.
    """
    if (
        not isinstance(claims, UntrustedHostClaims)
        or not isinstance(expected_source_sha, str)
        or _SHA.fullmatch(expected_source_sha) is None
        or not isinstance(expected_image_digest, str)
        or _IMAGE.fullmatch(expected_image_digest) is None
        or type(trusted_now) is not int
        or trusted_now <= 0
    ):
        raise HostContractError("untrusted_host_claims_invalid")
    if (
        claims.source_sha != expected_source_sha
        or claims.installed_source_sha != expected_source_sha
        or claims.image_digest != expected_image_digest
        or claims.installed_image_digest != expected_image_digest
        or type(claims.release_run_id) is not int
        or claims.release_run_id <= 0
        or type(claims.observed_at) is not int
        or abs(trusted_now - claims.observed_at) > 30
        or claims.controller_service != "controller"
        or claims.controller_engine_mode != "off"
        or claims.origin != "http://localhost:8443"
        or type(claims.rootless_uid) is not int
        or claims.rootless_uid != 10001
        or not isinstance(claims.recipient_fingerprint, str)
        or _FINGERPRINT.fullmatch(claims.recipient_fingerprint) is None
    ):
        raise HostContractError("host_identity_claims_unverified")
    requirements = (
        claims.owner_authenticated,
        claims.owner_subject_verified,
        claims.daemon_inventory_singleton,
        claims.daemon_installed_stopped,
        claims.sender_off,
        claims.browser_worker_absent,
        claims.volume_inventory_verified,
        claims.data_schema_0007_verified,
        claims.recipient_custody_verified,
        claims.dedicated_egress_verified,
        claims.no_competing_bot_poller_verified,
        claims.host_lease_exclusive,
        claims.unrelated_workloads_untouched,
    )
    if any(value is not True for value in requirements):
        raise HostContractError("host_protection_claims_unverified")
    # These are still caller-supplied booleans. Their validation cannot prove
    # who observed them or exclude a race after the sample.
    return HostContractReview(
        source_sha=expected_source_sha,
        image_digest=expected_image_digest,
        release_run_id=claims.release_run_id,
        recipient_fingerprint=claims.recipient_fingerprint,
    )
