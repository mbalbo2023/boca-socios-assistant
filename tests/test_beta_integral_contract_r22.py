"""R22 synthetic BETA boundary tests; no host, provider, or real navigation.

These acceptance slices intentionally compose existing public contracts. They
do not claim that a protected Actions operation or Samsung Chrome ran.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_cutover_cli as cutover
from boca_socios import host_boca_lifecycle as lifecycle
from boca_socios.events.official_catalog import build_observed_catalog, load_observed_notice
from boca_socios.events.official_presentation import (
    export_observed_catalog_json,
    render_observed_catalog_html,
)
from boca_socios.host_boca_cutover import CutoverPlan, CutoverReceipt
from boca_socios.panel.owner_session_store import OwnerBrowserSessionStore
from boca_socios.panel.owner_sessions import OwnerIdentity, OwnerSessions
from boca_socios.panel.telegram_pairing_staging import (
    STAGING_FILENAME,
    stage_private_telegram_pairing,
)
from boca_socios.storage.database import Database
from test_host_boca_cleanup import (
    ACTIVE_ID,
    ACTIVE_IMAGE,
    ATTEMPT,
    FOREIGN_ID,
    FOREIGN_IMAGE,
    _inventory,
    _probe_and_delete,
)
from test_host_boca_cutover_cli import reviewed_context as prepared_cutover  # noqa: F401
from test_private_beta_panel import _login, _request
from test_telegram_pairing_panel_handoff import _app_with_stage, _envelope, _stage_form


def test_chrome_option_b_survives_new_service_without_legacy_schema_mutation(
    tmp_path: Path,
) -> None:
    """Cross storage/session restart boundary; requires neither legacy 0008 nor TTL."""
    controller_path = tmp_path / "boca.sqlite3"
    controller = Database(controller_path)
    controller.migrate()
    before = hashlib.sha256(controller_path.read_bytes()).hexdigest()
    with sqlite3.connect(controller_path) as db:
        ledger = db.execute("SELECT version,checksum FROM schema_migrations").fetchall()

    store = OwnerBrowserSessionStore(controller, owner_subject="synthetic-owner")
    store.migrate()
    assert store.session_database_path == tmp_path / "boca_owner_session.sqlite3"
    permissions = frozenset({"members:enroll", "members:read", "simulation:write"})
    binding = bytes.fromhex("ba" * 32)

    def sessions() -> OwnerSessions:
        return OwnerSessions(
            owner_subject="synthetic-owner",
            verify_owner=lambda proof: (
                OwnerIdentity("synthetic-owner", permissions) if proof == "fake-proof" else None
            ),
            persistent_store=OwnerBrowserSessionStore(
                Database(controller_path), owner_subject="synthetic-owner"
            ),
            authorization_binding=binding,
            restore_permissions=permissions,
            clock=lambda: 9_000_000.0,
        )

    first = sessions()
    cookie = first.authenticate("fake-proof")
    assert cookie is not None and "Max-Age=34560000" in cookie
    token = cookie.partition(";")[0]
    first_session = first.lookup(token)
    assert first_session is not None
    new_service = sessions()
    restored = new_service.lookup(token)
    assert restored is not None and restored.csrf != first_session.csrf
    assert new_service.renew_cookie(token, restored) == cookie

    with sqlite3.connect(controller_path) as db:
        assert db.execute("SELECT version,checksum FROM schema_migrations").fetchall() == ledger
        assert db.execute(
            "SELECT count(*) FROM sqlite_master WHERE name='owner_browser_session'"
        ).fetchone() == (0,)
    assert hashlib.sha256(controller_path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("worker_running,worker_healthy", [(False, False), (True, False)])
def test_bot_start_requires_healthy_worker_but_stop_can_drain_unhealthy_worker(
    tmp_path: Path, worker_running: bool, worker_healthy: bool
) -> None:
    """The engine's host admission gate is asymmetric: STOP remains possible."""
    request = lifecycle.LifecycleHostCoordinates(
        attempt_id="42025021984",
        request_id=str(uuid4()),
        component="bot",
        target="start",
        source_sha="a" * 40,
        controller_id="b" * 64,
        controller_image="ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64,
        worker_id="c" * 64,
        worker_image="ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "e" * 64,
        database_path=tmp_path / "boca.sqlite3",
    )
    request.validate()
    observed = lifecycle.LifecycleHostSnapshot(
        controller_id=request.controller_id,
        controller_project="boca-socios",
        controller_service="controller",
        controller_image=request.controller_image,
        controller_sha=request.source_sha,
        worker_id=request.worker_id,
        worker_project="boca-socios",
        worker_service="browser-worker",
        worker_image=request.worker_image,
        worker_sha=request.source_sha,
        controller_running=True,
        controller_healthy=True,
        worker_running=worker_running,
        worker_healthy=worker_healthy,
        bot_engine_running=True,
        worker_network_mode="boca-socios_boca_browser_egress",
        published_controller_port="127.0.0.1:8443",
        rootless_uid=10001,
        controller_data_volume="boca-socios_boca_data",
        controller_data_mountpoint=tmp_path,
        controller_data_volume_exclusive=True,
        single_boca_project_verified=True,
        rootless_boca_uid_verified=True,
    )
    with pytest.raises(lifecycle.LifecycleHostUnavailable, match="healthy Chromium"):
        observed.require(request)
    assert observed.require(replace(request, target="stop")) is True


def test_private_telegram_stage_is_ciphertext_only_and_sender_stays_off(
    tmp_path: Path,
) -> None:
    """Fresh owner ES256 UV + encrypted stage never authorizes Bot API or ACK."""
    staged_path = tmp_path / STAGING_FILENAME
    clock = [0.0]
    app, key, credential = _app_with_stage(
        tmp_path / "boca.sqlite3",
        lambda encrypted: stage_private_telegram_pairing(staged_path, encrypted),
        clock=clock,
    )
    cookie = _login(app, key, credential)
    status, _, page = _request(app, "/telegram/emparejar", cookie=cookie)
    assert status == 200
    encrypted = _envelope()  # Synthetic WebCrypto output; no real token/provider.
    posted, _, body = _request(
        app,
        "/telegram/emparejar",
        cookie=cookie,
        method="POST",
        payload=_stage_form(app, cookie, page, encrypted, key, credential, clock),
    )
    assert posted == 202
    result = json.loads(body)
    assert result == {
        "state": "STAGED_PENDING_PROTECTED_CUTOVER",
        "telegram_connected": False,
        "sender": "OFF",
        "notification_receipt": "UNVERIFIED",
        "owner_passkey": "UV_VERIFIED_ONLY",
    }
    persisted = json.loads(staged_path.read_text(encoding="utf-8"))
    assert set(persisted) == {
        "envelope_base64url",
        "envelope_sha256",
        "purpose",
        "recipient_fingerprint",
        "stage_id",
        "staged_at",
        "version",
        "owner_witness",
    }
    assert persisted["envelope_sha256"] == hashlib.sha256(encrypted).hexdigest()
    assert "protected_nonce" not in persisted and "token" not in persisted


def test_official_jsonl_projection_never_promotes_window_to_ticket_action() -> None:
    """Even a valid bounded source line remains an observation, not an order."""
    envelope = {
        "version": "official-notice-observation-v1",
        "source_url": "https://www.bocajuniors.com.ar/noticias/partido-sintetico-no-publicado",
        "published_on": "2026-11-03",
        "observed_at": "2026-11-04T18:00:00-03:00",
        "source_sha256": "a" * 64,
        "event_key": "boca-evento-sintetico-2026",
        "title": "Partido sintetico solo para QA",
        "kickoff_at": "2026-11-07T17:30:00-03:00",
        "windows": [
            {
                "member_category": "abonados",
                "seat_area": "plateas",
                "opens_at": "2026-11-06T12:00:00-03:00",
                "closes_at": None,
                "close_rule": "unspecified",
            }
        ],
    }
    jsonl = json.dumps(envelope, sort_keys=True) + "\n"
    catalog = build_observed_catalog(load_observed_notice(line) for line in jsonl.splitlines())
    assert len(catalog) == 1 and catalog[0].actionable is False
    at = datetime.fromisoformat("2026-11-05T12:00:00-03:00")
    projection = json.loads(export_observed_catalog_json(catalog, at=at))
    assert projection["actionable"] is False
    assert projection["live_feed"] is False
    assert projection["availability_verified"] is False
    assert projection["events"][0]["actionable"] is False
    html = render_observed_catalog_html(catalog, at=at).lower()
    assert not any(tag in html for tag in ("<form", "<button", "<script"))


def test_cutover_default_missing_go_never_invokes_host_effect(
    request: pytest.FixtureRequest,
) -> None:
    encoded, _, _ = request.getfixturevalue("prepared_cutover")
    effects: list[str] = []

    def forbidden(_plan: CutoverPlan) -> CutoverReceipt:
        effects.append("mutate")
        raise AssertionError("unapproved host action")

    assert cutover.run_cli(encoded, execute=forbidden) == 3
    assert effects == []


@pytest.mark.parametrize("outcome", ["SUCCESS", "FAILURE"])
def test_selective_cleanup_both_outcomes_preserve_foreign_and_boca_state(
    outcome: cleanup.OUTCOME,
) -> None:
    probe, delete_exact, touched = _probe_and_delete(_inventory())
    receipt = cleanup.execute(
        outcome,
        ATTEMPT,
        preserve_images=frozenset({ACTIVE_IMAGE}),
        preserve_containers=frozenset({ACTIVE_ID}),
        retire_containers=frozenset({"2" * 64}),
        probe=probe,
        delete_exact=delete_exact,
    )
    assert receipt.status == "ACCEPT" and receipt.known_residue == ()
    # R244: IPC is a retained cross-upgrade resource, even when an old
    # synthetic cleanup attempt originally owned its creation label. It may
    # never be reclassified as disposable by current-attempt coincidence.
    assert {target.kind for target in touched} == {"container", "image", "network"}
    assert all(target.kind != "volume" for target in touched)
    after = probe()
    assert {container.ident for container in after.containers} == {ACTIVE_ID, FOREIGN_ID}
    assert {image.ident for image in after.images} == {ACTIVE_IMAGE, FOREIGN_IMAGE}
    assert "boca-socios_boca_data" in {volume.name for volume in after.volumes}
    assert "boca-socios_boca_browser_ipc" in {volume.name for volume in after.volumes}
