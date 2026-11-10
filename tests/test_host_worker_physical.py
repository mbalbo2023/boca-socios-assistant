"""Offline guards for a single disposable physical Boca browser-worker boot."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from boca_socios import host_worker_physical as physical


def _probe_record() -> dict[str, Any]:
    return {
        "Name": "/boca-physical-worker-42899999999",
        "Config": {
            "Image": physical.BROWSER_IMAGE,
            "Labels": {
                "boca.socios.physical-run": "42899999999",
                "boca.socios.physical-release": physical.RELEASE_RUN_ID,
            },
        },
        "State": {"Status": "created", "Running": False},
        "Mounts": [],
        "HostConfig": {
            "NetworkMode": "none",
            "RestartPolicy": {"Name": "no"},
            "Privileged": False,
            "ReadonlyRootfs": True,
            "Memory": 768 * 1024 * 1024,
            "NanoCpus": 1_000_000_000,
            "PidsLimit": 128,
            "IpcMode": "private",
            "CgroupnsMode": "private",
            "LogConfig": {"Type": "none"},
            "SecurityOpt": ["no-new-privileges:true", "seccomp=/srv/boca-socios/seccomp.json"],
            "CapDrop": ["ALL"],
            "CapAdd": ["SYS_CHROOT"],
            "Binds": None,
            "Tmpfs": {
                "/tmp": "rw,noexec,nosuid,size=32m",  # noqa: S108
                "/home/boca-browser": "rw,noexec,nosuid,size=16m",
                "/run/boca-browser-ipc": "rw,noexec,nosuid,size=16m,uid=10002,gid=10002,mode=0711",
            },
        },
    }


def test_created_probe_refuses_mounted_volumes_or_relaxed_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _probe_record()
    monkeypatch.setattr(physical.deploy, "_browser_inspect_record", lambda _: record)
    physical._inspect_probe("f" * 64, "42899999999")
    for key, changed in (
        ("Memory", 0),
        ("NanoCpus", 0),
        ("PidsLimit", 0),
        ("ReadonlyRootfs", False),
        ("NetworkMode", "bridge"),
        ("Privileged", True),
    ):
        bad = _probe_record()
        bad["HostConfig"][key] = changed
        monkeypatch.setattr(physical.deploy, "_browser_inspect_record", lambda _, value=bad: value)
        with pytest.raises(physical.PhysicalProbeUnavailable):
            physical._inspect_probe("f" * 64, "42899999999")
    bad = _probe_record()
    bad["Mounts"] = [{"Type": "volume", "Name": "boca-socios_boca_data"}]
    monkeypatch.setattr(physical.deploy, "_browser_inspect_record", lambda _: bad)
    with pytest.raises(physical.PhysicalProbeUnavailable):
        physical._inspect_probe("f" * 64, "42899999999")


def test_real_docker_effective_seccomp_json_and_cap_name_are_valid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from boca_socios import host_first_deploy as deploy

    seccomp = (Path(__file__).resolve().parents[1] / "docker/seccomp_profile.json").read_bytes()
    assert hashlib.sha256(seccomp).hexdigest() == physical.SECCOMP_SHA256
    path = tmp_path / "seccomp.json"
    path.write_bytes(seccomp)
    record = _probe_record()
    record["HostConfig"]["CapAdd"] = ["CAP_SYS_CHROOT"]
    # Docker stores effective compact JSON rather than the *filename* sent to create.
    record["HostConfig"]["SecurityOpt"] = [
        "no-new-privileges:true",
        "seccomp=" + json.dumps(json.loads(seccomp), separators=(",", ":")),
    ]
    monkeypatch.setattr(deploy, "_browser_inspect_record", lambda _: record)
    assert physical._inspect_probe("f" * 64, "42899999999", str(path)) is record


def test_exact_cid_cleanup_survives_create_config_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _probe_record()
    record["HostConfig"]["Memory"] = 0  # Create accepted but cgroups were not enforced.
    record["State"] = {"Status": "created", "Running": False}
    monkeypatch.setattr(physical.deploy, "_browser_inspect_record", lambda _: record)
    calls: list[tuple[str, ...]] = []

    def fake_run(*args: str, timeout: int) -> str:
        calls.append(args)
        return "f" * 64

    monkeypatch.setattr(physical.deploy, "_run", fake_run)
    monkeypatch.setattr(physical.cleanup, "_docker", lambda *args: "")
    physical._exact_cleanup("f" * 64, "42899999999", "/srv/boca-socios/seccomp.json")
    assert calls == [("docker", "rm", "f" * 64)]


def test_immutable_pull_is_admitted_and_checked_on_rootless_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots = iter(("before", "after"))
    events: list[tuple[object, ...]] = []
    monkeypatch.setattr(physical.deploy, "_storage_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(
        physical.deploy,
        "_validate_storage_capacity",
        lambda value: events.append(("capacity", value)),
    )
    monkeypatch.setattr(
        physical.deploy,
        "_validate_storage_continuity",
        lambda first, last, **kwargs: events.append(
            ("continuity", first, last, kwargs["min_free_bytes"])
        ),
    )
    monkeypatch.setattr(physical.deploy, "_run", lambda *args, **kwargs: events.append(args) or "")
    monkeypatch.setattr(
        physical.cleanup,
        "_docker",
        lambda *args: (
            json.dumps([physical.BROWSER_IMAGE])
            if "RepoDigests" in str(args)
            else physical.RELEASE_SOURCE_SHA
        ),
    )
    assert physical._image_pull_and_verify() == "before"
    assert events == [
        ("capacity", "before"),
        ("docker", "pull", physical.BROWSER_IMAGE),
        ("continuity", "before", "after", physical.deploy.POSTINSTALL_STORAGE_MIN_BYTES),
    ]


def test_storage_failed_admission_never_pulls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(physical.deploy, "_storage_snapshot", lambda: "low")

    def reject(_value: object) -> None:
        raise physical.deploy.PreflightError("low disk or inodes")

    monkeypatch.setattr(physical.deploy, "_validate_storage_capacity", reject)
    monkeypatch.setattr(
        physical.deploy, "_run", lambda *args, **kwargs: pytest.fail("must not pull")
    )
    with pytest.raises(physical.deploy.PreflightError):
        physical._image_pull_and_verify()


def test_release_claim_is_fsynced_and_never_reusable(tmp_path: Path) -> None:
    run_id = "42899999999"
    physical._claim_once(tmp_path, run_id)
    marker = tmp_path / f".boca-worker-physical-{physical.RELEASE_RUN_ID}.claim"
    assert json.loads(marker.read_text()) == {
        "run_id": run_id,
        "release_run_id": physical.RELEASE_RUN_ID,
    }
    assert marker.stat().st_mode & 0o777 == 0o600
    with pytest.raises(physical.PhysicalProbeUnavailable):
        physical._claim_once(tmp_path, run_id)


def test_lost_create_ack_is_indeterminate_and_never_retries_or_starts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(physical.cleanup, "protected_boca_job_lease", lambda _: _dummy_lease())
    monkeypatch.setattr(physical, "_verify_rootless", lambda: None)
    monkeypatch.setattr(physical, "_idle", lambda *_: (object(), "unchanged"))
    monkeypatch.setattr(physical, "_verified_boca_home", lambda: tmp_path)
    monkeypatch.setattr(physical, "_image_pull_and_verify", lambda: "storage-before")
    monkeypatch.setattr(physical, "_profile_path", lambda folder: str(folder / "seccomp.json"))
    monkeypatch.setattr(physical, "_claim_once", lambda *_: calls.append("claim"))
    monkeypatch.setattr(
        physical, "_exact_cleanup", lambda *_: pytest.fail("unknown CID must never be guessed")
    )

    def lost_ack(*argv: str, **_kwargs: object) -> str:
        calls.append(argv[1])
        raise physical.deploy.PreflightError("create response lost")

    monkeypatch.setattr(physical.deploy, "_run", lost_ack)
    with pytest.raises(physical.deploy.PreflightError):
        physical._diagnose("42899999999")
    assert calls == ["claim", "create"]


@pytest.mark.parametrize("early_exit", [False, True])
def test_physical_witness_arms_before_one_start_and_removes_exact_cid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    early_exit: bool,
) -> None:
    cid, run_id = "f" * 64, "42899999999"
    events: list[str] = []
    installed = object()
    monkeypatch.setattr(physical.cleanup, "protected_boca_job_lease", lambda _: _dummy_lease())
    monkeypatch.setattr(physical, "_verify_rootless", lambda: events.append("rootless"))
    monkeypatch.setattr(physical, "_idle", lambda _lease, _run: (installed, "same-fingerprint"))
    tmp_path.chmod(0o700)
    monkeypatch.setattr(physical, "_verified_boca_home", lambda: tmp_path)
    monkeypatch.setattr(
        physical, "_image_pull_and_verify", lambda: events.append("pull-digest") or "storage-before"
    )
    monkeypatch.setattr(physical.deploy, "_storage_snapshot", lambda: "storage-after")
    monkeypatch.setattr(
        physical.deploy,
        "_validate_storage_continuity",
        lambda before, after, **kwargs: events.append("storage-continuity"),
    )
    monkeypatch.setattr(physical, "_profile_path", lambda folder: str(folder / "seccomp.json"))
    monkeypatch.setattr(physical, "_claim_once", lambda _home, _run: events.append("claim"))

    def docker(action: str, *args: str, timeout: int):
        events.append(f"{action}-{args[0]}")
        if action == "docker":
            if args[0] == "create":
                return cid
            if args[0] == "start":
                assert args == ("start", cid)
                return cid
            if args[0] == "stop":
                assert args == ("stop", "-t", "8", cid)
                return cid
            if args[0] == "rm":
                assert args == ("rm", cid)
                return cid
        raise AssertionError("unexpected Docker operation")

    monkeypatch.setattr(physical.deploy, "_run", docker)
    monkeypatch.setattr(
        physical,
        "_inspect_probe",
        lambda _cid, _run, _profile: {
            "State": {"Status": "created", "Running": True},
        },
    )
    monkeypatch.setattr(
        physical,
        "_identify_probe",
        lambda _cid, _run: {
            "State": {"Status": "running", "Running": True},
        },
    )
    monkeypatch.setattr(physical.cleanup, "_docker", lambda *args: "")

    @contextmanager
    def arm(_socket: object, ident: str) -> Iterator[object]:
        assert ident == cid
        events.append("attach-before-start")

        class Captured:
            @staticmethod
            def finish():
                events.append("classify")
                return physical.capture.CaptureResult.MISSING_BARE_SYNTHETIC

        yield Captured()
        events.append("detach")

    monkeypatch.setattr(physical.capture, "attach_output", arm)

    def health(_cid: str) -> None:
        events.append("health")
        if early_exit:
            raise physical.deploy.WorkerHealthPhaseError(
                "HEALTH_EXITED",
                exit_code=1,
                oom_killed=False,
            )

    monkeypatch.setattr(physical.deploy, "_browser_wait_healthy", health)
    monkeypatch.setattr(
        physical.deploy, "_browser_worker_probe", lambda _cid: events.append("kernel-proof")
    )
    monkeypatch.setattr(physical, "_image_retained", lambda: events.append("image-retained"))
    result = physical._diagnose(run_id)
    assert result["boot"] == ("FAILED" if early_exit else "HEALTHY")
    assert result["cause"] == ("MISSING_BARE_SYNTHETIC" if early_exit else "NONE")
    assert result["cleanup"] == "VERIFIED"
    assert result["image_cache"] == "RETAINED"
    assert (
        events.index("claim") < events.index("docker-create") < events.index("attach-before-start")
    )
    assert events.index("attach-before-start") < events.index("docker-start")
    assert events.count("docker-start") == 1
    assert (
        events.index("kernel-proof") > events.index("health")
        if not early_exit
        else "kernel-proof" not in events
    )
    assert events.index("docker-rm") < events.index("storage-continuity")


@contextmanager
def _dummy_lease() -> Iterator[object]:
    yield object()


def test_probe_create_is_one_disposable_networkless_ipc_only_container() -> None:
    command = physical.create_argv("42899999999", "/srv/boca-socios/profile.json")
    assert command[:2] == ("create", "--pull")
    assert "--name" in command
    assert "boca-physical-worker-42899999999" in command
    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--restart") + 1] == "no"
    assert command[command.index("--user") + 1] == "10002:10002"
    assert command[command.index("--log-driver") + 1] == "none"
    assert command[command.index("--memory") + 1] == "768m"
    assert command[command.index("--pids-limit") + 1] == "128"
    assert command[command.index("--cpus") + 1] == "1.00"
    assert command[command.index("--tmpfs") + 1] == "/tmp:rw,noexec,nosuid,size=32m"  # noqa: S108
    assert (
        "/run/boca-browser-ipc:rw,noexec,nosuid,size=16m,uid=10002,gid=10002,mode=0711" in command
    )
    assert "--read-only" in command
    assert "--cap-drop" in command
    assert "no-new-privileges:true" in command
    assert "seccomp=/srv/boca-socios/profile.json" in command
    assert "BOCA_ENGINE_MODE=off" in command
    assert "BOCA_OBSERVER_STOP=1" in command
    assert "--mount" not in command
    assert "--volume" not in command
    assert command[-4:] == (
        physical.BROWSER_IMAGE,
        "python",
        "-m",
        "boca_socios.browser.ipc_worker",
    )


def test_receipt_rejects_healthy_without_real_boot_and_cleanup() -> None:
    good = {
        "schema": 1,
        "run_id": "42899999999",
        "release_run_id": physical.RELEASE_RUN_ID,
        "image_ref": physical.BROWSER_IMAGE,
        "container_id": "a" * 64,
        "started": True,
        "boot": "HEALTHY",
        "cause": "NONE",
        "exit_code": None,
        "oom": None,
        "controller": "HEALTHY",
        "engine": "STOPPED",
        "installed_worker": "IDLE",
        "cleanup": "VERIFIED",
        "image_cache": "RETAINED",
    }
    validated = physical.checked(good, good["run_id"])
    assert validated.startswith("BOCA_WORKER_PHYSICAL {")
    for field, bad in (
        ("started", False),
        ("cleanup", "INDETERMINATE"),
        ("engine", "RUNNING"),
        ("boot", "FAILED"),
        ("container_id", "boca-controller"),
        ("image_ref", "ghcr.io/example/foreign"),
    ):
        modified = dict(good, **{field: bad})
        with pytest.raises(physical.PhysicalProbeUnavailable):
            physical.checked(modified, good["run_id"])


def test_receipt_only_allows_bounded_error_classes() -> None:
    good = json.loads(
        physical.checked(
            {
                "schema": 1,
                "run_id": "42899999999",
                "release_run_id": physical.RELEASE_RUN_ID,
                "image_ref": physical.BROWSER_IMAGE,
                "container_id": "f" * 64,
                "started": True,
                "boot": "FAILED",
                "cause": "MISSING_BARE_SYNTHETIC",
                "exit_code": 1,
                "oom": False,
                "controller": "HEALTHY",
                "engine": "STOPPED",
                "installed_worker": "IDLE",
                "cleanup": "VERIFIED",
                "image_cache": "RETAINED",
            },
            "42899999999",
        ).removeprefix("BOCA_WORKER_PHYSICAL ")
    )
    assert good["cause"] == "MISSING_BARE_SYNTHETIC"
    with pytest.raises(physical.PhysicalProbeUnavailable):
        physical.checked(dict(good, **{"cause": "secret:PRIVATE_CREDENTIAL"}), good["run_id"])
