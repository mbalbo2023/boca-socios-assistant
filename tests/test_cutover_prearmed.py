"""Rootless pre-start identity, observation and cleanup with injected Docker I/O."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from boca_socios import host_first_deploy as host
from test_host_cutover_adapter import (
    ATTEMPT,
    CONFIG_HASH,
    LEGACY_IMAGE,
    LEGACY_SHA,
    ORIGINAL_ID,
    SECCOMP,
    SECCOMP_SHA,
    TARGET_SHA,
    WORKER_ID,
    WORKER_IMAGE,
    _worker_preparation_fake,
)

IMAGE_ID = "sha256:" + "d" * 64


def test_cutover_worker_confidential_create() -> None:
    argv = host._cutover_worker_create_argv(WORKER_IMAGE, TARGET_SHA, ATTEMPT, CONFIG_HASH)
    assert argv.count("--log-driver") == 1
    assert argv[argv.index("--log-driver") + 1] == "none"
    assert argv[argv.index("--health-cmd") + 1].endswith(" >/dev/null 2>&1")
    assert argv[-4:] == (WORKER_IMAGE, "python", "-m", "boca_socios.browser.ipc_server")
    assert "boca_socios.browser.ipc_worker" not in argv
    assert not {"--interactive", "--tty", "--attach"}.intersection(argv)


def capture_identity(monkeypatch):
    record = {
        "cid": WORKER_ID,
        "image_id": IMAGE_ID,
        "image_ref": WORKER_IMAGE,
        "attempt": ATTEMPT,
        "revision": TARGET_SHA,
        "service": "browser-worker",
        "project": "boca-socios",
        "config_hash": CONFIG_HASH,
        "status": "created",
        "tty": False,
        "open_stdin": False,
        "attach_stdin": False,
        "log_driver": "none",
        "log_options": 0,
        "health": True,
    }
    api = ["1.44 1.55"]
    monkeypatch.setattr(host, "_require_dedicated_identity", lambda: 10001)
    monkeypatch.setattr(host, "_rootless_socket_secure", lambda: True)

    def run(*args, **kwargs):
        if args[:2] == ("docker", "version"):
            return api[0]
        if args[:3] == ("docker", "image", "inspect") and args[-1] == WORKER_IMAGE:
            return IMAGE_ID
        assert args[:2] == ("docker", "inspect") and args[-1] == WORKER_ID
        return json.dumps(record)

    monkeypatch.setattr(host, "_run", run)
    return record, api


def validate_capture() -> None:
    host._cutover_capture_preflight(WORKER_ID, WORKER_IMAGE, TARGET_SHA, ATTEMPT, CONFIG_HASH)


def test_prearmed_identity_accepts_valid_current_rootless_worker(monkeypatch) -> None:
    capture_identity(monkeypatch)
    validate_capture()


def test_duplicate_engine_identity_fields_are_ambiguous(monkeypatch) -> None:
    record, _ = capture_identity(monkeypatch)
    docker = host._run

    def run(*args, **kwargs):
        if args[:2] == ("docker", "inspect"):
            return '{"tty":true,' + json.dumps(record)[1:]
        return docker(*args, **kwargs)

    monkeypatch.setattr(host, "_run", run)
    with pytest.raises(host.PreflightError):
        validate_capture()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cid", ORIGINAL_ID),
        ("image_id", "sha256:" + "e" * 64),
        ("image_ref", "other-image"),
        ("attempt", "11"),
        ("revision", "e" * 40),
        ("service", "controller"),
        ("project", "another-project"),
        ("config_hash", "0" * 64),
        ("status", "running"),
        ("tty", True),
        ("open_stdin", True),
        ("attach_stdin", True),
        ("attach_stdin", 0),
        ("log_driver", "json-file"),
        ("log_options", 1),
        ("log_options", False),
        ("health", False),
        ("health", 1),
    ],
)
def test_every_capture_identity_mismatch_prevents_admission(monkeypatch, field, value) -> None:
    record, _ = capture_identity(monkeypatch)
    record[field] = value
    with pytest.raises(host.PreflightError):
        validate_capture()


@pytest.mark.parametrize("api", ["1.49 1.55", "1.42 1.47", "1.44 1.48\nextra", "UNKNOWN"])
def test_outside_or_ambiguous_api_fails_closed(monkeypatch, api) -> None:
    _, version = capture_identity(monkeypatch)
    version[0] = api
    with pytest.raises(host.PreflightError):
        validate_capture()


def test_rootless_socket_drift_prevents_querying_engine(monkeypatch) -> None:
    capture_identity(monkeypatch)
    monkeypatch.setattr(host, "_rootless_socket_secure", lambda: False)
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: pytest.fail("reached Docker"))
    with pytest.raises(host.PreflightError):
        validate_capture()


def _prepare(sink):
    return host._cutover_prepare_worker(
        ORIGINAL_ID,
        LEGACY_IMAGE,
        LEGACY_SHA,
        WORKER_IMAGE,
        TARGET_SHA,
        ATTEMPT,
        CONFIG_HASH,
        SECCOMP_SHA,
        SECCOMP,
        sink,
    )


@pytest.mark.parametrize("cleanup_fails", [False, True])
@pytest.mark.parametrize("write_fails", [False, True])
def test_exact_capture_precedes_compensation_and_preserves_primary(
    monkeypatch, cleanup_fails, write_fails
) -> None:
    from boca_socios import worker_start_capture as streams

    _worker_preparation_fake(monkeypatch)
    events = []
    old_run = host._run

    def run(*args, **kwargs):
        if args[:2] == ("docker", "start"):
            events.append("start")
        return old_run(*args, **kwargs)

    def finish():
        events.append("observed")
        return streams.CaptureResult.PERMISSION_ERROR

    @contextmanager
    def attach(path, cid):
        assert path == host.ROOTLESS_SOCKET and cid == WORKER_ID
        events.append("armed")
        yield SimpleNamespace(finish=finish)
        events.append("detached")

    def health(cid):
        assert cid == WORKER_ID
        raise host.WorkerHealthPhaseError(
            "HEALTH_EXITED",
            exit_code=1,
            oom_killed=False,
            exit_signature="EMPTY.EXITED.EARLY_LT_5S.NOT_RUN",
        )

    def persist(cid, result):
        assert cid == WORKER_ID and result == "PERMISSION_ERROR"
        events.append("persist")
        if write_fails:
            raise OSError("PRIVATE-SYNTHETIC")

    def compensate(*args):
        assert args[-1] == WORKER_ID
        events.append("compensate")
        if cleanup_fails:
            raise host.PreflightError("PRIVATE-SYNTHETIC")

    monkeypatch.setattr(host, "_cutover_capture_preflight", lambda *a: events.append("verify"))
    monkeypatch.setattr(streams, "attach_output", attach)
    monkeypatch.setattr(host, "_run", run)
    monkeypatch.setattr(host, "_browser_wait_healthy", health)
    monkeypatch.setattr(host, "_cutover_compensate_worker", compensate)
    with pytest.raises(host.CutoverWorkerPhaseError) as failed:
        _prepare(persist)
    assert failed.value.primary == "HEALTH_EXITED"
    assert failed.value.compensation == ("INDETERMINATE" if cleanup_fails else "VERIFIED")
    assert failed.value.exit_code == 1 and failed.value.oom_killed is False
    assert failed.value.capture_worker_id == WORKER_ID
    assert failed.value.capture_result == "PERMISSION_ERROR"
    assert failed.value.capture_recorded is (not write_fails)
    assert events[:3] == ["verify", "armed", "start"]
    assert events.index("observed") < events.index("persist") < events.index("compensate")
    assert "PRIVATE" not in repr(failed.value.__dict__)


def test_rejected_attach_preserves_original_and_never_starts(monkeypatch) -> None:
    from boca_socios import worker_start_capture as streams

    calls, legacy, _ = _worker_preparation_fake(monkeypatch)
    monkeypatch.setattr(host, "_cutover_capture_preflight", lambda *args: None)

    def reject(*_):
        raise streams.CaptureFailure(streams.CaptureResult.TRANSPORT)

    monkeypatch.setattr(streams, "attach_output", reject)
    with pytest.raises(host.CutoverWorkerPhaseError) as failed:
        _prepare(lambda *args: pytest.fail("unstarted process cannot have an observation"))
    assert failed.value.primary == "CAPTURE_PREPARE"
    assert failed.value.capture_result is None and not failed.value.capture_recorded
    assert failed.value.compensation == "VERIFIED"
    assert not any(command[:2] == ("docker", "start") for command in calls)
    assert legacy["State"]["Running"] is True


def test_exit_without_v4_signature_has_no_capture_custody(monkeypatch) -> None:
    from boca_socios import worker_start_capture as streams

    _worker_preparation_fake(monkeypatch)

    @contextmanager
    def attach(*args):
        yield SimpleNamespace(finish=lambda: pytest.fail("missing V4 process evidence"))

    def health(cid):
        assert cid == WORKER_ID
        raise host.WorkerHealthPhaseError("HEALTH_EXITED", exit_code=1, oom_killed=False)

    monkeypatch.setattr(streams, "attach_output", attach)
    monkeypatch.setattr(host, "_browser_wait_healthy", health)
    with pytest.raises(host.CutoverWorkerPhaseError) as failure:
        _prepare(lambda *args: pytest.fail("missing V4 process evidence"))
    assert failure.value.primary == "HEALTH_EXITED" and failure.value.compensation == "VERIFIED"
    assert failure.value.exit_signature is None and failure.value.capture_result is None
    assert not failure.value.capture_recorded


def test_known_worker_cid_cannot_be_replaced_during_compensation(monkeypatch) -> None:
    monkeypatch.setattr(host, "_cutover_worker_name_id", lambda: "9" * 64)
    monkeypatch.setattr(host, "_run", lambda *args, **kwargs: pytest.fail("acted on a changed CID"))
    with pytest.raises(host.PreflightError, match="CID changed"):
        host._cutover_compensate_worker(
            WORKER_IMAGE, TARGET_SHA, ATTEMPT, SECCOMP_SHA, SECCOMP, WORKER_ID
        )


def test_healthy_worker_detaches_without_collecting_or_persisting_a_failure(monkeypatch) -> None:
    from boca_socios import worker_start_capture as streams

    calls, legacy, _ = _worker_preparation_fake(monkeypatch)
    events = []
    monkeypatch.setattr(host, "_cutover_capture_preflight", lambda *args: events.append("verified"))
    monkeypatch.setattr(host, "_browser_wait_healthy", lambda cid: events.append(("healthy", cid)))

    @contextmanager
    def attach(path, cid):
        assert path == host.ROOTLESS_SOCKET
        events.append(("armed", cid))
        try:
            yield SimpleNamespace(finish=lambda: pytest.fail("healthy worker has no exit"))
        finally:
            events.append(("closed", cid))

    monkeypatch.setattr(streams, "attach_output", attach)
    assert _prepare(lambda *args: pytest.fail("healthy worker has no failure receipt")) == WORKER_ID
    assert events == [
        "verified",
        ("armed", WORKER_ID),
        ("healthy", WORKER_ID),
        ("closed", WORKER_ID),
    ]
    assert [command for command in calls if command[:2] == ("docker", "start")] == [
        ("docker", "start", WORKER_ID)
    ]
    assert legacy["State"]["Running"] is True


def test_ambiguous_start_ack_is_never_a_process_observation(monkeypatch) -> None:
    from boca_socios import worker_start_capture as streams

    calls, legacy, _ = _worker_preparation_fake(monkeypatch)
    monkeypatch.setattr(host, "_cutover_capture_preflight", lambda *args: None)

    @contextmanager
    def attach(*args):
        yield SimpleNamespace(finish=lambda: pytest.fail("unconfirmed start"))

    docker = host._run

    def run(*args, **kwargs):
        result = docker(*args, **kwargs)
        return result + "\nwrong" if args[:2] == ("docker", "start") else result

    monkeypatch.setattr(streams, "attach_output", attach)
    monkeypatch.setattr(host, "_run", run)
    with pytest.raises(host.CutoverWorkerPhaseError) as failure:
        _prepare(lambda *args: pytest.fail("unconfirmed start"))
    assert failure.value.primary == "START" and failure.value.compensation == "VERIFIED"
    assert failure.value.capture_result is None and not failure.value.capture_recorded
    assert len([command for command in calls if command[:2] == ("docker", "start")]) == 1
    assert legacy["State"]["Running"] is True
