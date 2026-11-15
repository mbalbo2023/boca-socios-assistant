"""Fixed incident reader with real selection/profile/serialization and fake external I/O."""

from __future__ import annotations

import importlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

SOURCE = "845f31abfb1762dff27e6fc3274fcc40507f3f18"
CONTROLLER = "b0dd0fed57c55dbdeb9a6e833d913cb86c0868ae1587394a934450342114bfa1"
WORKER = "c9c882ff12666fb6cac130879925879cfc0c5c23173a843434adee96b4339dce"
HELPER = "d" * 64
WORKFLOW = "a" * 40
RUN = "43710000000"
INCIDENT = "43705714873"
APPLY = "43704768556"
IMAGE = "ghcr.io/mbalbo2023/boca-socios-assistant@sha256:9fc622a3a7165ce03d1113b5f7f334d402a0dad0c6cbfe2da28075843d11bea0"
BROWSER = "ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:1a59e0b0cb5eb3621820aed635364076542b691fa6e9c73c0e344f09dacc3abe"


def scenario(monkeypatch, *, helper=True, operation="initialize-volume", change=None, fault=""):
    observer = importlib.import_module("boca_socios.host_telegram_incident_readonly")
    from boca_socios import host_boca_binding_observe as binding
    from boca_socios import host_boca_cleanup as cleanup
    from boca_socios.telegram_maintenance_contract import MOUNTS

    events = []
    installed = SimpleNamespace(
        source_sha=SOURCE,
        installation_run_id=APPLY,
        controller_id=CONTROLLER,
        worker_id=WORKER,
        controller_image=IMAGE,
        worker_image=BROWSER,
        pair=SimpleNamespace(
            original_browser_attempt=APPLY,
            controller_config_hash="b" * 64,
            worker_config_hash="c" * 64,
            sender_id="",
            sender_config_hash="",
            sender_attempt_id="",
            sender_running=False,
        ),
    )
    if fault == "binding":
        installed.source_sha = "f" * 40
    binding_calls = []

    def read_binding():
        binding_calls.append(True)
        events.append(("BINDING",))
        result = deepcopy(installed)
        if fault == "binding-drift" and len(binding_calls) >= 3:
            result.pair.controller_config_hash = "e" * 64
        return result

    monkeypatch.setattr(binding, "_read_host_binding", read_binding)

    def daemon():
        events.append(("DAEMON",))
        if fault == "daemon":
            raise ValueError("private host bytes")
        return (999, 111, 22, 33 if fault != "daemon-drift" or len(binding_calls) < 2 else 34)

    monkeypatch.setattr(cleanup, "_rootless_docker_disk_inodes", daemon)
    monkeypatch.setattr(observer.os, "getuid", lambda: 10001)
    monkeypatch.setattr(observer.os, "geteuid", lambda: 10001)
    monkeypatch.setattr(observer.os, "getgid", lambda: 10001)
    monkeypatch.setattr(observer.os, "getegid", lambda: 10001)
    base = {
        "State.Status": "exited",
        "State.Running": False,
        "State.Restarting": False,
        "State.Pid": 0,
        "State.ExitCode": 0,
        "State.OOMKilled": False,
        "State.Health.Status": None,
        "Image": "sha256:" + "e" * 64,
    }
    records = {}
    for cid, name, image, service, config in (
        (CONTROLLER, "boca-socios-controller-1", IMAGE, "controller", "b" * 64),
        (WORKER, "boca-socios-browser-worker-1", BROWSER, "browser-worker", "c" * 64),
    ):
        records[cid] = {
            **base,
            "Id": cid,
            "Name": "/" + name,
            "Config.Image": image,
            "project": "boca-socios",
            "service": service,
            "revision": SOURCE,
            "config": config,
            "attempt": APPLY,
        }
    profiles = MOUNTS.get(operation, ())
    records[HELPER] = {
        **base,
        "Id": HELPER,
        "Name": "/boca-socios-telegram-maint-" + INCIDENT + "-" + "f" * 16,
        "Config.Image": IMAGE,
        "project": "boca-socios",
        "Config.User": "0:0" if operation == "initialize-volume" else "10001:10001",
        "Config.Cmd": ["python", "-m", "boca_socios.telegram_maintenance", operation],
        "HostConfig.NetworkMode": "none",
        "HostConfig.ReadonlyRootfs": True,
        "HostConfig.Privileged": False,
        "HostConfig.LogConfig.Type": "none",
        "HostConfig.CapDrop": ["ALL"],
        "HostConfig.CapAdd": ["CHOWN"] if operation == "initialize-volume" else None,
        "HostConfig.PidsLimit": 16,
        "HostConfig.Memory": 67108864,
        "HostConfig.NanoCpus": 250000000,
        "HostConfig.PublishAllPorts": False,
        "HostConfig.PortBindings": {},
        "HostConfig.RestartPolicy.Name": "no",
        "HostConfig.SecurityOpt": ["no-new-privileges"],
        "NetworkSettings.Networks": {"none": {}},
        "Mounts": [
            {
                "Type": "volume",
                "Name": "boca-socios_" + volume,
                "Driver": "local",
                "Source": "/home/boca-deploy/.local/share/docker/volumes/boca-socios_"
                + volume
                + "/_data",
                "Destination": target,
                "RW": rw,
            }
            for volume, target, rw in profiles
        ],
    }
    if change:
        records[HELPER].update(change)

    def docker(*args):
        events.append(args)
        if args[:2] == ("ps", "-a"):
            pairs = [
                (CONTROLLER, "boca-socios-controller-1"),
                (WORKER, "boca-socios-browser-worker-1"),
            ]
            if helper:
                pairs.append((HELPER, records[HELPER]["Name"].removeprefix("/")))
            if fault in {"ambiguous", "foreign"}:
                pairs.append(
                    (
                        "a" * 64,
                        "boca-socios-telegram-maint-" + INCIDENT + "-" + "a" * 16
                        if fault == "ambiguous"
                        else "foreign-secret-name",
                    )
                )
            if fault == "duplicate":
                pairs[1] = pairs[0]
            if fault == "missing-worker":
                pairs = [pair for pair in pairs if pair[0] != WORKER]
            if fault == "scope-drift" and len(binding_calls) >= 3:
                pairs = [pair for pair in pairs if pair[0] != WORKER]
            if fault == "empty":
                pairs = []
            return "".join(cid + " " + name + "\n" for cid, name in pairs)
        if args[:3] == ("volume", "ls", "-q"):
            return (
                "\n".join(
                    "boca-socios_" + name for name in ("boca_data", "boca_owner", "boca_telegram")
                )
                + "\n"
            )
        if args[:3] == ("volume", "inspect", "--format"):
            return json.dumps(
                "/home/boca-deploy/.local/share/docker/volumes/" + args[-1] + "/_data"
            )
        assert args[:2] == ("inspect", "--format")
        cid = args[-1]
        assert cid in {CONTROLLER, WORKER, HELPER}, "unrelated CID must never be inspected"
        template = args[2]
        assert all(
            secret not in template
            for secret in (".Env", ".State.Error", ".Health.Log", "{{json .}}")
        )
        if fault == "disappeared" and cid == HELPER:
            raise ValueError("private lost container")
        key = {template: field for field, template in observer._TEMPLATES.items()}[template]
        if fault == "oversized" and cid == HELPER and key == "Config.Cmd":
            return "x" * 8193
        value = records[cid][key]
        if fault == "profile-drift" and cid == HELPER and key == "Config.User":
            value = "private-one" if len(binding_calls) < 3 else "private-two"
        if fault == "image-drift" and key == "Image" and len(binding_calls) >= 3:
            value = "sha256:" + "f" * 64
        if fault == "binding-drift" and cid == CONTROLLER and key == "config":
            value = "b" * 64 if len(binding_calls) < 3 else "e" * 64
        if (
            fault == "drift"
            and len(binding_calls) >= 3
            and key == "State.ExitCode"
            and cid == HELPER
        ):
            value = 1
        return json.dumps(value)

    monkeypatch.setattr(cleanup, "_docker", docker)
    return observer, events


def decoded(observer, raw):
    assert observer.verify(raw, RUN, WORKFLOW) == raw
    return json.loads(raw[len(observer.PREFIX) :])


def test_incident_distinct_workflow_binding_and_incomplete_boundary(monkeypatch):
    observer, events = scenario(monkeypatch)
    value = decoded(observer, observer.observe(RUN, WORKFLOW))
    assert value["state"] == "OBSERVED_NO_GO"
    assert value["source_sha"] == SOURCE and value["workflow_sha"] == WORKFLOW
    assert value["installation_run_id"] == APPLY and value["incident_run_id"] == INCIDENT
    assert sum(event == ("DAEMON",) for event in events) == 2
    assert sum(event == ("BINDING",) for event in events) == 4
    observer, events = scenario(monkeypatch, fault="binding")
    value = decoded(observer, observer.observe(RUN, WORKFLOW))
    assert value["state"] == "INCOMPLETE_NO_GO" and value["phase"] == "BINDING"
    assert not any(event[0] == "ps" for event in events)


@pytest.mark.parametrize("helper", [False, True])
def test_incident_independent_census_and_stable_absence(monkeypatch, helper):
    observer, _ = scenario(monkeypatch, helper=helper)
    value = decoded(observer, observer.observe(RUN, WORKFLOW))
    assert value["state"] == "OBSERVED_NO_GO"
    assert value["helper"]["presence"] == ("PRESENT" if helper else "ABSENT")
    assert all(item["health"] == "NONE" for item in value["services"])


@pytest.mark.parametrize("fault", ["missing-worker", "empty"])
def test_incident_stable_fixed_cid_absence_is_observed_without_inspection(monkeypatch, fault):
    observer, events = scenario(monkeypatch, fault=fault)
    value = decoded(observer, observer.observe(RUN, WORKFLOW))
    assert value["state"] == "OBSERVED_NO_GO"
    assert value["services"][1] == {"cid": WORKER, "presence": "ABSENT"}
    if fault == "empty":
        assert value["services"][0] == {"cid": CONTROLLER, "presence": "ABSENT"}
        assert value["helper"] == {"presence": "ABSENT"}
    assert sum(event[0] == "ps" for event in events) == 2
    assert not any(event[0] == "inspect" and event[-1] == WORKER for event in events)


@pytest.mark.parametrize(
    "fault",
    [
        "ambiguous",
        "foreign",
        "duplicate",
        "disappeared",
        "oversized",
        "daemon",
        "drift",
        "daemon-drift",
        "scope-drift",
        "profile-drift",
        "image-drift",
        "binding-drift",
    ],
)
def test_incident_ambiguity_incomplete_and_drift_never_succeed(monkeypatch, fault):
    observer, events = scenario(monkeypatch, fault=fault)
    value = decoded(observer, observer.observe(RUN, WORKFLOW))
    assert value["state"] == "INCOMPLETE_NO_GO"
    assert value["helper"] == {"presence": "UNVERIFIED"} and value["services"] == []
    if fault in {"ambiguous", "foreign", "duplicate"}:
        assert not any(event[0] == "inspect" for event in events)


@pytest.mark.parametrize(
    "caps,observed,reason",
    [
        (["CHOWN"], "CHOWN", "MATCH"),
        (["CAP_CHOWN"], "CAP_CHOWN", "CAPADD_MISMATCH"),
        (None, "ABSENT", "CAPADD_MISMATCH"),
        (["SECRET_CAP"], "OTHER", "CAPADD_MISMATCH"),
    ],
)
def test_incident_complete_mismatch_has_finite_caps_diagnostic(monkeypatch, caps, observed, reason):
    observer, _ = scenario(monkeypatch, change={"HostConfig.CapAdd": caps})
    raw = observer.observe(RUN, WORKFLOW)
    value = decoded(observer, raw)
    assert value["state"] == "OBSERVED_NO_GO"
    assert value["helper"]["cap_add_observed"] == observed
    assert value["helper"]["profile"]["caps"] == [reason]
    assert b"SECRET" not in raw


@pytest.mark.parametrize("operation", ["unknown-secret-operation", "seal"])
def test_incident_unknown_operation_has_no_assumed_uid_or_mount_profile(monkeypatch, operation):
    observer, _ = scenario(monkeypatch, operation=operation)
    value = decoded(observer, observer.observe(RUN, WORKFLOW))
    helper = value["helper"]
    assert helper["operation"] == (
        "UNKNOWN" if operation.startswith("unknown") else "OUTSIDE_PREPARE"
    )
    assert helper["profile"]["uid"] == helper["profile"]["mounts"] == ["UNVERIFIED"]


def test_incident_commands_and_strict_receipt_exclude_secret_fields(monkeypatch):
    observer, events = scenario(
        monkeypatch, change={"HostConfig.Memory": 123, "HostConfig.NetworkMode": "secret-network"}
    )
    raw = observer.observe(RUN, WORKFLOW)
    value = decoded(observer, raw)
    assert len(raw) <= 4096 and b"secret-network" not in raw
    assert value["engine"] == "UNVERIFIED" and value["observer_writes"] == 0
    assert all(
        value[key] is False
        for key in ("restore_authorized", "cleanup_authorized", "deploy_authorized")
    )
    assert set(event[0] for event in events) <= {"DAEMON", "BINDING", "ps", "inspect", "volume"}
    for altered in (
        raw + b"\n",
        raw.replace(b'"observer_writes":0', b'"observer_writes":true'),
        raw.replace(b'"deploy_authorized":false', b'"deploy_authorized":true'),
    ):
        with pytest.raises(ValueError):
            observer.verify(altered, RUN, WORKFLOW)


@pytest.mark.parametrize(
    "operation,boundary",
    [
        ("initialize-volume", "uid"),
        ("prepare", "identity"),
        ("prepare", "command"),
        ("unknown-secret-operation", "identity"),
        ("unknown-secret-operation", "command"),
        ("seal", "identity"),
        ("seal", "command"),
    ],
)
def test_incident_receipt_cannot_label_known_unverified_profile_complete(
    monkeypatch, operation, boundary
):
    observer, _ = scenario(monkeypatch, operation=operation)
    value = decoded(observer, observer.observe(RUN, WORKFLOW))
    value["helper"]["profile"][boundary] = ["UNVERIFIED"]
    raw = (
        observer.PREFIX + json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    with pytest.raises(ValueError, match="receipt_unverified"):
        observer.verify(raw, RUN, WORKFLOW)
