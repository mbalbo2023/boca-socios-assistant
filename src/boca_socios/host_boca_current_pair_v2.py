"""R246: runner-authenticated *current* pair proof for successive Boca upgrades.

R188 V1 remains an immutable witness to the initial Boca resource *creators*;
its pinned R186 service identities are never reused as a current-pair proof.
The current pair is dynamically observed by a separate protected READ_ONLY
run, then bound to the genuinely published *previous* dual-image release.

This module is unwired evidence code: no CLI, defaults, host IO, credentials,
Docker effects, or deploy authorization. It deliberately cannot turn its own
canonical JSON into proof of GitHub origin or into a same-lease host witness.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import cast

from boca_socios import host_boca_upgrade_adapters as adapters
from boca_socios import host_boca_upgrade_observation_bridge as observation
from boca_socios import host_boca_upgrade_release_auth as releases
from boca_socios.browser_release_manifest import validate_browser_manifest
from boca_socios.host_boca_pair_upgrade import PairCoordinates
from boca_socios.release_manifest import validate_manifest
from boca_socios.release_run import validate_release_run

_PREFIX = b"BOCA_CURRENT_PAIR_V2 "
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_CONTAINER = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_CTRL = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant@sha256:[0-9a-f]{64}\Z")
_WORKER = re.compile(r"ghcr\.io/mbalbo2023/boca-socios-assistant-browser@sha256:[0-9a-f]{64}\Z")
_ROOT_FIELDS = frozenset(
    {
        "schema",
        "read_only",
        "observer_writes",
        "foreign_resources_touched",
        "apply_authorized",
        "requires_fresh_same_lease_reproof",
        "observation_run",
        "target_main_sha",
        "target_release_run",
        "apply_attempt",
        "previous_pair_source_sha",
        "previous_pair_attempt",
        "previous_controller_id",
        "previous_worker_id",
        "previous_controller_image_id",
        "previous_worker_image_id",
        "previous_controller_ref",
        "previous_worker_ref",
        "previous_release_run",
        "previous_release_manifest_sha256",
        "observed_pair_sha256",
        "observation_proof_sha256",
        "historical_resource_custody",
        "integrity_sha256",
    }
)
_HISTORY_FIELDS = frozenset(
    {
        "original_observation_run",
        "historical_installed_source_sha",
        "historical_install_attempt",
        "historical_receipt_sha256",
        "creator_ipc_attempt",
        "creator_ipc_inode_sha256",
        "creator_site_attempt",
        "creator_site_inode_sha256",
        "creator_egress_attempt",
        "creator_egress_id",
        "control_dir_inode_sha256",
    }
)


class CurrentPairV2NoGo(ValueError):
    """Fixed redacted refusal; never expose untrusted GitHub/host data."""


def _fail() -> CurrentPairV2NoGo:
    return CurrentPairV2NoGo("current Boca pair provenance unverified")


def _unique(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, item in items:
        if name in result:
            raise _fail()
        result[name] = item
    return result


def _json(raw: bytes) -> object:
    if type(raw) is not bytes or not 0 < len(raw) <= 4096:
        raise _fail()
    return json.loads(raw, object_pairs_hook=_unique)


def _canonical(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("ascii")


def _is(value: object, pattern: re.Pattern[str]) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def _previous_release(
    github: releases.GitHubEvidenceTransport,
    source_sha: str,
    release_run: str,
    controller_ref: str,
    worker_ref: str,
) -> dict[str, str]:
    """Authenticate past main's original run, not past SHA == *today's* main.

    ``download_authenticated_release`` correctly insists on the current main
    for a *target* release but is unsuitable for a previous release after a
    later merge. Its existing verified run/job/ZIP primitives are reused here
    with no fork of their allowlists, checksum, or first-attempt validation.
    """
    if not _is(source_sha, _SHA) or not _is(release_run, _RUN):
        raise _fail()
    validate_release_run(github.get_json(f"actions/runs/{release_run}"), source_sha, release_run)
    releases._verify_release_job(github, release_run, source_sha)
    controller_raw = releases._release_artifact(
        github, release_run, source_sha, "controller-release"
    )
    worker_raw = releases._release_artifact(github, release_run, source_sha, "paired-release")
    controller_value = _json(controller_raw)
    worker_value = _json(worker_raw)
    validate_manifest(controller_value, controller_ref, source_sha, release_run)
    validate_browser_manifest(worker_value, controller_ref, worker_ref, source_sha, release_run)
    # An artifact ZIP is run-scoped: a later Actions retry must not inherit it.
    validate_release_run(github.get_json(f"actions/runs/{release_run}"), source_sha, release_run)
    releases._verify_release_job(github, release_run, source_sha)
    return {
        "controller": hashlib.sha256(controller_raw).hexdigest(),
        "paired": hashlib.sha256(worker_raw).hexdigest(),
    }


def _history(custody: adapters.CustodyEvidence) -> dict[str, str]:
    pins = custody.resources
    pins.validate()
    return {
        "original_observation_run": custody.observation_run_id,
        "historical_installed_source_sha": custody.installed_source_sha,
        "historical_install_attempt": custody.installation_attempt,
        "historical_receipt_sha256": custody.receipt_sha256,
        "creator_ipc_attempt": pins.ipc_creator_attempt,
        "creator_ipc_inode_sha256": pins.ipc_inode_sha256,
        "creator_site_attempt": pins.site_creator_attempt,
        "creator_site_inode_sha256": pins.site_inode_sha256,
        "creator_egress_attempt": pins.egress_creator_attempt,
        "creator_egress_id": pins.egress_id,
        "control_dir_inode_sha256": custody.control_directory_inode_sha256,
    }


def authenticate_current_pair_v2(
    plan: PairCoordinates,
    *,
    previous_release_run_id: str,
    pair_receipt: bytes,
    current_main_sha: str,
    historical_receipt: bytes,
    historical_observation_run_id: str,
    historical_observer_source_sha: str,
    historical_authenticator: adapters.EvidenceAuthenticator | None,
    github: releases.GitHubEvidenceTransport | None,
    now: datetime | None = None,
) -> bytes:
    """Runner-only: authenticate old pair, separate old dual release and R188.

    ``github`` MUST be the genuine protected authenticated REST transport;
    ``historical_authenticator`` MUST verify the independent, exact R188
    artifact transport. No default or permissive fallback exists. R188 source,
    attempt and CIDs are historical creator coordinates and may differ from
    the newly observed, presently installed pair after multiple upgrades.
    ``now`` is solely a deterministic offline-test seam; a future production
    runner MUST leave it unset so freshness uses the trusted runtime clock.

    Even genuine results carry ``apply_authorized=false`` and need a fresh
    lease-bound host/binding/journal/resource reproof before any real upgrade.
    """
    try:
        if (
            type(plan) is not PairCoordinates
            or github is None
            or historical_authenticator is None
            or not _is(current_main_sha, _SHA)
            or not _is(previous_release_run_id, _RUN)
        ):
            raise _fail()
        plan.validate()
        if (
            current_main_sha != plan.new_source_sha
            or len(
                {
                    previous_release_run_id,
                    plan.old_attempt_id,
                    plan.observation_run_id,
                    plan.release_run_id,
                    plan.attempt_id,
                }
            )
            != 5
            or not int(previous_release_run_id)
            < int(plan.old_attempt_id)
            < int(plan.observation_run_id)
            < int(plan.attempt_id)
            or not int(plan.release_run_id) < int(plan.attempt_id)
        ):
            raise _fail()
        custody = adapters.verify_custody_seed(
            historical_receipt,
            observation_run_id=historical_observation_run_id,
            observer_source_sha=historical_observer_source_sha,
            authenticator=historical_authenticator,
        )
        authenticated_observation = observation.authenticate_runner_observation(
            current_main_sha,
            plan.observation_run_id,
            plan.attempt_id,
            plan.release_run_id,
            pair_receipt,
            github,
            now=now,
        )
        observed = observation.verify_bundled_observation(
            authenticated_observation,
            pair_receipt,
            current_main_sha,
            plan.observation_run_id,
            plan.attempt_id,
            plan.release_run_id,
        )
        if any(
            observed[key] != expected
            for key, expected in (
                ("old_attempt_id", plan.old_attempt_id),
                ("old_source_sha", plan.old_source_sha),
                ("controller_id", plan.old_controller_id),
                ("worker_id", plan.old_worker_id),
                ("controller_image_id", plan.old_controller_image_id),
                ("worker_image_id", plan.old_worker_image_id),
            )
        ):
            raise _fail()
        prior_manifests = _previous_release(
            github,
            plan.old_source_sha,
            previous_release_run_id,
            cast(str, observed["controller_ref"]),
            cast(str, observed["worker_ref"]),
        )
        # The current-main check for the observation occurred *before* two
        # historical ZIP downloads. Revalidate the target's main identity
        # after the complete prior-release proof, closing that race window.
        releases._main_is_exact(github, current_main_sha)
        payload: dict[str, object] = {
            "schema": 2,
            "read_only": True,
            "observer_writes": 0,
            "foreign_resources_touched": 0,
            "apply_authorized": False,
            "requires_fresh_same_lease_reproof": True,
            "observation_run": plan.observation_run_id,
            "target_main_sha": current_main_sha,
            "target_release_run": plan.release_run_id,
            "apply_attempt": plan.attempt_id,
            "previous_pair_source_sha": plan.old_source_sha,
            "previous_pair_attempt": plan.old_attempt_id,
            "previous_controller_id": plan.old_controller_id,
            "previous_worker_id": plan.old_worker_id,
            "previous_controller_image_id": plan.old_controller_image_id,
            "previous_worker_image_id": plan.old_worker_image_id,
            "previous_controller_ref": observed["controller_ref"],
            "previous_worker_ref": observed["worker_ref"],
            "previous_release_run": previous_release_run_id,
            "previous_release_manifest_sha256": prior_manifests,
            "observed_pair_sha256": hashlib.sha256(pair_receipt).hexdigest(),
            "observation_proof_sha256": hashlib.sha256(authenticated_observation).hexdigest(),
            "historical_resource_custody": _history(custody),
        }
        payload["integrity_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
        result = _PREFIX + _canonical(payload)
        verify_current_pair_v2(result)
        return result
    except Exception:
        raise _fail() from None


def verify_current_pair_v2(raw: bytes) -> dict[str, object]:
    """Check canonical V2 *integrity/schema*, NOT artifact-origin authentication.

    Caller-supplied canonical JSON can be fabricated. Only the protected
    ``authenticate_current_pair_v2`` runner call performs independent GitHub
    authentication; this parser grants no host authority.
    """
    try:
        if (
            type(raw) is not bytes
            or not 0 < len(raw) <= 4096
            or not raw.startswith(_PREFIX)
            or not raw.endswith(b"\n")
            or raw.count(b"\n") != 1
        ):
            raise _fail()
        obj = _json(raw[len(_PREFIX) :])
        if not isinstance(obj, dict) or obj.keys() != _ROOT_FIELDS:
            raise _fail()
        integrity = obj["integrity_sha256"]
        if not _is(integrity, _HASH):
            raise _fail()
        without_integrity = {k: v for k, v in obj.items() if k != "integrity_sha256"}
        if (
            raw != _PREFIX + _canonical(obj)
            or hashlib.sha256(_canonical(without_integrity)).hexdigest() != integrity
            or type(obj["schema"]) is not int
            or obj["schema"] != 2
            or obj["read_only"] is not True
            or type(obj["observer_writes"]) is not int
            or obj["observer_writes"] != 0
            or type(obj["foreign_resources_touched"]) is not int
            or obj["foreign_resources_touched"] != 0
            or obj["apply_authorized"] is not False
            or obj["requires_fresh_same_lease_reproof"] is not True
            or any(
                not _is(obj[key], _RUN)
                for key in (
                    "observation_run",
                    "target_release_run",
                    "apply_attempt",
                    "previous_pair_attempt",
                    "previous_release_run",
                )
            )
            or not _is(obj["target_main_sha"], _SHA)
            or not _is(obj["previous_pair_source_sha"], _SHA)
            or obj["target_main_sha"] == obj["previous_pair_source_sha"]
            or any(
                not _is(obj[key], _CONTAINER)
                for key in ("previous_controller_id", "previous_worker_id")
            )
            or obj["previous_controller_id"] == obj["previous_worker_id"]
            or any(
                not _is(obj[key], _IMAGE)
                for key in ("previous_controller_image_id", "previous_worker_image_id")
            )
            or not _is(obj["previous_controller_ref"], _CTRL)
            or not _is(obj["previous_worker_ref"], _WORKER)
            or any(
                not _is(obj[key], _HASH)
                for key in ("observed_pair_sha256", "observation_proof_sha256")
            )
        ):
            raise _fail()
        runs = (
            obj["previous_release_run"],
            obj["previous_pair_attempt"],
            obj["observation_run"],
            obj["target_release_run"],
            obj["apply_attempt"],
        )
        if (
            len(set(runs)) != 5
            or not int(cast(str, runs[0]))
            < int(cast(str, runs[1]))
            < int(cast(str, runs[2]))
            < int(cast(str, runs[4]))
            or not int(cast(str, runs[3])) < int(cast(str, runs[4]))
        ):
            raise _fail()
        manifests = obj["previous_release_manifest_sha256"]
        if (
            type(manifests) is not dict
            or set(manifests) != {"controller", "paired"}
            or not all(_is(item, _HASH) for item in manifests.values())
        ):
            raise _fail()
        history = obj["historical_resource_custody"]
        if (
            type(history) is not dict
            or history.keys() != _HISTORY_FIELDS
            or any(
                not _is(history[key], _RUN)
                for key in (
                    "original_observation_run",
                    "historical_install_attempt",
                    "creator_ipc_attempt",
                    "creator_site_attempt",
                    "creator_egress_attempt",
                )
            )
            or not _is(history["historical_installed_source_sha"], _SHA)
            or any(
                not _is(history[key], _HASH)
                for key in (
                    "historical_receipt_sha256",
                    "creator_ipc_inode_sha256",
                    "creator_site_inode_sha256",
                    "creator_egress_id",
                    "control_dir_inode_sha256",
                )
            )
            or int(history["historical_install_attempt"])
            >= int(history["original_observation_run"])
        ):
            raise _fail()
        return cast(dict[str, object], obj)
    except Exception:
        raise _fail() from None
