"""G3b V3: only installed-controller public recipient metadata may be observed."""

import copy
import importlib
import io
import json
import os
import stat
import subprocess
from contextlib import redirect_stdout
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from boca_socios import host_boca_public_recipient_metadata as metadata
from boca_socios.host_lifecycle_rootless_adapter import ReviewedInstalledPair
from boca_socios.host_on_demand_lifecycle import OnDemandInstallation
from test_host_boca_pair_upgrade_plan import _receipt as _historical_pair_receipt


def test_v3_observer_exports_exact_separate_operation() -> None:
    # This must fail while the dedicated W-source observer is absent.
    observer = importlib.import_module("boca_socios.host_boca_public_recipient_metadata")
    assert observer.OPERATION == "boca-public-recipient-metadata-observe"
    assert observer.PREFIX == b"BOCA_PUBLIC_RECIPIENT_METADATA_V3 "


def _valid_sample(
    *, mode: str = "0755", leaf: str = "METADATA_VALID_PARSE_UNVERIFIED"
) -> dict[str, Any]:
    return {
        "parent": "METADATA_VALID",
        "recipient": leaf,
        "parent_mode": mode,
        "parent_witness": "a" * 64,
        "recipient_witness": "b" * 64 if leaf == "METADATA_VALID_PARSE_UNVERIFIED" else "NONE",
    }


def _sample_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def test_valid_parent_cannot_claim_unattempted_leaf_and_complete_receipt() -> None:
    invalid = _valid_sample(leaf="NOT_ATTEMPTED")
    with pytest.raises(metadata.NoGo):
        metadata._sample(_sample_bytes(invalid))
    frame = _complete_frame()
    frame["samples"] = [invalid, invalid]
    frame["recipient"] = "NOT_ATTEMPTED"
    with pytest.raises(metadata.NoGo):
        metadata.verify(
            metadata._canonical(frame), run_id="43814281299", workflow_sha=metadata.SOURCE
        )


def test_exact_w_installed_guard_uses_oci_ref_not_docker_image_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Start with the historical *valid* pair schema fixture and remap exact
    # reviewed W/APPLY coordinates. Pair.verify and binding._attest are REAL.
    snapshot = json.loads(_historical_pair_receipt()[len(metadata.pair._PREFIX) :])
    controller_ref = f"ghcr.io/mbalbo2023/boca-socios-assistant@{metadata.CONTROLLER_OCI}"
    worker_ref = f"ghcr.io/mbalbo2023/boca-socios-assistant-browser@{metadata.WORKER_OCI}"
    snapshot.update(
        source_sha=metadata.SOURCE, attempt_id=metadata.APPLY, observation_run_id="43814281299"
    )
    controller, worker = snapshot["services"]
    controller.update(container_id=metadata.CONTROLLER, image_ref=controller_ref)
    worker.update(
        container_id=metadata.WORKER,
        image_ref=worker_ref,
        network_name="boca-socios_boca_browser_egress",
        network_id="d" * 64,
    )
    site = "boca-socios_boca_site_config"
    snapshot["volumes"] = sorted([*snapshot["volumes"], site])
    for service in (controller, worker):
        service["volumes"] = sorted([*service["volumes"], site])
    item = OnDemandInstallation(
        installation_run_id=metadata.APPLY,
        source_sha=metadata.SOURCE,
        controller_id=metadata.CONTROLLER,
        controller_image=controller_ref,
        worker_id=metadata.WORKER,
        worker_image=worker_ref,
        database_path=metadata.binding.CANONICAL_DATABASE,
        pair=ReviewedInstalledPair(
            metadata.APPLY, controller["config_hash"], worker["config_hash"]
        ),
    )
    holder = {"raw": metadata.pair._canonical(snapshot), "item": item}
    assert metadata.pair.verify(holder["raw"], "43814281299") == holder["raw"]
    assert controller["image_id"] != metadata.CONTROLLER_OCI
    assert worker["image_id"] != metadata.WORKER_OCI
    monkeypatch.setattr(metadata.pair, "observe", lambda run: holder["raw"])
    monkeypatch.setattr(metadata.binding, "_read_host_binding", lambda: holder["item"])
    witness = metadata._guard("43814281299")
    assert witness["fingerprint"] == item.fingerprint()
    assert witness["controller_oci"] == metadata.CONTROLLER_OCI
    assert witness["worker_oci"] == metadata.WORKER_OCI
    for kind in (
        "source",
        "controller_cid",
        "worker_cid",
        "controller_oci",
        "worker_oci",
        "worker_running",
        "sender",
    ):
        changed = copy.deepcopy(snapshot)
        holder["item"] = item
        if kind == "source":
            changed["source_sha"] = "f" * 40
        elif kind == "controller_cid":
            changed["services"][0]["container_id"] = "e" * 64
        elif kind == "worker_cid":
            changed["services"][1]["container_id"] = "f" * 64
        elif kind == "controller_oci":
            changed["services"][0]["image_ref"] = controller_ref[:-64] + "e" * 64
        elif kind == "worker_oci":
            changed["services"][1]["image_ref"] = worker_ref[:-64] + "f" * 64
        elif kind == "worker_running":
            changed["services"][1].update(status="running", running=True, pid=54321)
        else:
            holder["item"] = replace(
                item,
                pair=replace(
                    item.pair,
                    sender_id="d" * 64,
                    sender_config_hash="e" * 64,
                    sender_attempt_id=metadata.APPLY,
                    sender_running=True,
                ),
            )
        holder["raw"] = metadata.pair._canonical(changed)
        # The hostile snapshot may be structurally valid and still MUST fail
        # the installed binding/pin guard; sender is solely in stored binding.
        if kind != "sender":
            assert metadata.pair.verify(holder["raw"], "43814281299") == holder["raw"]
        with pytest.raises((metadata.NoGo, metadata.binding.BindingNoGo)):
            metadata._guard("43814281299")


def _complete_frame() -> dict[str, Any]:
    frame = metadata._frame("43814281299", metadata.SOURCE)
    frame.update(
        state="OBSERVED_NO_GO",
        phase="COMPLETE",
        reason="NONE",
        guards={"before": "VERIFIED", "after": "VERIFIED"},
        samples=[_valid_sample(), _valid_sample()],
        binding={
            "installed_source_sha": metadata.SOURCE,
            "apply_run_id": metadata.APPLY,
            "controller_id": metadata.CONTROLLER,
            "worker_id": metadata.WORKER,
            "controller_oci": metadata.CONTROLLER_OCI,
            "worker_oci": metadata.WORKER_OCI,
            "fingerprint": "c" * 64,
        },
        parent="METADATA_VALID",
        recipient="METADATA_VALID_PARSE_UNVERIFIED",
        engine="UNVERIFIED",
        sender="ABSENT",
        exec_attempts=2,
        exec_started=2,
        exec_retired=2,
    )
    return frame


def test_canonical_v3_receipt_and_closed_negative_type_matrix() -> None:
    sample = _complete_frame()
    raw = metadata._canonical(sample)
    assert len(raw) <= 4096
    assert metadata.verify(raw, run_id="43814281299", workflow_sha=metadata.SOURCE) == sample
    mutations: tuple[tuple[str, object], ...] = (
        ("version", True),
        ("version", 2),
        ("state", "READY"),
        ("reason", "EXEC_UNVERIFIED"),
        ("phase", "METADATA_B"),
        ("operation", "boca-binding-observe"),
        ("observation_run_id", 43814281299),
        ("workflow_source_sha", metadata.SOURCE[:-1] + "f"),
        ("exec_attempts", True),
        ("exec_started", False),
        ("exec_retired", 1),
        ("application_data_writes", True),
        ("prepare_authorized", True),
        ("adopt_authorized", 1),
        ("repair_authorized", 0),
        ("admin", "INSPECTED"),
        ("custody", "INSPECTED"),
        ("stage", "INSPECTED"),
        ("document_parse", "PARSED"),
        ("recommendation", "RETRY"),
        ("engine", "STARTED"),
        ("sender", "PRESENT"),
        ("parent", "INVALID"),
        ("recipient", "ABSENT"),
    )
    for key, mutation in mutations:
        tampered = dict(sample, **{key: mutation})
        with pytest.raises(metadata.NoGo):
            metadata.verify(
                metadata._canonical(tampered), run_id="43814281299", workflow_sha=metadata.SOURCE
            )
    with pytest.raises(metadata.NoGo):
        metadata.verify(raw + b" " * 4096, run_id="43814281299", workflow_sha=metadata.SOURCE)
    with pytest.raises(metadata.NoGo):
        metadata.verify(
            raw.replace(b'"version":3', b'"version":3,"version":3'),
            run_id="43814281299",
            workflow_sha=metadata.SOURCE,
        )
    for key in sample:
        tampered = dict(sample)
        del tampered[key]
        with pytest.raises((metadata.NoGo, KeyError)):
            metadata.verify(
                metadata._canonical(tampered), run_id="43814281299", workflow_sha=metadata.SOURCE
            )


def test_incomplete_receipt_cannot_claim_guards_or_execution_without_evidence() -> None:
    base = metadata._frame("43814281299", metadata.SOURCE)
    assert (
        metadata.verify(
            metadata._canonical(base),
            run_id="43814281299",
            workflow_sha=metadata.SOURCE,
            allow_failure=True,
        )
        == base
    )
    distortions: tuple[tuple[str, object], ...] = (
        ("binding", _complete_frame()["binding"]),
        ("engine", "STOPPED"),
        ("sender", "ABSENT"),
        ("guards", {"before": "NOT_ATTEMPTED", "after": "VERIFIED"}),
        ("exec_attempts", 1),
        ("samples", [_valid_sample()]),
        ("parent", "METADATA_VALID"),
        ("recipient", "METADATA_VALID_PARSE_UNVERIFIED"),
    )
    for key, value in distortions:
        tampered = dict(base, **{key: value})
        with pytest.raises(metadata.NoGo):
            metadata.verify(
                metadata._canonical(tampered),
                run_id="43814281299",
                workflow_sha=metadata.SOURCE,
                allow_failure=True,
            )


@pytest.mark.parametrize(
    "kind",
    [
        "valid",
        "valid_0700",
        "leaf_min_1",
        "leaf_max_1024",
        "uid_mismatch",
        "parent_absent",
        "parent_reappears",
        "parent_mode_750",
        "parent_mode_777",
        "parent_owner",
        "parent_symlink",
        "leaf_symlink",
        "leaf_owner",
        "leaf_mode_600",
        "leaf_nlink_2",
        "leaf_zero",
        "leaf_1025",
        "leaf_drift",
        "leaf_drift_invalid",
        "leaf_absent",
        "leaf_reappears",
        "leaf_disappears",
        "parent_drift",
        "parent_drift_invalid",
    ],
)
def test_fixed_container_program_stat_only_no_open_leaf(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Execute the literal controller program with an os/stat adapter; no Docker
    # or /data host access. This validates the executable branches themselves.
    import builtins

    def state(
        mode: int, *, uid: int = 10001, nlink: int = 1, size: int = 42, ino: int = 9
    ) -> SimpleNamespace:
        return SimpleNamespace(
            st_dev=1,
            st_ino=ino,
            st_mode=mode,
            st_uid=uid,
            st_gid=10001,
            st_nlink=nlink,
            st_size=size,
            st_mtime_ns=11,
            st_ctime_ns=12,
        )

    dir_mode = stat.S_IFDIR | (
        0o750
        if kind in ("parent_mode_750", "parent_drift_invalid")
        else 0o777
        if kind == "parent_mode_777"
        else 0o700
        if kind == "valid_0700"
        else 0o755
    )
    if kind == "parent_symlink":
        dir_mode = stat.S_IFLNK | 0o777
    directory = state(dir_mode, uid=1 if kind == "parent_owner" else 10001)
    leaf_mode = (
        stat.S_IFLNK | 0o777
        if kind == "leaf_symlink"
        else stat.S_IFREG | (0o600 if kind in ("leaf_mode_600", "leaf_drift_invalid") else 0o400)
    )
    leaf = state(
        leaf_mode,
        uid=1 if kind == "leaf_owner" else 10001,
        nlink=2 if kind == "leaf_nlink_2" else 1,
        size=0
        if kind == "leaf_zero"
        else 1025
        if kind == "leaf_1025"
        else 1
        if kind == "leaf_min_1"
        else 1024
        if kind == "leaf_max_1024"
        else 42,
    )
    seen: list[tuple[str, str]] = []
    counters = {"parent": 0, "leaf": 0}

    def opened(path: str, flags: int, *, dir_fd: int | None = None) -> int:
        assert path in ("/", "data"), "recipient/admin leaf must never be opened"
        assert flags & os.O_NOFOLLOW and flags & os.O_DIRECTORY and flags & os.O_CLOEXEC
        seen.append(("open", path))
        return 11 if path == "/" else 12

    def statted(
        path: str, *, dir_fd: int | None = None, follow_symlinks: bool = True
    ) -> SimpleNamespace:
        assert follow_symlinks is False and dir_fd in (11, 12)
        seen.append(("stat", path))
        if path == "data":
            counters["parent"] += 1
            if kind in ("parent_absent", "parent_reappears") and (
                kind == "parent_absent" or counters["parent"] == 1
            ):
                raise FileNotFoundError
            if kind in ("parent_drift", "parent_drift_invalid") and counters["parent"] > 1:
                return state(directory.st_mode, ino=77)
            return directory
        assert path == "telegram_recipient_public_v2.json" and dir_fd == 12
        counters["leaf"] += 1
        if kind in ("leaf_absent", "leaf_reappears") and (
            kind == "leaf_absent" or counters["leaf"] == 1
        ):
            raise FileNotFoundError
        if kind in ("leaf_drift", "leaf_drift_invalid") and counters["leaf"] > 1:
            return state(leaf.st_mode, ino=99)
        if kind == "leaf_disappears" and counters["leaf"] > 1:
            raise FileNotFoundError
        return leaf

    fake_os = SimpleNamespace(
        O_RDONLY=os.O_RDONLY,
        O_DIRECTORY=os.O_DIRECTORY,
        O_NOFOLLOW=os.O_NOFOLLOW,
        O_CLOEXEC=os.O_CLOEXEC,
        O_XDEV=getattr(os, "O_XDEV", 0),
        X_OK=os.X_OK,
        getuid=lambda: 1000 if kind == "uid_mismatch" else 10001,
        geteuid=lambda: 10001,
        getgid=lambda: 10001,
        getegid=lambda: 10001,
        open=opened,
        stat=statted,
        fstat=lambda fd: directory,
        close=lambda fd: None,
        access=lambda *args, **kwargs: True,
    )
    original_import = builtins.__import__

    def imported(name: str, *args: Any, **kwargs: Any) -> Any:
        return fake_os if name == "os" else original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", imported)
    stream = io.StringIO()
    try:
        with redirect_stdout(stream):
            try:
                exec(  # noqa: S102 - fixed reviewed literal, synthetic os.stat only
                    metadata.METADATA_PROGRAM, {"__name__": "__metadata_probe__"}
                )
            except SystemExit as termination:
                assert termination.code == 0
    finally:
        monkeypatch.setattr(builtins, "__import__", original_import)
    value = metadata._sample(stream.getvalue().encode())
    if kind in ("valid", "valid_0700", "leaf_min_1", "leaf_max_1024"):
        assert (value["parent"], value["recipient"]) == (
            "METADATA_VALID",
            "METADATA_VALID_PARSE_UNVERIFIED",
        )
    elif kind == "uid_mismatch":
        assert (value["parent"], value["recipient"]) == ("NOT_READ", "NOT_ATTEMPTED")
        assert not seen
    elif kind in ("parent_absent", "parent_reappears"):
        assert value["parent"] == ("ABSENT" if kind == "parent_absent" else "CHANGED")
        assert counters["parent"] == 2
        assert ("open", "data") not in seen
    elif kind.startswith("parent_mode") or kind in ("parent_owner", "parent_symlink"):
        assert value["parent"] == "INVALID"
        assert len(value["parent_witness"]) == 64
        assert value["parent_mode"] == format(stat.S_IMODE(directory.st_mode), "04o")
        assert counters["parent"] == 2
        assert value["recipient"] == "NOT_ATTEMPTED"
        assert ("stat", "telegram_recipient_public_v2.json") not in seen
    elif kind in ("parent_drift", "parent_drift_invalid"):
        assert value["parent"] == "CHANGED"
    elif kind in ("leaf_drift", "leaf_disappears", "leaf_drift_invalid", "leaf_reappears"):
        assert value["recipient"] == "CHANGED"
    elif kind == "leaf_absent":
        assert value["recipient"] == "ABSENT"
        assert counters["leaf"] == 2
    else:
        assert value["recipient"] == "INVALID"
        assert counters["leaf"] == 2
        assert len(value["recipient_witness"]) == 64
    assert all(event != "open" or name in ("/", "data") for event, name in seen)


def test_witness_must_be_exact_string_not_large_json_integer() -> None:
    for field in ("parent_witness", "recipient_witness"):
        sample = _valid_sample()
        sample[field] = int("1" * 64)
        with pytest.raises(metadata.NoGo):
            metadata._sample(_sample_bytes(sample))


def test_two_serial_guards_and_samples_with_drift_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metadata.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(metadata.os, "getegid", lambda: 10001)
    fingerprints = ["c" * 64, "c" * 64]
    sample_one = _valid_sample()
    sample_two = _valid_sample(mode="0700")
    calls: list[str] = []

    def guard(_: str) -> dict[str, Any]:
        calls.append("guard")
        return dict(_complete_frame()["binding"], fingerprint=fingerprints.pop(0))

    samples = [_sample_bytes(sample_one), _sample_bytes(sample_two)]

    def execute(cid: str) -> bytes:
        assert cid == metadata.CONTROLLER
        calls.append("exec")
        return samples.pop(0)

    monkeypatch.setattr(metadata, "_guard", guard)
    monkeypatch.setattr(metadata, "_docker_exec", execute)
    raw = metadata.observe("43814281299", metadata.SOURCE)
    item = metadata.verify(
        raw, run_id="43814281299", workflow_sha=metadata.SOURCE, allow_failure=True
    )
    assert (item["state"], item["phase"], item["reason"]) == (
        "INCOMPLETE_NO_GO",
        "POSTFLIGHT",
        "METADATA_CHANGED",
    )
    assert item["exec_attempts"] == item["exec_started"] == item["exec_retired"] == 2
    assert calls == ["guard", "exec", "exec", "guard"]
    with pytest.raises(metadata.NoGo):
        metadata.verify(raw, run_id="43814281299", workflow_sha=metadata.SOURCE)


@pytest.mark.parametrize(
    ("parent", "recipient", "reason"),
    [
        ("NOT_READ", "NOT_ATTEMPTED", "METADATA_UNVERIFIED"),
        ("CHANGED", "CHANGED", "METADATA_CHANGED"),
        ("METADATA_VALID", "CHANGED", "METADATA_CHANGED"),
    ],
)
def test_stable_unread_or_changed_never_completes_observation(
    parent: str, recipient: str, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(metadata.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(metadata.os, "getegid", lambda: 10001)
    sample = (
        _valid_sample(leaf="CHANGED")
        if parent == "METADATA_VALID"
        else {
            "parent": parent,
            "recipient": recipient,
            "parent_mode": "NONE",
            "parent_witness": "NONE",
            "recipient_witness": "NONE",
        }
    )
    monkeypatch.setattr(metadata, "_guard", lambda _: dict(_complete_frame()["binding"]))
    monkeypatch.setattr(metadata, "_docker_exec", lambda _: _sample_bytes(sample))
    raw = metadata.observe("43814281299", metadata.SOURCE)
    result = metadata.verify(
        raw, run_id="43814281299", workflow_sha=metadata.SOURCE, allow_failure=True
    )
    assert (result["state"], result["reason"], result["phase"]) == (
        "INCOMPLETE_NO_GO",
        reason,
        "POSTFLIGHT",
    )
    assert result["guards"] == {"before": "VERIFIED", "after": "VERIFIED"}
    assert result["exec_retired"] == 2
    with pytest.raises(metadata.NoGo):
        metadata.verify(raw, run_id="43814281299", workflow_sha=metadata.SOURCE)


def test_host_actor_distinct_uid_denied_before_any_docker_or_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(metadata.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(metadata.os, "getegid", lambda: 1000)

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("identity gate must precede any host read or Docker exec")

    monkeypatch.setattr(metadata, "_guard", forbidden)
    monkeypatch.setattr(metadata, "_docker_exec", forbidden)
    with pytest.raises(metadata.NoGo):
        metadata.observe("43814281299", metadata.SOURCE)


@pytest.mark.parametrize("outcome", ["ok", "empty", "rc", "stderr", "overflow", "timeout"])
def test_exact_cid_docker_exec_bounded_pipe_and_local_retirement(
    outcome: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    class SimulatedDockerClient:
        def __init__(self) -> None:
            self.killed = False
            self.status: int | None = None if outcome == "timeout" else 1 if outcome == "rc" else 0
            read_out, write_out = os.pipe()
            read_err, write_err = os.pipe()
            payload = (
                _sample_bytes(_valid_sample())
                if outcome == "ok"
                else b""
                if outcome == "empty"
                else b"x" * 1025
                if outcome == "overflow"
                else b"{}\n"
            )
            os.write(write_out, payload)
            os.close(write_out)
            os.write(write_err, b"blocked" if outcome == "stderr" else b"")
            os.close(write_err)
            self.stdout = os.fdopen(read_out, "rb", buffering=0)
            self.stderr = os.fdopen(read_err, "rb", buffering=0)

        def poll(self) -> int | None:
            return self.status

        def kill(self) -> None:
            self.killed = True
            self.status = -9

        def wait(self, timeout: float = 0) -> int:
            return -9 if self.killed else int(self.status or 0)

    observed: list[tuple[str, ...]] = []
    processes: list[SimulatedDockerClient] = []

    def popen(command: tuple[str, ...], **kwargs: Any) -> SimulatedDockerClient:
        observed.append(command)
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["stdout"] == subprocess.PIPE
        assert kwargs["stderr"] == subprocess.PIPE
        assert kwargs["cwd"] == "/"
        assert kwargs["env"]["DOCKER_HOST"] == metadata.cleanup.DOCKER_SOCKET
        process = SimulatedDockerClient()
        processes.append(process)
        return process

    monkeypatch.setattr(metadata.subprocess, "Popen", popen)
    if outcome == "timeout":
        clock = iter([0.0, 25.0])
        monkeypatch.setattr(metadata.time, "monotonic", lambda: next(clock))
    if outcome == "ok":
        assert (
            metadata._sample(metadata._docker_exec(metadata.CONTROLLER))["recipient"]
            == "METADATA_VALID_PARSE_UNVERIFIED"
        )
    else:
        with pytest.raises(metadata.NoGo):
            metadata._docker_exec(metadata.CONTROLLER)
    assert len(observed) == 1
    command = observed[0]
    assert command[:6] == (
        "/usr/bin/docker",
        "--host",
        metadata.cleanup.DOCKER_SOCKET,
        "exec",
        "--user",
        "10001:10001",
    )
    assert command[6:] == (
        metadata.CONTROLLER,
        "/app/.venv/bin/python",
        "-I",
        "-B",
        "-c",
        metadata.METADATA_PROGRAM,
    )
    assert processes[0].stdout.closed and processes[0].stderr.closed
    if outcome == "timeout":
        assert processes[0].killed is True
