"""R92: synthetic STOP stdout evidence stays categorical and fail-closed."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from scripts import host_cutover_worker_preflight as probe  # noqa: E402

from test_r83_cleanup_stages import CID, PROFILE, CleanupRig  # noqa: E402


@pytest.mark.parametrize(
    ("ack", "cause"),
    [
        ("", "ACK_EMPTY"),
        (CID[:12], "ACK_SHORT_ID"),
        ("boca-socios-cutover-preflight-42341290485", "ACK_NAME"),
        (CID + "\nprivate extra", "ACK_MULTILINE"),
        ("e" * 64, "ACK_OTHER_ID"),
        ("unexpected private bytes", "ACK_MISMATCH"),
        (CID + " extra", "ACK_MISMATCH"),
        ("PRIVATE" * 200_000, "ACK_MISMATCH"),
        ("\x00\x1b[31mPRIVATE", "ACK_MISMATCH"),
        ("PRIVATÉ\ud800", "ACK_MISMATCH"),
    ],
)
def test_r92_ambiguous_stop_stdout_has_typed_evidence_and_no_rm(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    ack: str,
    cause: str,
) -> None:
    rig = CleanupRig(monkeypatch)
    real_docker = rig.docker

    def fake_docker(*args: str, **kwargs: Any) -> str:
        if args[:2] != ("docker", "stop"):
            return real_docker(*args, **kwargs)
        assert args == ("docker", "stop", "-t", "5", CID)
        assert kwargs.get("timeout") == 20
        rig.calls.append(args)
        rig.stop_attempts += 1
        rig.running = False  # Host effect may have happened despite wrong ACK.
        return ack

    monkeypatch.setattr(probe.host, "_run", fake_docker)
    monkeypatch.setattr(probe, "_reviewed_seccomp", lambda: PROFILE)
    assert probe.main(["host", *rig.coords.__dict__.values()]) == 3
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.count("\n") == 1
    assert len(output.out.encode("ascii")) <= 256
    assert f"stop_failure_cause={cause}\n" in output.out
    assert "phase_claim=" not in output.out  # Host uses the exact non-runner schema.
    assert "PRIVATE" not in output.out and "private" not in output.out
    assert rig.stop_attempts == 1 and rig.rm_attempts == 0
    assert rig.present and not rig.running


def test_r92_full_exact_stop_ack_retains_one_stop_one_rm_and_pass_receipt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = CleanupRig(monkeypatch)
    monkeypatch.setattr(probe, "_reviewed_seccomp", lambda: PROFILE)
    assert probe.main(["host", *rig.coords.__dict__.values()]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.startswith("BOCA_CUTOVER_WORKER_PREFLIGHT state=PASS ")
    assert "stop_failure_cause" not in output.out
    assert rig.stop_attempts == rig.rm_attempts == 1
    assert not rig.present


def test_r92_invalid_stdout_encoding_is_unverified_and_does_not_remove(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A subprocess text-decoding failure must not crash or emit private bytes."""
    rig = CleanupRig(monkeypatch)
    real_docker = rig.docker

    def fake_docker(*args: str, **kwargs: Any) -> str:
        if args[:2] != ("docker", "stop"):
            return real_docker(*args, **kwargs)
        assert args == ("docker", "stop", "-t", "5", CID)
        rig.stop_attempts += 1
        raise UnicodeDecodeError("utf-8", b"\xffPRIVATE", 0, 1, "bad encoding")

    monkeypatch.setattr(probe.host, "_run", fake_docker)
    monkeypatch.setattr(probe, "_reviewed_seccomp", lambda: PROFILE)
    assert probe.main(["host", *rig.coords.__dict__.values()]) == 3
    output = capsys.readouterr()
    assert output.err == ""
    assert "stop_failure_cause=UNVERIFIED\n" in output.out
    assert "PRIVATE" not in output.out and len(output.out.encode("ascii")) <= 256
    assert rig.stop_attempts == 1 and rig.rm_attempts == 0 and rig.present
