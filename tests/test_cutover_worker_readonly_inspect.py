"""P0 regression: diagnose a failed Boca worker probe without host writes."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
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


def _fake_docker_process(
    monkeypatch: pytest.MonkeyPatch, script: str
) -> tuple[list[tuple[str, ...]], list[subprocess.Popen[bytes]]]:
    """Exercise real pipes/child lifecycle without a Docker daemon or host access."""
    real_popen = subprocess.Popen
    calls: list[tuple[str, ...]] = []
    children: list[subprocess.Popen[bytes]] = []

    def spawn(argv: tuple[str, ...], **kwargs: object) -> subprocess.Popen[bytes]:
        calls.append(argv)
        assert argv[0] == "docker"
        env = kwargs["env"]
        assert isinstance(env, dict)
        assert env["DOCKER_HOST"] == "unix:///run/user/10001/docker.sock"
        assert all(not key.startswith("DOCKER_") for key in env if key != "DOCKER_HOST")
        child = real_popen((sys.executable, "-c", script), **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(observer.subprocess, "Popen", spawn)
    return calls, children


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
        "image_ref": observer.FAILED_WORKER_IMAGE,
        "revision": observer.FAILED_WORKER_SOURCE,
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
    monkeypatch.setattr(observer, "_inspect_no_health", lambda _cid: _probe())
    monkeypatch.setattr(observer, "_inspect_id", lambda _cid: _original())
    monkeypatch.setattr(observer, "_full_json_length", lambda _cid: 4096)
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    assert record["probe"] == "PRESENT_PIN_MATCH"
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
    monkeypatch.setattr(observer, "_inspect_no_health", lambda _cid: wrong)
    monkeypatch.setattr(observer, "_inspect_id", lambda _cid: _original())
    monkeypatch.setattr(observer, "_full_json_length", lambda _cid: 4096)
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
    monkeypatch.setattr(observer, "_inspect_id", lambda _cid: _original())
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    assert record["docker"] == "PARTIAL"
    assert record["probe_list_stage"] == "COMMAND_FAILED"
    assert record["probe_list_rc"] == 1
    assert record["probe"] == "UNVERIFIED"
    assert record["original"] == "RUNNING_HEALTHY"
    observer.verify(observer.canonical(record) + b"\n", ATTEMPT, LEGACY_ID)


def test_failed_probe_inspect_preserves_candidate_and_original_and_redacts_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _rootless(monkeypatch)
    monkeypatch.setattr(observer, "_named_id", lambda _name: PROBE_ID)

    def inspect(cid: str) -> dict[str, object]:
        if cid == PROBE_ID:
            raise subprocess.CalledProcessError(1, ["docker", "inspect"], stderr="SECRET_MARKER")
        return _original()

    monkeypatch.setattr(observer, "_inspect_no_health", inspect)
    monkeypatch.setattr(observer, "_inspect_id", lambda _cid: _original())
    size_calls: list[str] = []

    def size(cid: str) -> int:
        size_calls.append(cid)
        return 4096

    monkeypatch.setattr(observer, "_full_json_length", size)
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    assert record["docker"] == "PARTIAL"
    assert record["probe_candidate_id"] == PROBE_ID
    assert record["probe_id"] is None
    assert record["probe"] == "PRESENT_UNVERIFIED"
    assert record["probe_inspect_stage"] == "COMMAND_FAILED"
    assert record["probe_inspect_rc"] == 1
    assert record["probe_full_json_stage"] == "BELOW_CLEANUP_LIMIT"
    assert record["original"] == "RUNNING_HEALTHY"
    assert record["original_port"] == "LOOPBACK_8443"
    assert record["original_inspect_stage"] == "OK"
    assert size_calls == [PROBE_ID]
    raw = observer.canonical(record) + b"\n"
    assert b"SECRET_MARKER" not in raw
    assert observer.verify(raw, ATTEMPT, LEGACY_ID) == record


def test_probe_attested_but_original_inspect_fails_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _rootless(monkeypatch)
    monkeypatch.setattr(observer, "_named_id", lambda _name: PROBE_ID)

    def inspect(cid: str) -> dict[str, object]:
        if cid == LEGACY_ID:
            raise subprocess.CalledProcessError(125, ["docker", "inspect"])
        return _original()

    monkeypatch.setattr(observer, "_inspect_id", inspect)
    monkeypatch.setattr(observer, "_inspect_no_health", lambda _cid: _probe())
    monkeypatch.setattr(observer, "_full_json_length", lambda _cid: 4096)
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    assert record["probe"] == "PRESENT_PIN_MATCH"
    assert record["probe_id"] == PROBE_ID
    assert record["original"] == "UNVERIFIED"
    assert record["original_inspect_stage"] == "COMMAND_FAILED"
    assert record["original_inspect_rc"] == 125
    assert record["probe_full_json_stage"] == "BELOW_CLEANUP_LIMIT"
    observer.verify(observer.canonical(record) + b"\n", ATTEMPT, LEGACY_ID)


def test_probe_lookup_ambiguous_still_inspects_original(monkeypatch: pytest.MonkeyPatch) -> None:
    _rootless(monkeypatch)
    monkeypatch.setattr(
        observer,
        "_named_id",
        lambda _name: (_ for _ in ()).throw(observer.InspectError("PROBE_SET")),
    )
    monkeypatch.setattr(observer, "_inspect_id", lambda _cid: _original())
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    assert record["probe_list_stage"] == "METADATA_INVALID"
    assert record["probe_candidate_id"] is None
    assert record["original"] == "RUNNING_HEALTHY"
    observer.verify(observer.canonical(record) + b"\n", ATTEMPT, LEGACY_ID)


def test_timeout_still_checks_full_json_size_and_independent_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _rootless(monkeypatch)
    monkeypatch.setattr(observer, "_named_id", lambda _name: PROBE_ID)

    def inspect(cid: str) -> dict[str, object]:
        if cid == PROBE_ID:
            raise subprocess.TimeoutExpired(["docker", "inspect"], 12)
        return _original()

    monkeypatch.setattr(observer, "_inspect_no_health", inspect)
    monkeypatch.setattr(observer, "_inspect_id", lambda _cid: _original())
    monkeypatch.setattr(observer, "_full_json_length", lambda _cid: 65536)
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    assert record["probe_inspect_stage"] == "TIMEOUT"
    assert record["probe_full_json_stage"] == "AT_OR_ABOVE_CLEANUP_LIMIT"
    assert record["original"] == "RUNNING_HEALTHY"


def test_four_reads_have_fixed_order_even_when_both_compact_inspects_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _rootless(monkeypatch)
    seen: list[str] = []

    def lookup(_name: str) -> str:
        seen.append("list")
        return PROBE_ID

    def rich(cid: str) -> dict[str, object]:
        seen.append(f"compact:{cid}")
        raise subprocess.CalledProcessError(1, ["docker", "inspect"])

    def size(cid: str) -> int:
        seen.append(f"full-json-size:{cid}")
        return 65536

    monkeypatch.setattr(observer, "_named_id", lookup)
    monkeypatch.setattr(observer, "_inspect_id", rich)
    monkeypatch.setattr(observer, "_inspect_no_health", rich)
    monkeypatch.setattr(observer, "_full_json_length", size)
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    assert seen == [
        "list",
        f"compact:{PROBE_ID}",
        f"full-json-size:{PROBE_ID}",
        f"compact:{LEGACY_ID}",
    ]
    assert record["probe_full_json_stage"] == "AT_OR_ABOVE_CLEANUP_LIMIT"
    assert record["original_inspect_stage"] == "COMMAND_FAILED"
    assert observer.verify(observer.canonical(record) + b"\n", ATTEMPT, LEGACY_ID) == record


def test_unusual_docker_exit_code_is_categorized_not_leaked() -> None:
    assert observer._failure(subprocess.CalledProcessError(-9, ["docker"])) == (
        "COMMAND_FAILED",
        255,
    )
    assert observer._failure(subprocess.CalledProcessError(900, ["docker"])) == (
        "COMMAND_FAILED",
        255,
    )


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
    calls, children = _fake_docker_process(monkeypatch, f"print('{PROBE_ID}')")
    assert observer._named_id(f"{observer.PREFIX}{ATTEMPT}") == PROBE_ID
    assert calls[0][:3] == ("docker", "ps", "-a")
    observer._docker("inspect", "--format", observer.INSPECT_NO_HEALTH, PROBE_ID)
    observer._docker("inspect", "--format", observer.INSPECT_FULL_JSON_LENGTH, PROBE_ID)
    assert calls[1][3] == observer.INSPECT_NO_HEALTH
    assert calls[2][3] == observer.INSPECT_FULL_JSON_LENGTH
    for forbidden in (
        ("stop", PROBE_ID),
        ("rm", PROBE_ID),
        ("system", "prune"),
        ("inspect", "--format", "{{json .}}", PROBE_ID),
    ):
        with pytest.raises(observer.InspectError, match="DOCKER_COMMAND"):
            observer._docker(*forbidden)
    assert len(calls) == 3
    assert all(proc.poll() == 0 for proc in children)


def test_full_json_size_query_is_bounded_to_exact_cid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual, children = _fake_docker_process(monkeypatch, "print('65536')")
    assert observer._full_json_length(PROBE_ID) == 65536
    assert actual == [("docker", "inspect", "--format", "{{len (json .)}}", PROBE_ID)]
    assert children[0].poll() == 0


def test_full_json_length_inspect_failure_is_classified_without_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_docker_process(
        monkeypatch,
        "import sys; sys.stderr.write('SECRET_MARKER'); sys.exit(1)",
    )
    with pytest.raises(subprocess.CalledProcessError) as exc:
        observer._full_json_length(PROBE_ID)
    assert observer._failure(exc.value) == ("COMMAND_FAILED", 1)
    assert "SECRET_MARKER" not in str(exc.value)


def test_oversized_docker_metadata_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    _, children = _fake_docker_process(
        monkeypatch,
        "import sys,time; sys.stdout.write('f'*2049); sys.stdout.flush(); time.sleep(2)",
    )
    start = time.monotonic()
    with pytest.raises(observer.InspectError, match="DOCKER_BOUNDS"):
        observer._named_id(f"{observer.PREFIX}{ATTEMPT}")
    assert time.monotonic() - start < 1.5, "must stop before the emitter exits"
    assert children[0].poll() is not None


def test_docker_stderr_is_byte_bounded_during_progressive_emission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, children = _fake_docker_process(
        monkeypatch,
        f"import sys,time; sys.stdout.write('{PROBE_ID}\\n'); "
        "sys.stdout.flush(); sys.stderr.buffer.write(b'x'*2049); "
        "sys.stderr.flush(); time.sleep(2)",
    )
    start = time.monotonic()
    with pytest.raises(observer.InspectError, match="DOCKER_BOUNDS"):
        observer._named_id(f"{observer.PREFIX}{ATTEMPT}")
    assert time.monotonic() - start < 1.5
    assert children[0].poll() is not None


def test_docker_stdout_limit_is_bytes_not_decoded_characters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, children = _fake_docker_process(
        monkeypatch,
        "import sys; sys.stdout.buffer.write('é'.encode()*1025)",
    )
    with pytest.raises(observer.InspectError, match="DOCKER_BOUNDS"):
        observer._docker("inspect", "--format", observer.INSPECT_FULL_JSON_LENGTH, PROBE_ID)
    assert children[0].poll() is not None


def test_docker_deadline_kills_and_reaps_hung_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(observer, "DOCKER_TIMEOUT_SECONDS", 0.1)
    _, children = _fake_docker_process(monkeypatch, "import time; time.sleep(3)")
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as error:
        observer._named_id(f"{observer.PREFIX}{ATTEMPT}")
    assert error.value.timeout == 0.1
    assert time.monotonic() - start < 1.0
    assert children[0].poll() is not None


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
        ("probe", "PRESENT_PIN_MATCH"),
        ("probe_running", True),
        ("original_port", "UNVERIFIED"),
        ("probe_list_stage", "TIMEOUT"),
        ("original_inspect_stage", "COMMAND_FAILED"),
        ("probe_candidate_id", "not-a-cid"),
        ("probe_list_rc", 1),
        ("probe_full_json_stage", "AT_OR_ABOVE_CLEANUP_LIMIT"),
        ("probe_full_json_rc", 1),
        ("probe_candidate_id", PROBE_ID),
        ("socket", "ABSENT"),
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


def test_r78_healthless_probe_is_pinned_and_inspected_with_four_bounded_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing HEALTHCHECK must not block a safe exact-SHA metadata comparison."""
    _rootless(monkeypatch)
    probe = {
        **_probe(),
        "image_ref": (
            "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
            "3894cfff995858d7c0ffdb994180a0d28a8a92bb69a0526fb040db2297fd8bf9"
        ),
        "revision": "92624ed6b7e75c6010f59670c866df00a29766dd",
    }
    calls: list[tuple[str, ...]] = []

    def fake_docker(*args: str) -> str:
        calls.append(args)
        if args[0] == "ps":
            return PROBE_ID
        if args[3] == PROBE_ID and "len (json .)" in args[2]:
            return "54321"
        if args[3] == PROBE_ID:
            assert '"health":null' in args[2]
            return json.dumps(probe)
        assert args[3] == LEGACY_ID
        return json.dumps(_original())

    monkeypatch.setattr(observer, "_docker", fake_docker)
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    assert record["probe"] == "PRESENT_PIN_MATCH"
    assert record["probe_running"] is False
    assert record["probe_full_json_stage"] == "BELOW_CLEANUP_LIMIT"
    assert record["original"] == "RUNNING_HEALTHY"
    assert record["observer_writes"] == 0
    assert record["cutover_authorized"] is False
    assert len(calls) == 4
    assert observer.verify(observer.canonical(record) + b"\n", ATTEMPT, LEGACY_ID) == record


def test_r78_wrong_browser_digest_never_attests_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A name/label match with a different digest is not Boca ownership."""
    _rootless(monkeypatch)
    probe = {
        **_probe(),
        "image_ref": f"ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:{'b' * 64}",
    }

    def fake_docker(*args: str) -> str:
        if args[0] == "ps":
            return PROBE_ID
        if args[3] == PROBE_ID and "len (json .)" in args[2]:
            return "65536"
        return json.dumps(probe if args[3] == PROBE_ID else _original())

    monkeypatch.setattr(observer, "_docker", fake_docker)
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    assert record["probe"] == "PRESENT_UNVERIFIED"
    assert record["probe_inspect_stage"] == "IDENTITY_MISMATCH"
    assert record["probe_full_json_stage"] == "AT_OR_ABOVE_CLEANUP_LIMIT"
    assert record["probe_id"] is None
    assert record["cutover_authorized"] is False
    observer.verify(observer.canonical(record) + b"\n", ATTEMPT, LEGACY_ID)


def test_r78_json_size_failure_is_redacted_and_does_not_hide_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One failed metadata size read cannot suppress the separate legacy observation."""
    _rootless(monkeypatch)
    calls: list[str] = []

    def fake_docker(*args: str) -> str:
        if args[0] == "ps":
            return PROBE_ID
        if args[3] == PROBE_ID and "len (json .)" in args[2]:
            raise subprocess.CalledProcessError(1, ["docker", "inspect"], stderr="PRIVATE_TOKEN")
        if args[3] == PROBE_ID:
            return json.dumps(_probe())
        calls.append(args[3])
        return json.dumps(_original())

    monkeypatch.setattr(observer, "_docker", fake_docker)
    record = observer.observe(ATTEMPT, LEGACY_ID, LEGACY_SHA, LEGACY_IMAGE)
    assert record["probe_full_json_stage"] == "COMMAND_FAILED"
    assert record["probe_full_json_rc"] == 1
    assert record["original"] == "RUNNING_HEALTHY"
    assert calls == [LEGACY_ID]
    assert b"PRIVATE_TOKEN" not in observer.canonical(record)
    observer.verify(observer.canonical(record) + b"\n", ATTEMPT, LEGACY_ID)
