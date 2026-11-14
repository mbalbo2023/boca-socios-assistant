"""R95: portable Docker STOP flag keeps the strict full-CID ACK boundary."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from test_ci_parallel_pytest_contract import assert_required_ci_covers

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from scripts import host_cutover_worker_preflight as probe  # noqa: E402

from test_r83_cleanup_stages import CID, PROFILE, CleanupRig  # noqa: E402


def test_r95_cli_deprecation_differential_preserves_exact_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthetic modern CLI prints warning for old flag, no warning for -t."""
    rig = CleanupRig(monkeypatch)
    original_docker = rig.docker

    def synthetic_cli(*args: str, **kwargs: Any) -> str:
        if args[:2] != ("docker", "stop"):
            return original_docker(*args, **kwargs)
        assert kwargs.get("timeout") == 20
        assert args[3:] == ("5", CID)
        rig.calls.append(args)
        rig.stop_attempts += 1
        rig.running = False
        if args[2] == "--time":
            return f"Flag --time has been deprecated, use --timeout instead\n{CID}"
        assert args[2] == "-t"
        return CID

    monkeypatch.setattr(probe.host, "_run", synthetic_cli)
    probe.execute(rig.coords, PROFILE)
    assert rig.stop_attempts == 1
    assert rig.rm_attempts == 1
    assert not rig.present
    assert rig.calls.count(("docker", "stop", "-t", "5", CID)) == 1


def test_r95_multiline_ambiguity_remains_no_go_even_with_short_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = CleanupRig(monkeypatch)
    original_docker = rig.docker

    def synthetic_cli(*args: str, **kwargs: Any) -> str:
        if args[:2] != ("docker", "stop"):
            return original_docker(*args, **kwargs)
        assert args == ("docker", "stop", "-t", "5", CID)
        rig.calls.append(args)
        rig.stop_attempts += 1
        rig.running = False
        return f"UNVERIFIED_PRIVATE_WARNING\n{CID}"

    monkeypatch.setattr(probe.host, "_run", synthetic_cli)
    with pytest.raises(probe.PreflightFailure) as captured:
        probe.execute(rig.coords, PROFILE)
    assert captured.value.phase == "CLEANUP"
    assert captured.value.cleanup == "INDETERMINATE"
    assert captured.value.cleanup_failed_stage == "STOP"
    assert captured.value.stop_failure_cause == "ACK_MULTILINE"
    assert rig.stop_attempts == 1
    assert rig.rm_attempts == 0
    assert rig.present and not rig.running


def test_r95_stop_short_alias_is_selected_by_protected_first_deploy_ci() -> None:
    assert_required_ci_covers(
        "tests/test_r95_stop_short_alias.py",
    )
