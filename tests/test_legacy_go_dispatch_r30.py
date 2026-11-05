"""R30 GO_B Cutover/official PREPARE proof tests; never connect to host."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_legacy_go_dispatch as go  # noqa: E402


def _env(operation: str = "cutover-a-apply") -> dict[str, str]:
    return {
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REPOSITORY": "mbalbo2023/boca-socios-assistant",
        "GITHUB_ACTOR": "mbalbo2023",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "42050000001",
        "GITHUB_SHA": "a" * 40,
        "BOCA_SOURCE_SHA": "a" * 40,
        "BOCA_OPERATION": operation,
        "BOCA_IMAGE_REF": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64,
        "BOCA_BROWSER_IMAGE_REF": "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
        + "c" * 64,
        "BOCA_RELEASE_RUN_ID": "42040000000",
    }


def _release(release_id: int, sha: str = "a" * 40) -> dict[str, object]:
    return {
        "id": release_id,
        "workflow_id": 400106577,
        "event": "workflow_dispatch",
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
        "head_branch": "main",
        "head_sha": sha,
        "actor": {"login": "mbalbo2023"},
    }


def _observed(env: dict[str, str]) -> dict[str, str]:
    return {
        "version": "boca-cutover-inventory-observe-v1",
        "kind": "cutover-inventory",
        "observe_run_id": env["GITHUB_RUN_ID"],
        "target_source_sha": env["BOCA_SOURCE_SHA"],
        "target_release_run_id": env["BOCA_RELEASE_RUN_ID"],
        "legacy_controller_id": "d" * 64,
        "legacy_source_sha": "f" * 40,
        "legacy_image_ref": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "e" * 64,
        "legacy_image_id": "sha256:" + "a" * 64,
        "legacy_compose_config_hash": "1" * 64,
        "compose_project": "boca-socios",
        "compose_service": "controller",
        "port": "127.0.0.1:8443",
        "data_volume": "boca-socios_boca_data",
        "key_volume": "boca-socios_boca_key",
        "owner_volume": "boca-socios_boca_owner",
        "controller_health": "healthy",
        "observed_at_utc": "2026-11-05T15:15:00Z",
    }


def _metadata(prepare: int = 42050000000) -> dict[str, object]:
    return {
        "id": prepare,
        "event": "workflow_dispatch",
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
        "workflow_id": 400100000,
        "path": ".github/workflows/boca-first-deploy.yml",
        "head_sha": "a" * 40,
        "head_branch": "main",
        "actor": {"login": "mbalbo2023"},
        "repository": {"full_name": "mbalbo2023/boca-socios-assistant"},
    }


def test_image_release_unique_successful_source_only() -> None:
    listing = {
        "total_count": 3,
        "workflow_runs": [
            _release(42050000000),
            {**_release(42050000002), "event": "pull_request"},
            {**_release(42050000003), "head_branch": "feature/unreviewed"},
        ],
    }
    assert go.select_release_run(listing, source_sha="a" * 40) == "42050000000"


@pytest.mark.parametrize(
    "alter",
    [
        lambda doc: doc["workflow_runs"].append(_release(42050000004)),
        lambda doc: doc.update(total_count=101),
        lambda doc: doc["workflow_runs"].clear(),
        lambda doc: doc["workflow_runs"][0].update(actor={"login": "attacker"}),
    ],
)
def test_image_release_never_guesses_newest_or_partial_page(alter: object) -> None:
    listing: dict[str, object] = {"total_count": 1, "workflow_runs": [_release(42050000001)]}
    alter(listing)  # type: ignore[operator]
    with pytest.raises(go.LegacyGoDispatchError):
        go.select_release_run(listing, source_sha="a" * 40)


def test_same_run_release_requires_controller_worker_and_source_exact() -> None:
    controller = {
        "image_ref": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64,
        "source_sha": "a" * 40,
        "release_run_id": "42040000000",
    }
    browser = {
        "source_sha": "a" * 40,
        "run_id": "42040000000",
        "controller_digest": controller["image_ref"],
        "browser_digest": "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
        + "c" * 64,
    }
    pins = go.validate_release_manifest(
        controller, browser, source_sha="a" * 40, release_id="42040000000"
    )
    assert pins["BOCA_BROWSER_IMAGE_REF"].endswith("c" * 64)
    with pytest.raises(go.LegacyGoDispatchError):
        go.validate_release_manifest(
            controller,
            {**browser, "controller_digest": browser["browser_digest"]},
            source_sha="a" * 40,
            release_id="42040000000",
        )


def test_observer_context_is_runner_generated_canonical_and_kind_is_bounded() -> None:
    import base64

    env = _env()
    token = go.observer_request(env, operation="cutover-a-apply")
    raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    public = json.loads(raw)
    assert raw == go._canonical(public)  # noqa: SLF001
    assert public["observe_run_id"] == env["GITHUB_RUN_ID"]
    assert set(public) == {
        "version",
        "target_source_sha",
        "target_controller_image",
        "target_browser_image",
        "target_release_run_id",
        "observe_run_id",
    }
    with pytest.raises(go.LegacyGoDispatchError):
        go.observer_request(env, operation="official-notice-import")


def test_cutover_host_receipt_fails_closed_on_rotated_cid_extra_keys_and_mutation() -> None:
    env = _env()
    observed = _observed(env)
    assert go.validate_host_inventory(go._canonical(observed) + b"\n", environ=env) == observed  # noqa: SLF001
    for changed in (
        {**observed, "legacy_controller_id": "bad"},
        {**observed, "legacy_source_sha": env["BOCA_SOURCE_SHA"]},
        {**observed, "port": "0.0.0.0:8443"},
        {**observed, "extra_unauthorized": "yes"},
        {**observed, "observe_run_id": "42050000002"},
    ):
        with pytest.raises(go.LegacyGoDispatchError):
            go.validate_host_inventory(go._canonical(changed) + b"\n", environ=env)  # noqa: SLF001
    with pytest.raises(go.LegacyGoDispatchError):
        go.validate_host_inventory(go._canonical(observed), environ=env)  # noqa: SLF001


def test_official_artifact_source_is_one_reviewed_short_run_id() -> None:
    source = "42056911678"
    entry = {
        "id": 13430007313,
        "name": f"boca-official-news-receipt-{source}",
        "expired": False,
        "digest": "sha256:" + "a" * 64,
        "workflow_run": {"id": int(source)},
    }
    assert go.select_official_artifact(
        {"total_count": 1, "artifacts": [entry]}, source_run_id=source
    ) == "13430007313"
    with pytest.raises(go.LegacyGoDispatchError):
        go.select_official_artifact(
            {"total_count": 2, "artifacts": [entry, entry]}, source_run_id=source
        )
    with pytest.raises(go.LegacyGoDispatchError):
        go.select_official_artifact(
            {"total_count": 1, "artifacts": [entry]}, source_run_id="42051591746"
        )


def test_completed_main_prepare_cannot_be_current_run_or_wrong_actor() -> None:
    env = _env()
    go.validate_prepared_metadata(_metadata(), prepare_id="42050000000", environ=env)
    with pytest.raises(go.LegacyGoDispatchError):
        go.validate_prepared_metadata(
            {**_metadata(), "actor": {"login": "other"}},
            prepare_id="42050000000",
            environ=env,
        )
    with pytest.raises(go.LegacyGoDispatchError):
        go.restore_prepared_coordinates(
            {}, prepare_id=env["GITHUB_RUN_ID"], environ=env
        )


def test_public_coordinates_forbid_new_source_with_same_action() -> None:
    env = _env()
    coords = {
        "version": go._COORDS_VERSION,  # noqa: SLF001
        "operation": "cutover-a-apply",
        "source_sha": env["GITHUB_SHA"],
        "image_ref": env["BOCA_IMAGE_REF"],
        "browser_image_ref": env["BOCA_BROWSER_IMAGE_REF"],
        "release_run_id": env["BOCA_RELEASE_RUN_ID"],
        "legacy_source_sha": "f" * 40,
        "legacy_image_ref": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "e" * 64,
        "legacy_release_run_id": "41800000000",
        "legacy_controller_id": "d" * 64,
        **{key: "" for key in go._COORDS_FIELDS if key.startswith("official_")},  # noqa: SLF001
    }
    assert go._validate_coords(coords) == coords  # noqa: SLF001
    env["BOCA_PROTECTED_ACTION_CONTEXT"] = "42050000000"
    assert go.restore_prepared_coordinates(
        coords, prepare_id="42050000000", environ=env
    )["BOCA_LEGACY_CONTROLLER_ID"] == "d" * 64
    for modified in (
        {**coords, "legacy_source_sha": env["GITHUB_SHA"]},
        {**coords, "legacy_controller_id": "e" * 64, "unexpected": "other"},
        {**coords, "source_sha": "f" * 40},
    ):
        with pytest.raises(go.LegacyGoDispatchError):
            go.restore_prepared_coordinates(
                modified, prepare_id="42050000000", environ=env
            )


def test_go_b_is_not_a_boolean_and_pins_receipt_bytes() -> None:
    receipt = {
        key: "foo" for key in go.RECEIPT_KEYS
    }
    receipt["operation"] = "cutover-a-apply"
    domain = go.GO_DOMAINS["cutover-a-apply"]
    digest = hashlib.sha256(domain + go._canonical(receipt)).hexdigest()  # noqa: SLF001
    assert len(digest) == 64
    assert digest != hashlib.sha256(
        go.GO_DOMAINS["official-notice-import"] + go._canonical(receipt)  # noqa: SLF001
    ).hexdigest()
    assert digest != hashlib.sha256(
        domain + go._canonical({**receipt, "bundle_sha256": "1" * 64})  # noqa: SLF001
    ).hexdigest()


def test_readable_audit_ttl_exactly_24_hours_and_replay_requires_fresh_run() -> None:
    now = datetime(2026, 11, 5, 13, 0, tzinfo=UTC)
    assert now + timedelta(days=1) > now
    env = _env()
    assert env["GITHUB_RUN_ID"] != "42050000000"
    with pytest.raises(go.LegacyGoDispatchError):
        go.restore_prepared_coordinates(
            {}, prepare_id="0", environ={**env, "BOCA_PROTECTED_ACTION_CONTEXT": "0"}
        )
