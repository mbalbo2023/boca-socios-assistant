"""R260 host-only owner ES256 challenge is separate from 8443 health and cookies."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_owner_acceptance_v2 as owner
from boca_socios import host_cutover_stage as stage
from boca_socios.panel.passkey import PasskeyAssertion, PasskeyOwnerAuthentication


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _assertion(
    key: ec.EllipticCurvePrivateKey,
    credential: bytes,
    challenge: bytes,
    *,
    origin: str = "http://localhost:8443",
    rp: str = "localhost",
    flags: int = 5,
) -> PasskeyAssertion:
    client = json.dumps(
        {"type": "webauthn.get", "challenge": _b64(challenge), "origin": origin},
        separators=(",", ":"),
    ).encode()
    authenticator = hashlib.sha256(rp.encode()).digest() + bytes((flags,)) + bytes(4)
    signed = key.sign(authenticator + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
    return PasskeyAssertion(_b64(credential), _b64(client), _b64(authenticator), _b64(signed))


@pytest.fixture
def readiness(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(stage, "ROOT", tmp_path)
    monkeypatch.setattr(stage, "UID", os.geteuid())
    monkeypatch.setattr(stage, "GID", os.getegid())
    pinned = owner.InstalledOwnerPair(
        "44500000011",
        "d" * 40,
        "1" * 64,
        "2" * 64,
        "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "3" * 64,
        "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:" + "4" * 64,
    )
    key = ec.generate_private_key(ec.SECP256R1())
    credential = b"boca-owner-chrome-credential-v2"
    verifier = PasskeyOwnerAuthentication(
        credential_id=credential,
        public_key_der=key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
        rp_id="localhost",
        origin="http://localhost:8443",
        owner_subject="owner",
        permissions=frozenset({"local-status:read"}),
    )
    issue_lease = cleanup.BocaJobLease("44500000012", -1, -1, True)
    finish_lease = cleanup.BocaJobLease("44500000013", -1, -1, True)
    allowed = (issue_lease, finish_lease)

    def assert_lease(found, attempt):
        if found not in allowed or attempt != found.attempt_id:
            raise ValueError("foreign host lease")

    monkeypatch.setattr(cleanup, "verify_protected_boca_job_lease", assert_lease)
    monkeypatch.setattr(
        cleanup,
        "protected_boca_job_lease",
        lambda *_: pytest.fail("unexpected extra lease"),
    )
    observed: list[tuple[object, object]] = []

    def installed(pins, lease):
        observed.append((pins, lease))
        if pins != pinned or lease not in allowed:
            raise ValueError("pair mismatch")

    monkeypatch.setattr(owner, "_attest_installed_pair", installed)
    monkeypatch.setattr(owner, "_trusted_owner_verifier", lambda pins, lease: verifier)
    monkeypatch.setattr(owner, "_host_boot_digest", lambda: "b" * 64)
    times = [1_800_000_000, 50_000_000_000]
    monkeypatch.setattr(owner.time, "time", lambda: times[0])
    monkeypatch.setattr(owner.time, "monotonic_ns", lambda: times[1])
    return (
        owner.HostOwnerAcceptanceV2(),
        pinned,
        verifier,
        key,
        credential,
        issue_lease,
        finish_lease,
        times,
        observed,
        tmp_path,
    )


def test_real_es256_uv_host_challenge_persists_digest_only_and_pending_acceptance(readiness):
    (
        service,
        pair,
        _verifier,
        key,
        credential,
        issue_lease,
        finish_lease,
        times,
        observed,
        folder,
    ) = readiness
    issued = service.issue(pair, issue_lease)
    intent_path = folder / f".boca-owner-accept-{issued.operation_id}.challenge"
    intent = intent_path.read_bytes()
    assert issued.challenge not in intent and credential not in intent
    assert not any(k in intent for k in (b"client_data_json", b"signature", b"raw_assertion"))
    assert intent_path.stat().st_mode & 0o777 == 0o600
    times[0] += 4
    times[1] += 4_000_000_000
    proof = service.accept(issued, _assertion(key, credential, issued.challenge), finish_lease)
    assert proof.owner_passkey == "ES256_UP_UV_VERIFIED"
    assert proof.beta_deploy == "NO_GO"
    assert proof.apply_authorized is False
    assert proof.accepted_pair_sha256 == hashlib.sha256(pair.canonical()).hexdigest()
    assert (folder / proof.filename).read_bytes() == proof.raw
    assert issued.challenge not in proof.raw and credential not in proof.raw
    assert len(observed) >= 4
    with pytest.raises(owner.OwnerAcceptanceNoGo):
        service.accept(issued, _assertion(key, credential, issued.challenge), finish_lease)


def test_cookie_without_new_assertion_never_creates_owner_receipt(readiness):
    service, pair, *_rest = readiness
    issue_lease, finish_lease, folder = readiness[5], readiness[6], readiness[-1]
    issued = service.issue(pair, issue_lease)
    with pytest.raises(owner.OwnerAcceptanceNoGo):
        service.accept(issued, None, finish_lease)
    assert not list(folder.glob("*.receipt"))


@pytest.mark.parametrize("bad", ("uv", "up", "origin", "rp", "credential"))
def test_fake_origin_rp_uv_up_credential_cannot_finalize(readiness, bad):
    service, pair, _verifier, key, credential, issue_lease, finish_lease, _times, _, folder = (
        readiness
    )
    issued = service.issue(pair, issue_lease)
    kwargs = {}
    if bad == "uv":
        kwargs["flags"] = 1
    elif bad == "up":
        kwargs["flags"] = 4
    elif bad == "origin":
        kwargs["origin"] = "https://elsewhere.example"
    elif bad == "rp":
        kwargs["rp"] = "elsewhere.example"
    else:
        credential = b"different-passkey-credential-id"
    assertion = _assertion(key, credential, issued.challenge, **kwargs)
    with pytest.raises(owner.OwnerAcceptanceNoGo):
        service.accept(issued, assertion, finish_lease)
    assert not list(folder.glob("*.receipt"))


@pytest.mark.parametrize("bad", ("expired", "boot", "pair", "lease", "challenge"))
def test_stale_rebooted_changed_pair_lease_or_challenge_refused(readiness, monkeypatch, bad):
    service, pair, _verifier, key, credential, issue_lease, finish_lease, times, _, folder = (
        readiness
    )
    issued = service.issue(pair, issue_lease)
    if bad == "expired":
        times[0] += 121
        times[1] += 121_000_000_000
    elif bad == "boot":
        monkeypatch.setattr(owner, "_host_boot_digest", lambda: "c" * 64)
    elif bad == "pair":
        monkeypatch.setattr(
            owner, "_attest_installed_pair", lambda *_: (_ for _ in ()).throw(ValueError())
        )
    elif bad == "lease":
        finish_lease = cleanup.BocaJobLease("44500000014", -1, -1, True)
    else:
        issued = replace(issued, challenge=b"z" * 32)
    with pytest.raises(owner.OwnerAcceptanceNoGo):
        service.accept(issued, _assertion(key, credential, issued.challenge), finish_lease)
    assert not list(folder.glob("*.receipt"))


def test_duplicate_or_symlink_challenge_cannot_be_replaced(readiness, monkeypatch):
    service, pair, *_ = readiness
    lease, folder = readiness[5], readiness[-1]
    issued = service.issue(pair, lease)
    file = folder / f".boca-owner-accept-{issued.operation_id}.challenge"
    original = file.read_bytes()
    file.unlink()
    file.symlink_to(folder / "other")
    with pytest.raises(owner.OwnerAcceptanceNoGo):
        service.accept(issued, None, readiness[6])
    assert file.is_symlink()
    assert not list(folder.glob("*.receipt"))
    file.unlink()
    file.write_bytes(original)
    monkeypatch.setattr(owner, "uuid4", lambda: UUID(issued.operation_id))
    with pytest.raises(owner.OwnerAcceptanceNoGo):
        service.issue(pair, lease)


def test_independent_readonly_receipt_rechecks_live_pair_without_writes(readiness, monkeypatch):
    service, pair, _verifier, key, credential, issue_lease, finish_lease, times, _, folder = (
        readiness
    )
    issued = service.issue(pair, issue_lease)
    times[0] += 2
    times[1] += 2_000_000_000
    receipt = service.accept(issued, _assertion(key, credential, issued.challenge), finish_lease)
    before = sorted(folder.iterdir())
    monkeypatch.setattr(
        stage,
        "_create_exclusive",
        lambda *_: pytest.fail("read-only verifier must never persist/repair"),
    )
    readback = service.verify_readonly(receipt.operation_id, pair, finish_lease)
    assert readback == receipt.raw
    assert sorted(folder.iterdir()) == before
    with pytest.raises(owner.OwnerAcceptanceNoGo):
        service.verify_readonly(
            receipt.operation_id, replace(pair, source_sha="a" * 40), finish_lease
        )


def test_receipt_tamper_or_wrong_inode_fails_readonly(readiness):
    service, pair, _verifier, key, credential, issue_lease, finish_lease, _times, _, folder = (
        readiness
    )
    issued = service.issue(pair, issue_lease)
    receipt = service.accept(issued, _assertion(key, credential, issued.challenge), finish_lease)
    path = folder / receipt.filename
    raw = path.read_bytes()
    path.write_bytes(raw + b"tamper")
    with pytest.raises(owner.OwnerAcceptanceNoGo):
        service.verify_readonly(receipt.operation_id, pair, finish_lease)


def test_host_public_verifier_refuses_unattested_volume_files(readiness, monkeypatch):
    _service, pair, *_rest = readiness
    monkeypatch.undo()
    lease = cleanup.BocaJobLease("44500000012", -1, -1, True)
    with pytest.raises(owner.OwnerAcceptanceNoGo):
        owner._trusted_owner_verifier(pair, lease)


def test_public_owner_credential_reader_requires_exact_nonlink_file_custody(tmp_path: Path):
    private = tmp_path / "owner"
    private.mkdir(mode=0o700)
    credential = private / "credential_id"
    credential.write_bytes(b"genuine-public-id")
    credential.chmod(0o600)
    assert owner._read_public(private, "credential_id", 1024) == b"genuine-public-id"
    linked = private / "linked"
    linked.symlink_to(credential)
    with pytest.raises(owner.OwnerAcceptanceNoGo):
        owner._read_public(private, "linked", 1024)
    linked.unlink()
    os.link(credential, linked)
    with pytest.raises(owner.OwnerAcceptanceNoGo):
        owner._read_public(private, "credential_id", 1024)
    linked.unlink()
    credential.chmod(0o644)
    with pytest.raises(owner.OwnerAcceptanceNoGo):
        owner._read_public(private, "credential_id", 1024)


@pytest.mark.parametrize(
    "defect", ("valid", "missing", "duplicate", "wrong_origin", "wrong_path", "subject")
)
def test_owner_subject_must_come_from_real_controller_config_env(
    monkeypatch: pytest.MonkeyPatch, readiness, defect: str
) -> None:
    pair = readiness[1]
    fields = [
        "BOCA_PANEL_ORIGIN=http://localhost:8443",
        "BOCA_RUNTIME_MODE=simulation",
        "BOCA_ENGINE_MODE=off",
        "BOCA_PASSKEY_CREDENTIAL_ID_FILE=/run/owner/credential_id",
        "BOCA_PASSKEY_PUBLIC_KEY_DER_FILE=/run/owner/public_key.der",
        "BOCA_OWNER_SUBJECT=Tincho",
    ]
    if defect == "missing":
        fields.pop()
    elif defect == "duplicate":
        fields.append("BOCA_OWNER_SUBJECT=other")
    elif defect == "wrong_origin":
        fields[0] = "BOCA_PANEL_ORIGIN=https://localhost:8443"
    elif defect == "wrong_path":
        fields[3] = "BOCA_PASSKEY_CREDENTIAL_ID_FILE=/tmp/id"
    elif defect == "subject":
        fields[-1] = "BOCA_OWNER_SUBJECT=bad subject"
    calls = []

    def inspect(*args):
        calls.append(args)
        assert args == ("inspect", "--format", "{{json .Config.Env}}", pair.controller_id)
        return json.dumps(fields)

    monkeypatch.setattr(cleanup, "_docker", inspect)
    if defect == "valid":
        assert owner._controller_owner_subject(pair) == "Tincho"
    else:
        with pytest.raises(owner.OwnerAcceptanceNoGo):
            owner._controller_owner_subject(pair)
    assert len(calls) == 1
