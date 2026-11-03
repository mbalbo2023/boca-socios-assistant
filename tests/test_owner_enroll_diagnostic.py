"""RCA #275: owner enrollment start must emit only reviewed failure codes."""

from __future__ import annotations

from pathlib import Path

import pytest

from boca_socios import host_first_deploy as host
from boca_socios import owner_enroll_diagnostic as diagnostic

IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "a" * 64
SHA = "b" * 40
DIGEST = "c" * 64


@pytest.mark.parametrize(
    "phase",
    ["preflight", "port", "storage", "image_inventory", "marker", "pull",
     "image_provenance", "storage_continuity", "recipient", "volume_create",
     "volume_verify", "volume_permissions", "network_create", "network_verify",
     "container_create", "container_verify", "listener_health"],
)
def test_only_reviewed_owner_enroll_phase_codes_pass(phase: str) -> None:
    assert diagnostic.classify(
        f"BOCA_NO_GO: owner enrollment phase={phase}\n".encode()
    ) == phase


@pytest.mark.parametrize(
    "payload",
    [b"", b"ssh: connection reset",
     b"BOCA_NO_GO: owner enrollment phase=secret\n",
     b"BOCA_NO_GO: owner enrollment phase=port\nSECRET=value\n",
     b"BOCA_NO_GO: owner enrollment phase=port\x00",
     b"BOCA_NO_GO: owner enrollment phase=port\r\n",
     b"x" * 4097],
)
def test_unknown_stderr_never_echoes_sensitive_data(payload: bytes) -> None:
    assert diagnostic.classify(payload) == "unclassified"


def test_reader_rejects_symlink(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "receipt"
    target.write_text("BOCA_NO_GO: owner enrollment phase=port\n")
    alias = tmp_path / "alias"
    alias.symlink_to(target)
    assert diagnostic.main([str(alias)]) == 0
    assert capsys.readouterr().out == "unclassified\n"


def test_reader_accepts_single_bounded_reason(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "receipt"
    target.write_text("BOCA_NO_GO: owner enrollment phase=preflight\n")
    assert diagnostic.main([str(target)]) == 0
    assert capsys.readouterr().out == "preflight\n"


def test_start_redacts_original_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def bad(*_a: object) -> None:
        raise host.PreflightError("private_host_details_do_not_print")
    monkeypatch.setattr(host, "_owner_enroll_preflight", bad)
    with pytest.raises(host.PreflightError, match=r"^owner enrollment phase=preflight$") as caught:
        host._owner_enroll_start(IMAGE, SHA, "http://localhost:8443", "synthetic", DIGEST)
    assert "private_host_details" not in str(caught.value)


def test_busy_port_never_reaches_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(host, "_owner_enroll_preflight", lambda *_a: None)
    monkeypatch.setattr(host, "_owner_enroll_port_free", lambda: False)
    monkeypatch.setattr(host, "_run", lambda *_a: pytest.fail("Docker side effect"))
    with pytest.raises(host.PreflightError, match=r"^owner enrollment phase=port$"):
        host._owner_enroll_start(IMAGE, SHA, "http://localhost:8443", "synthetic", DIGEST)


def test_workflow_redacts_only_ephemeral_stderr_and_preserves_cleanup() -> None:
    text = (Path(__file__).resolve().parents[1] /
            ".github/workflows/boca-first-deploy.yml").read_text(encoding="utf-8")
    start = text.index("Start disposable owner enrollment only on Boca loopback 8443")
    cleanup = text.index("Clean Boca-only disposable owner enrollment artifacts")
    fragment = text[start:cleanup]
    assert '2> "$RUNNER_TEMP/boca-owner-enroll-start.stderr"' in fragment
    assert "python3 -m boca_socios.owner_enroll_diagnostic" in fragment
    assert "reason=%s" in fragment
    assert 'cat "$RUNNER_TEMP/boca-owner-enroll-start.stderr"' not in fragment
    assert "if: always() && inputs.operation == 'owner-enroll'" in text[cleanup:]
    assert "Stop only Boca services and daemon after owner custody" in text[cleanup:]
