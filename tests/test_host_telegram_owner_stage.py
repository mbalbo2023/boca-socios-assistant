"""Offline proof of Telegram owner stage under Boca's exact host topology.

No Docker daemon, Telegram API, token, sender, SSH, or live host is used here.
Injected IO and simulated lease MUST NEVER produce activation authority.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from boca_socios import host_telegram_owner_stage as bridge
from boca_socios import host_telegram_postcutover as topology
from boca_socios import telegram_same_lease_stage as staged
from boca_socios.host_boca_cleanup import BocaJobLease
from boca_socios.panel.passkey import PasskeyOwnerAuthentication
from boca_socios.panel.telegram_pairing_staging import (
    STAGING_FILENAME,
    PairingStageRequest,
    stage_private_telegram_pairing,
)
from boca_socios.telegram_owner_webauthn import TelegramStageOwnerWitness, stage_owner_challenge
from boca_socios.telegram_pairing_cutover import CutoverCoordinates
from test_host_lifecycle_rootless_adapter import FakeIO
from test_host_telegram_postcutover import _fake, _lease, _pins
from test_telegram_owner_webauthn import _envelope, _signed

_CREDENTIAL = b"fresh-telegram-owner-test-credential"


def _prepared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    with_witness: bool = True,
) -> tuple[topology.TelegramHostPins, CutoverCoordinates, BocaJobLease, FakeIO, Path]:
    root = tmp_path / "volumes"
    data = root / "boca-socios_boca_data" / "_data"
    owner = root / "boca-socios_boca_owner" / "_data"
    data.mkdir(parents=True, mode=0o700)
    owner.mkdir(parents=True, mode=0o700)
    data.chmod(0o700)
    owner.chmod(0o700)
    reader = _fake(tmp_path)
    reader.fields[("volume", "boca-socios_boca_data", "Mountpoint")] = str(data)
    reader.fields[("volume", "boca-socios_boca_owner", "Mountpoint")] = str(owner)
    reader.fields[("container", _pins().controller_id, "Config.Env")] = [
        "BOCA_PANEL_ORIGIN=http://localhost:8443",
        "BOCA_RUNTIME_MODE=simulation",
        "BOCA_ENGINE_MODE=off",
        "BOCA_TELEGRAM_PAIRING_STAGE_MODE=encrypted-only",
        "BOCA_PASSKEY_CREDENTIAL_ID_FILE=/run/owner/credential_id",
        "BOCA_PASSKEY_PUBLIC_KEY_DER_FILE=/run/owner/public_key.der",
        "BOCA_OWNER_SUBJECT=owner",
    ]
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    (owner / "credential_id").write_bytes(_CREDENTIAL)
    (owner / "public_key.der").write_bytes(public)
    (owner / "credential_id").chmod(0o600)
    (owner / "public_key.der").chmod(0o600)
    verifier = PasskeyOwnerAuthentication(
        credential_id=_CREDENTIAL,
        public_key_der=public,
        rp_id="localhost",
        origin="http://localhost:8443",
        owner_subject="owner",
        permissions=bridge._OWNER_PERMISSIONS,
        clock=lambda: 100.0,
    )
    envelope = _envelope()
    recipient_fingerprint = json.loads(envelope)["recipient_fingerprint"]
    pins = replace(_pins(), recipient_fingerprint=recipient_fingerprint)
    coords = CutoverCoordinates(
        pins.attempt_id,
        pins.source_sha,
        pins.controller_image,
        pins.owner_digest,
        "3" * 64,
        pins.controller_id,
        recipient_fingerprint,
    )
    if with_witness:
        now = int(time.time())
        nonce = secrets.token_hex(32)
        operation = str(uuid4())
        challenge = stage_owner_challenge(
            envelope_sha256=hashlib.sha256(envelope).hexdigest(),
            operation_id=operation,
            request_nonce=nonce,
            challenged_at=now,
            verifier_binding=verifier.authorization_binding.hex(),
        )
        assert verifier.issue_telegram_stage_challenge(challenge)
        signed = _signed(
            challenge, key, _CREDENTIAL, origin="http://localhost:8443", rp_id="localhost"
        )
        assert verifier.verify_telegram_stage_assertion(signed, challenge) is not None
        witness = TelegramStageOwnerWitness(
            operation,
            nonce,
            now,
            verifier.authorization_binding.hex(),
            signed,
        )
        request = PairingStageRequest(envelope, witness)
    else:
        request = envelope
    stage_private_telegram_pairing(data / STAGING_FILENAME, request)

    def _lease_verified(current: BocaJobLease, attempt: str) -> None:
        assert current.active and current.owner_pid == os.getpid()
        assert current.attempt_id == attempt

    monkeypatch.setattr(bridge, "verify_protected_boca_job_lease", _lease_verified)
    monkeypatch.setattr(topology, "verify_protected_boca_job_lease", _lease_verified)
    monkeypatch.setattr(staged, "verify_protected_boca_job_lease", _lease_verified)
    return pins, coords, _lease(), reader, data


def test_fresh_es256_stage_verifies_under_single_lease_but_never_authorizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pins, coords, lease, reader, data = _prepared(tmp_path, monkeypatch)
    original = (data / STAGING_FILENAME).read_bytes()
    result = bridge.observe_owner_stage_under_same_lease(pins, coords, lease=lease, io=reader)
    assert result.state == "OWNER_STAGE_VERIFIED_EGRESS_NO_GO"
    assert result.sender_state == "OFF"
    assert result.authorized is False and result.host_effects is False
    assert result.nonce_consumed is False and result.bot_api_reads == 0
    assert result.human_receipt == "UNVERIFIED"
    assert result.recipient_fingerprint == pins.recipient_fingerprint
    assert (data / STAGING_FILENAME).read_bytes() == original
    assert reader.effects == []


def test_cookie_only_legacy_stage_cannot_become_owner_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pins, coords, lease, reader, _ = _prepared(tmp_path, monkeypatch, with_witness=False)
    with pytest.raises(bridge.TelegramOwnerStageNoGo, match="fresh_owner_webauthn"):
        bridge.observe_owner_stage_under_same_lease(pins, coords, lease=lease, io=reader)


@pytest.mark.parametrize("failure", ["foreign_path", "symlink_credential", "subject_changed"])
def test_volume_identity_and_owner_public_origin_are_not_workflow_claims(
    failure: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pins, coords, lease, reader, data = _prepared(tmp_path, monkeypatch)
    owner = data.parent.parent / "boca-socios_boca_owner" / "_data"
    if failure == "foreign_path":
        reader.fields[("volume", "boca-socios_boca_owner", "Mountpoint")] = str(tmp_path)
    elif failure == "symlink_credential":
        (owner / "credential_id").rename(owner / "credential_saved")
        (owner / "credential_id").symlink_to(owner / "credential_saved")
    else:
        entries = reader.fields[("container", pins.controller_id, "Config.Env")]
        assert isinstance(entries, list)
        entries[-1] = "BOCA_OWNER_SUBJECT=another_owner"
    with pytest.raises(bridge.TelegramOwnerStageNoGo):
        bridge.observe_owner_stage_under_same_lease(pins, coords, lease=lease, io=reader)


def test_stale_stage_is_denied_without_touching_the_nonce_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pins, coords, lease, reader, data = _prepared(tmp_path, monkeypatch)
    original = (data / STAGING_FILENAME).read_bytes()
    monkeypatch.setattr(bridge.time, "time", lambda: 2**31)
    with pytest.raises(bridge.TelegramOwnerStageNoGo, match="fresh_owner_webauthn"):
        bridge.observe_owner_stage_under_same_lease(pins, coords, lease=lease, io=reader)
    assert (data / STAGING_FILENAME).read_bytes() == original


def test_pins_and_cutover_must_match_before_reading_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pins, coords, lease, reader, _ = _prepared(tmp_path, monkeypatch)
    invalid = replace(coords, owner_digest="1" * 64)
    with pytest.raises(bridge.TelegramOwnerStageNoGo, match="cutover_coordinate_mismatch"):
        bridge.observe_owner_stage_under_same_lease(pins, invalid, lease=lease, io=reader)
    assert reader.effects == []


def test_duplicate_controller_env_is_denied_before_owner_public_file_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pins, coords, lease, reader, _ = _prepared(tmp_path, monkeypatch)
    entries = reader.fields[("container", pins.controller_id, "Config.Env")]
    assert isinstance(entries, list)
    entries.append("BOCA_ENGINE_MODE=off")
    with pytest.raises(bridge.TelegramOwnerStageNoGo, match="controller_config"):
        bridge.observe_owner_stage_under_same_lease(pins, coords, lease=lease, io=reader)
