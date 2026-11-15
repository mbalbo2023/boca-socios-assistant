"""Current CLI observation retains finite, independently bound historical APIs."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from test_r304_telegram_incident_readonly import (
    INCIDENT,
    RUN,
    WORKFLOW,
    scenario,
)

CURRENT = "43738415332"

# Frozen items from e16bfb78bc16b9f7554c76191c50f354e61fcbbc; no checkout history required.
_BASE_TEMPLATE_ITEMS = (
    ("Id", "{{json .Id}}"),
    ("Name", "{{json .Name}}"),
    ("Image", "{{json .Image}}"),
    ("Config.Image", "{{json .Config.Image}}"),
    ("Config.User", "{{json .Config.User}}"),
    ("Config.Cmd", "{{json .Config.Cmd}}"),
    ("project", '{{json (index .Config.Labels "com.docker.compose.project")}}'),
    ("service", '{{json (index .Config.Labels "com.docker.compose.service")}}'),
    ("revision", '{{json (index .Config.Labels "org.opencontainers.image.revision")}}'),
    ("config", '{{json (index .Config.Labels "com.docker.compose.config-hash")}}'),
    ("attempt", '{{json (index .Config.Labels "boca.socios.browser-ipc-attempt")}}'),
    ("State.Status", "{{json .State.Status}}"),
    ("State.Running", "{{json .State.Running}}"),
    ("State.Restarting", "{{json .State.Restarting}}"),
    ("State.Pid", "{{json .State.Pid}}"),
    ("State.ExitCode", "{{json .State.ExitCode}}"),
    ("State.OOMKilled", "{{json .State.OOMKilled}}"),
    ("State.Health.Status", "{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}}"),
    ("HostConfig.NetworkMode", "{{json .HostConfig.NetworkMode}}"),
    ("HostConfig.ReadonlyRootfs", "{{json .HostConfig.ReadonlyRootfs}}"),
    ("HostConfig.Privileged", "{{json .HostConfig.Privileged}}"),
    ("HostConfig.LogConfig.Type", "{{json .HostConfig.LogConfig.Type}}"),
    ("HostConfig.CapDrop", "{{json .HostConfig.CapDrop}}"),
    ("HostConfig.CapAdd", "{{json .HostConfig.CapAdd}}"),
    ("HostConfig.PidsLimit", "{{json .HostConfig.PidsLimit}}"),
    ("HostConfig.Memory", "{{json .HostConfig.Memory}}"),
    ("HostConfig.NanoCpus", "{{json .HostConfig.NanoCpus}}"),
    ("HostConfig.PublishAllPorts", "{{json .HostConfig.PublishAllPorts}}"),
    ("HostConfig.PortBindings", "{{json .HostConfig.PortBindings}}"),
    ("HostConfig.RestartPolicy.Name", "{{json .HostConfig.RestartPolicy.Name}}"),
    ("HostConfig.SecurityOpt", "{{json .HostConfig.SecurityOpt}}"),
    ("Mounts", "{{json .Mounts}}"),
    ("NetworkSettings.Networks", "{{json .NetworkSettings.Networks}}"),
)


def current_scenario(monkeypatch, *, change=None, **options):
    """Reuse the external Docker/binding transport, retaining actual acquisition."""
    return scenario(
        monkeypatch,
        change={
            "Name": "/boca-socios-telegram-maint-43738415332-" + "f" * 16,
            **(change or {}),
        },
        **options,
    )


def frame(observer, value):
    return (
        observer.PREFIX + json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )


def value_of(observer, raw):
    return json.loads(raw[len(observer.PREFIX) :])


def cli(monkeypatch, observer, mode, raw=b""):
    output = io.BytesIO()
    monkeypatch.setattr(observer.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
    monkeypatch.setattr(observer.sys, "stdout", SimpleNamespace(buffer=output))
    rc = observer.main([mode, RUN, WORKFLOW])
    return rc, output.getvalue()


def test_current_cli_host_acquires_1167_helper_without_caller_selector(monkeypatch):
    observer, events = current_scenario(monkeypatch)
    rc, raw = cli(monkeypatch, observer, "host")
    value = value_of(observer, raw)
    assert rc == 0
    assert value["incident_run_id"] == CURRENT
    assert value["state"] == "OBSERVED_NO_GO" and value["reason"] == "NONE"
    assert value["helper"]["presence"] == "PRESENT"
    assert sum(event == ("DAEMON",) for event in events) == 2


def test_current_cli_verifier_accepts_1167_receipt_with_same_three_arguments(monkeypatch):
    observer, _ = scenario(monkeypatch, helper=False)
    value = value_of(observer, observer.observe(RUN, WORKFLOW))
    value["incident_run_id"] = CURRENT
    raw = frame(observer, value)
    rc, output = cli(monkeypatch, observer, "verify", raw)
    assert rc == 0 and output == raw


@pytest.mark.parametrize("selected,fixture", [(INCIDENT, scenario), (CURRENT, current_scenario)])
def test_receipts_reject_both_cross_incident_directions_with_identical_run_sha(
    monkeypatch, selected, fixture
):
    observer, _ = fixture(monkeypatch)
    raw = observer.observe(RUN, WORKFLOW, selected)
    assert observer.verify(raw, RUN, WORKFLOW, selected) == raw
    wrong = CURRENT if selected == INCIDENT else INCIDENT
    with pytest.raises(ValueError, match="receipt_unverified"):
        observer.verify(raw, RUN, WORKFLOW, wrong)
    if selected == INCIDENT:
        assert observer.observe(RUN, WORKFLOW) == raw
        assert observer.verify(raw, RUN, WORKFLOW) == raw
        assert cli(monkeypatch, observer, "verify", raw)[0] == 3
    else:
        with pytest.raises(ValueError, match="receipt_unverified"):
            observer.verify(raw, RUN, WORKFLOW)


@pytest.mark.parametrize("selected,fixture", [(INCIDENT, scenario), (CURRENT, current_scenario)])
@pytest.mark.parametrize("caps", [["CHOWN"], ["CAP_CHOWN"], ["CHOWN", "CAP_CHOWN"], None])
def test_initializer_capability_profile_is_incident_specific(monkeypatch, selected, fixture, caps):
    observer, _ = fixture(monkeypatch, change={"HostConfig.CapAdd": caps})
    raw = observer.observe(RUN, WORKFLOW, selected)
    value = value_of(observer, raw)
    assert observer.verify(raw, RUN, WORKFLOW, selected) == raw
    assert value["state"] == "OBSERVED_NO_GO"
    matched = caps == ["CHOWN"] or selected == CURRENT and caps == ["CAP_CHOWN"]
    assert value["helper"]["profile"]["caps"] == ["MATCH" if matched else "CAPADD_MISMATCH"]


@pytest.mark.parametrize("operation", ["publish-status", "publish-status-absent"])
@pytest.mark.parametrize("selected,fixture", [(INCIDENT, scenario), (CURRENT, current_scenario)])
def test_status_publication_profile_and_codec_are_finite_and_incident_specific(
    monkeypatch, operation, selected, fixture
):
    observer, _ = fixture(monkeypatch, operation=operation)
    raw = observer.observe(RUN, WORKFLOW, selected)
    assert observer.verify(raw, RUN, WORKFLOW, selected) == raw
    helper = value_of(observer, raw)["helper"]
    if selected == CURRENT:
        assert helper["operation"] == operation
        assert all(reasons == ["MATCH"] for reasons in helper["profile"].values())
        altered = value_of(observer, raw)
        altered["helper"]["operation"] = "publish-secret-operation"
        with pytest.raises(ValueError, match="receipt_unverified"):
            observer.verify(frame(observer, altered), RUN, WORKFLOW, selected)
    else:
        assert helper["operation"] == "OUTSIDE_PREPARE"
        assert helper["profile"]["command"] == ["OPERATION_OUTSIDE_PREPARE"]
        assert helper["profile"]["mounts"] == ["UNVERIFIED"]


@pytest.mark.parametrize(
    "operation", ["verify-schema", "owner-identity", "prepare", "publish-recipient"]
)
def test_current_profile_retains_other_prepare_operations(monkeypatch, operation):
    observer, _ = current_scenario(monkeypatch, operation=operation)
    raw = observer.observe(RUN, WORKFLOW, CURRENT)
    assert observer.verify(raw, RUN, WORKFLOW, CURRENT) == raw
    helper = value_of(observer, raw)["helper"]
    assert helper["operation"] == operation
    assert all(reasons == ["MATCH"] for reasons in helper["profile"].values())


@pytest.mark.parametrize("bad", ["", "43738415333", 43738415332, None, [CURRENT]])
def test_invalid_incident_selection_rejects_before_any_docker_or_field_access(monkeypatch, bad):
    observer, events = current_scenario(monkeypatch)
    for call in (
        lambda: observer.observe(RUN, WORKFLOW, bad),
        lambda: observer._snapshot(bad),
        lambda: observer._inventory(bad),
        lambda: observer._profile({}, bad),
        lambda: observer._base(RUN, WORKFLOW, bad),
        lambda: observer._verify_helper({"presence": "ABSENT"}, bad),
        lambda: observer.verify(b"invalid", RUN, WORKFLOW, bad),
    ):
        with pytest.raises(ValueError):
            call()
    assert events == []


@pytest.mark.parametrize("kind", ["historical", "alien", "multiple"])
def test_current_inventory_rejects_wrong_or_multiple_helpers_before_field_inspection(
    monkeypatch, kind
):
    name = "/boca-socios-telegram-maint-" + INCIDENT + "-" + "f" * 16
    observer, events = current_scenario(
        monkeypatch,
        change={"Name": name if kind == "historical" else "/private-foreign-token"}
        if kind != "multiple"
        else None,
        fault="ambiguous" if kind == "multiple" else "",
    )
    raw = observer.observe(RUN, WORKFLOW, CURRENT)
    value = value_of(observer, raw)
    assert value["state"] == "INCOMPLETE_NO_GO"
    assert (value["phase"], value["reason"]) == (
        "INVENTORY",
        "MALFORMED" if kind == "multiple" else "AMBIGUOUS",
    )
    assert not any(event[0] == "inspect" for event in events)
    assert b"private" not in raw


def test_historical_inventory_rejects_current_helper_before_field_inspection(monkeypatch):
    observer, events = current_scenario(monkeypatch)
    value = value_of(observer, observer.observe(RUN, WORKFLOW))
    assert (value["phase"], value["reason"]) == ("INVENTORY", "AMBIGUOUS")
    assert not any(event[0] == "inspect" for event in events)


def test_current_helper_absence_is_complete_without_causality_or_permissions(monkeypatch):
    observer, _ = current_scenario(monkeypatch, helper=False)
    raw = observer.observe(RUN, WORKFLOW, CURRENT)
    value = value_of(observer, raw)
    assert observer.verify(raw, RUN, WORKFLOW, CURRENT) == raw
    assert (value["state"], value["phase"], value["reason"]) == (
        "OBSERVED_NO_GO",
        "COMPLETE",
        "NONE",
    )
    assert value["helper"] == {"presence": "ABSENT"}
    assert value["engine"] == "UNVERIFIED" and value["observer_writes"] == 0
    assert all(
        value[key] is False
        for key in ("restore_authorized", "cleanup_authorized", "deploy_authorized")
    )
    value["reason"] = "HELPER_ABSENT"
    with pytest.raises(ValueError, match="receipt_unverified"):
        observer.verify(frame(observer, value), RUN, WORKFLOW, CURRENT)


@pytest.mark.parametrize("fault", ["drift", "profile-drift", "binding-drift", "scope-drift"])
def test_current_acquisition_still_requires_stable_double_snapshot(monkeypatch, fault):
    observer, _ = current_scenario(monkeypatch, fault=fault)
    raw = observer.observe(RUN, WORKFLOW, CURRENT)
    assert observer.verify(raw, RUN, WORKFLOW, CURRENT) == raw
    value = value_of(observer, raw)
    assert (value["state"], value["phase"], value["reason"]) == (
        "INCOMPLETE_NO_GO",
        "DRIFT",
        "CHANGED",
    )
    assert value["services"] == [] and value["helper"] == {"presence": "UNVERIFIED"}


def test_current_receipt_redacts_synthetic_token_like_raw_fields(monkeypatch):
    token = "123456789:AA_SYNTHETIC_PRIVATE_TOKEN_EXAMPLE"
    observer, events = current_scenario(
        monkeypatch,
        operation=token,
        change={"Config.User": token, "HostConfig.CapAdd": [token]},
    )
    raw = observer.observe(RUN, WORKFLOW, CURRENT)
    assert observer.verify(raw, RUN, WORKFLOW, CURRENT) == raw
    helper = value_of(observer, raw)["helper"]
    assert helper["operation"] == "UNKNOWN" and helper["cap_add_observed"] == "OTHER"
    assert helper["profile"]["command"] == ["ARGV_MISMATCH", "UNKNOWN_OPERATION"]
    assert helper["profile"]["uid"] == ["UNVERIFIED"]
    assert token.encode() not in raw and len(raw) <= 4096
    assert set(event[0] for event in events) <= {"DAEMON", "BINDING", "ps", "inspect", "volume"}


def test_fixed_inspect_templates_and_derived_orders_match_immutable_base():
    # Acquisition order is part of snapshot/ZIP compatibility, so dict equality is insufficient.
    from boca_socios import host_telegram_incident_readonly as observer

    original = dict(_BASE_TEMPLATE_ITEMS)
    assert tuple(observer._TEMPLATES.items()) == _BASE_TEMPLATE_ITEMS
    assert observer._STATE_FIELDS == tuple(key for key in original if key.startswith("State."))
    assert observer._HELPER_FIELDS == (
        "Config.User",
        "Config.Cmd",
        *tuple(key for key in original if key.startswith("HostConfig.")),
        "Mounts",
        "NetworkSettings.Networks",
    )
    assert len(observer._TEMPLATES) == 33
