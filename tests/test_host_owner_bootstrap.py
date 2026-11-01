"""Host-side owner gate stays in an empty, dedicated Boca namespace."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host

IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64
SHA = "a" * 40
ORIGIN = "https://owner.boca.example.test"
SUBJECT = "synthetic-owner"


def _envelope() -> str:
    public = base64.urlsafe_b64encode(b"p" * 32).rstrip(b"=").decode()
    fields = {
        "version": 1,
        "repository": "mbalbo2023/boca-socios-assistant",
        "purpose": "boca-owner-passkey-tls-v1",
        "uid": 10001,
        "panel_origin": ORIGIN,
        "owner_subject": SUBJECT,
        "recipient_public_key": public,
        "recipient_fingerprint": hashlib.sha256(b"p" * 32).hexdigest(),
        "ephemeral_public_key": base64.urlsafe_b64encode(b"e" * 32).rstrip(b"=").decode(),
        "salt": base64.urlsafe_b64encode(b"s" * 16).rstrip(b"=").decode(),
        "nonce": base64.urlsafe_b64encode(b"n" * 12).rstrip(b"=").decode(),
        "ciphertext": base64.urlsafe_b64encode(b"c" * 32).rstrip(b"=").decode(),
    }
    raw = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _snapshot(volumes: set[str]) -> host.HostSnapshot:
    return host.HostSnapshot(
        arch="x86_64",
        uid=10001,
        available_memory_kib=853288,
        available_disk_bytes=8 * 1024**3,
        available_inodes=100000,
        docker_disk_bytes=8 * 1024**3,
        docker_inodes=100000,
        root_ready=True,
        boca_containers=False,
        boca_volume=bool(volumes),
        boca_network=False,
        cpu_headroom=1.0,
    )


def test_transport_rejects_unexpected_plaintext_or_wrong_owner() -> None:
    sealed = _envelope()
    assert host._owner_envelope(sealed, ORIGIN, SUBJECT).startswith("{")
    for wrong in ("", sealed + "=", "a" * 44000, "Zg", "plain-token"):
        with pytest.raises(host.PreflightError, match="sealed owner envelope"):
            host._owner_envelope(wrong, ORIGIN, SUBJECT)
    with pytest.raises(host.PreflightError, match="sealed owner envelope"):
        host._owner_envelope(sealed, ORIGIN, "another-owner")
    data = json.loads(base64.urlsafe_b64decode(sealed + "=" * (-len(sealed) % 4)))
    data["tls.key"] = "plaintext-key"
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(host.PreflightError, match="sealed owner envelope"):
        host._owner_envelope(base64.urlsafe_b64encode(raw).rstrip(b"=").decode(), ORIGIN, SUBJECT)


def test_container_is_network_free_capped_and_owner_volume_only() -> None:
    for operation in ("prepare", "install", "verify"):
        args = host._owner_container(IMAGE, operation, ORIGIN, SUBJECT)
        assert args[args.index("--user") + 1] == "10001:10001"
        assert args[args.index("--network") + 1] == "none"
        assert args[args.index("--cap-drop") + 1] == "ALL"
        assert args[args.index("--tmpfs") + 1] == "/tmp:rw,noexec,nosuid,size=4m"  # noqa: S108
        assert "--read-only" in args and "--pull" in args
        assert args[-5:] == ("-m", "boca_socios.owner_bootstrap", operation, ORIGIN, SUBJECT)
        mount = args[args.index("--mount") + 1]
        assert mount.startswith(f"type=volume,source={host.OWNER_VOLUME},target=/run/owner")
        assert mount.endswith(",readonly") is (operation == "verify")
        assert ("-i" in args) is (operation == "install")
    with pytest.raises(host.PreflightError):
        host._owner_container(IMAGE, "delete", ORIGIN, SUBJECT)


def test_prepare_checks_full_daemon_before_pull_and_volume_effect(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(host, "COMPOSE", Path("/nonexistent-owner-compose"))
    monkeypatch.setattr(host, "BETA_COMPOSE", Path("/nonexistent-owner-beta-compose"))
    monkeypatch.setattr(host, "_run", lambda *args, **_kwargs: calls.append(args) or "foreign-id")
    with pytest.raises(host.PreflightError, match="dedicated Site daemon"):
        host._owner_phase("owner-prepare", IMAGE, SHA, ORIGIN, SUBJECT, "")
    assert calls == [("docker", "ps", "-a", "-q", "--no-trunc")]
    assert capsys.readouterr().out == ""


def test_prepare_creates_volume_only_after_verified_digest(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    volumes: set[str] = set()
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(host, "COMPOSE", Path("/nonexistent-owner-compose"))
    monkeypatch.setattr(host, "BETA_COMPOSE", Path("/nonexistent-owner-beta-compose"))
    monkeypatch.setattr(host, "_names", lambda *_args: set(volumes))
    monkeypatch.setattr(host, "collect_snapshot", lambda: _snapshot(volumes))
    monkeypatch.setattr(host, "_validate_owner_volume", lambda: None)
    monkeypatch.setattr(host, "_storage_snapshot", lambda: object())
    monkeypatch.setattr(host, "_validate_storage_capacity", lambda _x: None)
    monkeypatch.setattr(host, "_validate_storage_continuity", lambda _x, _y: None)
    public = base64.urlsafe_b64encode(b"p" * 32).rstrip(b"=").decode()
    fingerprint = hashlib.sha256(b"p" * 32).hexdigest()

    def fake_run(*args: str, input_data: str | None = None) -> str:
        assert input_data is None
        calls.append(args)
        if args[1:3] == ("image", "inspect"):
            return json.dumps([IMAGE]) if "RepoDigests" in args[4] else SHA
        if args[1:3] == ("volume", "create"):
            volumes.add(host.OWNER_VOLUME)
            return host.OWNER_VOLUME
        if args[-3:] == ("prepare", ORIGIN, SUBJECT):
            return (
                f"BOCA_OWNER_BOOTSTRAP state=PREPARED public_key={public} fingerprint={fingerprint}"
            )
        return ""

    monkeypatch.setattr(host, "_run", fake_run)
    host._owner_phase("owner-prepare", IMAGE, SHA, ORIGIN, SUBJECT, "")
    assert "BOCA_OWNER_BOOTSTRAP state=PREPARED" in capsys.readouterr().out
    assert next(i for i, call in enumerate(calls) if call[1:3] == ("volume", "create")) > next(
        i for i, call in enumerate(calls) if call[1:3] == ("image", "inspect")
    )
    assert calls[-1] == ("docker", "ps", "-a", "-q", "--no-trunc")


def test_install_rejects_partial_or_foreign_inventory_before_ciphertext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host, "COMPOSE", Path("/nonexistent-owner-compose"))
    monkeypatch.setattr(host, "BETA_COMPOSE", Path("/nonexistent-owner-beta-compose"))
    monkeypatch.setattr(host, "_run", lambda *_args, **_kwargs: "foreign-id")
    with pytest.raises(host.PreflightError, match="dedicated Site daemon"):
        host._owner_phase("owner-install", IMAGE, SHA, ORIGIN, SUBJECT, _envelope())
    with pytest.raises(host.PreflightError, match="sealed owner envelope required"):
        host._owner_phase("owner-install", IMAGE, SHA, ORIGIN, SUBJECT, "")
    with pytest.raises(host.PreflightError, match="sealed owner envelope required"):
        host._owner_phase("owner-verify", IMAGE, SHA, ORIGIN, SUBJECT, _envelope())


def test_phase_rejects_owner_ciphertext_outside_owner_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        host, "_validate_coordinates", lambda *_args, **_kwargs: pytest.fail("host access")
    )
    with pytest.raises(host.PreflightError, match="unexpected owner envelope"):
        host.phase("site-verify", IMAGE, SHA, SHA, owner_envelope=_envelope())
    with pytest.raises(host.PreflightError, match="invalid private BETA coordinates"):
        host.phase("owner-prepare", IMAGE, SHA, SHA)


@pytest.mark.parametrize(
    "origin",
    ["https://a..b.example.test", "https://bad-.example.test", "https://a.example.test:443"],
)
def test_malformed_owner_rp_fails_before_any_host_access(
    monkeypatch: pytest.MonkeyPatch, origin: str
) -> None:
    monkeypatch.setattr(
        host, "_validate_coordinates", lambda *_args, **_kwargs: pytest.fail("host access")
    )
    with pytest.raises(host.PreflightError, match="invalid private"):
        host.phase("owner-prepare", IMAGE, SHA, SHA, origin, SUBJECT)


def test_exact_tunnel_origin_is_validated_before_owner_host_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host._validate_owner_context("https://localhost:8443", SUBJECT)
    for origin in (
        "https://localhost",
        "https://localhost:9000",
        "https://boca.localhost:8443",
        "https://127.0.0.1:8443",
        "https://LOCALHOST:8443",
        "https://localhost:8443/",
    ):
        with pytest.raises(host.PreflightError, match="invalid private"):
            host._validate_owner_context(origin, SUBJECT)
    monkeypatch.setattr(
        host, "_validate_coordinates", lambda *_args, **_kwargs: pytest.fail("host access")
    )
    with pytest.raises(host.PreflightError, match="invalid private"):
        host.phase("owner-prepare", IMAGE, SHA, SHA, "https://localhost:9000", SUBJECT)


def test_owner_workflow_stops_daemon_in_same_job_on_failure() -> None:
    workflow = (
        Path(__file__).resolve().parents[1] / ".github/workflows/boca-first-deploy.yml"
    ).read_text()
    assert (
        workflow.index("Recheck current main before owner custody operation")
        < workflow.index("Mark owner custody host attempt before starting dedicated daemon")
        < workflow.index("Start only the stopped prepared Boca rootless daemon for owner custody")
        < workflow.index(
            "Prepare, install or verify only Boca owner-volume passkey and TLS custody"
        )
        < workflow.index("Stop only Boca services and daemon after owner custody")
    )
    section = workflow.split(
        "      - name: Stop only Boca services and daemon after owner custody"
    )[1].split("      - name:", 1)[0]
    assert "if: always() && startsWith(inputs.operation, 'owner-')" in section
    assert "steps.boca_owner_attempt.outputs.started == 'true'" in section
    assert "python3 - stop-test" in section
