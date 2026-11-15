"""Current source/IDs belong to the installed binding, independently of main."""

import io
import json
import sys
from contextlib import redirect_stdout
from dataclasses import asdict, replace
from pathlib import Path
from uuid import uuid4

import pytest

import test_host_lifecycle_rootless_adapter as fixture
from boca_socios import host_on_demand_lifecycle as demand
from boca_socios import host_on_demand_status as status
from test_host_on_demand_status import PINS, host  # noqa: F401 - shared offline host fixture

WORKFLOW = "f" * 40


def _controller_program(path, args, monkeypatch):
    """Map only the controller filesystem boundary; use the real ledger reader."""
    original = demand.lifecycle._controller_ledger
    opened = []
    output = io.StringIO()
    code = 0

    def controller_ledger(visible_path, *, readonly=False):
        opened.append((visible_path, readonly))
        assert visible_path == Path("/data/boca.sqlite3")
        assert readonly is True
        return original(path, readonly=readonly)

    with monkeypatch.context() as boundary, redirect_stdout(output):
        boundary.setattr(demand.lifecycle, "_controller_ledger", controller_ledger)
        boundary.setattr(sys, "argv", ["-c", *args])
        try:
            exec(status._CURRENT_LEDGER_PROGRAM, {})  # noqa: S102 - exact reviewed program
        except SystemExit as stopped:
            code = stopped.code
    return code, output.getvalue(), opened


def test_current_status_reports_installed_binding_when_main_has_advanced(bound_current, capsys):
    assert status.main(["host-current", WORKFLOW, PINS[3]]) == 0
    value = json.loads(capsys.readouterr().out.removeprefix("BOCA_CURRENT_STATUS "))
    assert value["schema"] == 3 and value["workflow_source_sha"] == WORKFLOW
    installed = value["installed"]
    assert installed["source_sha"] == PINS[0] and installed["source_sha"] != WORKFLOW
    assert installed["controller_image"] == PINS[1]
    assert installed["worker_image"] == PINS[2]
    assert installed["operation"]["target"] == "start"
    assert installed["worker_state"] == "exited" and installed["worker_pid"] == 0


def test_current_verifier_binds_workflow_run_and_closed_installed_schema(
    bound_current, monkeypatch, capsys
):
    assert status.main(["host-current", WORKFLOW, PINS[3]]) == 0
    raw = capsys.readouterr().out
    for payload, workflow, run in (
        (raw, WORKFLOW, PINS[3]),
        (raw, PINS[0], PINS[3]),
        (raw, WORKFLOW, "9"),
        (raw.replace('"schema":3', '"schema":3,"extra":"PRIVATE"'), WORKFLOW, PINS[3]),
        (raw + raw, WORKFLOW, PINS[3]),
    ):
        monkeypatch.setattr(status.sys, "stdin", io.TextIOWrapper(io.BytesIO(payload.encode())))
        ok = payload == raw and workflow == WORKFLOW and run == PINS[3]
        assert status.main(["verify-current", workflow, run]) == (0 if ok else 3)
        assert capsys.readouterr().out == (raw if ok else status.NO_GO + "\n")


def test_current_status_does_not_publish_binding_drift(bound_current, monkeypatch, capsys):
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


@pytest.fixture
def preserved_stop(request, tmp_path, monkeypatch):
    """Only Docker/host sampling is inert; controller program and ledger are real."""
    request.getfixturevalue("host")
    path = tmp_path / "controller" / "data" / "boca.sqlite3"
    path.parent.mkdir(parents=True)
    host_path = (
        tmp_path / "host" / ".local/share/docker/volumes/boca-socios_boca_data/_data/boca.sqlite3"
    )
    _, ledger = fixture._request_with_real_ledger(path, "bot", "stop")
    operation = str(uuid4())
    ledger.request("bot", "stop", operation, on_demand=True)
    current = demand.OnDemandInstallation(
        fixture.INSTALLED,
        fixture.SOURCE,
        fixture.CONTROLLER,
        fixture.CONTROLLER_REF,
        fixture.WORKER,
        fixture.WORKER_REF,
        host_path,
        fixture._binding(),
    )
    previous = replace(current, source_sha="8" * 40, controller_id="7" * 64)
    demand._transact(path, operation, previous.fingerprint(), "claim")
    demand._transact(path, operation, previous.fingerprint(), "APPLIED")
    live = {
        "sample": ("created", 0, False, False),
        "calls": 0,
        "after_read": lambda: None,
        "program_argv": [],
        "ledger_paths": [],
    }

    def controller(*args):
        assert args[:6] == (
            "exec",
            "--user",
            "10001:10001",
            current.controller_id,
            "/app/.venv/bin/python",
            "-I",
        )
        assert args[6] == "-B"
        live["calls"] += 1
        if args[7] == "-m":
            assert args[8:10] == ("boca_socios.host_on_demand_lifecycle", "status")
            return demand._status_wire(path, args[10]) + "\n"
        assert args[7] == "-c"
        assert args[8] == status._CURRENT_LEDGER_PROGRAM
        live["program_argv"].append(args[9:])
        code, output, opened = _controller_program(path, args[9:], monkeypatch)
        live["ledger_paths"].extend(opened)
        if code:
            raise demand.OnDemandUnavailable("controller diagnostic refused")
        live["after_read"]()
        return output

    monkeypatch.setattr(status, "read_installed_binding", lambda lease: current)
    monkeypatch.setattr(status, "_physical", lambda *args: live["sample"])
    monkeypatch.setattr(status, "read_panel_status", demand.read_panel_status)
    monkeypatch.setattr(demand.cleanup, "_docker", controller)
    return path, ledger, operation, current, previous, live


@pytest.fixture
def bound_current(preserved_stop):
    path, ledger, _, current, _, live = preserved_stop
    operation = str(uuid4())
    ledger.request("bot", "start", operation, on_demand=True)
    demand._transact(path, operation, current.fingerprint(), "claim")
    demand._transact(path, operation, current.fingerprint(), "APPLIED")
    live["sample"] = ("exited", 0, False, False)
    return preserved_stop


def test_current_program_uses_canonical_path_and_host_fingerprint(bound_current, monkeypatch):
    path, _, _, current, _, _ = bound_current
    assert current.database_path != path and not current.database_path.exists()
    identity, before = path.stat().st_ino, path.read_bytes()

    code, output, opened = _controller_program(path, [current.fingerprint()], monkeypatch)

    assert code == 0
    assert opened == [(Path("/data/boca.sqlite3"), True)]
    scope, operation = status._ledger_checked(json.loads(output))
    assert scope == "CURRENT_INSTALLATION" and operation.target == "start"
    assert path.stat().st_ino == identity and path.read_bytes() == before
    assert not current.database_path.exists()


def test_current_observer_does_not_send_host_database_path(bound_current, capsys):
    path, _, _, current, _, live = bound_current
    identity, before = path.stat().st_ino, path.read_bytes()

    assert status.main(["host-current", WORKFLOW, PINS[3]]) == 0

    document = json.loads(capsys.readouterr().out.removeprefix(status.CURRENT_PREFIX))
    assert document["ledger"]["scope"] == "CURRENT_INSTALLATION"
    assert live["program_argv"] == [(current.fingerprint(),)] * 2
    assert live["ledger_paths"] == [(Path("/data/boca.sqlite3"), True)] * 2
    assert path.stat().st_ino == identity and path.read_bytes() == before
    assert not current.database_path.exists()


@pytest.mark.parametrize(
    "args",
    [
        [],
        [""],
        ["PRIVATE"],
        ["A" * 64],
        ["a" * 64, "/host/PRIVATE/boca.sqlite3"],
        ["a" * 64, "/data/boca.sqlite3"],
    ],
    ids=[
        "missing_fingerprint",
        "empty_fingerprint",
        "malformed_fingerprint",
        "uppercase_fingerprint",
        "extra_host_path",
        "extra_controller_path",
    ],
)
def test_current_program_rejects_invalid_argv_before_opening_ledger(
    preserved_stop, monkeypatch, args
):
    path, _, _, _, _, _ = preserved_stop
    identity, before = path.stat().st_ino, path.read_bytes()

    code, output, opened = _controller_program(path, args, monkeypatch)

    assert code == 3 and output == ""
    assert opened == []
    assert path.stat().st_ino == identity and path.read_bytes() == before


def test_preserved_stop_is_not_a_receipt_for_the_new_installation(preserved_stop, capsys):
    path, _, operation, current, _, live = preserved_stop
    with demand.lifecycle._controller_ledger(path, readonly=True) as db:
        before = tuple(db.iterdump())
        assert db.execute("PRAGMA query_only").fetchone() == (1,)
    identity = path.stat().st_ino
    with pytest.raises(demand.OnDemandUnavailable, match="another installation"):
        demand._status_wire(path, current.fingerprint())

    assert status.main(["host-current", WORKFLOW, PINS[3]]) == 0
    doc = json.loads(capsys.readouterr().out.removeprefix(status.CURRENT_PREFIX))
    assert doc["schema"] == 3
    assert doc["installed"]["operation"] is None
    assert doc["installed"]["worker_state"] == "created"
    assert doc["ledger"] == {
        "schema": 1,
        "scope": "NOT_BOUND_TO_CURRENT_INSTALLATION",
        "operation": {
            "operation_id": operation,
            "target": "stop",
            "status": "APPLIED",
            "cause": "NONE",
            "exit_code": None,
            "oom": None,
            "exit_signature": None,
        },
    }
    assert live["calls"] == 2
    with demand.lifecycle._controller_ledger(path, readonly=True) as db:
        assert tuple(db.iterdump()) == before
    assert path.stat().st_ino == identity


def test_current_failed_receipt_keeps_its_bound_categorical_detail(preserved_stop, capsys):
    path, ledger, _, current, _, live = preserved_stop
    operation = str(uuid4())
    ledger.request("bot", "start", operation, on_demand=True)
    fp = current.fingerprint()
    demand._transact(path, operation, fp, "claim")
    demand._transact(path, operation, fp, "note", "HEALTH_EXITED|7|0|-")
    demand._transact(path, operation, fp, "FAILED")
    live["sample"] = ("exited", 0, False, False)
    strict = demand.read_panel_status(current)
    assert strict.exit_code == 7 and strict.cause == "HEALTH_EXITED"
    assert status.main(["host-current", WORKFLOW, PINS[3]]) == 0
    doc = json.loads(capsys.readouterr().out.removeprefix(status.CURRENT_PREFIX))
    assert doc["installed"]["operation"] == asdict(strict)
    assert doc["ledger"] == {
        "schema": 1,
        "scope": "CURRENT_INSTALLATION",
        "operation": asdict(strict),
    }


@pytest.mark.parametrize("phase", ["REQUESTED", "CLAIMED", "UNCERTAIN"])
@pytest.mark.parametrize("binding", ["current", "previous"])
def test_pending_or_uncertain_ledger_is_not_suppressed(preserved_stop, capsys, phase, binding):
    path, ledger, _, current, previous, _ = preserved_stop
    operation = str(uuid4())
    ledger.request("bot", "start", operation, on_demand=True)
    fp = (current if binding == "current" else previous).fingerprint()
    if phase != "REQUESTED":
        demand._transact(path, operation, fp, "claim")
    if phase == "UNCERTAIN":
        demand._transact(path, operation, fp, "UNCERTAIN")
    assert status.main(["host-current", WORKFLOW, PINS[3]]) == 3
    assert capsys.readouterr().out == status.NO_GO + "\n"


@pytest.mark.parametrize(
    "sample",
    [
        ("exited", 0, False, False),
        ("created", 0, False, True),
        ("created", 0, True, False),
        ("running", 1, True, False),
    ],
)
def test_unbound_stop_never_authorizes_other_physical_states(preserved_stop, capsys, sample):
    *_, live = preserved_stop
    live["sample"] = sample
    assert status.main(["host-current", WORKFLOW, PINS[3]]) == 3
    assert capsys.readouterr().out == status.NO_GO + "\n"


@pytest.mark.parametrize("corruption", ["unknown_action", "profile", "missing_claim", "binding"])
def test_malformed_preserved_ledger_remains_no_go(preserved_stop, capsys, corruption):
    path, _, operation, current, _, _ = preserved_stop
    with demand.lifecycle._controller_ledger(path) as db, db:
        if corruption == "unknown_action":
            db.execute(
                "UPDATE audit_events SET action=? WHERE audit_id=?",
                ("owner_lifecycle_v1_unknown", operation),
            )
        elif corruption == "profile":
            db.execute(
                "UPDATE audit_events SET action=? WHERE action LIKE ?",
                ("boca_bot_on_demand_v1:invalid", "boca_bot_on_demand_v1:%"),
            )
        elif corruption == "missing_claim":
            db.execute(
                "DELETE FROM audit_events WHERE audit_id=?",
                (demand.host_marker(operation, "bot", "stop", "CLAIMED")[0],),
            )
        else:
            db.execute(
                "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
                (demand._marker_id(operation, current.fingerprint(), "binding"), "PRIVATE"),
            )
    assert status.main(["host-current", WORKFLOW, PINS[3]]) == 3
    assert capsys.readouterr().out == status.NO_GO + "\n"


def test_corrupt_current_note_is_not_hidden(bound_current, capsys):
    path, ledger, _, current, _, _ = bound_current
    operation = ledger.current().operation_id
    with demand.lifecycle._controller_ledger(path) as db, db:
        db.execute(
            "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
            (demand._marker_id(operation, current.fingerprint(), "note"), "PRIVATE"),
        )
    assert status.main(["host-current", WORKFLOW, PINS[3]]) == 3
    assert capsys.readouterr().out == status.NO_GO + "\n"


@pytest.mark.parametrize("note", ["boca_demand_v1_note_NONE|-|-|-", "PRIVATE"])
def test_current_fingerprint_note_without_binding_is_not_historical(preserved_stop, capsys, note):
    path, _, operation, current, _, _ = preserved_stop
    fp = current.fingerprint()
    with pytest.raises(demand.OnDemandUnavailable, match="another installation"):
        demand._transact(path, operation, fp, "note", "NONE|-|-|-")
    with demand.lifecycle._controller_ledger(path) as db, db:
        db.execute(
            "INSERT INTO audit_events(audit_id,action) VALUES (?,?)",
            (demand._marker_id(operation, fp, "note"), note),
        )
    assert status.main(["host-current", WORKFLOW, PINS[3]]) == 3
    assert capsys.readouterr().out == status.NO_GO + "\n"


def test_new_intent_between_real_ledger_samples_suppresses_receipt(preserved_stop, capsys):
    _, ledger, _, _, _, live = preserved_stop

    def request_after_first_read():
        if live["calls"] == 1:
            ledger.request("bot", "start", str(uuid4()), on_demand=True)

    live["after_read"] = request_after_first_read
    assert status.main(["host-current", WORKFLOW, PINS[3]]) == 3
    assert capsys.readouterr().out == status.NO_GO + "\n"


def test_physical_race_suppresses_preserved_ledger_projection(preserved_stop, monkeypatch, capsys):
    original = status._physical
    calls = 0

    def racing(*args):
        nonlocal calls
        calls += 1
        return original(*args) if calls == 1 else ("running", 11, True, True)

    monkeypatch.setattr(status, "_physical", racing)
    assert status.main(["host-current", WORKFLOW, PINS[3]]) == 3
    assert capsys.readouterr().out == status.NO_GO + "\n"


def test_verifier_rejects_historical_receipt_relabeling(preserved_stop, monkeypatch, capsys):
    assert status.main(["host-current", WORKFLOW, PINS[3]]) == 0
    doc = json.loads(capsys.readouterr().out.removeprefix(status.CURRENT_PREFIX))
    mutations = [
        {**doc, "installed": {**doc["installed"], "operation": doc["ledger"]["operation"]}},
        {**doc, "ledger": {**doc["ledger"], "scope": "CURRENT_INSTALLATION"}},
        {**doc, "ledger": {**doc["ledger"], "schema": True}},
        {**doc, "ledger": {**doc["ledger"], "extra": "PRIVATE"}},
        {
            **doc,
            "ledger": {
                **doc["ledger"],
                "operation": {
                    **doc["ledger"]["operation"],
                    "target": "start",
                },
            },
        },
        {**doc, "installed": {**doc["installed"], "engine": "RUNNING"}},
    ]
    for changed in mutations:
        raw = (
            status.CURRENT_PREFIX
            + json.dumps(changed, separators=(",", ":"), sort_keys=True)
            + "\n"
        )
        monkeypatch.setattr(status.sys, "stdin", io.TextIOWrapper(io.BytesIO(raw.encode())))
        assert status.main(["verify-current", WORKFLOW, PINS[3]]) == 3
        assert capsys.readouterr().out == status.NO_GO + "\n"


def test_no_intent_is_distinct_from_an_unbound_terminal(preserved_stop, capsys):
    path, _, _, _, _, _ = preserved_stop
    with demand.lifecycle._controller_ledger(path) as db, db:
        db.execute("DELETE FROM audit_events")
    assert status.main(["host-current", WORKFLOW, PINS[3]]) == 0
    doc = json.loads(capsys.readouterr().out.removeprefix(status.CURRENT_PREFIX))
    assert doc["ledger"] == {"schema": 1, "scope": "NONE", "operation": None}
    assert doc["installed"]["operation"] is None


def test_controller_diagnostic_parser_refuses_unbounded_or_noncanonical_data(
    preserved_stop, monkeypatch, capsys
):
    _, _, _, current, _, _ = preserved_stop
    good = status._read_current_ledger(current)
    canonical = json.dumps(good, separators=(",", ":"), sort_keys=True) + "\n"
    for raw in (
        canonical * 2,
        canonical.rstrip(),
        " " + canonical,
        canonical.replace('"schema":1', '"schema":1,"schema":1'),
        canonical.replace('"schema":1', '"schema":true'),
        canonical.replace('"scope":', '"extra":"PRIVATE","scope":'),
        "PRIVATE" * 100,
    ):
        monkeypatch.setattr(status.cleanup, "_docker", lambda *args, reply=raw: reply)
        assert status.main(["host-current", WORKFLOW, PINS[3]]) == 3
        assert capsys.readouterr().out == status.NO_GO + "\n"


def test_unbound_start_ack_is_not_accepted_as_historical_stop(preserved_stop, capsys):
    path, ledger, _, _, previous, _ = preserved_stop
    operation = str(uuid4())
    ledger.request("bot", "start", operation, on_demand=True)
    demand._transact(path, operation, previous.fingerprint(), "claim")
    demand._transact(path, operation, previous.fingerprint(), "APPLIED")
    assert status.main(["host-current", WORKFLOW, PINS[3]]) == 3
    assert capsys.readouterr().out == status.NO_GO + "\n"
