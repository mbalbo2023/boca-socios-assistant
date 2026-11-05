"""Offline regression: precise, fixed-code diagnostics for failed Boca Cutover PREPARE.

Tests never execute Docker, SSH, ZIP/bootstrap or a host action.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from boca_socios import host_cutover_inventory_observe as inventory
from boca_socios.host_boca_cleanup import BocaJobLease, CleanupError


def _request() -> str:
    body = {
        "version": "boca-cutover-inventory-observe-v1",
        "target_source_sha": "a" * 40,
        "target_controller_image": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64,
        "target_browser_image": "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "c" * 64,
        "target_release_run_id": "42076459492",
        "observe_run_id": "42077145948",
    }
    return base64.urlsafe_b64encode(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).rstrip(b"=").decode("ascii")


@pytest.mark.parametrize(
    ("public_message", "reason"),
    [
        ("Boca historical image provenance unavailable", "IMAGE_PROVENANCE"),
        ("Boca historical GHCR image not uniquely attested", "IMAGE_DIGEST"),
        ("Boca bounded Docker field unavailable", "DOCKER_FIELD"),
        ("Boca legacy service isolation or health drifted", "SERVICE_HEALTH"),
        ("Boca legacy singleton absent or ambiguous", "LEGACY_SINGLETON"),
        ("Boca rootless inventory observation unverified", "ROOTLESS_INVENTORY"),
        ("Boca original rootless network/volumes changed", "NETWORK_VOLUMES"),
        ("Boca historical Compose labels unavailable", "COMPOSE_LABELS"),
    ],
)
def test_observer_emits_only_known_public_reason(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    public_message: str,
    reason: str,
) -> None:
    @contextmanager
    def fake_lease(attempt: str) -> Iterator[BocaJobLease]:
        assert attempt == "42077145948"
        yield BocaJobLease(attempt, 5, 1, True)

    def fake_observe(*_args: object, **_kwargs: object) -> dict[str, str]:
        raise inventory.CutoverInventoryNoGo(public_message)

    monkeypatch.setattr(inventory, "protected_boca_job_lease", fake_lease)
    monkeypatch.setattr(inventory, "observe_cutover_inventory", fake_observe)

    assert inventory.main([_request()]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    line = f"BOCA_CUTOVER_INVENTORY_OBSERVE state=NO_GO reason={reason}\n"
    assert captured.err == line
    assert inventory.parse_cutover_no_go_stderr(line.encode("ascii")) == reason


@pytest.mark.parametrize(
    "exc",
    [
        inventory.CutoverInventoryNoGo("secret=/srv/private/random"),
        RuntimeError("TOKEN=SHOULD_NOT_ESCAPE"),
        CleanupError("private Docker socket path changed"),
    ],
)
def test_unknown_error_text_cannot_escape(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    exc: Exception,
) -> None:
    @contextmanager
    def fake_lease(attempt: str) -> Iterator[BocaJobLease]:
        yield BocaJobLease(attempt, 5, 1, True)

    def fake_observe(*_args: object, **_kwargs: object) -> dict[str, str]:
        raise exc

    monkeypatch.setattr(inventory, "protected_boca_job_lease", fake_lease)
    monkeypatch.setattr(inventory, "observe_cutover_inventory", fake_observe)
    assert inventory.main([_request()]) == 3
    log = capsys.readouterr()
    assert log.out == ""
    assert "SHOULD_NOT_ESCAPE" not in log.err
    assert "/srv/private" not in log.err
    assert "Docker socket path" not in log.err
    assert log.err == (
        "BOCA_CUTOVER_INVENTORY_OBSERVE state=NO_GO reason=OBSERVER_UNVERIFIED\n"
    )


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"ssh: error details\n",
        b"BOCA_CUTOVER_INVENTORY_OBSERVE state=NO_GO reason=OWNER_SECRET\n",
        b"BOCA_CUTOVER_INVENTORY_OBSERVE state=NO_GO reason=IMAGE_PROVENANCE\n"
        b"BOCA_CUTOVER_INVENTORY_OBSERVE state=NO_GO reason=DOCKER_FIELD\n",
        b"BOCA_CUTOVER_INVENTORY_OBSERVE state=NO_GO reason=IMAGE_PROVENANCE suffix\n",
        b"BOCA_OFFICIAL_INVENTORY_OBSERVE state=NO_GO\n",
    ],
)
def test_runner_refuses_unknown_unbounded_or_multiple_codes(raw: bytes) -> None:
    assert inventory.parse_cutover_no_go_stderr(raw) == "TRANSPORT_OR_BOOTSTRAP"


def test_runner_does_not_consume_unbounded_host_stderr() -> None:
    assert (
        inventory.parse_cutover_no_go_stderr(
            b"BOCA_CUTOVER_INVENTORY_OBSERVE state=NO_GO reason=IMAGE_PROVENANCE\n"
            + b"x" * 4096
        )
        == "TRANSPORT_OR_BOOTSTRAP"
    )
