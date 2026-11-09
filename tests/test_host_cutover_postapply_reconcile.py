"""Offline regression for incident #386; no real Docker, host, or network."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "host_cutover_postapply_reconcile", ROOT / "scripts" / "host_cutover_postapply_reconcile.py"
)
assert SPEC is not None and SPEC.loader is not None
reconcile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reconcile)

RUN = "42096941815"
PREPARE = "42091200929"
LEGACY_ID = "a" * 64
TARGET_SHA = "c" * 40


def _intent() -> bytes:
    return reconcile._canonical(
        {
            "version": "boca-cutover-a-intent-v1",
            "attempt_id": RUN,
            "legacy_id": LEGACY_ID,
            "legacy_source_sha": "b" * 40,
            "legacy_image_ref": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "d" * 64,
            "legacy_compose_sha": "e" * 64,
            "target_source_sha": TARGET_SHA,
            "target_image_ref": "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:" + "f" * 64,
            "browser_image_ref": "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:"
            + "0" * 64,
            "target_compose_sha": "e" * 64,
            "overlay_sha": "1" * 64,
            "seccomp_sha": "2" * 64,
            "owner_subject_sha256": "3" * 64,
            "origin": "http://localhost:8443",
        }
    )


def _result() -> bytes:
    return reconcile._canonical(
        {
            "version": "boca-cutover-a-terminal-v1",
            "attempt_id": RUN,
            "legacy_id": LEGACY_ID,
            "legacy_source_sha": "b" * 40,
            "target_source_sha": TARGET_SHA,
            "intent_sha256": hashlib.sha256(_intent()).hexdigest(),
            "state": "NO_GO",
            "cleanup": "INDETERMINATE",
            "original_restored": False,
            "irreversible_commit_started": False,
            "candidate_id": None,
            "worker_id": None,
        }
    )


def _container(ident: str, *, service: str, revision: str, name: str, running: bool):
    return {
        "id": ident,
        "name": name,
        "running": running,
        "health": "healthy" if running else None,
        "image_id": "sha256:" + "d" * 64,
        "revision": revision,
        "service": service,
        "attempt": RUN,
        "port_binding": {"8443/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8443"}]}
        if service == "controller"
        else {},
    }


@pytest.mark.parametrize("kind,raw", [("intent", _intent()), ("result", _result())])
def test_exact_canonical_markers(kind: str, raw: bytes) -> None:
    assert reconcile._record(raw, RUN, kind=kind)["attempt_id"] == RUN
    with pytest.raises(reconcile.ReconcileError):
        reconcile._record(raw, "42096941816", kind=kind)
    with pytest.raises(reconcile.ReconcileError):
        reconcile._record(raw + b"\n", RUN, kind=kind)


def _typed_result(**overrides: object) -> bytes:
    result = json.loads(_result())
    result.update(
        version="boca-cutover-a-terminal-v2",
        worker_primary_phase="CREATE",
        worker_compensation="INDETERMINATE",
    )
    result.update(overrides)
    return reconcile._canonical(result)


def _exit_result(**overrides: object) -> bytes:
    result = json.loads(_typed_result())
    result.update(
        version="boca-cutover-a-terminal-v3",
        worker_primary_phase="HEALTH_EXITED",
        worker_compensation="VERIFIED",
        worker_exit_code=1,
        worker_oom_killed=False,
    )
    result.update(overrides)
    return reconcile._canonical(result)


def test_v3_terminal_exit_evidence_is_accepted_by_readonly_observer() -> None:
    result = reconcile._record(_exit_result(), RUN, kind="result")
    assert result is not None
    assert result["version"] == "boca-cutover-a-terminal-v3"
    assert result["worker_primary_phase"] == "HEALTH_EXITED"
    assert result["worker_exit_code"] == 1
    assert result["worker_oom_killed"] is False
    assert reconcile._record(_typed_result(), RUN, kind="result")["version"] == (
        "boca-cutover-a-terminal-v2"
    )


def test_v4_terminal_exit_signature_readonly_schema_and_canary_rejection() -> None:
    signature = "EMPTY.EXITED.EARLY_LT_5S.NOT_RUN"
    raw = _exit_result(version="boca-cutover-a-terminal-v4", worker_exit_signature=signature)
    record = reconcile._record(raw, RUN, kind="result")
    assert record is not None and record["worker_exit_signature"] == signature
    for bad in ("PRIVATE", "UNKNOWN", 1, "EMPTY.DEAD.LATE_GE_5S.INVALID"):
        with pytest.raises(reconcile.ReconcileError):
            reconcile._record(
                _exit_result(version="boca-cutover-a-terminal-v4", worker_exit_signature=bad),
                RUN,
                kind="result",
            )
    # Adding V4-only fields to historical V3 is always rejected.
    with pytest.raises(reconcile.ReconcileError):
        reconcile._record(_exit_result(worker_exit_signature=signature), RUN, kind="result")


@pytest.mark.parametrize(
    "change",
    [
        {"worker_exit_code": -1},
        {"worker_exit_code": 256},
        {"worker_exit_code": True},
        {"worker_exit_code": "1"},
        {"worker_exit_code": None},
        {"worker_oom_killed": 0},
        {"worker_oom_killed": "NO"},
        {"worker_oom_killed": None},
        {"worker_primary_phase": "CREATE"},
        {"state": "ACCEPTED"},
        {"private_data": "do-not-leak"},
    ],
)
def test_v3_terminal_rejects_bad_exit_evidence(change: dict[str, object]) -> None:
    with pytest.raises(reconcile.ReconcileError):
        reconcile._record(_exit_result(**change), RUN, kind="result")


def test_v3_terminal_accepts_explicit_unknown_exit_evidence() -> None:
    result = reconcile._record(
        _exit_result(worker_exit_code="UNKNOWN", worker_oom_killed="UNKNOWN"),
        RUN,
        kind="result",
    )
    assert result is not None
    assert result["worker_exit_code"] == "UNKNOWN"


@pytest.mark.parametrize("code,oom", [(0, False), (255, True), (137, True)])
def test_v3_terminal_accepts_bounded_exact_exit_evidence(code: int, oom: bool) -> None:
    result = reconcile._record(
        _exit_result(worker_exit_code=code, worker_oom_killed=oom), RUN, kind="result"
    )
    assert result is not None
    assert result["worker_exit_code"] == code
    assert result["worker_oom_killed"] is oom


@pytest.mark.parametrize("absent", ["worker_exit_code", "worker_oom_killed"])
def test_v3_terminal_rejects_partial_exit_evidence(absent: str) -> None:
    payload = json.loads(_exit_result())
    del payload[absent]
    with pytest.raises(reconcile.ReconcileError):
        reconcile._record(reconcile._canonical(payload), RUN, kind="result")


def test_v3_terminal_rejects_duplicate_exit_field() -> None:
    payload = _exit_result().replace(
        b'"worker_exit_code":1', b'"worker_exit_code":1,"worker_exit_code":1'
    )
    with pytest.raises(reconcile.ReconcileError):
        reconcile._record(payload, RUN, kind="result")


@pytest.mark.parametrize("primary", ["CREATE", "HEALTH_UNHEALTHY"])
def test_typed_v2_terminal_is_accepted_by_shared_readonly_observer(primary: str) -> None:
    result = reconcile._record(_typed_result(worker_primary_phase=primary), RUN, kind="result")
    assert result is not None
    assert result["worker_primary_phase"] == primary
    assert result["worker_compensation"] == "INDETERMINATE"
    assert reconcile._record(_result(), RUN, kind="result")["version"] == (
        "boca-cutover-a-terminal-v1"
    )


@pytest.mark.parametrize(
    "change",
    [
        {"worker_primary_phase": "SHELL"},
        {"worker_primary_phase": "PULL;echo secret"},
        {"worker_primary_phase": None},
        {"worker_primary_phase": ["CREATE"]},
        {"worker_compensation": "UNKNOWN"},
        {"worker_compensation": None},
        {"worker_compensation": {"phase": "VERIFIED"}},
        {"state": "ACCEPTED"},
        {"extra_field": "leak"},
    ],
)
def test_typed_v2_terminal_rejects_invalid_and_extra_fields(change: dict[str, object]) -> None:
    with pytest.raises(reconcile.ReconcileError):
        reconcile._record(_typed_result(**change), RUN, kind="result")


@pytest.mark.parametrize("absent", ["worker_primary_phase", "worker_compensation"])
def test_typed_v2_terminal_rejects_partial_receipts(absent: str) -> None:
    record = json.loads(_typed_result())
    del record[absent]
    with pytest.raises(reconcile.ReconcileError):
        reconcile._record(reconcile._canonical(record), RUN, kind="result")


def test_duplicate_marker_keys_rejected() -> None:
    malformed = _intent().replace(
        b'"attempt_id":"42096941815"', b'"attempt_id":"42096941815","attempt_id":"42096941815"'
    )
    with pytest.raises(reconcile.ReconcileError):
        reconcile._record(malformed, RUN, kind="intent")


def test_postapply_runtime_only_read_from_boca_fixtures(monkeypatch: pytest.MonkeyPatch) -> None:
    files = {
        f"boca-cutover-a-intent-{RUN}.json": _intent(),
        f"boca-cutover-a-result-{RUN}.json": _result(),
    }
    monkeypatch.setattr(reconcile.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(reconcile.os, "getegid", lambda: 10001)
    monkeypatch.setattr(reconcile, "_private_home", lambda: Path("/home/fixture-boca-owner"))
    monkeypatch.setattr(reconcile.Path, "is_dir", lambda self: self.name == reconcile.RECEIPT_DIR)
    monkeypatch.setattr(reconcile.Path, "is_symlink", lambda self: False)
    monkeypatch.setattr(reconcile, "_read_private", lambda name, *, directory: files.get(name))
    original = _container(
        LEGACY_ID,
        service="controller",
        revision="b" * 40,
        name="/boca-socios-controller-legacy-" + RUN,
        running=False,
    )
    candidate = _container(
        "f" * 64,
        service="controller",
        revision=TARGET_SHA,
        name="/boca-socios-controller-1",
        running=True,
    )
    worker = _container(
        "9" * 64,
        service="browser-worker",
        revision=TARGET_SHA,
        name="/boca-socios-browser-worker-1",
        running=True,
    )
    monkeypatch.setattr(reconcile, "_docker_snapshot", lambda: [original, candidate, worker])
    monkeypatch.setattr(
        reconcile, "_marker", lambda marker: ("PRESENT_VERIFIED", "MARKER_SCHEMA_VALID")
    )
    monkeypatch.setattr(
        reconcile,
        "_stage_preflight",
        lambda intent: {
            "reason": "STAGE_PREFLIGHT_MATCH",
            "root_entries_count": 1,
            "root_entries_expected": True,
            "compose_digest_match": True,
            "compose_digest_evaluated": True,
            "compose_inode_checks": {
                "regular": True,
                "uid_ok": True,
                "gid_ok": True,
                "nlink_one": True,
                "mode_0600": True,
                "size_ok": True,
            },
            "compose_inode_mode_octal": "0600",
            "compose_legacy_mode_accepted": True,
            "plan_hashes_unique": True,
        },
    )
    monkeypatch.setattr(
        reconcile,
        "_staged_attempt",
        lambda attempt: {
            "stage": "PRESENT",
            "promotion_intent": "ABSENT",
            "promotion_result": "ABSENT",
        },
    )
    output = reconcile._host(RUN, PREPARE)
    assert output["original"]["running"] is False
    assert output["candidate_controllers"][0]["running"] is True
    assert output["browser_workers"][0]["running"] is True
    assert output["port_8443"] == "BOCA_CONTROLLER_DOCKER_BOUND"
    assert output["result"] == "PRESENT"
    assert output["worker_id_recorded"] is False
    assert output["candidate_id_recorded"] is False
    assert output["prepared_go_marker_reason"] == "MARKER_SCHEMA_VALID"
    assert output["stage_preflight"]["reason"] == "STAGE_PREFLIGHT_MATCH"
    assert output["stage_preflight"]["compose_digest_evaluated"] is True
    assert output["go_for_retry"] is False
    assert output["foreign_resources_touched"] is False
    assert len(reconcile._canonical(output) + b"\n") <= reconcile.MAX_JSON
    assert reconcile.verify_runner(reconcile._canonical(output) + b"\n", RUN, PREPARE) == output


@pytest.mark.parametrize(
    ("worker_id", "candidate_id", "expected"),
    [
        (None, None, (False, False)),
        ("9" * 64, None, (True, False)),
        ("9" * 64, "f" * 64, (True, True)),
    ],
)
def test_readonly_observer_reports_durable_phase_without_exposing_ids(
    monkeypatch: pytest.MonkeyPatch,
    worker_id: str | None,
    candidate_id: str | None,
    expected: tuple[bool, bool],
) -> None:
    result = json.loads(_result())
    result["worker_id"] = worker_id
    result["candidate_id"] = candidate_id
    files = {
        f"boca-cutover-a-intent-{RUN}.json": _intent(),
        f"boca-cutover-a-result-{RUN}.json": reconcile._canonical(result),
    }
    monkeypatch.setattr(reconcile.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(reconcile.os, "getegid", lambda: 10001)
    monkeypatch.setattr(reconcile, "_private_home", lambda: Path("/home/fixture-boca-owner"))
    monkeypatch.setattr(reconcile.Path, "is_dir", lambda self: self.name == reconcile.RECEIPT_DIR)
    monkeypatch.setattr(reconcile.Path, "is_symlink", lambda self: False)
    monkeypatch.setattr(reconcile, "_read_private", lambda name, *, directory: files.get(name))
    monkeypatch.setattr(reconcile, "_docker_snapshot", lambda: [])
    monkeypatch.setattr(reconcile, "_marker", lambda prepared: ("UNREADABLE", "DIRECTORY"))
    monkeypatch.setattr(
        reconcile, "_stage_preflight", lambda intent: {"reason": "STAGE_ROOT_ENTRIES"}
    )
    monkeypatch.setattr(
        reconcile,
        "_staged_attempt",
        lambda attempt: {
            "stage": "PRESENT",
            "promotion_intent": "ABSENT",
            "promotion_result": "ABSENT",
        },
    )
    observed = reconcile._host(RUN, PREPARE)
    assert (observed["worker_id_recorded"], observed["candidate_id_recorded"]) == expected
    assert worker_id not in reconcile._canonical(observed).decode() if worker_id else True
    assert candidate_id not in reconcile._canonical(observed).decode() if candidate_id else True
    assert reconcile.verify_runner(reconcile._canonical(observed) + b"\n", RUN, PREPARE) == observed


def test_no_docker_write_or_foreign_inspect_command() -> None:
    for command in (
        ("exec", "container", "python"),
        ("rm", "container"),
        ("ps", "-q"),
        ("volume", "rm", "boca-socios_boca_data"),
        ("compose", "down"),
        ("system", "prune"),
    ):
        with pytest.raises(reconcile.ReconcileError, match="DOCKER_COMMAND"):
            reconcile._docker(*command)


def test_runner_rejects_forged_accept_and_noncanonical_payload() -> None:
    payload = {
        "version": "boca-postapply-reconcile-v1",
        "incident_run_id": RUN,
        "prepare_run_id": PREPARE,
        "go_for_retry": True,
        "runtime_attested": False,
        "foreign_resources_touched": False,
    }
    with pytest.raises(reconcile.ReconcileError):
        reconcile.verify_runner(reconcile._canonical(payload) + b"\n", RUN, PREPARE)
    payload["go_for_retry"] = False
    with pytest.raises(reconcile.ReconcileError):
        reconcile.verify_runner(reconcile._canonical(payload) + b" \n", RUN, PREPARE)


def test_readonly_code_scope_and_no_blackbox_import() -> None:
    source = Path(reconcile.__file__).read_text(encoding="utf-8")
    assert "src/boca_socios/browser" not in source
    assert "subprocess.run" in source
    assert "DOCKER_HOST" in source


def test_stage_preflight_accepts_compose_reuse_and_inspects_host_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Canonical plan permits identical historical/target bytes, without writes."""
    payload = reconcile._record(_intent(), RUN, kind="intent")
    assert payload is not None
    attempted: list[str] = []

    def unavailable_root(path: str, *_args: object, **_kwargs: object) -> int:
        attempted.append(path)
        raise PermissionError("simulated read-only host root unavailable")

    monkeypatch.setattr(reconcile.os, "open", unavailable_root)
    observed = reconcile._stage_preflight(payload)
    assert observed["legacy_target_compose_equal"] is True
    assert observed["plan_hashes_unique"] is True
    assert observed["reason"] == "STAGE_ROOT_UNREADABLE"
    assert attempted == ["/srv/boca-socios"]


@pytest.mark.parametrize("bad_role", ["target_equals_overlay", "legacy_equals_seccomp"])
def test_stage_preflight_detects_invalid_digest_roles_and_still_observes_root(
    monkeypatch: pytest.MonkeyPatch, bad_role: str
) -> None:
    payload = reconcile._record(_intent(), RUN, kind="intent")
    assert payload is not None
    if bad_role == "target_equals_overlay":
        payload["overlay_sha"] = payload["target_compose_sha"]
    else:
        payload["seccomp_sha"] = payload["legacy_compose_sha"]
    attempted: list[str] = []

    def unavailable_root(path: str, *_args: object, **_kwargs: object) -> int:
        attempted.append(path)
        raise PermissionError("simulated read-only host root unavailable")

    monkeypatch.setattr(reconcile.os, "open", unavailable_root)
    observed = reconcile._stage_preflight(payload)
    assert observed["plan_hashes_unique"] is False
    assert observed["reason"] == "STAGE_ROOT_UNREADABLE"
    assert attempted == ["/srv/boca-socios"]


@pytest.mark.parametrize(
    "failed_check",
    [
        None,
        "sha_mismatch",
        "legacy_0644",
        "regular",
        "uid_ok",
        "gid_ok",
        "nlink_one",
        "mode_0600",
        "size_ok",
    ],
)
def test_stage_compose_inode_evidence_reads_only_after_all_six_checks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failed_check: str | None
) -> None:
    """Observe the actual open FD's metadata; a bad field must prevent data reads."""
    host_root = tmp_path / "boca-stage-fixture"
    host_root.mkdir(mode=0o700)
    data = b"services:\n  controller: {}\n"
    compose = host_root / "compose.beta.yaml"
    compose.write_bytes(data)
    compose.chmod(0o600)
    payload = reconcile._record(_intent(), RUN, kind="intent")
    assert payload is not None
    if failed_check != "sha_mismatch":
        payload["legacy_compose_sha"] = hashlib.sha256(data).hexdigest()
    payload["target_compose_sha"] = payload["legacy_compose_sha"]

    real_open = os.open
    real_fstat = os.fstat
    real_read = os.read
    reads: list[int] = []

    def open_fixture(path: str, flags: int, *args: object, **kwargs: object) -> int:
        return real_open(
            str(host_root) if path == "/srv/boca-socios" else path, flags, *args, **kwargs
        )

    def fstat_fixture(fd: int) -> SimpleNamespace:
        observed = real_fstat(fd)
        base = {
            "st_dev": observed.st_dev,
            "st_ino": observed.st_ino,
            "st_size": observed.st_size,
            "st_mtime_ns": observed.st_mtime_ns,
            "st_ctime_ns": observed.st_ctime_ns,
            "st_mode": (stat.S_IFDIR | 0o700)
            if stat.S_ISDIR(observed.st_mode)
            else (stat.S_IFREG | 0o600),
            "st_uid": reconcile.UID,
            "st_gid": reconcile.UID,
            "st_nlink": 1,
        }
        if stat.S_ISREG(observed.st_mode):
            if failed_check == "regular":
                base["st_mode"] = stat.S_IFDIR | 0o600
            elif failed_check == "uid_ok":
                base["st_uid"] += 1
            elif failed_check == "gid_ok":
                base["st_gid"] += 1
            elif failed_check == "nlink_one":
                base["st_nlink"] = 2
            elif failed_check == "mode_0600":
                base["st_mode"] = stat.S_IFREG | 0o640
            elif failed_check == "legacy_0644":
                base["st_mode"] = stat.S_IFREG | 0o644
            elif failed_check == "size_ok":
                base["st_size"] = 0
        return SimpleNamespace(**base)

    def bounded_read(fd: int, size: int) -> bytes:
        reads.append(size)
        if failed_check not in (None, "sha_mismatch", "legacy_0644"):
            pytest.fail("invalid Compose inode metadata must prevent reading bytes")
        return real_read(fd, size)

    monkeypatch.setattr(reconcile.os, "open", open_fixture)
    monkeypatch.setattr(reconcile.os, "fstat", fstat_fixture)
    monkeypatch.setattr(reconcile.os, "read", bounded_read)

    result = reconcile._stage_preflight(payload)
    expected = {
        "regular": True,
        "uid_ok": True,
        "gid_ok": True,
        "nlink_one": True,
        "mode_0600": True,
        "size_ok": True,
    }
    if failed_check not in (None, "sha_mismatch", "legacy_0644"):
        expected[failed_check] = False
    if failed_check == "legacy_0644":
        expected["mode_0600"] = False
    assert result["compose_inode_checks"] == expected
    assert result["compose_inode_mode_octal"] == (
        "0640"
        if failed_check == "mode_0600"
        else "0644"
        if failed_check == "legacy_0644"
        else "0600"
    )
    assert result["compose_legacy_mode_accepted"] is (failed_check != "mode_0600")
    assert result["compose_digest_evaluated"] is (
        failed_check in (None, "sha_mismatch", "legacy_0644")
    )
    assert result["compose_digest_match"] is (failed_check in (None, "legacy_0644"))
    assert result["reason"] == (
        "STAGE_PREFLIGHT_MATCH"
        if failed_check in (None, "legacy_0644")
        else "STAGE_COMPOSE_SHA"
        if failed_check == "sha_mismatch"
        else "STAGE_COMPOSE_INODE_MODE"
    )
    assert reads == ([32769] if failed_check in (None, "sha_mismatch", "legacy_0644") else [])


def test_stage_preflight_without_compose_fd_has_no_invented_inode_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = reconcile._record(_intent(), RUN, kind="intent")
    assert payload is not None
    monkeypatch.setattr(
        reconcile.os,
        "open",
        lambda *_a, **_k: (_ for _ in ()).throw(PermissionError("unavailable")),
    )
    result = reconcile._stage_preflight(payload)
    assert result["compose_inode_checks"] is None
    assert result["compose_inode_mode_octal"] is None
    assert result["compose_legacy_mode_accepted"] is None
    assert result["compose_digest_evaluated"] is False
    assert result["reason"] == "STAGE_ROOT_UNREADABLE"


def test_marker_unknown_volume_is_readonly_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reconcile, "_docker", lambda *args: "")
    assert reconcile._marker(PREPARE) == ("VOLUME_UNVERIFIED", "VOLUME_NAME_UNVERIFIED")


def test_v3_postapply_reconcile_without_prepare_is_readonly_and_source_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V3 #853 has no PREPARE; host evidence must bind to authenticated run SHA."""
    files = {
        f"boca-cutover-a-intent-{RUN}.json": _intent(),
        f"boca-cutover-a-result-{RUN}.json": _result(),
    }
    monkeypatch.setattr(reconcile.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(reconcile.os, "getegid", lambda: 10001)
    monkeypatch.setattr(reconcile, "_private_home", lambda: Path("/home/fixture-boca-owner"))
    monkeypatch.setattr(reconcile.Path, "is_dir", lambda self: self.name == reconcile.RECEIPT_DIR)
    monkeypatch.setattr(reconcile.Path, "is_symlink", lambda self: False)
    monkeypatch.setattr(reconcile, "_read_private", lambda name, *, directory: files.get(name))
    original = _container(
        LEGACY_ID,
        service="controller",
        revision="b" * 40,
        name="/boca-socios-controller-legacy-" + RUN,
        running=True,
    )
    worker = _container(
        "9" * 64,
        service="browser-worker",
        revision=TARGET_SHA,
        name="/boca-socios-browser-worker-1",
        running=False,
    )
    monkeypatch.setattr(reconcile, "_docker_snapshot", lambda: [original, worker])
    monkeypatch.setattr(
        reconcile, "_marker", lambda prepared: pytest.fail("V3 must not inspect PREPARE marker")
    )
    monkeypatch.setattr(reconcile, "_stage_preflight", lambda intent: {"reason": "STAGE_CHECK"})
    monkeypatch.setattr(
        reconcile,
        "_staged_attempt",
        lambda attempt: {
            "stage": "PRESENT",
            "promotion_intent": "ABSENT",
            "promotion_result": "ABSENT",
        },
    )

    record = reconcile._host(RUN, None, source_sha=TARGET_SHA)
    assert record["version"] == "boca-postapply-reconcile-v3"
    assert record["prepare_run_id"] is None
    assert record["incident_source_sha"] == TARGET_SHA
    assert record["prepared_go_marker"] == "NOT_APPLICABLE"
    assert record["prepared_go_marker_reason"] == "V3_DISPATCH_WITHOUT_PREPARE"
    assert record["original"]["id"] == LEGACY_ID
    assert record["browser_workers"][0]["running"] is False
    assert record["runtime_attested"] is False
    assert record["go_for_retry"] is False
    assert record["foreign_resources_touched"] is False
    raw = reconcile._canonical(record) + b"\n"
    assert reconcile.verify_runner(raw, RUN, None, source_sha=TARGET_SHA) == record
    with pytest.raises(reconcile.ReconcileError, match="RECEIPT_CONTRACT"):
        reconcile.verify_runner(raw, RUN, None, source_sha="e" * 40)
    with pytest.raises(reconcile.ReconcileError, match="RECEIPT_CONTRACT"):
        reconcile.verify_runner(raw, RUN, PREPARE)
    with pytest.raises(reconcile.ReconcileError, match="V3_SOURCE_MISMATCH"):
        reconcile._host(RUN, None, source_sha="e" * 40)


def test_v3_readonly_observer_rejects_untrusted_run_coordinates() -> None:
    for run, source in (("0", TARGET_SHA), (RUN, "not-a-sha"), (RUN, "")):
        with pytest.raises(reconcile.ReconcileError):
            reconcile._host(run, None, source_sha=source)
    with pytest.raises(reconcile.ReconcileError, match="V3_SOURCE_ID"):
        reconcile._host(RUN, PREPARE, source_sha=TARGET_SHA)
