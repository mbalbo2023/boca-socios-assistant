"""Protected Site credential staging must touch only the Boca owner volume."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host
from boca_socios import site_bootstrap

IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "b" * 64


def _snapshot() -> host.HostSnapshot:
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
        boca_volume=True,
        boca_network=False,
        cpu_headroom=1.0,
    )


def test_site_inventory_allows_only_exact_owner_volume() -> None:
    host.validate_site_snapshot(_snapshot(), {host.OWNER_VOLUME}, require_owner=True)
    host.validate_site_snapshot(replace(_snapshot(), boca_volume=False), set(), require_owner=False)
    for volumes in (
        {"boca-socios_other"},
        {host.OWNER_VOLUME, "boca-socios_boca_data"},
        set(),
    ):
        with pytest.raises(host.PreflightError):
            host.validate_site_snapshot(_snapshot(), volumes, require_owner=True)
    with pytest.raises(host.PreflightError):
        host.validate_site_snapshot(
            replace(_snapshot(), boca_containers=True), {host.OWNER_VOLUME}, require_owner=True
        )


def test_site_envelope_is_bounded_canonical_ciphertext_transport_only() -> None:
    assert host.SITE_ORIGIN == site_bootstrap.SITE_ORIGIN
    public = base64.urlsafe_b64encode(b"p" * 32).rstrip(b"=").decode("ascii")
    fields = {
        "version": 1,
        "repository": "mbalbo2023/boca-socios-assistant",
        "purpose": "boca-site-bridge-machine-v1",
        "uid": 10001,
        "site_origin": host.SITE_ORIGIN,
        "recipient_fingerprint": hashlib.sha256(b"p" * 32).hexdigest(),
        "recipient_public_key": public,
        "ephemeral_public_key": base64.urlsafe_b64encode(b"e" * 32).rstrip(b"=").decode(),
        "salt": base64.urlsafe_b64encode(b"s" * 16).rstrip(b"=").decode(),
        "nonce": base64.urlsafe_b64encode(b"n" * 12).rstrip(b"=").decode(),
        "ciphertext": base64.urlsafe_b64encode(b"c" * 32).rstrip(b"=").decode(),
    }
    raw = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("ascii")
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    assert host._site_envelope(encoded) == raw.decode("ascii")
    for unsafe in ("", "not+url/safe", encoded + "=", "a" * 11000, "Zg"):
        with pytest.raises(host.PreflightError, match="sealed Site envelope"):
            host._site_envelope(unsafe)
    fields["site_bypass_token"] = "plaintext-leak"
    unsafe = (
        base64.urlsafe_b64encode(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    with pytest.raises(host.PreflightError, match="sealed Site envelope"):
        host._site_envelope(unsafe)


def test_owner_volume_identity_rejects_redirects_and_wrong_labels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "docker"
    expected = root / "volumes" / host.OWNER_VOLUME / "_data"
    expected.mkdir(parents=True)
    volume = {
        "Name": host.OWNER_VOLUME,
        "Driver": "local",
        "Scope": "local",
        "Options": None,
        "Mountpoint": str(expected),
        "Labels": {
            "com.docker.compose.project": host.PROJECT,
            "com.docker.compose.volume": "boca_owner",
        },
    }
    monkeypatch.setattr(
        host,
        "_run",
        lambda *args: json.dumps(volume) if args[1:3] == ("volume", "inspect") else str(root),
    )
    host._validate_owner_volume()
    labels = volume["Labels"]
    assert isinstance(labels, dict)
    labels["com.docker.compose.volume"] = "boca_key"
    with pytest.raises(host.PreflightError, match="owner volume identity"):
        host._validate_owner_volume()
    labels["com.docker.compose.volume"] = "boca_owner"
    expected.rmdir()
    expected.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(host.PreflightError, match="redirected"):
        host._validate_owner_volume()


def test_site_container_uses_fixed_image_uid_network_and_volume_only() -> None:
    prepare = host._site_container(IMAGE, "prepare")
    assert prepare[:4] == ("docker", "run", "--rm", "--pull")
    assert ("--network", "none") == prepare[
        prepare.index("--network") : prepare.index("--network") + 2
    ]
    assert prepare[prepare.index("--user") + 1] == "10001:10001"
    assert "--cap-drop" in prepare and prepare[prepare.index("--cap-drop") + 1] == "ALL"
    assert "--read-only" in prepare and "docker.sock" not in " ".join(prepare)
    assert f"type=volume,source={host.OWNER_VOLUME},target=/run/owner,volume-nocopy" in prepare
    assert prepare[-4:] == ("python", "-m", "boca_socios.site_bootstrap", "prepare")
    install = host._site_container(IMAGE, "install")
    assert "-i" in install
    verify = host._site_container(IMAGE, "verify")
    assert "-i" not in verify
    assert (
        f"type=volume,source={host.OWNER_VOLUME},target=/run/owner,volume-nocopy,readonly" in verify
    )
    with pytest.raises(host.PreflightError):
        host._site_container(IMAGE, "other")


def test_site_receipt_rejects_unbounded_or_unexpected_output() -> None:
    public = base64.urlsafe_b64encode(b"p" * 32).rstrip(b"=").decode("ascii")
    fingerprint = hashlib.sha256(b"p" * 32).hexdigest()
    prepared = f"BOCA_SITE_BOOTSTRAP state=PREPARED public_key={public} fingerprint={fingerprint}"
    assert host._site_receipt(prepared, "prepare") == prepared
    for output, phase in (
        (prepared + "\nsecret=foo", "prepare"),
        ("BOCA_SITE_BOOTSTRAP state=CONFIGURED fingerprint=" + fingerprint, "prepare"),
        (prepared + "x" * 1024, "prepare"),
        ("BOCA_SITE_BOOTSTRAP state=VERIFIED fingerprint=" + fingerprint, "install"),
    ):
        with pytest.raises(host.PreflightError):
            host._site_receipt(output, phase)


def test_site_prepare_only_creates_owner_volume_after_exact_image_and_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    volumes: set[str] = set()
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(host, "COMPOSE", Path("/nonexistent-boca-test-compose"))
    monkeypatch.setattr(host, "_names", lambda *_args: set(volumes))
    monkeypatch.setattr(
        host,
        "collect_snapshot",
        lambda: replace(_snapshot(), boca_volume=bool(volumes)),
    )
    monkeypatch.setattr(host, "_validate_owner_volume", lambda: None)
    monkeypatch.setattr(host, "_storage_snapshot", lambda: object())
    monkeypatch.setattr(host, "_validate_storage_capacity", lambda _snapshot: None)
    monkeypatch.setattr(host, "_validate_storage_continuity", lambda _before, _after: None)
    public = base64.urlsafe_b64encode(b"p" * 32).rstrip(b"=").decode("ascii")
    fingerprint = hashlib.sha256(b"p" * 32).hexdigest()

    def fake_run(*args: str, input_data: str | None = None) -> str:
        assert input_data is None
        calls.append(args)
        if args[1:3] == ("image", "inspect"):
            return json.dumps([IMAGE]) if "RepoDigests" in args[4] else "a" * 40
        if args[1:3] == ("volume", "create"):
            volumes.add(host.OWNER_VOLUME)
            return host.OWNER_VOLUME
        if args[-1] == "prepare":
            return (
                f"BOCA_SITE_BOOTSTRAP state=PREPARED public_key={public} fingerprint={fingerprint}"
            )
        return ""

    monkeypatch.setattr(host, "_run", fake_run)
    host._site_phase("site-prepare", IMAGE, "a" * 40, "")
    assert next(i for i, call in enumerate(calls) if call[1:3] == ("volume", "create")) > next(
        i for i, call in enumerate(calls) if call[1:3] == ("image", "inspect")
    )
    assert any("--cap-add" in call and call[-1].startswith("import os;") for call in calls)
    assert any(call[-1] == "prepare" for call in calls)
    assert calls[-1] == ("docker", "ps", "-a", "-q", "--no-trunc")


@pytest.mark.parametrize("rogue_after", [1, 2, 3, 4, 5])
def test_site_custody_refuses_foreign_dedicated_daemon_container_before_each_effect(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], rogue_after: int
) -> None:
    """Regression #195: a foreign rootless container cannot be invisible to Site."""
    volumes: set[str] = set()
    global_checks = 0
    seen: list[tuple[str, ...]] = []
    monkeypatch.setattr(host, "COMPOSE", Path("/nonexistent-boca-test-compose"))
    monkeypatch.setattr(host, "_names", lambda *_args: set(volumes))
    monkeypatch.setattr(
        host, "collect_snapshot", lambda: replace(_snapshot(), boca_volume=bool(volumes))
    )
    monkeypatch.setattr(host, "_validate_owner_volume", lambda: None)
    monkeypatch.setattr(host, "_storage_snapshot", lambda: object())
    monkeypatch.setattr(host, "_validate_storage_capacity", lambda _snapshot: None)
    monkeypatch.setattr(host, "_validate_storage_continuity", lambda _before, _after: None)

    def fake_run(*args: str, input_data: str | None = None) -> str:
        nonlocal global_checks
        assert input_data is None
        seen.append(args)
        if args == ("docker", "ps", "-a", "-q", "--no-trunc"):
            global_checks += 1
            return "f" * 64 if global_checks == rogue_after else ""
        if args[1:3] == ("image", "inspect"):
            return json.dumps([IMAGE]) if "RepoDigests" in args[4] else "a" * 40
        if args[1:3] == ("volume", "create"):
            if rogue_after in {1, 2}:
                pytest.fail("Site owner volume created despite foreign container")
            volumes.add(host.OWNER_VOLUME)
            return host.OWNER_VOLUME
        if args[-1] == "prepare":
            if rogue_after != 5:
                pytest.fail("Site bootstrap ran despite foreign container")
            public = base64.urlsafe_b64encode(b"p" * 32).rstrip(b"=").decode("ascii")
            fingerprint = hashlib.sha256(b"p" * 32).hexdigest()
            return (
                f"BOCA_SITE_BOOTSTRAP state=PREPARED public_key={public} fingerprint={fingerprint}"
            )
        return ""

    monkeypatch.setattr(host, "_run", fake_run)
    with pytest.raises(host.PreflightError, match="dedicated Site daemon"):
        host._site_phase("site-prepare", IMAGE, "a" * 40, "")
    assert global_checks == rogue_after
    assert any(args[-1] == "prepare" for args in seen) is (rogue_after == 5)
    assert volumes == ({host.OWNER_VOLUME} if rogue_after >= 3 else set())
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("operation", ["site-install", "site-verify"])
def test_site_existing_owner_operations_reject_foreign_daemon_before_token_or_verify(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    monkeypatch.setattr(host, "COMPOSE", Path("/nonexistent-boca-test-compose"))
    monkeypatch.setattr(host, "_site_envelope", lambda _value: "synthetic-ciphertext")
    monkeypatch.setattr(host, "_names", lambda *_args: pytest.fail("Boca inventory after rogue"))

    def fake_run(*args: str, input_data: str | None = None) -> str:
        assert args == ("docker", "ps", "-a", "-q", "--no-trunc")
        return "f" * 64

    monkeypatch.setattr(host, "_run", fake_run)
    with pytest.raises(host.PreflightError, match="dedicated Site daemon"):
        host._site_phase(
            operation, IMAGE, "a" * 40, "ciphertext" if operation == "site-install" else ""
        )


def test_wrong_image_revision_refuses_owner_volume_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host, "COMPOSE", Path("/nonexistent-boca-test-compose"))
    monkeypatch.setattr(host, "_names", lambda *_args: set())
    monkeypatch.setattr(host, "collect_snapshot", lambda: replace(_snapshot(), boca_volume=False))
    monkeypatch.setattr(host, "_storage_snapshot", lambda: object())
    monkeypatch.setattr(host, "_validate_storage_capacity", lambda _snapshot: None)
    seen: list[tuple[str, ...]] = []

    def fake_run(*args: str, input_data: str | None = None) -> str:
        seen.append(args)
        if args[1:3] == ("image", "inspect"):
            return json.dumps([IMAGE]) if "RepoDigests" in args[4] else "f" * 40
        return ""

    monkeypatch.setattr(host, "_run", fake_run)
    with pytest.raises(host.PreflightError, match="image differs"):
        host._site_phase("site-prepare", IMAGE, "a" * 40, "")
    assert not any(call[1:3] == ("volume", "create") for call in seen)


def test_attached_owner_volume_blocks_site_operation_before_image_pull(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host, "COMPOSE", Path("/nonexistent-boca-test-compose"))
    monkeypatch.setattr(host, "_names", lambda *_args: {host.OWNER_VOLUME})
    monkeypatch.setattr(host, "collect_snapshot", _snapshot)
    monkeypatch.setattr(host, "_validate_owner_volume", lambda: None)
    seen: list[tuple[str, ...]] = []

    def fake_run(*args: str, input_data: str | None = None) -> str:
        seen.append(args)
        if args == ("docker", "ps", "-a", "-q", "--no-trunc"):
            return ""
        return "c" * 64

    monkeypatch.setattr(host, "_run", fake_run)
    with pytest.raises(host.PreflightError, match="attached"):
        host._site_phase("site-verify", IMAGE, "a" * 40, "")
    assert seen == [
        ("docker", "ps", "-a", "-q", "--no-trunc"),
        ("docker", "ps", "-a", "-q", "--filter", f"volume={host.OWNER_VOLUME}"),
    ]


def test_legacy_phase_rejects_unexpected_envelope_before_host_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        host, "_validate_docker_boundary", lambda: pytest.fail("rootless host probed")
    )
    with pytest.raises(host.PreflightError, match="unexpected Site envelope"):
        host.phase("observe", "", "a" * 40, "d" * 64, "ciphertext")


def test_site_dispatch_has_exact_source_release_and_no_plaintext_fields() -> None:
    workflow = Path(".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    assert "site-prepare" in workflow and "site-install" in workflow and "site-verify" in workflow
    assert "BOCA_SITE_ENVELOPE" in workflow
    assert "BOCA_SITE_TOKEN" not in workflow
    assert "BOCA_SITE_HMAC_KEY" not in workflow
    assert "python scripts/check_release_run.py" in workflow
    assert "python scripts/check_main_ref.py" in workflow
    assert "environment: boca-first-deploy" in workflow
