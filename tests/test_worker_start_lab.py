"""The prospective worker capture is exercised only against a disposable image."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "boca_capture_lab_fixture",
    ROOT / "scripts/check_worker_start_capture.py",
)
assert spec and spec.loader
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


def test_image_job_executes_capture_lab_after_build() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    image_job = workflow.split("  image:\n", 1)[1]
    command = "python3 -m scripts.check_worker_start_capture"
    assert command in image_job
    assert image_job.index("docker build --file Dockerfile.browser") < image_job.index(command)
    assert "runs-on: ubuntu-24.04" in image_job[: image_job.index(command)]
    assert command not in (ROOT / ".github/workflows/boca-first-deploy.yml").read_text()


def test_local_or_self_hosted_runner_refuses_before_docker(monkeypatch) -> None:
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "self-hosted")
    monkeypatch.setattr(lab, "docker", lambda *args: pytest.fail("Docker must stay untouched"))
    with pytest.raises(lab.LabError, match="RUNNER_SCOPE"):
        lab.main()


def test_prestart_contract_failure_keeps_primary_when_cleanup_fails(monkeypatch, capsys) -> None:
    cid, image = "a" * 64, "sha256:" + "b" * 64
    monkeypatch.setattr(lab, "create_fixture", lambda *args: cid)
    monkeypatch.setattr(lab, "field", lambda *args: "wrong-cid")
    monkeypatch.setattr(lab, "attach_output", lambda *args: pytest.fail("cannot attach"))
    monkeypatch.setattr(lab, "start_fixture", lambda *args: pytest.fail("cannot start"))
    removed = []

    def fail_removal(actual_cid, key, actual_image):
        removed.append((actual_cid, key, actual_image))
        raise lab.LabError("CLEANUP_IDENTITY")

    monkeypatch.setattr(lab, "remove_fixture", fail_removal)
    with pytest.raises(lab.LabError, match="PRESTART_CONTRACT"):
        lab.exercise(image, "123", "silent", "raise SystemExit(1)", "EMPTY", 1)
    assert removed == [(cid, "123-silent", image)]
    assert "cleanup=INDETERMINATE" in capsys.readouterr().out


def test_rejected_attachment_prevents_start_and_confirms_cleanup(monkeypatch, capsys) -> None:
    cid, image = "a" * 64, "sha256:" + "b" * 64
    monkeypatch.setattr(lab, "create_fixture", lambda *args: cid)
    monkeypatch.setattr(lab, "verify_fixture", lambda *args: None)
    monkeypatch.setattr(lab, "start_fixture", lambda *args: pytest.fail("not armed"))
    cleaned = []

    def rejected(*args):
        raise lab.CaptureFailure(lab.CaptureResult.TRANSPORT)

    monkeypatch.setattr(lab, "attach_output", rejected)
    monkeypatch.setattr(lab, "remove_fixture", lambda *args: cleaned.append(args))
    with pytest.raises(lab.CaptureFailure):
        lab.exercise(image, "123", "silent", "raise SystemExit(1)", "EMPTY", 1)
    assert cleaned == [(cid, "123-silent", image)]
    assert "cleanup=VERIFIED" in capsys.readouterr().out


def test_valid_observation_is_published_before_failed_removal(monkeypatch, capsys) -> None:
    from contextlib import nullcontext
    from types import SimpleNamespace

    cid, image = "a" * 64, "sha256:" + "b" * 64
    monkeypatch.setattr(lab, "create_fixture", lambda *args: cid)
    monkeypatch.setattr(lab, "verify_fixture", lambda *args: None)
    collector = SimpleNamespace(finish=lambda: lab.CaptureResult.PERMISSION_ERROR)
    monkeypatch.setattr(lab, "attach_output", lambda *args: nullcontext(collector))
    monkeypatch.setattr(lab, "start_fixture", lambda asserted_cid: None)
    monkeypatch.setattr(lab, "docker", lambda *args: "1")
    monkeypatch.setattr(lab, "field", lambda cid, path: 1 if path == ".State.ExitCode" else False)

    def removal(*args):
        assert "observed=PERMISSION_ERROR state=EXIT_1" in capsys.readouterr().out
        raise lab.LabError("CLEANUP_VERIFY")

    monkeypatch.setattr(lab, "remove_fixture", removal)
    with pytest.raises(lab.LabError, match="CLEANUP_INDETERMINATE"):
        lab.exercise(image, "123", "denied", "fixture", "PERMISSION_ERROR", 1)


@pytest.mark.parametrize("result", ["", "a" * 64, "a" * 64 + "\n" + "b" * 64])
def test_lost_create_ack_reconciles_only_one_matching_cid(monkeypatch, result, capsys) -> None:
    def lost(*args):
        raise lab.LabError("DOCKER_TIMEOUT")

    ids = []
    lookups = []
    monkeypatch.setattr(lab, "create_fixture", lost)
    monkeypatch.setattr(lab, "start_fixture", lambda *args: pytest.fail("no create ACK"))

    def inventory(*args):
        lookups.append(args)
        return result

    monkeypatch.setattr(lab, "docker", inventory)
    monkeypatch.setattr(lab, "remove_fixture", lambda cid, *args: ids.append(cid))
    with pytest.raises(lab.LabError, match="DOCKER_TIMEOUT"):
        lab.exercise("sha256:" + "b" * 64, "123", "silent", "fixture", "EMPTY", 1)
    assert lookups == [
        ("ps", "-aq", "--no-trunc", "--filter", "label=boca.socios.ci-capture=123-silent")
    ]
    assert ids == (["a" * 64] if result == "a" * 64 else [])
    receipt = capsys.readouterr().out
    if not result:
        assert "cleanup=ABSENT_AT_INVENTORY" in receipt
    else:
        assert ("cleanup=VERIFIED" if ids else "cleanup=INDETERMINATE") in receipt


def test_resident_requires_active_detach_before_observing_fresh_health(monkeypatch) -> None:
    from contextlib import nullcontext
    from types import SimpleNamespace

    cid, image = "a" * 64, "sha256:" + "b" * 64
    cleaned = []
    monkeypatch.setattr(lab, "create_fixture", lambda *args: cid)
    monkeypatch.setattr(lab, "verify_fixture", lambda *args: None)
    monkeypatch.setattr(
        lab, "attach_output", lambda *args: nullcontext(SimpleNamespace(close=lambda: False))
    )
    monkeypatch.setattr(lab, "start_fixture", lambda asserted: None)
    monkeypatch.setattr(lab, "wait_healthy", lambda asserted: None)
    monkeypatch.setattr(
        lab, "verify_detached_progress", lambda *args: pytest.fail("inactive detach")
    )
    monkeypatch.setattr(lab, "remove_fixture", lambda *args: cleaned.append(args))
    with pytest.raises(lab.LabError, match="DETACH_INACTIVE"):
        lab.exercise(image, "123", "resident", lab.RESIDENT, "DETACHED_HEALTHY", 0)
    assert cleaned == [(cid, "123-resident", image)]


@pytest.mark.parametrize(
    "stamps, succeeds",
    [([2, 2, 3, 3, 4], True), ([2, 2, 2, 2, 2], False), ([2, 3, 2, 3, 2], False)],
)
def test_resident_requires_two_distinct_later_successful_probes(
    monkeypatch, stamps, succeeds
) -> None:
    from itertools import chain, count, repeat

    expected_cid = "a" * 64
    samples = chain(stamps, repeat(stamps[-1]))
    ticks = count()
    monkeypatch.setattr(lab, "last_successful_probe", lambda cid: next(samples))
    monkeypatch.setattr(lab, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(lab, "sleep", lambda value: None)
    monkeypatch.setattr(
        lab, "field", lambda cid, path: True if path == ".State.Running" else "healthy"
    )
    if succeeds:
        lab.verify_detached_progress(expected_cid)
    else:
        with pytest.raises(lab.LabError, match="DETACH_CHANGED_PROCESS"):
            lab.verify_detached_progress(expected_cid)


@pytest.mark.parametrize("tty,valid", [(False, True), (0, False)])
def test_protected_projection_requires_exact_boolean_types(monkeypatch, tty, valid) -> None:
    import json

    from boca_socios.host_first_deploy import _CUTOVER_CAPTURE_INSPECT

    cid, image = "a" * 64, "sha256:" + "b" * 64
    observed = []

    def metadata(*args):
        observed.append(args)
        return json.dumps(
            {
                "cid": cid,
                "image_id": image,
                "image_ref": image,
                "attempt": "fixture-attempt",
                "revision": "fixture-revision",
                "service": "fixture-service",
                "project": "fixture-project",
                "config_hash": "fixture-hash",
                "status": "created",
                "tty": tty,
                "open_stdin": False,
                "attach_stdin": False,
                "log_driver": "none",
                "log_options": 0,
                "health": False,
            }
        )

    monkeypatch.setattr(lab, "docker", metadata)
    if valid:
        lab.verify_capture_projection(cid, image)
    else:
        with pytest.raises(lab.LabError, match="CAPTURE_PROJECTION"):
            lab.verify_capture_projection(cid, image)
    assert observed == [("inspect", "--format", _CUTOVER_CAPTURE_INSPECT, cid)]


def test_progress_uses_timestamp_of_last_successful_healthcheck(monkeypatch) -> None:
    from datetime import datetime

    cid = "a" * 64
    inspected = []

    def metadata(*args):
        inspected.append(args)
        return (
            '"2026-11-10T01:02:03.012345678Z" 1\n'
            '"2026-11-10T01:02:05.012345678Z" 0\n'
            '"2026-11-10T01:02:07.012345678Z" 1\n'
        )

    monkeypatch.setattr(lab, "docker", metadata)
    assert lab.last_successful_probe(cid) == datetime.fromisoformat("2026-11-10T01:02:05.012345Z")
    assert len(inspected) == 1
    assert ".Output" not in inspected[0][2]
