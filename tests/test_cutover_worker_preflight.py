"""P0 offline contracts for pre-Cutover Boca-only GHCR/rootless probe."""

from __future__ import annotations

import re
import sys
from contextlib import contextmanager, nullcontext
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from scripts import host_cutover_worker_preflight as probe  # noqa: E402 - src-layout test


def pins() -> probe.Coordinates:
    return probe.Coordinates(
        attempt="42345678901",
        source="a" * 40,
        controller=f"ghcr.io/mbalbo2023/boca-socios-assistant@sha256:{'a' * 64}",
        browser=f"ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:{'b' * 64}",
        legacy_source="c" * 40,
        legacy_image=f"ghcr.io/mbalbo2023/boca-socios-assistant@sha256:{'c' * 64}",
        legacy_id="d" * 64,
    )


def test_coordinates_strict_and_no_remote_effect_before_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coords = pins()
    with pytest.raises(probe.WorkerPreflightError):
        probe.Coordinates(**{**coords.__dict__, "legacy_source": coords.source}).validate()
    with pytest.raises(probe.WorkerPreflightError):
        probe.Coordinates(**{**coords.__dict__, "browser": "docker.io/untrusted:latest"}).validate()
    monkeypatch.setattr(
        probe, "protected_boca_job_lease", lambda _id: pytest.fail("lease acquired")
    )
    with pytest.raises(probe.WorkerPreflightError):
        probe.execute(probe.Coordinates(**{**coords.__dict__, "attempt": "0"}), b"{}")


def test_probe_argv_has_no_ipc_mount_volumes_ports_or_navigation() -> None:
    args = probe._probe_argv(pins(), Path("/run/user/10001/reviewed-seccomp.json"))
    joined = " ".join(args)
    assert args[:2] == ("docker", "create")
    assert args[-4:] == (pins().browser, "python", "-c", "import time; time.sleep(90)")
    assert "--pull never" in joined
    assert "--network none" in joined
    assert "--user 10002:10002" in joined
    assert "--security-opt no-new-privileges:true" in joined
    assert "--read-only" in args
    assert "--publish" not in args and "--mount" not in args and "--volume" not in args
    assert "127.0.0.1:8443" not in joined
    assert "boca_socios.browser.ipc_worker" not in joined
    assert "docker system prune" not in joined
    assert "curl" not in joined


def _fake_container(coords: probe.Coordinates, *, running: bool) -> dict[str, object]:
    return {
        "Id": "f" * 64,
        "Name": f"/{probe.PREFIX}{coords.attempt}",
        "Config": {
            "Image": coords.browser,
            "User": "10002:10002",
            "Cmd": ["python", "-c", "import time; time.sleep(90)"],
            "Labels": {
                probe.LABEL: coords.attempt,
                "com.docker.compose.project": "boca-socios",
                "org.opencontainers.image.revision": coords.source,
            },
        },
        "HostConfig": {
            "NetworkMode": "none",
            "IpcMode": "private",
            "CgroupnsMode": "private",
            "ReadonlyRootfs": True,
            "Privileged": False,
            "Init": True,
            "NanoCpus": 1_000_000_000,
            "Memory": 805_306_368,
            "PidsLimit": 128,
            "CapDrop": ["ALL"],
            "CapAdd": ["SYS_CHROOT"],
            "PortBindings": None,
            "SecurityOpt": ["no-new-privileges:true", "seccomp=verified"],
        },
        "State": {"Running": running},
        "Mounts": [],
        "NetworkSettings": {"Ports": None, "Networks": {"none": {}}},
    }


def test_exact_success_pulls_boca_pair_once_and_cleans_only_own_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coords = pins()
    events: list[tuple[str, ...]] = []
    status = {"present": False, "running": False}
    monkeypatch.setattr(probe, "protected_boca_job_lease", lambda _attempt: nullcontext())
    monkeypatch.setattr(
        probe, "_temporary_seccomp", lambda _a, _p: nullcontext(Path("/run/user/10001/seccomp"))
    )
    monkeypatch.setattr(
        probe.host, "_cutover_legacy_record", lambda *a, **k: events.append(("attest",))
    )
    monkeypatch.setattr(probe.host, "_browser_engine_version", lambda: "28.0.1")
    monkeypatch.setattr(probe.host, "_storage_snapshot", lambda: object())
    monkeypatch.setattr(
        probe.host, "_browser_validate_image", lambda *a: events.append(("image", *a))
    )
    monkeypatch.setattr(probe.host, "_validate_storage_continuity", lambda *a, **k: None)
    monkeypatch.setattr(
        probe.host,
        "_browser_inspect_record",
        lambda _id: _fake_container(coords, running=status["running"]),
    )
    monkeypatch.setattr(probe.host, "_browser_effective_seccomp_options", lambda *a, **k: None)

    def run(*args: str, **_kwargs: object) -> str:
        events.append(args)
        if args[:2] == ("docker", "ps"):
            if "--format" in args:
                return ""
            return "f" * 64 if status["present"] else ""
        if args[:2] == ("docker", "pull"):
            return ""
        if args[:2] == ("docker", "create"):
            status["present"] = True
            return "f" * 64
        if args[:2] == ("docker", "start"):
            status["running"] = True
            return "f" * 64
        if args[:2] == ("docker", "exec"):
            return "BOCA_CUTOVER_WORKER_BOUNDARY_PASS"
        if args[:2] == ("docker", "stop"):
            status["running"] = False
            return "f" * 64
        if args[:2] == ("docker", "rm"):
            status["present"] = False
            return "f" * 64
        raise AssertionError(args)

    monkeypatch.setattr(probe.host, "_run", run)
    assert probe.execute(coords, b'{"defaultAction":"SCMP_ACT_ALLOW"}') == (
        "WORKER_BOUNDARY",
        "VERIFIED",
    )
    assert events.count(("attest",)) == 2
    assert events.count(("docker", "pull", coords.controller)) == 1
    assert events.count(("docker", "pull", coords.browser)) == 1
    assert events.count(("image", coords.controller, coords.source)) == 1
    assert events.count(("image", coords.browser, coords.source)) == 1
    assert any(item[:2] == ("docker", "rm") for item in events)
    assert not status["present"]
    assert not any(item[:2] == ("docker", "volume") for item in events)
    assert not any(item[:2] == ("docker", "image") for item in events)


def test_cleanup_refuses_foreign_identity_before_any_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coords = pins()
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(probe, "_named_id", lambda _name: "e" * 64)
    fake = _fake_container(coords, running=True)
    fake["Config"]["Labels"][probe.LABEL] = "wrong"  # type: ignore[index]
    monkeypatch.setattr(probe.host, "_browser_inspect_record", lambda _id: fake)
    monkeypatch.setattr(probe.host, "_run", lambda *a, **k: calls.append(a))
    with pytest.raises(probe.WorkerPreflightError, match="ownership unverified"):
        probe._cleanup_exact(coords, f"{probe.PREFIX}{coords.attempt}")
    assert calls == []


def test_seccomp_cleanup_indeterminate_must_not_be_reported_as_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coords = pins()
    monkeypatch.setattr(probe, "protected_boca_job_lease", lambda _id: nullcontext())
    monkeypatch.setattr(probe.host, "_cutover_legacy_record", lambda *a, **k: None)
    monkeypatch.setattr(probe, "_require_clean_namespace", lambda _name: None)
    monkeypatch.setattr(probe.host, "_browser_engine_version", lambda: "28.0.1")
    monkeypatch.setattr(probe.host, "_storage_snapshot", lambda: object())
    monkeypatch.setattr(probe, "_pull_observing_capacity", lambda _pins: None)
    monkeypatch.setattr(probe, "_cleanup_exact", lambda *_a: None)

    @contextmanager
    def failed_temp(_attempt: str, _profile: bytes):
        raise probe.TempSeccompCleanupError("simulated inode mismatch")
        yield Path("/run/user/10001/not-reached")

    monkeypatch.setattr(probe, "_temporary_seccomp", failed_temp)
    with pytest.raises(probe.PreflightFailure) as caught:
        probe.execute(coords, b"{}")
    assert caught.value.phase == "CLEANUP"
    assert caught.value.cleanup == "INDETERMINATE"


def test_workflow_requires_immutable_release_and_is_single_boca_workflow() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/boca-first-deploy.yml").read_text()
    assert "cutover-a-worker-preflight" in workflow
    assert "scripts/build_protected_boca_bundle.py" in workflow
    assert "scripts/check_release_run.py" in workflow
    assert "boca-browser-release-manifest" in workflow
    assert "BOCA_CUTOVER_WORKER_PREFLIGHT state=PASS" in workflow
    assert "ipc_worker=NOT_TESTED" in workflow
    assert "prepared_go=UNCONSUMED" in workflow
    assert re.search(r"if: inputs.operation == 'cutover-a-worker-preflight'", workflow)
    # The input is an incident PREPARE ID only for reconcile/recovery, but the
    # same field is the LEGACY release ID for Cutover observation/apply. Do not
    # accidentally reject a valid APPLY before its independent GO check.
    assert (
        '"$BOCA_OPERATION" != cutover-a-observe && '
        '"$BOCA_OPERATION" != cutover-a-worker-preflight && '
        '"$BOCA_OPERATION" != cutover-a-apply' in workflow
    )
