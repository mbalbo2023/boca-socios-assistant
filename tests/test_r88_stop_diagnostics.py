"""R88 RED contracts for one-shot STOP diagnostics in synthetic Boca preflight.

All Docker effects are simulated. No Actions, SSH, or host workload is touched.
"""

from __future__ import annotations

import builtins
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from scripts import host_cutover_worker_preflight as preflight  # noqa: E402

from test_r83_cleanup_stages import CID, PROFILE, CleanupRig  # noqa: E402


def _prepare_stop_case(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cause: BaseException | None = None,
    ack: str | None = None,
    stopped_before_error: bool = False,
    primary_failure: bool = False,
) -> CleanupRig:
    """Intercept only the exact STOP; execute() and all checks remain real."""
    rig = CleanupRig(monkeypatch, primary_failure=primary_failure)
    real_docker = rig.docker

    def docker(*args: str, **kwargs: Any) -> str:
        if args[:2] != ("docker", "stop"):
            return real_docker(*args, **kwargs)
        assert args == ("docker", "stop", "--time", "5", CID)
        assert kwargs.get("timeout") == 20
        rig.calls.append(args)
        rig.stop_attempts += 1
        if stopped_before_error:
            rig.running = False
        if ack is not None:
            return ack
        if cause is not None:
            raise preflight.host.PreflightError("PRIVATE_STOP_DIAGNOSTIC") from cause
        raise preflight.host.PreflightError("PRIVATE_STOP_DIAGNOSTIC")

    monkeypatch.setattr(preflight.host, "_run", docker)
    return rig


def _stop_failure(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cause: BaseException | None = None,
    ack: str | None = None,
    stopped_before_error: bool = False,
    primary_failure: bool = False,
) -> tuple[CleanupRig, preflight.PreflightFailure]:
    rig = _prepare_stop_case(
        monkeypatch,
        cause=cause,
        ack=ack,
        stopped_before_error=stopped_before_error,
        primary_failure=primary_failure,
    )
    with pytest.raises(preflight.PreflightFailure) as failure:
        preflight.execute(rig.coords, PROFILE)
    return rig, failure.value


def test_r88_stop_timeout_is_typed_without_removal_or_second_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig, failure = _stop_failure(
        monkeypatch,
        cause=subprocess.TimeoutExpired(("docker", "stop"), 20),
    )
    assert failure.phase == "CLEANUP"
    assert failure.primary_failed_phase == "NONE"
    assert failure.cleanup_failed_stage == "STOP"
    assert failure.cleanup == "INDETERMINATE"
    assert failure.stop_failure_cause == "TIMEOUT"
    assert rig.stop_attempts == 1 and rig.rm_attempts == 0
    assert rig.present and rig.running


@pytest.mark.parametrize(
    ("cause", "expected"),
    [
        (subprocess.CalledProcessError(1, ("docker", "stop")), "NONZERO"),
        (OSError("PRIVATE_DOCKER_STOP_PIPE"), "OSERROR"),
    ],
)
def test_r88_stop_native_failure_is_classified_without_raw_stderr(
    monkeypatch: pytest.MonkeyPatch, cause: BaseException, expected: str
) -> None:
    rig, failure = _stop_failure(monkeypatch, cause=cause)
    assert failure.stop_failure_cause == expected
    assert failure.cleanup_failed_stage == "STOP"
    assert failure.cleanup == "INDETERMINATE"
    assert failure.primary_failed_phase == "NONE"
    assert rig.stop_attempts == 1 and rig.rm_attempts == 0
    assert "PRIVATE" not in str(failure)


@pytest.mark.parametrize(
    ("ack", "expected"),
    [
        ("", "ACK_EMPTY"),
        ("other-container", "ACK_MISMATCH"),
        ("e" * 64, "ACK_OTHER_ID"),
        (CID + " extra", "ACK_MISMATCH"),
    ],
)
def test_r88_stop_ack_mismatch_leaves_the_probe_untouched_after_ambiguous_effect(
    monkeypatch: pytest.MonkeyPatch, ack: str, expected: str
) -> None:
    rig, failure = _stop_failure(monkeypatch, ack=ack, stopped_before_error=True)
    assert failure.stop_failure_cause == expected
    assert failure.cleanup_failed_stage == "STOP"
    assert failure.cleanup == "INDETERMINATE"
    assert rig.stop_attempts == 1 and rig.rm_attempts == 0
    assert rig.present and not rig.running


@pytest.mark.parametrize(
    ("cause", "expected"),
    [
        (subprocess.TimeoutExpired(("docker", "stop"), 20), "TIMEOUT"),
        (subprocess.CalledProcessError(1, ("docker", "stop")), "NONZERO"),
    ],
)
def test_r88_stop_effect_may_have_happened_despite_lost_ack_and_never_triggers_rm(
    monkeypatch: pytest.MonkeyPatch, cause: BaseException, expected: str
) -> None:
    # Also covers the timer-driven sleep(90) exit between Running=true and STOP.
    rig, failure = _stop_failure(monkeypatch, cause=cause, stopped_before_error=True)
    assert failure.stop_failure_cause == expected
    assert failure.phase == "CLEANUP" and failure.primary_failed_phase == "NONE"
    assert failure.cleanup_failed_stage == "STOP"
    assert rig.present and not rig.running
    assert rig.stop_attempts == 1 and rig.rm_attempts == 0
    assert rig.legacy_reads == 2


def test_r88_natural_process_exit_between_running_inspect_and_stop_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The process exits after the Running=True inspect but before STOP's ACK.
    rig, failure = _stop_failure(
        monkeypatch,
        cause=subprocess.CalledProcessError(1, ("docker", "stop")),
        stopped_before_error=True,
    )
    assert rig.boundary_done and rig.present and not rig.running
    assert failure.stop_failure_cause == "NONZERO"
    assert failure.cleanup_failed_stage == "STOP"
    assert failure.cleanup == "INDETERMINATE"
    assert rig.stop_attempts == 1 and rig.rm_attempts == 0


def test_r88_stopped_at_cleanup_inspect_skips_stop_and_removes_exact_id_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = CleanupRig(monkeypatch)
    real_inspect = rig.inspect

    def inspect(cid: str) -> dict[str, Any]:
        if rig.boundary_done:
            rig.running = False  # Natural exit before the cleanup snapshot.
        return real_inspect(cid)

    monkeypatch.setattr(preflight.host, "_browser_inspect_record", inspect)
    assert preflight.execute(rig.coords, PROFILE) == ("WORKER_BOUNDARY", "VERIFIED")
    assert rig.stop_attempts == 0 and rig.rm_attempts == 1
    assert not rig.present


def test_r88_stop_unclassified_private_failure_is_unverified_not_an_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig, failure = _stop_failure(monkeypatch)
    assert failure.stop_failure_cause == "UNVERIFIED"
    assert failure.cleanup_failed_stage == "STOP"
    assert rig.stop_attempts == 1 and rig.rm_attempts == 0
    assert "PRIVATE_STOP_DIAGNOSTIC" not in str(failure)


def test_r88_primary_failure_survives_independent_stop_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig, failure = _stop_failure(
        monkeypatch,
        cause=subprocess.TimeoutExpired(("docker", "stop"), 20),
        primary_failure=True,
    )
    assert failure.phase == "CLEANUP"
    assert failure.primary_failed_phase == "WORKER_BOUNDARY"
    assert failure.cleanup_failed_stage == "STOP"
    assert failure.stop_failure_cause == "TIMEOUT"
    assert rig.stop_attempts == 1 and rig.rm_attempts == 0


def test_r88_non_stop_cleanup_failure_has_no_fabricated_stop_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = CleanupRig(monkeypatch, failure="RM")
    with pytest.raises(preflight.PreflightFailure) as observed:
        preflight.execute(rig.coords, PROFILE)
    failure = observed.value
    assert failure.cleanup_failed_stage == "RM"
    assert failure.stop_failure_cause == "NONE"
    assert rig.stop_attempts == rig.rm_attempts == 1


def test_r88_success_receipt_remains_exactly_the_historical_pass_contract(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = CleanupRig(monkeypatch)
    monkeypatch.setattr(preflight, "_reviewed_seccomp", lambda: PROFILE)
    assert preflight.main(["host", *rig.coords.__dict__.values()]) == 0
    stdout = capsys.readouterr().out
    assert stdout == (
        f"BOCA_CUTOVER_WORKER_PREFLIGHT state=PASS source_sha={rig.coords.source} "
        "images=VERIFIED worker_boundary=VERIFIED cleanup=VERIFIED "
        "original=RUNNING port=127.0.0.1:8443 ipc_worker=NOT_TESTED "
        "prepared_go=UNCONSUMED foreign=UNTOUCHED\n"
    )
    assert "stop_failure_cause" not in stdout


@pytest.mark.parametrize("case", ["TIMEOUT", "NONZERO", "OSERROR", "ACK_MISMATCH", "UNVERIFIED"])
def test_r88_cli_receipt_preserves_fifth_categorical_stop_cause_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    causes: dict[str, BaseException] = {
        "TIMEOUT": subprocess.TimeoutExpired(("docker", "stop"), 20),
        "NONZERO": subprocess.CalledProcessError(3, ("docker", "stop")),
        "OSERROR": OSError("PRIVATE_STOP_ERROR_NO_LOG"),
    }
    rig = _prepare_stop_case(
        monkeypatch,
        cause=causes.get(case),
        ack="foreign" if case == "ACK_MISMATCH" else None,
    )
    monkeypatch.setattr(preflight, "_reviewed_seccomp", lambda: PROFILE)
    assert preflight.main(["host", *rig.coords.__dict__.values()]) == 3
    result = capsys.readouterr()
    assert result.err == ""
    assert len(result.out.encode("ascii")) <= 256
    assert result.out.count("\n") == 1
    assert f"stop_failure_cause={case}\n" in result.out
    assert "cleanup_failed_stage=STOP" in result.out
    assert "PRIVATE" not in result.out
    assert rig.stop_attempts == 1 and rig.rm_attempts == 0


def _run_worker_boundary(*, optimized: bool, bad: str | None) -> tuple[bool, list[str]]:
    """Change one synthetic isolation invariant while executing real code."""
    values = {
        "/sys/fs/cgroup/memory.max": "9999999999" if bad == "memory" else "805306368",
        "/sys/fs/cgroup/pids.max": "999" if bad == "pids" else "128",
        "/sys/fs/cgroup/cpu.max": "200000 100000" if bad == "cpu" else "100000 100000",
        "/proc/self/status": (
            f"NoNewPrivs: {0 if bad == 'no_new_privs' else 1}\n"
            f"Seccomp: {0 if bad == 'seccomp' else 2}\n"
            f"Seccomp_filters: {0 if bad == 'filters' else 1}\n"
        ),
    }

    class FakePath:
        def __init__(self, value: str):
            self.value = value

        def __truediv__(self, other: str) -> FakePath:
            return FakePath(self.value + "/" + other)

        def read_text(self) -> str:
            return values[self.value]

    fake_os = SimpleNamespace(
        geteuid=lambda: 0 if bad == "uid" else 10002,
        getegid=lambda: 0 if bad == "gid" else 10002,
        listdir=lambda _path: ["eth0"] if bad == "network" else ["lo"],
    )
    fake_pathlib = SimpleNamespace(Path=FakePath)
    imports = {"os": fake_os, "pathlib": fake_pathlib}

    def fake_import(name: str, *_args: Any, **_kwargs: Any) -> Any:
        if name not in imports:
            raise AssertionError(f"unexpected boundary import: {name}")
        return imports[name]

    printed: list[str] = []
    builtins_map = {**vars(builtins), "__import__": fake_import, "print": printed.append}
    compiled = compile(
        preflight.BOUNDARY_COMMAND, "<synthetic-worker-boundary>", "exec", optimize=int(optimized)
    )
    failed = False
    try:
        exec(compiled, {"__builtins__": builtins_map})  # noqa: S102 - synthetic imports only
    except (Exception, SystemExit):
        failed = True
    return failed, printed


@pytest.mark.parametrize("optimized", [False, True])
def test_r88_real_worker_boundary_passes_only_with_verified_isolation(optimized: bool) -> None:
    failed, printed = _run_worker_boundary(optimized=optimized, bad=None)
    assert failed is False
    assert printed == ["BOCA_CUTOVER_WORKER_BOUNDARY_PASS"]


@pytest.mark.parametrize(
    "bad", ["uid", "gid", "memory", "pids", "cpu", "no_new_privs", "seccomp", "filters", "network"]
)
@pytest.mark.parametrize("optimized", [False, True])
def test_r88_optimized_python_cannot_silently_disable_worker_isolation(
    optimized: bool, bad: str
) -> None:
    failed, printed = _run_worker_boundary(optimized=optimized, bad=bad)
    assert failed is True
    assert "BOCA_CUTOVER_WORKER_BOUNDARY_PASS" not in printed
