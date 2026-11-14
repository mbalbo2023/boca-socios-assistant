"""Current source/IDs belong to the installed binding, independently of main."""

import io
import json

import pytest

from boca_socios import host_on_demand_status as status
from test_host_on_demand_status import PINS, host  # noqa: F401 - shared offline host fixture

WORKFLOW = "f" * 40
pytestmark = pytest.mark.usefixtures("host")


def test_current_status_reports_installed_binding_when_main_has_advanced(capsys):
    assert status.main(["host-current", WORKFLOW, PINS[3]]) == 0
    value = json.loads(capsys.readouterr().out.removeprefix("BOCA_CURRENT_STATUS "))
    assert value["schema"] == 2 and value["workflow_source_sha"] == WORKFLOW
    installed = value["installed"]
    assert installed["source_sha"] == PINS[0] and installed["source_sha"] != WORKFLOW
    assert installed["controller_image"] == PINS[1]
    assert installed["worker_image"] == PINS[2]
    assert installed["operation"]["target"] == "start"
    assert installed["worker_state"] == "exited" and installed["worker_pid"] == 0


def test_current_verifier_binds_workflow_run_and_closed_installed_schema(monkeypatch, capsys):
    assert status.main(["host-current", WORKFLOW, PINS[3]]) == 0
    raw = capsys.readouterr().out
    for payload, workflow, run in (
        (raw, WORKFLOW, PINS[3]),
        (raw, PINS[0], PINS[3]),
        (raw, WORKFLOW, "9"),
        (raw.replace('"schema":2', '"schema":2,"extra":"PRIVATE"'), WORKFLOW, PINS[3]),
        (raw + raw, WORKFLOW, PINS[3]),
    ):
        monkeypatch.setattr(status.sys, "stdin", io.TextIOWrapper(io.BytesIO(payload.encode())))
        ok = payload == raw and workflow == WORKFLOW and run == PINS[3]
        assert status.main(["verify-current", workflow, run]) == (0 if ok else 3)
        assert capsys.readouterr().out == (raw if ok else status.NO_GO + "\n")


def test_current_status_does_not_publish_binding_drift(monkeypatch, capsys):
    original = status.read_installed_binding
    calls = 0

    def race(lease):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("PRIVATE binding changed")
        return original(lease)

    monkeypatch.setattr(status, "read_installed_binding", race)
    assert status.main(["host-current", WORKFLOW, PINS[3]]) == 3
    assert capsys.readouterr().out == status.NO_GO + "\n"
