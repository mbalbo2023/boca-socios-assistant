"""R259 READ_ONLY mapping preflight: physical Boca evidence, never deploy GO."""

from __future__ import annotations

import io
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest

from boca_socios import host_boca_cleanup as cleanup
from boca_socios import host_boca_rootless_mapped_custody as custody
from boca_socios import host_boca_rootless_mapping_cli as bridge
from test_host_boca_binding_observe import _installed
from test_host_boca_pair_upgrade_plan import CONTROLLER_ID, RUN, _receipt
from test_host_boca_rootless_mapped_custody import _volume


def _stage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, list[str]]:
    """Keep real pair/binding and real inode validators, stub only host IO."""
    root, _ = _volume(tmp_path)
    events: list[str] = []
    lease = cleanup.BocaJobLease(RUN, -1, os.getpid(), True)

    @contextmanager
    def held(run_id: str) -> Iterator[cleanup.BocaJobLease]:
        assert run_id == RUN
        events.append("acquire")
        yield lease
        events.append("release")

    monkeypatch.setattr(bridge, "_readonly_lease", held)
    monkeypatch.setattr(bridge.cleanup, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(bridge.cleanup, "EXPECTED_GID", os.getegid())

    def verify(found: cleanup.BocaJobLease, attempt: str) -> None:
        assert found is lease and attempt == RUN
        events.append("lease")

    def pair(_run: str) -> bytes:
        assert _run == RUN
        events.append("pair")
        return _receipt()

    def binding(found: cleanup.BocaJobLease) -> object:
        assert found is lease
        events.append("binding")
        return _installed()

    def docker(*args: str) -> str:
        assert args == ("inspect", "--format", "{{json .State.Pid}}", CONTROLLER_ID)
        events.append("pid")
        return "1133025\n"

    def volume() -> None:
        events.append("volume")

    def mapped_owner(cid: str) -> custody.MappedOwner:
        if cid != CONTROLLER_ID:
            pytest.fail("foreign CID must not be opened")
        events.append("kernel_identity")
        return custody.MappedOwner(os.geteuid(), os.getegid())

    monkeypatch.setattr(bridge.cleanup, "verify_protected_boca_job_lease", verify)
    monkeypatch.setattr(bridge.pair, "observe", pair)
    monkeypatch.setattr(bridge.service, "read_installed_binding", binding)
    monkeypatch.setattr(bridge.cleanup, "_docker", docker)
    monkeypatch.setattr(bridge.host, "_checked_docker_storage_dir", lambda: root)
    monkeypatch.setattr(bridge.host, "_validate_data_volume", volume)
    monkeypatch.setattr(bridge.host, "_validate_key_volume", volume)
    monkeypatch.setattr(bridge.host, "_validate_owner_volume", volume)
    monkeypatch.setattr(bridge.custody, "_DOCKER_ROOT", root)
    monkeypatch.setattr(bridge.custody, "read_container_mapped_owner", mapped_owner)
    return root, events


def test_predeploy_genuine_pair_binding_pid_three_private_inodes_and_same_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _root, events = _stage(monkeypatch, tmp_path)
    raw = bridge.observe_predeploy(RUN)
    assert bridge.verify(raw, RUN) == raw
    assert json.loads(raw.removeprefix(b"BOCA_ROOTLESS_MAPPING ")) == {
        "schema": 1,
        "attempt_id": RUN,
        "stage": "PREDEPLOY",
        "state": "PRELIMINARY_PREDEPLOY",
        "observer_writes": 0,
        "foreign_resources_touched": 0,
        "cutover_authorized": False,
        "lease_verified": True,
    }
    assert events[0] == "acquire" and events[-1] == "release"
    assert events.count("pair") >= 2
    assert events.count("binding") >= 2
    assert events.count("pid") == 4
    assert events.count("kernel_identity") == 2
    assert events.count("volume") == 9
    assert b"10001" not in raw and b"sqlite" not in raw and b"/home" not in raw
    assert b"VERIFIED_FINAL" not in raw


def test_changed_live_pair_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stage(monkeypatch, tmp_path)
    genuine = _receipt()
    tampered = json.loads(genuine.split(b" ", 1)[1])
    tampered["services"][0]["container_id"] = "f" * 64
    changed = bridge.pair._canonical(tampered)
    iterator = iter((genuine, changed))
    monkeypatch.setattr(bridge.pair, "observe", lambda _: next(iterator))
    with pytest.raises(bridge.MappingBridgeNoGo):
        bridge.observe_predeploy(RUN)


def test_mismatched_docker_pid_never_reads_foreign_proc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stage(monkeypatch, tmp_path)
    monkeypatch.setattr(bridge.cleanup, "_docker", lambda *_: "333333\n")
    monkeypatch.setattr(
        bridge.custody,
        "read_container_mapped_owner",
        lambda _: pytest.fail("foreign CID namespace must not be opened"),
    )
    with pytest.raises(bridge.MappingBridgeNoGo):
        bridge.observe_predeploy(RUN)


def test_missing_volume_attestation_never_becomes_preliminary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stage(monkeypatch, tmp_path)
    monkeypatch.setattr(
        bridge.host, "_validate_owner_volume", lambda: (_ for _ in ()).throw(ValueError("private"))
    )
    with pytest.raises(bridge.MappingBridgeNoGo) as exc:
        bridge.observe_predeploy(RUN)
    assert "private" not in str(exc.value)


def test_changed_mapped_subuid_between_reads_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stage(monkeypatch, tmp_path)
    first = custody.MappedOwner(os.geteuid(), os.getegid())
    iterator = iter((first, replace(first, uid=first.uid + 1)))
    monkeypatch.setattr(bridge.custody, "read_container_mapped_owner", lambda _: next(iterator))
    with pytest.raises(bridge.MappingBridgeNoGo):
        bridge.observe_predeploy(RUN)


def test_changed_pidfd_or_user_namespace_fails_closed_before_preliminary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _root, events = _stage(monkeypatch, tmp_path)

    def denied(cid: str) -> custody.MappedOwner:
        assert cid == CONTROLLER_ID
        events.append("kernel_denied")
        raise custody.MappedCustodyNoGo("private namespace drift")

    monkeypatch.setattr(bridge.custody, "read_container_mapped_owner", denied)
    with pytest.raises(bridge.MappingBridgeNoGo) as exc:
        bridge.observe_predeploy(RUN)
    assert "namespace drift" not in str(exc.value)
    assert events.count("kernel_denied") == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"state": "VERIFIED_MAPPED"},
        {"state": "PRELIMINARY_PREDEPLOY", "lease_verified": False},
        {"stage": "POSTFLIGHT"},
        {"observer_writes": 1},
        {"foreign_resources_touched": 1},
        {"cutover_authorized": True},
        {"lease_verified": 1},
        {"attempt_id": "1234"},
        {"debug": "private"},
    ],
)
def test_verifier_rejects_inflation_or_wrong_attempt(changes: dict[str, object]) -> None:
    payload: dict[str, object] = {
        "schema": 1,
        "attempt_id": RUN,
        "stage": "PREDEPLOY",
        "state": "PRELIMINARY_PREDEPLOY",
        "observer_writes": 0,
        "foreign_resources_touched": 0,
        "cutover_authorized": False,
        "lease_verified": True,
    }
    payload.update(changes)
    raw = (
        b"BOCA_ROOTLESS_MAPPING "
        + json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )
    with pytest.raises(bridge.MappingBridgeNoGo):
        bridge.verify(raw, RUN)


def test_runner_verifier_refuses_duplicate_fields_noncanonical_or_surplus() -> None:
    valid = bridge.encode(RUN, "PRELIMINARY_PREDEPLOY", lease_verified=True)
    for raw in (
        valid.replace(b'"schema":1', b'"schema":1,"schema":1'),
        valid.replace(b'"schema":1', b'"schema" : 1'),
        valid + b"sensitive-data",
        valid.rstrip(b"\n"),
        valid + b" " * 1000,
    ):
        with pytest.raises(bridge.MappingBridgeNoGo):
            bridge.verify(raw, RUN)


def test_receipt_encoder_does_not_treat_integer_as_verified_boolean() -> None:
    with pytest.raises(bridge.MappingBridgeNoGo):
        bridge.encode(RUN, "PRELIMINARY_PREDEPLOY", lease_verified=1)  # type: ignore[arg-type]


def test_changed_systemd_archive_binding_fails_before_probing_private_inodes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stage(monkeypatch, tmp_path)
    monkeypatch.setattr(
        bridge.service,
        "read_installed_binding",
        lambda _: replace(_installed(), worker_id="e" * 64),
    )
    monkeypatch.setattr(
        bridge.custody,
        "capture_mapped_custody",
        lambda *_args, **_kwargs: pytest.fail("no file read without authentic binding"),
    )
    with pytest.raises(bridge.MappingBridgeNoGo):
        bridge.observe_predeploy(RUN)


def test_readonly_lease_requires_preexisting_file_never_creates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    folder = tmp_path / "only-boca"
    folder.mkdir(mode=0o700)
    monkeypatch.setattr(bridge.cleanup, "LEASE_DIR", folder)
    monkeypatch.setattr(bridge.cleanup, "EXPECTED_UID", os.geteuid())
    monkeypatch.setattr(bridge.cleanup, "EXPECTED_GID", os.getegid())
    lock = folder / cleanup.LEASE_FILE
    with pytest.raises(bridge.MappingBridgeNoGo):
        with bridge._readonly_lease(RUN):
            pytest.fail("no lease file means no observer")
    assert not lock.exists()

    lock.touch(mode=0o600)
    lock.chmod(0o600)
    with bridge._readonly_lease(RUN) as held:
        cleanup.verify_protected_boca_job_lease(held, RUN)
        assert held.active is True
    assert held.active is False
    assert lock.stat().st_size == 0


def test_cli_observe_redacts_failure_and_verify_copies_only_canonical_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stage(monkeypatch, tmp_path)
    success = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", type("Sink", (), {"buffer": success})())
    assert bridge.main(["observe", RUN]) == 0
    assert bridge.verify(success.getvalue(), RUN) == success.getvalue()

    verify_stdout = io.BytesIO()
    monkeypatch.setattr(
        sys, "stdin", type("Input", (), {"buffer": io.BytesIO(success.getvalue())})()
    )
    monkeypatch.setattr(sys, "stdout", type("Sink", (), {"buffer": verify_stdout})())
    assert bridge.main(["verify", RUN]) == 0
    assert verify_stdout.getvalue() == success.getvalue()

    monkeypatch.setattr(
        bridge.host, "_validate_key_volume", lambda: (_ for _ in ()).throw(ValueError("secret"))
    )
    failed = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", type("Sink", (), {"buffer": failed})())
    assert bridge.main(["observe", RUN]) == 3
    no_go = bridge.verify(failed.getvalue(), RUN)
    assert b'"state":"NO_GO"' in no_go
    assert b'"lease_verified":false' in no_go
    assert b"secret" not in no_go


def test_failed_boundary_is_fixed_and_does_not_publish_private_host_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stage(monkeypatch, tmp_path)
    monkeypatch.setattr(
        bridge.host,
        "_validate_key_volume",
        lambda: (_ for _ in ()).throw(OSError("private/key/path:175536")),
    )
    sink = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", type("Sink", (), {"buffer": sink})())
    assert bridge.main(["observe", RUN]) == 3
    receipt = bridge.verify(sink.getvalue(), RUN)
    payload = json.loads(receipt.split(b" ", 1)[1])
    assert payload["failed_boundary"] == "VOLUMES"
    assert payload["schema"] == 2
    assert b"private" not in receipt and b"175536" not in receipt


def test_missing_host_lease_diagnoses_lease_without_private_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stage(monkeypatch, tmp_path)

    @contextmanager
    def missing(_run: str) -> Iterator[cleanup.BocaJobLease]:
        raise OSError("private runtime path")
        yield cleanup.BocaJobLease(_run, -1, os.getpid(), False)  # pragma: no cover

    monkeypatch.setattr(bridge, "_readonly_lease", missing)
    sink = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", type("Sink", (), {"buffer": sink})())
    assert bridge.main(["observe", RUN]) == 3
    receipt = bridge.verify(sink.getvalue(), RUN)
    assert json.loads(receipt.split(b" ", 1)[1])["failed_boundary"] == "LEASE"
    assert b"private" not in receipt


def test_verify_cli_forwards_only_valid_refusal_and_rejects_malformed_without_recoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = bridge.encode(RUN, "NO_GO", lease_verified=False, failed_boundary="PID_MAP")
    for candidate, expected_rc, expected_stdout in (
        (valid, 3, valid),
        (valid + b"secret", 4, b""),
        (b"untrusted raw details\n", 4, b""),
    ):
        sink = io.BytesIO()
        monkeypatch.setattr(sys, "stdin", type("Input", (), {"buffer": io.BytesIO(candidate)})())
        monkeypatch.setattr(sys, "stdout", type("Sink", (), {"buffer": sink})())
        assert bridge.main(["verify", RUN]) == expected_rc
        assert sink.getvalue() == expected_stdout


def test_rejects_schema_downgrade_of_diagnostic_refusal() -> None:
    valid = bridge.encode(RUN, "NO_GO", lease_verified=False, failed_boundary="PID_MAP")
    assert b'"schema":2' in valid
    with pytest.raises(bridge.MappingBridgeNoGo):
        bridge.verify(valid.replace(b'"schema":2', b'"schema":1'), RUN)


@pytest.mark.parametrize("boundary", ["/private/path", "KEY_10001", "UNVERIFIED"])
def test_failure_boundary_rejects_unspecified_private_or_unknown_categories(boundary: str) -> None:
    with pytest.raises(bridge.MappingBridgeNoGo):
        bridge.encode(RUN, "NO_GO", lease_verified=False, failed_boundary=boundary)
