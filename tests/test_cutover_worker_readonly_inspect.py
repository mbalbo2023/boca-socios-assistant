"""P0 regression: diagnose a failed Boca worker probe without host writes."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from scripts import host_cutover_worker_inspect as observer  # noqa: E402
from scripts import host_cutover_worker_preflight as preflight  # noqa: E402

ATTEMPT = "42329475083"
LEGACY_ID = "d" * 64
LEGACY_SHA = "c" * 40
LEGACY_IMAGE = f"ghcr.io/mbalbo2023/boca-socios-assistant@sha256:{'c' * 64}"
PROBE_ID = "f" * 64


def _original() -> dict[str, object]:
    return {
        "id": LEGACY_ID,
        "name": observer.ORIGINAL_NAME,
        "image_ref": LEGACY_IMAGE,
        "revision": LEGACY_SHA,
        "project": observer.PROJECT,
        "attempt": None,
        "running": True,
        "health": "healthy",
        "ports": {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]},
    }


def _probe() -> dict[str, object]:
    return {
        "id": PROBE_ID,
        "name": f"/{observer.PREFIX}{ATTEMPT}",
        "image_ref": f"ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:{'b' * 64}",
        "revision": "a" * 40,
        "project": observer.PROJECT,
        "attempt": ATTEMPT,
        "running": False,
        "health": None,
        "ports": {},
    }


def _rootless(monkeypatch: pytest.MonkeyPatch, *, seccomp: str = "ABSENT") -> None:
    monkeypatch.setattr(observer.os, "geteuid", lambda: observer.UID)
    monkeypatch.setattr(observer.os, "getegid", lambda: observer.UID)
    monkeypatch.setattr(
        observer,
        "_runtime_stat",
        lambda name: "PRESENT_OWNED" if name == "docker.sock" else seccomp,
    )


def test_observer_protocol_mirrors_preflight_without_importing_blackboxes() -> None:
    assert observer.PREFIX == preflight.PREFIX
    assert observer.PROBE_LABEL == preflight.LABEL
    assert observer.RUNTIME == preflight.RUNTIME
    assert observer.PROJECT == preflight.host.PROJECT


def test_absent_probe_and_healthy_original_are_separate_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _rootless(monkeypatch)
    monkeypatch.setattr(observer, "_named_id", lambda _name: None)
    monkeypatch.setattr(
        observer, "_inspect_id", lambda cid: _original() if cid == LEGACY_ID else {}
    )
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    assert (record["probe"], record["seccomp"]) == ("ABSENT", "ABSENT")
    assert (record["original"], record["original_port"]) == (
        "RUNNING_HEALTHY",
        "LOOPBACK_8443",
    )
    assert record["docker"] == "OBSERVED"
    assert record["cutover_authorized"] is False
    assert observer.verify(observer.canonical(record) + b"\n", ATTEMPT, LEGACY_ID) == record


def test_exact_leftover_probe_does_not_trigger_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    _rootless(monkeypatch, seccomp="PRESENT_OWNED")
    monkeypatch.setattr(observer, "_named_id", lambda _name: PROBE_ID)
    monkeypatch.setattr(
        observer, "_inspect_id", lambda cid: _probe() if cid == PROBE_ID else _original()
    )
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    assert record["probe"] == "PRESENT_LABEL_MATCH"
    assert record["probe_id"] == PROBE_ID
    assert record["probe_running"] is False
    assert record["seccomp"] == "PRESENT_OWNED"
    assert record["original"] == "RUNNING_HEALTHY"
    assert record["observer_writes"] == 0
    observer.verify(observer.canonical(record) + b"\n", ATTEMPT, LEGACY_ID)


def test_foreign_label_is_never_authentic_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    _rootless(monkeypatch)
    wrong = _probe()
    wrong["project"] = "some-other-app"
    monkeypatch.setattr(observer, "_named_id", lambda _name: PROBE_ID)
    monkeypatch.setattr(
        observer, "_inspect_id", lambda cid: wrong if cid == PROBE_ID else _original()
    )
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    assert record["probe"] == "PRESENT_UNVERIFIED"
    assert record["probe_id"] is None
    assert record["foreign_resources_touched"] is False


def test_original_with_wrong_image_is_not_attested(monkeypatch: pytest.MonkeyPatch) -> None:
    _rootless(monkeypatch)
    wrong = _original()
    wrong["image_ref"] = LEGACY_IMAGE.replace("c" * 64, "e" * 64)
    monkeypatch.setattr(observer, "_named_id", lambda _name: None)
    monkeypatch.setattr(observer, "_inspect_id", lambda _cid: wrong)
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    assert record["docker"] == "OBSERVED"
    assert record["original"] == "UNVERIFIED"
    assert record["original_port"] == "UNVERIFIED"


def test_daemon_failure_is_reported_without_fabricated_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _rootless(monkeypatch)

    def failed(_name: str) -> None:
        raise subprocess.CalledProcessError(1, ["docker", "ps"])

    monkeypatch.setattr(observer, "_named_id", failed)
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    assert record["docker"] == "READ_FAILED"
    assert record["probe"] == "UNVERIFIED"
    assert record["original"] == "UNVERIFIED"
    observer.verify(observer.canonical(record) + b"\n", ATTEMPT, LEGACY_ID)


def test_socket_absent_never_queries_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(observer.os, "geteuid", lambda: observer.UID)
    monkeypatch.setattr(observer.os, "getegid", lambda: observer.UID)
    monkeypatch.setattr(observer, "_runtime_stat", lambda _name: "ABSENT")
    monkeypatch.setattr(observer, "_named_id", lambda _name: pytest.fail("Docker queried"))
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    assert record["docker"] == "SOCKET_UNVERIFIED"
    assert record["original"] == "UNVERIFIED"


def test_wrong_uid_does_not_query_rootless_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(observer.os, "geteuid", lambda: 0)
    monkeypatch.setattr(observer.os, "getegid", lambda: 0)
    monkeypatch.setattr(observer, "_runtime_stat", lambda _name: "PRESENT_OWNED")
    monkeypatch.setattr(observer, "_named_id", lambda _name: pytest.fail("Docker queried"))
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    assert record["docker"] == "WRONG_UID"
    assert record["probe"] == "UNVERIFIED"
    assert record["original"] == "UNVERIFIED"
    observer.verify(observer.canonical(record) + b"\n", ATTEMPT, LEGACY_ID)


def test_docker_inspect_requires_exact_id_and_metadata_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(observer, "_docker", lambda *_args: json.dumps(_original()))
    assert observer._inspect_id(LEGACY_ID)["image_ref"] == LEGACY_IMAGE
    wrong = _original()
    wrong["id"] = PROBE_ID
    monkeypatch.setattr(observer, "_docker", lambda *_args: json.dumps(wrong))
    with pytest.raises(observer.InspectError, match="INSPECT_IDENTITY"):
        observer._inspect_id(LEGACY_ID)
    wrong = _original()
    wrong["unexpected"] = "value"
    monkeypatch.setattr(observer, "_docker", lambda *_args: json.dumps(wrong))
    with pytest.raises(observer.InspectError, match="INSPECT_IDENTITY"):
        observer._inspect_id(LEGACY_ID)


def test_docker_command_allowlist_and_exact_rootless_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        env = kwargs["env"]
        assert isinstance(env, dict)
        assert env["DOCKER_HOST"] == "unix:///run/user/10001/docker.sock"
        assert all(not key.startswith("DOCKER_") for key in env if key != "DOCKER_HOST")
        return subprocess.CompletedProcess(argv, 0, stdout=PROBE_ID + "\n", stderr="")

    monkeypatch.setattr(observer.subprocess, "run", fake_run)
    assert observer._named_id(f"{observer.PREFIX}{ATTEMPT}") == PROBE_ID
    assert calls[0][:3] == ("docker", "ps", "-a")
    for forbidden in (("stop", PROBE_ID), ("rm", PROBE_ID), ("system", "prune")):
        with pytest.raises(observer.InspectError, match="DOCKER_COMMAND"):
            observer._docker(*forbidden)
    assert len(calls) == 1


def test_oversized_docker_metadata_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def oversized(argv: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, stdout="f" * 2049, stderr="")

    monkeypatch.setattr(observer.subprocess, "run", oversized)
    with pytest.raises(observer.InspectError, match="DOCKER_BOUNDS"):
        observer._named_id(f"{observer.PREFIX}{ATTEMPT}")


def test_runtime_stat_never_follows_symlink(monkeypatch: pytest.MonkeyPatch) -> None:
    root = os.stat_result((stat.S_IFDIR | 0o700, 1, 0, 1, observer.UID, observer.UID, 0, 0, 0, 0))
    link = os.stat_result((stat.S_IFLNK | 0o777, 2, 0, 1, observer.UID, observer.UID, 0, 0, 0, 0))
    monkeypatch.setattr(observer.os, "open", lambda *_a: 42)
    monkeypatch.setattr(observer.os, "fstat", lambda _fd: root)

    def fake_stat(name: str, *, dir_fd: int, follow_symlinks: bool) -> os.stat_result:
        assert name in {"docker.sock", f"{observer.PREFIX}{ATTEMPT}-seccomp.json"}
        assert dir_fd == 42 and follow_symlinks is False
        return link

    monkeypatch.setattr(observer.os, "stat", fake_stat)
    monkeypatch.setattr(observer.os, "close", lambda _fd: None)
    assert observer._runtime_stat("docker.sock") == "PRESENT_UNVERIFIED"
    assert (
        observer._runtime_stat(f"{observer.PREFIX}{ATTEMPT}-seccomp.json") == "PRESENT_UNVERIFIED"
    )


def test_verify_rejects_forged_acks_and_invalid_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(observer, "_docker", lambda *_args: pytest.fail("Docker queried"))
    with pytest.raises(observer.InspectError):
        observer.observe("0", LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    with pytest.raises(observer.InspectError):
        observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, "docker.io/foreign:latest")
    _rootless(monkeypatch)
    monkeypatch.setattr(observer, "_named_id", lambda _name: None)
    monkeypatch.setattr(observer, "_inspect_id", lambda _cid: _original())
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    for key, value in (
        ("cutover_authorized", True),
        ("observer_writes", 1),
        ("probe", "PRESENT_LABEL_MATCH"),
        ("probe_running", True),
        ("original_port", "UNVERIFIED"),
    ):
        bad = {**record, key: value}
        with pytest.raises(observer.InspectError):
            observer.verify(observer.canonical(bad) + b"\n", ATTEMPT, LEGACY_ID)
    bad_json = json.dumps(record, indent=2).encode() + b"\n"
    with pytest.raises(observer.InspectError):
        observer.verify(bad_json, ATTEMPT, LEGACY_ID)


def test_one_time_protected_workflow_has_no_host_mutation_for_inspection() -> None:
    workflow = (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()
    assert "cutover-a-worker-inspect" in workflow
    assert 'test "$BOCA_PROTECTED_ACTION_CONTEXT" = 42329475083' in workflow
    assert (
        'test "$BOCA_LEGACY_CONTROLLER_ID" = 27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793'
        in workflow
    )
    block = workflow.split(
        "- name: Inspect one failed Boca worker probe READ_ONLY by exact identity"
    )[1].split("- name: Reconcile exact failed Cutover A")[0]
    assert "scripts/host_cutover_worker_inspect.py" in block
    assert "observer_writes=0 retry=NO_GO" in block
    assert "docker stop" not in block and "docker rm" not in block and "docker exec" not in block
