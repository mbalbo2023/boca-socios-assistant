"""Owner engine controls keep their form and private inspection boundaries."""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from collections.abc import Mapping
from html import escape
from html.parser import HTMLParser
from uuid import uuid4

import pytest

from boca_socios.panel.members import MemberView


class Page(HTMLParser):
    def __init__(self, body: bytes) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.forms: dict[str, list[tuple[str, dict[str, str | None]]]] = {}
        self.form: str | None = None
        self.text: dict[str, str] = {}
        self.open_elements: list[tuple[str, str | None]] = []
        self.ancestors: dict[str, tuple[str, ...]] = {}
        self.feed(body.decode())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        self.elements.append((tag, attributes))
        if attributes.get("id"):
            self.ancestors[str(attributes["id"])] = tuple(tag for tag, _ in self.open_elements)
        if tag not in {"input", "meta", "link", "br", "hr"}:
            self.open_elements.append((tag, attributes.get("id")))
        if tag == "form":
            assert attributes["method"] == "post"
            self.form = str(attributes["action"])
            assert self.form not in self.forms
            self.forms[self.form] = []
        elif self.form is not None:
            self.forms[self.form].append((tag, attributes))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.open_elements) - 1, -1, -1):
            if self.open_elements[index][0] == tag:
                del self.open_elements[index:]
                break
        if tag == "form":
            self.form = None

    def handle_data(self, data: str) -> None:
        for _, identifier in self.open_elements:
            if identifier is not None:
                self.text[identifier] = self.text.get(identifier, "") + data

    def fields(self, action: str) -> dict[str, dict[str, str | None]]:
        return {
            str(attrs["name"]): attrs
            for tag, attrs in self.forms[action]
            if tag in {"input", "select"}
        }

    def button(self, action: str) -> dict[str, str | None]:
        return next(attrs for tag, attrs in self.forms[action] if tag == "button")


def render(
    *,
    snapshot: Mapping[str, object] | None = None,
    members: tuple[MemberView, ...] | None = None,
    site_url_ready: bool = True,
    csrf: str = "csrf-fixture",
    legacy_operation: str | None = None,
    activity: bool = False,
    engine: str | None = None,
) -> tuple[Page, bytes, dict[str, str]]:
    from boca_socios.panel import engine_view

    operations = {
        f"{engine}:{action}": str(uuid4())
        for engine in ("queues_tokens", "browsers_members")
        for action in ("start", "stop")
    }
    if legacy_operation is not None:
        operations["legacy:stop"] = legacy_operation
    body = engine_view.page(
        snapshot or {"version": 1, "engines": []},
        csrf,
        operations,
        (MemberView(str(uuid4()), "Socio de prueba", "s•••@example.invalid", True),)
        if members is None
        else members,
        site_url_ready=site_url_ready,
        engine=engine,
    )
    if activity:
        from boca_socios.panel.private_ui import worker_activity
        from boca_socios.panel.worker_activity import WorkerActivitySnapshot

        body = worker_activity(
            WorkerActivitySnapshot("2026-11-16T12:00:00Z", "fixed_stages_only", "missing", ()),
            engine_snapshot=snapshot or {"version": 1, "engines": []},
            members=members or (),
        )
    return Page(body), body, operations


@pytest.mark.parametrize("engine", ["queues_tokens", "browsers_members"])
def test_filtered_page_poll_handles_absent_other_engine_dom(engine):
    snapshot = {
        "version": 1,
        "observed_at": "2026-11-17T18:00:00Z",
        "context_limit": 50,
        "engines": [
            {
                "engine": name,
                "state": "STARTING",
                "phase": "WORKER_RECEIPT_UNVERIFIED",
                "updated_at": "2026-11-17T17:00:00Z",
                "requested_contexts": 3,
                "created": 0,
                "active": 0,
                "closed": 0,
                "failed": 0,
                "sessions": [],
            }
            for name in ("queues_tokens", "browsers_members")
        ],
    }
    actual = _run_poll_script([snapshot], mode=engine)
    assert actual["status"] == "Estados y sesiones actualizados."
    assert actual["requests"][0]["url"] == "/control/motores.json"
    assert "15:00:00" in actual["results"][0]["checked"]
    if engine == "queues_tokens":
        assert "14:00:00" in actual["results"][0]["updated"]
        assert actual["results"][0]["state"] == "Iniciando"
    page, body, _ = render(snapshot=snapshot, engine=engine)
    assert page.text[f"{engine}-phase"] == "Arranque del navegador sin confirmar"
    assert page.text[f"{engine}-requested_contexts"] == "3"
    assert page.text[f"{engine}-created"] == page.text[f"{engine}-active"] == "0"
    assert "Múltiples contextos concurrentes" in body.decode()
    assert (
        "Reserva real y capturas terminales no están implementadas" in body.decode()
        if engine == "browsers_members"
        else True
    )


def test_queue_page_links_to_existing_private_reveal_without_leaking_bearer():
    session_id = str(uuid4())
    snapshot = {
        "engines": [
            {
                "engine": "queues_tokens",
                "sessions": [
                    {
                        "session_id": session_id,
                        "browser": "chromium",
                        "has_target_url": True,
                        "display_url": "https://example.invalid/queue?queueittoken=private-fixture",
                        "observed_at": "2026-11-17T17:00:00Z",
                        "phase": "NO_EVENT_OBSERVED",
                    }
                ],
            }
        ]
    }
    page, body, _ = render(snapshot=snapshot, engine="queues_tokens")
    assert b"private-fixture" not in body
    assert any(
        tag == "a" and attrs.get("href") == f"/control/sesiones/{session_id}"
        for tag, attrs in page.elements
    )
    links = [
        attrs
        for tag, attrs in page.elements
        if tag == "a" and attrs.get("href") == f"/control/sesiones/{session_id}"
    ]
    assert len(links) == 2
    assert links[0]["id"] == "queues_tokens-live-inspect"
    assert links[1]["data-field"] == "inspect"
    assert "Ver y copiar token/URL de la sesión 1" in body.decode()
    assert "La página informa que no hay eventos disponibles" in body.decode()
    assert b"queueittoken=" not in body


def test_live_session_rotation_has_only_current_private_links_and_truthful_copy_labels():
    ids = [str(uuid4()) for _ in range(3)]
    first = _evidence_snapshot(
        {
            "session_id": ids[0],
            "browser": "chromium",
            "has_target_url": True,
        }
    )
    first["engines"][0]["sessions"].append(
        {
            "session_id": ids[1],
            "browser": "firefox",
            "has_target_url": False,
        }
    )
    second = _evidence_snapshot(
        {
            "session_id": ids[2],
            "browser": "webkit",
            "has_target_url": False,
        }
    )
    actual = _run_poll_script([first, second], mode="queues_tokens", rotation=True)
    assert actual["results"][0]["inspectionLinks"] == [
        {
            "href": f"/control/sesiones/{ids[0]}",
            "label": "Ver y copiar token/URL de la sesión 1 de colas y tokens",
        },
        {"href": f"/control/sesiones/{ids[1]}", "label": "Inspeccionar sesión 2 de colas y tokens"},
    ]
    assert actual["results"][1]["inspectionLinks"] == [
        {"href": f"/control/sesiones/{ids[2]}", "label": "Inspeccionar sesión 1 de colas y tokens"},
    ]
    for snapshot in (first, second):
        page, body, _ = render(snapshot=snapshot, engine="queues_tokens")
        sessions = snapshot["engines"][0]["sessions"]
        links = [
            attrs
            for tag, attrs in page.elements
            if tag == "a" and attrs.get("data-field") == "inspect"
        ]
        assert len(links) == len(sessions)
        assert "queueittoken=" not in body.decode()
    assert actual["clipboard"] == actual["selects"] == 0


@pytest.mark.parametrize("engine", ["queues_tokens", "browsers_members"])
def test_dedicated_engine_shows_received_distribution_not_next_start_defaults(engine):
    first = {
        "version": 1,
        "observed_at": "2026-11-17T18:00:00Z",
        "context_limit": 50,
        "engines": [
            {
                "engine": engine,
                "state": "RUNNING",
                "requested_contexts": 10,
                "created": 4,
                "active": 3,
                "closed": 0,
                "failed": 0,
                "sessions": [],
                "counts": {"chromium": 7, "firefox": 2, "webkit": 1},
            }
        ],
    }
    second = copy.deepcopy(first)
    second["engines"][0].update(
        counts={"chromium": 1, "firefox": 8, "webkit": 2},
        requested_contexts=11,
        created=6,
        active=5,
    )
    parsed, body, _ = render(snapshot=first, engine=engine)
    assert parsed.text[f"{engine}-counts"] == "Chromium: 7 · Firefox: 2 · WebKit: 1"
    assert parsed.text[f"{engine}-created"] == "4"
    assert parsed.text[f"{engine}-active"] == "3"
    assert "Sin desglose verificable de creados/activos por tipo de navegador" in body.decode()
    fields = parsed.fields(f"/control/motores/{engine}/iniciar")
    assert [fields[kind]["value"] for kind in ("chromium", "firefox", "webkit")] == [
        "15",
        "5",
        "5",
    ]
    actual = _run_poll_script([first, second], mode=engine)
    assert [result["distribution"][engine] for result in actual["results"]] == [
        "Chromium: 7 · Firefox: 2 · WebKit: 1",
        "Chromium: 1 · Firefox: 8 · WebKit: 2",
    ]
    assert [result["contextTotals"][engine] for result in actual["results"]] == [
        {"created": "4", "active": "3"},
        {"created": "6", "active": "5"},
    ]
    assert all(
        result["status"] == "Estados y sesiones actualizados." for result in actual["results"]
    )


@pytest.mark.parametrize("engine", ["queues_tokens", "browsers_members"])
def test_cold_engine_does_not_claim_default_counts_are_received_requests(engine):
    snapshot = {
        "version": 1,
        "observed_at": "2026-11-17T18:00:00Z",
        "context_limit": 50,
        "engines": [
            {
                "engine": engine,
                "state": "STOPPED",
                "activation_id": None,
                "requested_contexts": 0,
                "created": 0,
                "active": 0,
                "closed": 0,
                "failed": 0,
                "sessions": [],
                "counts": {"chromium": 15, "firefox": 5, "webkit": 5},
            }
        ],
    }
    parsed, _, _ = render(snapshot=snapshot, engine=engine)
    assert parsed.text[f"{engine}-counts"] == "Sin solicitudes verificadas"
    actual = _run_poll_script([snapshot], mode=engine)
    assert actual["results"][0]["distribution"][engine] == "Sin solicitudes verificadas"


@pytest.mark.parametrize(
    "engine,title",
    [
        ("queues_tokens", "Motor A · Colas y tokens"),
        ("browsers_members", "Motor B · Navegadores y socios"),
    ],
)
def test_engine_destination_identifies_itself_with_its_own_heading(engine, title):
    _, body, _ = render(engine=engine)
    assert f"<h1>{title}</h1>".encode() in body


def test_start_forms_scope_member_and_counts_to_the_chosen_engine() -> None:
    page, _, operations = render()

    assert set(page.forms) == {
        "/control/motores/queues_tokens/iniciar",
        "/control/motores/queues_tokens/detener",
        "/control/motores/browsers_members/iniciar",
        "/control/motores/browsers_members/detener",
    }
    labels = {attrs.get("for") for tag, attrs in page.elements if tag == "label"}
    ids = [attrs["id"] for _, attrs in page.elements if "id" in attrs]
    assert len(ids) == len(set(ids))
    for engine in ("queues_tokens", "browsers_members"):
        fields = page.fields(f"/control/motores/{engine}/iniciar")
        expected = {"csrf", "operation_id", "chromium", "firefox", "webkit"}
        if engine == "browsers_members":
            expected.add("member_id")
            assert "required" in fields["member_id"]
            assert fields["member_id"]["id"] in labels
        assert set(fields) == expected
        assert fields["csrf"]["value"] == "csrf-fixture"
        assert fields["operation_id"]["value"] == operations[f"{engine}:start"]
        for browser, count in (("chromium", "15"), ("firefox", "5"), ("webkit", "5")):
            assert fields[browser]["value"] == count
            assert fields[browser]["type"] == "number"
            assert fields[browser]["min"] == "0"
            assert fields[browser]["max"] == "50"
            assert "required" in fields[browser]
            assert fields[browser]["id"] in labels


def test_session_evidence_stays_readable_with_native_details_closed():
    from boca_socios.panel.engine_view import _SESSION_LABELS

    session_id = str(uuid4())
    snapshot = _evidence_snapshot(
        {
            "session_id": session_id,
            "browser": "chromium",
            "state": "CLOSED",
            "phase": "unknown-sensitive-marker",
            "event_state": "NO_EVENT_CONFIRMED",
            "queue_state": "QUEUE_INACTIVE",
            "has_auth": True,
        }
    )
    _, page, _ = render(snapshot=snapshot, activity=True)
    row = re.search(
        rf'<li class="engine-session" data-session-id="{session_id}">(.*?)</li>',
        page.decode(),
        re.S,
    )
    assert row is not None
    details = re.search(r"<details>(<summary[^>]*>.*?</summary>)(.*?)</details>", row[1], re.S)
    assert details is not None and "sesión 1" in details[1].lower() and "Chromium" in details[1]
    assert re.findall(r'<dd data-field="([^"]+)"', details[2]) == list(_SESSION_LABELS)
    visible = row[1].replace(details[0], "")
    assert '<h4 data-field="title">' in visible and 'data-field="inspect"' in visible
    assert set(re.findall(r'data-summary-field="([^"]+)"', visible)) == {
        "state",
        "phase",
        "observed_at",
        "event_state",
        "queue_state",
        "has_target_url",
        "has_auth",
    }
    assert "histórica" in visible and "no hay eventos" in visible and "no confirma" in visible
    assert "unknown-sensitive-marker" not in visible


def test_each_stop_form_carries_its_own_activation_fence() -> None:
    activations = {"queues_tokens": str(uuid4()), "browsers_members": str(uuid4())}
    page, _, operations = render(
        snapshot={
            "version": 1,
            "engines": [
                {"engine": engine, "state": "RUNNING", "activation_id": activation, "generation": n}
                for n, (engine, activation) in enumerate(activations.items(), 1)
            ],
        },
        site_url_ready=False,
    )

    for n, (engine, activation) in enumerate(activations.items(), 1):
        action = f"/control/motores/{engine}/detener"
        fields = page.fields(action)
        assert set(fields) == {"csrf", "operation_id", "activation_id", "generation"}
        assert fields["operation_id"]["value"] == operations[f"{engine}:stop"]
        assert fields["activation_id"]["value"] == activation
        assert fields["generation"]["value"] == str(n)
        assert "disabled" not in page.button(action)


def test_current_member_comes_from_activation_without_preselecting_next_start() -> None:
    members = (
        MemberView(str(uuid4()), "Primer socio", "p•••@example.invalid", True),
        MemberView(str(uuid4()), "Segundo socio", "s•••@example.invalid", True),
    )
    page, _, _ = render(
        members=members,
        snapshot={
            "version": 1,
            "engines": [
                {
                    "engine": "browsers_members",
                    "state": "RUNNING",
                    "member_id": members[1].member_id,
                }
            ],
        },
    )

    assert page.text["browsers_members-current-member"] == "Segundo socio · s•••@example.invalid"
    selected = [attrs for tag, attrs in page.elements if tag == "option" and "selected" in attrs]
    assert len(selected) == 1 and selected[0]["value"] == ""


@pytest.mark.parametrize(
    ("state", "can_start", "disabled"), [("UNCERTAIN", True, False), ("STOPPED", False, True)]
)
def test_start_obeys_explicit_read_only_restart_readiness(state, can_start, disabled) -> None:
    activation = str(uuid4())
    snapshot = {
        "version": 1,
        "engines": [
            {
                "engine": "queues_tokens",
                "state": state,
                "can_start": can_start,
                "activation_id": activation,
                "generation": 3,
            }
        ],
    }
    original = copy.deepcopy(snapshot)
    page, _, _ = render(snapshot=snapshot)

    assert ("disabled" in page.button("/control/motores/queues_tokens/iniciar")) is disabled
    fields = page.fields("/control/motores/queues_tokens/detener")
    assert fields["activation_id"]["value"] == activation
    assert fields["generation"]["value"] == "3"
    assert snapshot == original


@pytest.mark.parametrize("site_url_ready", [False, True])
def test_missing_active_member_disables_only_the_applicable_start(site_url_ready: bool) -> None:
    revoked = MemberView(str(uuid4()), "Revocado", "r•••@example.invalid", False)
    page, _, _ = render(members=(revoked,), site_url_ready=site_url_ready)

    queue_button = page.button("/control/motores/queues_tokens/iniciar")
    assert ("disabled" not in queue_button) is site_url_ready
    assert "disabled" in page.button("/control/motores/browsers_members/iniciar")
    for engine in ("queues_tokens", "browsers_members"):
        assert "disabled" in page.button(f"/control/motores/{engine}/detener")
    assert all(
        attrs.get("value") != revoked.member_id for tag, attrs in page.elements if tag == "option"
    )


def test_member_and_snapshot_text_cannot_create_markup_or_expose_extra_secret_fields() -> None:
    attack = '"><img src=x onerror="bad()">'
    member = MemberView(str(uuid4()), attack, "m•••@example.invalid", True)
    page, body, _ = render(
        members=(member,),
        csrf=attack,
        snapshot={
            "version": 1,
            "engines": [
                {
                    "engine": "queues_tokens",
                    "state": "RUNNING",
                    "phase": attack,
                    "sessions": [{"session_id": str(uuid4()), "phase": attack}],
                    "token": "not-for-aggregate-display",
                }
            ],
        },
    )

    assert not any(tag == "img" for tag, _ in page.elements)
    assert all(not key.startswith("on") for _, attrs in page.elements for key in attrs)
    assert page.fields("/control/motores/queues_tokens/iniciar")["csrf"]["value"] == attack
    assert b"not-for-aggregate-display" not in body
    options = [attrs for tag, attrs in page.elements if tag == "option"]
    assert any(attrs.get("value") == member.member_id for attrs in options)
    assert any(attrs.get("value") == "" and "selected" in attrs for attrs in options)


def test_inspection_links_use_only_valid_private_session_identities() -> None:
    session_id = str(uuid4())
    page, body, _ = render(
        activity=True,
        snapshot={
            "version": 1,
            "engines": [
                {
                    "engine": "queues_tokens",
                    "state": "RUNNING",
                    "sessions": [
                        {
                            "session_id": session_id,
                            "browser": "chromium",
                            "display_url": "https://queue.example.invalid/path?bearer=secret#pass",
                        },
                        {"session_id": "../../configuracion", "browser": "firefox"},
                    ],
                }
            ],
        },
    )

    links = [attrs["href"] for tag, attrs in page.elements if tag == "a" and "href" in attrs]
    assert f"/control/sesiones/{session_id}" in links
    assert not any(str(link).startswith("https:") or "../" in str(link) for link in links)
    assert b"bearer=secret" not in body
    assert b"#pass" not in body
    assert b"https://queue.example.invalid/path" in body


@pytest.mark.parametrize("session_count", [0, 2, 50])
def test_control_stays_short_and_activity_owns_histories(session_count: int) -> None:
    engines = ("queues_tokens", "browsers_members")
    identities = {engine: [str(uuid4()) for _ in range(session_count // 2)] for engine in engines}
    snapshot = {
        "version": 1,
        "engines": [
            {
                "engine": engine,
                "state": "RUNNING",
                "sessions": [
                    {"session_id": identity, "browser": "chromium"}
                    for identity in identities[engine]
                ],
            }
            for engine in engines
        ],
    }
    control, control_body, _ = render(snapshot=snapshot)
    assert len(control.forms) == 4
    assert all(b'id="' + engine.encode() + b'-sessions"' not in control_body for engine in engines)
    page, body, _ = render(snapshot=snapshot, activity=True)
    assert not page.forms
    for engine, label in zip(engines, ("colas y tokens", "navegadores de socios"), strict=True):
        summary = (
            f'<details class="activity-motor-details" id="{engine}-advanced">'
            f"<summary>Sesiones y métricas del motor {'A' if engine == 'queues_tokens' else 'B'}</summary>"
        ).encode()
        assert body.count(summary) == 1
        heading = f"<h3>Sesiones de {label}</h3>".encode()
        assert body.index(f'id="{engine}-live-card"'.encode()) < body.index(summary)
        assert body.index(summary) < body.index(heading)
        assert body.index(heading) < body.index(f'id="{engine}-sessions"'.encode())
        assert "details" in page.ancestors[f"{engine}-sessions"]
    rows = [
        attrs["data-session-id"]
        for tag, attrs in page.elements
        if tag == "li" and "data-session-id" in attrs
    ]
    assert rows == [identity for engine in engines for identity in identities[engine]]
    links = [
        attrs["href"]
        for tag, attrs in page.elements
        if tag == "a" and attrs.get("data-field") == "inspect"
    ]
    assert links == [f"/control/sesiones/{identity}" for identity in rows]
    assert sum(tag == "h4" for tag, _ in page.elements) == session_count
    assert b'id="worker-events"' in body
    assert all(f'id="{engine}-state"'.encode() in body for engine in engines)


_OBSERVATION_TEXT_CASES = (
    ("QUEUE_ACTIVE", "Cola activa observada"),
    ("PREQUEUE", "Prefila observada"),
    ("QUEUE_INACTIVE", "La página informa que la cola no está activa"),
    ("NO_EVENT_OBSERVED", "La página informa que no hay eventos disponibles"),
    ("TARGET_OBSERVED", "Enlace de acceso recibido"),
    ("ACCESS_OBSERVED", "Enlace de acceso recibido"),
    ("CHALLENGE", "La página requiere intervención del titular"),
    ("UNKNOWN", "Sin señales suficientes para determinar evento o cola"),
    ("CHECK_FAILED", "No se pudo completar la comprobación"),
    (None, "Sin dato"),
    (0, "Sin dato"),
    (False, "Sin dato"),
    ([], "Sin dato"),
    (["QUEUE_ACTIVE"], "Sin dato"),
    ({}, "Sin dato"),
    ({"toString": "QUEUE_ACTIVE"}, "Sin dato"),
    ("UNRECOGNIZED_FROM_PAGE", "Sin dato"),
    ("", "Sin dato"),
    ("__proto__", "Sin dato"),
    ("constructor", "Sin dato"),
)


@pytest.mark.parametrize(("value", "expected"), _OBSERVATION_TEXT_CASES)
def test_initial_observation_labels_accept_only_recognized_strings(value, expected) -> None:
    _, body, _ = render(
        activity=True,
        snapshot={
            "version": 1,
            "engines": [
                {
                    "engine": "queues_tokens",
                    "sessions": [
                        {
                            "session_id": str(uuid4()),
                            "outcome": value,
                            "queue_state": value,
                            "phase": "UNLISTED_PHASE",
                        }
                    ],
                }
            ],
        },
    )

    for field in ("outcome", "queue_state"):
        assert f'data-field="{field}">{expected}</dd>'.encode() in body
    assert b'data-field="phase">UNLISTED_PHASE</dd>' in body


@pytest.mark.parametrize(
    ("state", "hidden", "disabled"),
    [
        ("REQUIRED", False, False),
        ("REQUESTED", False, False),
        ("CLAIMED", False, False),
        ("NONE", True, True),
    ],
)
def test_previous_worker_recovery_uses_only_existing_scoped_stop_form(state, hidden, disabled):
    operation = str(uuid4())
    snapshot = {"version": 1, "engines": [], "legacy_recovery_state": state}
    before = copy.deepcopy(snapshot)
    page, _, _ = render(snapshot=snapshot, csrf="owner-proof", legacy_operation=operation)

    attributes = next(
        attrs for tag, attrs in page.elements if attrs.get("id") == "legacy-worker-recovery"
    )
    assert ("hidden" in attributes) is hidden
    fields = page.fields("/control/bot/detener")
    assert set(fields) == {"csrf", "operation_id"}
    assert fields["csrf"]["value"] == "owner-proof"
    assert fields["operation_id"]["value"] == operation
    assert ("disabled" in page.button("/control/bot/detener")) is disabled
    assert len(page.forms) == 5
    assert snapshot == before


def test_old_fixture_without_legacy_operation_has_only_four_engine_forms():
    page, _, _ = render(snapshot={"version": 1, "engines": [], "legacy_recovery_state": "REQUIRED"})
    assert len(page.forms) == 4
    assert "/control/bot/detener" not in page.forms
    assert not any(attrs.get("id") == "legacy-worker-recovery" for _, attrs in page.elements)


def test_received_queue_size_and_service_estimate_are_present_without_computation():
    _, body, _ = render(
        activity=True,
        snapshot={
            "version": 1,
            "engines": [
                {
                    "engine": "queues_tokens",
                    "state": "RUNNING",
                    "sessions": [
                        {
                            "session_id": str(uuid4()),
                            "queue_size": 2034,
                            "expected_service_time": "2030-01-01T13:45:00Z <dato recibido>",
                        }
                    ],
                }
            ],
        },
    )
    assert b'data-field="queue_size">2034</dd>' in body
    assert (
        b'data-field="expected_service_time">2030-01-01T13:45:00Z &lt;dato recibido&gt;</dd>'
        in body
    )


def _run_poll_script(snapshots, *, present=True, session_id=None, mode="combined", rotation=False):
    from boca_socios.panel import engine_view

    node = shutil.which("node")
    assert node is not None
    identifiers = None
    script = engine_view._SCRIPT
    if mode != "combined":
        parsed, rendered, _ = render(
            snapshot=snapshots[0],
            activity=mode == "activity",
            engine=mode if mode in {"queues_tokens", "browsers_members"} else None,
        )
        identifiers = [attrs["id"] for _, attrs in parsed.elements if "id" in attrs]
        script = "\n".join(re.findall(r"<script>(.*?)</script>", rendered.decode(), re.S))
    harness = r"""
const vm = require('node:vm');
const input = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const elements = new Map();
let snapshot;
function element(id) {
  if (id === 'legacy-worker-recovery' && !input.present) return null;
  if (!elements.has(id)) elements.set(id, {
    textContent: '', hidden: true, disabled: true, children: [],
    dataset: {ready: 'true'}, fields: new Map(),
    replaceChildren(...children) { this.children = children; },
    append(...children) { this.children.push(...children); },
    setAttribute(name, value) { this[name] = value; },
    addEventListener(name, callback) { this[name] = callback; },
    get elements() { return {namedItem: name => {
      if (!this.fields.has(name)) this.fields.set(name, {value: 'original-' + name,
        select() { selects++; }, focus() { context.document.activeElement = this; }});
      return this.fields.get(name);
    }}; }
  });
  return elements.get(id);
}
let row = null;
if (input.session_id) {
  row = {dataset: {sessionId: input.session_id}, fields: new Map(),
    querySelector(selector) {
      if (!this.fields.has(selector)) this.fields.set(selector, {textContent: ''});
      return this.fields.get(selector);
    },
    remove() { throw new Error('existing observation row removed'); }
  };
  element('queues_tokens-sessions').children = [row];
}
const operation = element('legacy-worker-recovery-form').elements.namedItem('operation_id');
const form = element('queues_tokens-start');
const count = form.elements.namedItem('chromium');
const engineOperation = form.elements.namedItem('operation_id');
const member = element('browsers_members-member');
member.value = 'owner-member-selection';
const sessionLink = row ? row.querySelector('[data-field="inspect"]') : null;
if (sessionLink) sessionLink.href = '/control/sesiones/' + input.session_id;
const requests = [];
const intervals = [];
let clipboard = 0;
let selects = 0;
const context = {
  document: {hidden: true, activeElement: count, getElementById(id) {
    if (input.identifiers && !input.identifiers.includes(id)) return null;
    return element(id);
  }, addEventListener() {},
    createElement(tag) {
      if (input.rotation) return {
        tag, dataset: {}, children: [], textContent: '',
        append(...children) { this.children.push(...children); },
        querySelector(selector) {
          const match = selector.match(/data-(summary-)?field="([^"]+)"/);
          const find = node => (match ? node.dataset[match[1] ? 'summaryField' : 'field'] === match[2] : node.tag === selector) ? node :
            node.children.map(find).find(Boolean);
          return find(this);
        },
        remove() {
          for (const node of elements.values()) {
            node.children = node.children.filter(child => child !== this);
          }
        }
      };
      if (input.mode === 'activity' && tag === 'li') return {textContent: ''};
      throw new Error('existing row replaced');
    }},
  navigator: {clipboard: {writeText() { clipboard++; }}},
  select() { selects++; },
  setInterval(callback, ms) { intervals.push(ms); }, URL,
  fetch: async (url, options) => {
    requests.push({url, options});
    if (url === '/control/actividad.json') return {ok: true, json: async () => ({
      events: [{at: '2026-11-15T15:00:00Z', source: 'host', message: 'Acuse no verificado'}],
      observed_at: '2026-11-15T16:00:00Z', chromium_telemetry: 'degraded'})};
    if (snapshot === 'network-error') throw new Error('offline fixture');
    return {ok: true, json: async () => snapshot};
  }
};
vm.runInNewContext(input.script, context, {timeout: 1000});
(async () => {
  const results = [];
  let opened, focused;
  for (snapshot of input.snapshots) {
    await element('engines-refresh').click();
    const section = element('legacy-worker-recovery');
    const result = {recovery: section ? {hidden: section.hidden,
      disabled: element('legacy-worker-recovery-button').disabled} : null,
      status: element('engines-live').textContent,
      state: element('queues_tokens-state').textContent,
      phase: element('queues_tokens-phase').textContent,
      checked: element('engines-checked').textContent,
      updated: element('queues_tokens-updated').textContent,
      currentMember: element('browsers_members-current-member').textContent,
      startDisabled: element('queues_tokens-start-button').disabled,
      startReason: element('queues_tokens-start-reason').textContent};
    result.distribution = Object.fromEntries(['queues_tokens', 'browsers_members']
      .map(engine => [engine, element(engine + '-counts').textContent]));
    result.contextTotals = Object.fromEntries(['queues_tokens', 'browsers_members']
      .map(engine => [engine, {created: element(engine + '-created').textContent,
        active: element(engine + '-active').textContent}]));
    result.cards = Object.fromEntries(['queues_tokens', 'browsers_members']
      .map(engine => [engine, Object.fromEntries(['state', 'error', 'navigation',
        'configured-url', 'final-url', 'event', 'queue', 'tokens', 'motor-status']
        .map(field => [field, element(engine + '-live-' + field).textContent]))]));
    result.sessionCounts = Object.fromEntries(['queues_tokens', 'browsers_members']
      .map(engine => [engine, element(engine + '-sessions').children.length]));
    if (input.rotation) result.inspectionLinks = element('queues_tokens-sessions').children
      .map(item => {const link = item.querySelector('[data-field="inspect"]');
        return {href: link.href, label: link.textContent};});
    if (input.rotation) {
      const rows = element('queues_tokens-sessions').children;
      if (!opened && rows.length && rows[0].querySelector('details')) {
        opened = rows[0].querySelector('details'); opened.open = true;
        focused = rows[0].querySelector('summary'); context.document.activeElement = focused;
      }
      result.disclosures = rows.map(r => ({
        id: r.dataset.sessionId, open: Boolean(r.querySelector('details')?.open),
        retained: r.querySelector('details') === opened && opened !== undefined,
        focused: r.querySelector('summary') === context.document.activeElement,
        state: r.querySelector('[data-summary-field="state"]')?.textContent
      }));
    }
    if (row) for (const field of ['outcome', 'queue_state', 'phase', 'event_state', 'event_id',
      'reason', 'configured_url', 'navigation_attempt', 'display_url', 'inspect',
      'queue_opening_at', 'countdown', 'expected_service_time']) {
      result[field] = row.querySelector('[data-field="' + field + '"]').textContent;
    }
    results.push(result);
  }
  process.stdout.write(JSON.stringify({results, operation: operation.value,
    status: element('engines-live').textContent, requests, clipboard, selects, intervals,
    timeline: element('worker-activity-status').textContent,
    retained: {row: element('queues_tokens-sessions').children[0] === row,
      form: element('queues_tokens-start') === form,
      engineOperation: form.elements.namedItem('operation_id') === engineOperation,
      operationValue: engineOperation.value,
      focus: context.document.activeElement === count, count: count.value,
      member: member.value, href: sessionLink && sessionLink.href}}));
})().catch(() => {process.exitCode = 1;});
"""
    completed = subprocess.run(  # noqa: S603 - actual static UI script, fixed offline DOM only
        [node, "-e", harness],
        input=json.dumps(
            {
                "script": script,
                "identifiers": identifiers,
                "present": present,
                "session_id": session_id,
                "snapshots": snapshots,
                "mode": mode,
                "rotation": rotation,
            }
        ),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return json.loads(completed.stdout)


def test_keyed_session_keeps_open_disclosure_and_focus_while_new_session_stays_closed():
    first, second = str(uuid4()), str(uuid4())
    snapshots = [_evidence_snapshot({"session_id": first, "state": "ACTIVE"})]
    newer = copy.deepcopy(snapshots[0])
    newer["engines"][0]["sessions"][0]["state"] = "CLOSED"
    newer["engines"][0]["sessions"].append({"session_id": second, "state": "ACTIVE"})
    last = copy.deepcopy(newer)
    last["engines"][0]["sessions"].pop(0)
    before, after, removed = _run_poll_script([*snapshots, newer, last], rotation=True)["results"]
    assert before["disclosures"][0]["open"] and before["disclosures"][0]["focused"]
    older, added = after["disclosures"]
    assert (
        older["retained"] and older["open"] and older["focused"] and "histórica" in older["state"]
    )
    assert added["id"] == second and not added["open"] and not added["focused"]
    assert [r["id"] for r in removed["disclosures"]] == [second]


def test_failed_poll_marks_visible_session_summary_historical_and_recovers_without_closing_it():
    snap = _evidence_snapshot({"session_id": str(uuid4()), "state": "ACTIVE"})
    results = _run_poll_script([snap, "network-error", "network-error", snap], rotation=True)[
        "results"
    ]
    rows = [result["disclosures"][0] for result in results]
    assert rows[0]["state"] == rows[3]["state"] == "Activa"
    assert "histórica" in rows[1]["state"] and rows[1]["state"] == rows[2]["state"]
    assert all(row["open"] and row["focused"] for row in rows)


def test_duplicate_or_invalid_session_ids_never_create_duplicate_disclosures():
    ident = str(uuid4())
    snap = _evidence_snapshot({"session_id": ident, "state": "ACTIVE"})
    snap["engines"][0]["sessions"] += [{"session_id": ident}, {"session_id": "invalid"}]
    parsed, _, _ = render(snapshot=snap, activity=True)
    assert [
        attrs.get("data-session-id")
        for tag, attrs in parsed.elements
        if tag == "li" and "data-session-id" in attrs
    ] == [ident]
    polled = _run_poll_script([snap], rotation=True)["results"][0]["disclosures"]
    assert [row["id"] for row in polled] == [ident]


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (90061, "25 h 01 min 01 s"),
        (61, "00 h 01 min 01 s"),
        (0, "Hora informada alcanzada; pendiente de confirmación de la página"),
        (None, "Sin fecha de apertura vigente"),
        (-1, "Sin fecha de apertura vigente"),
        (True, "Sin fecha de apertura vigente"),
        (1.1, "Sin fecha de apertura vigente"),
        ("61", "Sin fecha de apertura vigente"),
    ],
)
def test_opening_initial_and_actual_poll_show_same_art_duration_and_no_phase_change(
    seconds, expected
):
    session_id = str(uuid4())
    session = {
        "session_id": session_id,
        "queue_opening_at": "2026-11-15T18:05:07+00:00",
        "countdown": seconds,
        "outcome": "PREQUEUE",
        "phase": "PREQUEUE",
        "expected_service_time": "ETA unchanged",
    }
    snapshot = _evidence_snapshot(session)
    _, body, _ = render(snapshot=snapshot, activity=True)
    assert b"Tiempo estimado hasta la apertura informada" in body
    assert ('data-field="countdown">' + expected + "</dd>").encode() in body
    assert b'data-field="queue_opening_at">2026-11-15 15:05:07 ART</dd>' in body
    polled = _run_poll_script([snapshot], session_id=session_id)["results"][0]
    assert polled["countdown"] == expected
    assert polled["queue_opening_at"] == "2026-11-15 15:05:07 ART"
    assert polled["expected_service_time"] == "ETA unchanged"
    assert polled["phase"] == polled["outcome"] == "Prefila observada"


@pytest.mark.parametrize("failure", ["network-error", {"version": 999}])
def test_failed_poll_removes_live_countdown_and_recovers_without_focus_or_timer_changes(failure):
    from boca_socios.panel import engine_view

    session_id = str(uuid4())
    snapshot = _evidence_snapshot(
        {"session_id": session_id, "countdown": 61, "queue_opening_at": "2026-11-15T18:05:07+00:00"}
    )
    actual = _run_poll_script([snapshot, failure, snapshot], session_id=session_id)
    assert [item["countdown"] for item in actual["results"]] == [
        "00 h 01 min 01 s",
        "Sin fecha de apertura vigente",
        "00 h 01 min 01 s",
    ]
    assert actual["results"][1]["queue_opening_at"] == "2026-11-15 15:05:07 ART"
    assert actual["retained"]["focus"] and actual["retained"]["row"]
    assert actual["clipboard"] == actual["selects"] == 0
    assert engine_view._SCRIPT.count("setInterval(") == 1


@pytest.mark.parametrize("present", [True, False])
def test_actual_poll_script_updates_optional_recovery_without_replacing_its_operation(present):
    snapshots = [
        {
            "version": 1,
            "observed_at": "2020-01-01T12:00:00Z",
            "context_limit": 50,
            "engines": [],
            "legacy_recovery_state": state,
        }
        for state in ("NONE", "REQUIRED", "REQUESTED", "CLAIMED", "NONE")
    ]
    result = _run_poll_script(snapshots, present=present)
    expected = [
        {"hidden": True, "disabled": True},
        {"hidden": False, "disabled": False},
        {"hidden": False, "disabled": False},
        {"hidden": False, "disabled": False},
        {"hidden": True, "disabled": True},
    ]
    assert [item["recovery"] for item in result["results"]] == (expected if present else [None] * 5)
    assert result["operation"] == "original-operation_id"
    assert "históricos" not in result["status"]


def test_actual_poll_script_translates_observations_without_value_coercion() -> None:
    session_id = str(uuid4())
    snapshots = [
        {
            "version": 1,
            "observed_at": "2020-01-01T12:00:00Z",
            "context_limit": 50,
            "engines": [
                {
                    "engine": "queues_tokens",
                    "state": "RUNNING",
                    "requested_contexts": 1,
                    "created": 1,
                    "active": 1,
                    "closed": 0,
                    "failed": 0,
                    "sessions": [
                        {
                            "session_id": session_id,
                            "outcome": value,
                            "queue_state": value,
                            "phase": "UNLISTED_PHASE",
                        }
                    ],
                }
            ],
        }
        for value, _ in _OBSERVATION_TEXT_CASES
    ]
    result = _run_poll_script(snapshots, session_id=session_id)

    for actual, (_, expected) in zip(result["results"], _OBSERVATION_TEXT_CASES, strict=True):
        assert actual["status"] == "Estados y sesiones actualizados."
        assert actual["outcome"] == expected
        assert actual["queue_state"] == expected
        assert actual["phase"] == "UNLISTED_PHASE"


_EVENT_CASES = (
    ("EVENT_ANNOUNCED", "Identificador de evento recibido; faltan señales de cola o acceso"),
    ("EVENT_VERIFIED", "Evento identificado en la observación de la página"),
    ("NO_EVENT_CONFIRMED", "La página informa explícitamente que no hay eventos"),
    ("UNRECOGNIZED", "No se pudo identificar un evento con esta muestra"),
)
_REASON_CASES = (
    ("VISIBLE_CHALLENGE", "Intervención requerida"),
    ("CHECK_FAILED", "Comprobación fallida"),
    ("HTTP_FAILURE", "Respuesta HTTP de error"),
    ("INVALID_OBSERVATION", "Muestra no interpretable"),
    ("CONTRADICTORY_EVIDENCE", "Señales contradictorias"),
    ("RECEIVED_TARGET", "Enlace de acceso recibido"),
    ("OBSERVED_IDLE", "Cola inactiva observada"),
    ("OBSERVED_PREQUEUE", "Prefila observada"),
    ("OBSERVED_QUEUE", "Cola observada"),
    ("EXPLICIT_NO_EVENTS", "Ausencia declarada por la página"),
    ("EVENT_ID_OBSERVED", "ID recibido sin otras señales"),
    ("NO_RECOGNIZED_EVIDENCE", "Sin señales reconocidas"),
)


def _evidence_snapshot(session):
    return {
        "version": 1,
        "context_limit": 50,
        "observed_at": "2026-11-15T16:00:00Z",
        "engines": [
            {
                "engine": "queues_tokens",
                "state": "RUNNING",
                "requested_contexts": 1,
                "created": 1,
                "active": 1,
                "closed": 0,
                "failed": 0,
                "sessions": [session],
            }
        ],
    }


def test_activity_poll_updates_two_live_cards_and_session_rows_from_one_engine_fetch():
    first = _evidence_snapshot({})
    first["observed_at"] = "2026-11-18T11:55:32Z"
    first["engines"][0].update(
        state="FAILED",
        phase="WORKER_RECEIPT_UNVERIFIED",
        requested_contexts=25,
        created=0,
        active=0,
        sessions=[],
    )
    first["engines"].append(
        {
            "engine": "browsers_members",
            "state": "RUNNING",
            "phase": "AUTHENTICATING",
            "requested_contexts": 1,
            "created": 1,
            "active": 1,
            "closed": 0,
            "failed": 0,
            "sessions": [
                {
                    "session_id": str(uuid4()),
                    "state": "ACTIVE",
                    "phase": "AUTHENTICATING",
                    "observed_at": "2026-11-18T11:54:00Z",
                    "configured_url": "https://boca.example.invalid/login?secret=hidden",
                    "navigation_attempt": {
                        "purpose": "SITE_URL",
                        "result": "RETURNED",
                        "http_status": 200,
                        "started_at": "2026-11-18T11:52:00Z",
                        "display_url": "https://boca.example.invalid/login?bearer=hidden",
                    },
                    "display_url": "https://boca.example.invalid/login/final?pass=hidden",
                }
            ],
        }
    )
    second = copy.deepcopy(first)
    second["observed_at"] = "2026-11-18T12:00:00Z"
    second["engines"][0].update(
        state="RUNNING",
        phase="QUEUE_ACTIVE",
        requested_contexts=1,
        created=1,
        active=1,
        sessions=[
            {
                "session_id": str(uuid4()),
                "state": "ACTIVE",
                "observed_at": "2026-11-18T11:59:00Z",
                "event_state": "EVENT_VERIFIED",
                "queue_state": "QUEUE_ACTIVE",
                "has_target_url": True,
                "configured_url": "https://queue.example.invalid/start?secret=hidden",
            }
        ],
    )
    second["engines"][1].update(
        state="FAILED",
        phase="WORKER_RECEIPT_UNVERIFIED",
        requested_contexts=25,
        created=0,
        active=0,
        sessions=[],
    )
    page, body, _ = render(snapshot=first, activity=True)
    assert b"secret=hidden" not in body and b"bearer=hidden" not in body
    assert "No se confirmó la apertura" in page.text["queues_tokens-live-error"]
    assert "https://boca.example.invalid/login" in page.text["browsers_members-live-navigation"]

    actual = _run_poll_script([first, second, "network-error"], mode="activity", rotation=True)
    failed, changed, historical = actual["results"]
    assert failed["cards"]["queues_tokens"]["error"] == page.text["queues_tokens-live-error"]
    assert (
        failed["cards"]["browsers_members"]["navigation"]
        == page.text["browsers_members-live-navigation"]
    )
    assert (
        failed["cards"]["browsers_members"]["configured-url"]
        == page.text["browsers_members-live-configured-url"]
    )
    assert (
        failed["cards"]["browsers_members"]["final-url"]
        == page.text["browsers_members-live-final-url"]
    )
    assert failed["sessionCounts"] == {"queues_tokens": 0, "browsers_members": 1}
    assert changed["sessionCounts"] == {"queues_tokens": 1, "browsers_members": 0}
    assert changed["contextTotals"]["queues_tokens"] == {"created": "1", "active": "1"}
    assert (
        "https://queue.example.invalid/start" in changed["cards"]["queues_tokens"]["configured-url"]
    )
    assert "evento identificado" in changed["cards"]["queues_tokens"]["event"]
    assert "Cola activa observada" in changed["cards"]["queues_tokens"]["queue"]
    assert "Enlaces observados: 1" in changed["cards"]["queues_tokens"]["tokens"]
    assert "Sin tokens" in changed["cards"]["browsers_members"]["tokens"]
    assert "histórico" in historical["cards"]["queues_tokens"]["motor-status"]
    assert historical["sessionCounts"] == changed["sessionCounts"]
    assert sum(request["url"] == "/control/motores.json" for request in actual["requests"]) == 3
    assert not any(
        "secret=hidden" in result or "bearer=hidden" in result
        for result in (
            item["navigation"] + item["configured-url"] + item["final-url"]
            for cycle in (failed, changed)
            for item in cycle["cards"].values()
        )
    )


def test_activity_shows_selected_member_once_above_closed_technical_details():
    member_id = str(uuid4())
    member = MemberView(member_id, "Titular de ejemplo", "t•••@example.invalid", True)
    snapshot = _evidence_snapshot({})
    snapshot["engines"][0].update(engine="browsers_members", member_id=member_id, sessions=[])
    page, body, _ = render(snapshot=snapshot, activity=True, members=(member,))
    assert page.text["browsers_members-current-member"] == (
        "Titular de ejemplo · t•••@example.invalid"
    )
    assert body.count(b'id="browsers_members-current-member"') == 1
    assert "details" not in page.ancestors["browsers_members-current-member"]
    assert (
        body.index(b'id="browsers_members-live-card"')
        < body.index(b'id="browsers_members-current-member"')
        < body.index(b'id="browsers_members-advanced"')
    )


def test_activity_advanced_sessions_are_closed_and_private_link_has_distinct_identity_node():
    """The CI visual harness must count list rows, not every session-ID-bearing link."""
    first, second = str(uuid4()), str(uuid4())
    snapshot = _evidence_snapshot(
        {"session_id": first, "browser": "chromium", "has_target_url": True}
    )
    browser = copy.deepcopy(snapshot["engines"][0])
    browser.update(
        engine="browsers_members",
        sessions=[{"session_id": second, "browser": "webkit", "has_target_url": False}],
    )
    snapshot["engines"].append(browser)
    page, _, _ = render(snapshot=snapshot, activity=True)
    rows = [attrs for tag, attrs in page.elements if tag == "li" and "data-session-id" in attrs]
    all_session_identity_nodes = [attrs for _, attrs in page.elements if "data-session-id" in attrs]
    assert len(rows) == 2
    assert len(all_session_identity_nodes) == 3  # A private inspect link plus two session rows.
    assert (
        next(
            attrs
            for tag, attrs in page.elements
            if tag == "a" and attrs.get("id") == "queues_tokens-live-inspect"
        )["href"]
        == f"/control/sesiones/{first}"
    )
    for engine in ("queues_tokens", "browsers_members"):
        advanced = next(
            attrs
            for tag, attrs in page.elements
            if tag == "details" and attrs.get("id") == f"{engine}-advanced"
        )
        assert "open" not in advanced
        assert "details" in page.ancestors[f"{engine}-sessions"]


def test_event_and_navigation_labels_remain_closed_and_private():
    from boca_socios.panel import engine_view

    session_id = str(uuid4())
    base = {
        "session_id": session_id,
        "state": "FAILED",
        "phase": "SESSION_FAILED",
        "event_id": "campaign:page-42",
        "observed_at": "2026-11-15T16:00:00Z",
        "configured_url": "https://site.example.invalid/start?configured-secret#private",
        "display_url": "https://final.example.invalid/prior?final-secret#private",
        "final_url_observed_at": "2026-11-15T15:00:00Z",
        "navigation_attempt": {
            "sequence": 2,
            "purpose": "QUEUE_BRIDGE",
            "display_url": "https://queue.example.invalid/next?attempt-secret#private",
            "started_at": "2026-11-15T16:00:00Z",
            "result": "RETURNED",
            "http_status": 503,
        },
    }
    sessions = [{**base, "event_state": code} for code, _ in _EVENT_CASES]
    sessions += [{**base, "reason": code} for code, _ in _REASON_CASES]
    for value in (None, [], {}, False, "constructor", "__proto__", "private-provider-error"):
        sessions.append({**base, "event_state": value, "reason": value, "event_id": "<invalid-id>"})
    sessions.append({"session_id": session_id})
    attack = '</script><img src=x onerror="bad()">'
    sessions.append({**base, "event_id": attack, "navigation_attempt": {"purpose": attack}})
    actual = _run_poll_script(
        [_evidence_snapshot(item) for item in sessions], session_id=session_id
    )
    for session, result in zip(sessions, actual["results"], strict=True):
        page, body, _ = render(snapshot=_evidence_snapshot(session), activity=True)
        for field in (
            "event_state",
            "event_id",
            "reason",
            "configured_url",
            "navigation_attempt",
            "display_url",
        ):
            expected = engine_view._session_value(session, field)
            assert result[field] == expected
            assert f'data-field="{field}">{escape(expected)}</dd>'.encode() in body
        assert not any(tag == "img" for tag, _ in page.elements)
        for secret in (
            b"configured-secret",
            b"final-secret",
            b"attempt-secret",
            b"private-provider-error",
        ):
            assert secret not in body
    for index, (_, expected) in enumerate(_EVENT_CASES):
        assert actual["results"][index]["event_state"] == expected
    for index, (_, expected) in enumerate(_REASON_CASES, len(_EVENT_CASES)):
        assert actual["results"][index]["reason"] == expected
    for item in actual["results"][len(_EVENT_CASES) + len(_REASON_CASES) :]:
        assert item["event_state"] == "Dato no recibido o no reconocido"
        assert item["reason"] == "Dato no recibido o no reconocido"
        assert item["event_id"] == "Dato no recibido"
    first = actual["results"][0]
    assert first["event_id"] == "campaign:page-42"
    assert first["configured_url"] == "https://site.example.invalid/start"
    assert first["display_url"] == "https://final.example.invalid/prior · 2026-11-15 12:00:00 ART"
    assert first["navigation_attempt"] == (
        "Enlace de cola recibido · https://queue.example.invalid/next · 2026-11-15 13:00:00 ART"
        " · La llamada de navegación retornó · HTTP 503"
    )
    missing = actual["results"][-2]
    assert missing["configured_url"] == "Dato no recibido"
    assert missing["display_url"] == "Dato no recibido"
    assert missing["navigation_attempt"] == "Dato no recibido"
    _, body, _ = render(snapshot=_evidence_snapshot(base), activity=True)
    assert "ID de evento observado en la página".encode() in body
    assert "Última URL final recibida".encode() in body
    assert (
        "Cada fila conserva la última muestra recibida. Si la sesión falla o se cierra, esos datos son históricos.".encode()
        in body
    )


def test_actual_poll_relabels_received_tokens_without_replacing_controls():
    session_id = str(uuid4())
    cases = (
        (False, False, "Inspeccionar sesión 1 de colas y tokens"),
        (True, False, "Ver y copiar token/URL de la sesión 1 de colas y tokens"),
        (False, True, "Ver y copiar tokens de autenticación de la sesión 1 de colas y tokens"),
        (
            True,
            True,
            "Ver y copiar tokens de cola y autenticación/URL de la sesión 1 de colas y tokens",
        ),
    )
    snapshots = [
        _evidence_snapshot({"session_id": session_id, "has_target_url": queue, "has_auth": auth})
        for queue, auth, _ in cases
    ]
    actual = _run_poll_script(snapshots, session_id=session_id)
    for snapshot, result, (_, _, label) in zip(snapshots, actual["results"], cases, strict=True):
        assert result["status"] == "Estados y sesiones actualizados."
        assert result["inspect"] == label
        _, body, _ = render(snapshot=snapshot, activity=True)
        assert f'href="/control/sesiones/{session_id}">{label}</a>'.encode() in body
    assert actual["retained"] == {
        "row": True,
        "form": True,
        "engineOperation": True,
        "operationValue": "original-operation_id",
        "focus": True,
        "count": "original-chromium",
        "member": "owner-member-selection",
        "href": f"/control/sesiones/{session_id}",
    }
    assert actual["operation"] == "original-operation_id"
    assert actual["clipboard"] == actual["selects"] == 0
    assert len(actual["requests"]) == 4
    assert all(request["url"] == "/control/motores.json" for request in actual["requests"])
    assert all(request["options"].get("method", "GET") == "GET" for request in actual["requests"])


def test_event_identifier_requires_the_same_whole_value_in_initial_and_poll_render():
    session_id = str(uuid4())
    values = ("campaign-42\n", "campaign-42 ", "<img src=x>", "x" * 129, "a" * 128)
    result = _run_poll_script(
        [_evidence_snapshot({"session_id": session_id, "event_id": value}) for value in values],
        session_id=session_id,
    )
    for value, actual in zip(values, result["results"], strict=True):
        expected = value if value == "a" * 128 else "Dato no recibido"
        assert actual["event_id"] == expected
        _, body, _ = render(
            activity=True,
            snapshot=_evidence_snapshot({"session_id": session_id, "event_id": value}),
        )
        assert f'data-field="event_id">{expected}</dd>'.encode() in body


def test_navigation_purpose_and_result_labels_are_shared_without_claiming_success():
    session_id = str(uuid4())
    purposes = (
        ("SITE_URL", "Carga de SITE_URL"),
        ("QUEUE_BRIDGE", "Enlace de cola recibido"),
        ("RECEIVED_TARGET", "Enlace de acceso recibido"),
        ("constructor", "Dato no recibido o no reconocido"),
    )
    results = (
        ("STARTED", "Inicio del intento registrado"),
        ("RETURNED", "La llamada de navegación retornó"),
        ("FAILED", "El intento falló"),
        ("CANCELLED", "El intento fue cancelado"),
        ([], "Dato no recibido o no reconocido"),
    )
    sessions, expected = [], []
    for purpose, purpose_label in purposes:
        for result, result_label in results:
            sessions.append(
                {
                    "session_id": session_id,
                    "navigation_attempt": {
                        "sequence": 1,
                        "purpose": purpose,
                        "result": result,
                        "http_status": 503,
                        "display_url": "https://example.invalid/path",
                        "started_at": "2026-11-15T16:00:00Z",
                    },
                }
            )
            expected.append(
                f"{purpose_label} · https://example.invalid/path · "
                f"2026-11-15 13:00:00 ART · {result_label}"
                + (" · HTTP 503" if result == "RETURNED" else "")
            )
    actual = _run_poll_script(
        [_evidence_snapshot(item) for item in sessions], session_id=session_id
    )
    for session, received, label in zip(sessions, actual["results"], expected, strict=True):
        assert received["navigation_attempt"] == label
        page, body, _ = render(snapshot=_evidence_snapshot(session), activity=True)
        assert f'data-field="navigation_attempt">{escape(label)}</dd>'.encode() in body
        assert not any(tag == "path" for tag, _ in page.elements)
    snapshot = _evidence_snapshot({"session_id": session_id, "has_auth": True})
    snapshot["engines"][0]["engine"] = "browsers_members"
    _, body, _ = render(snapshot=snapshot, activity=True)
    assert b"Ver y copiar tokens de autenticaci" in body
    assert b"de la sesi" in body and b"1 de navegadores de socios</a>" in body


def test_counts_collapse_inside_start_but_required_member_stays_visible():
    page, _, _ = render()
    for engine in ("queues_tokens", "browsers_members"):
        for browser in ("chromium", "firefox", "webkit"):
            assert "details" in page.ancestors[f"{engine}-{browser}"]
            assert "form" in page.ancestors[f"{engine}-{browser}"]
    assert "details" not in page.ancestors["browsers_members-member"]
    assert "form" in page.ancestors["browsers_members-member"]


@pytest.mark.parametrize("mode", ["control", "activity"])
def test_aggregate_phase_cannot_claim_no_event_without_session_evidence(mode):
    snapshot = _evidence_snapshot({})
    snapshot["engines"][0].update(phase="NO_EVENT_OBSERVED", sessions=[])
    page, _, _ = render(snapshot=snapshot, activity=mode == "activity")
    expected = "Comprobación de evento registrada; consulte las sesiones"
    assert page.text["queues_tokens-phase"] == expected
    assert _run_poll_script([snapshot], mode=mode)["results"][0]["phase"] == expected


@pytest.mark.parametrize("mode", ["control", "activity"])
def test_poll_separate_dom_updates_true_states_and_marks_failure_historical(mode):
    session_id = str(uuid4())
    snapshot = _evidence_snapshot({"session_id": session_id, "phase": "UNKNOWN"})
    snapshot["engines"][0].update(updated_at="2026-11-15T15:00:00Z", can_start=False)
    actual = _run_poll_script(
        [snapshot, "network-error", snapshot], mode=mode, session_id=session_id
    )
    first, failed, recovered = actual["results"]
    assert first["status"] == "Estados y sesiones actualizados."
    assert first["state"] == "En ejecución"
    assert "13:00:00 ART" in first["checked"]
    assert "12:00:00 ART" in first["updated"]
    assert "histórico" in failed["state"] and "no verificado" in failed["state"]
    assert "históricos" in failed["status"]
    assert recovered["state"] == "En ejecución"
    if mode == "control":
        assert first["startDisabled"] and "no permite" in first["startReason"]
        assert actual["intervals"] == [5000]
    else:
        assert actual["intervals"] == [5000, 5000]
        assert actual["timeline"] == "Último evento: Acuse no verificado"
        assert sum(item["url"] == "/control/actividad.json" for item in actual["requests"]) == 1
    assert actual["retained"]["focus"] and actual["retained"]["count"] == "original-chromium"


@pytest.mark.parametrize("mode", ["control", "activity"])
def test_polled_member_change_without_selector_does_not_claim_missing_directory_entry(mode):
    snapshots = []
    for member_id in (str(uuid4()), str(uuid4()), None):
        snapshot = _evidence_snapshot({})
        snapshot["engines"][0].update(engine="browsers_members", member_id=member_id, sessions=[])
        snapshots.append(snapshot)
    results = _run_poll_script(snapshots, mode=mode)["results"]
    expected = (
        "Socio asociado; nombre no disponible en esta vista"
        if mode == "activity"
        else "Socio no disponible en la lista actual"
    )
    assert [item["currentMember"] for item in results] == [expected, expected, "Sin socio asociado"]


@pytest.mark.parametrize(
    "site_ready,members,can_start", [(False, (), True), (True, (), True), (True, None, False)]
)
def test_disabled_controls_explain_site_mirror_credentials_and_activation(
    site_ready, members, can_start
):
    page, _, _ = render(
        site_url_ready=site_ready,
        members=members,
        snapshot={
            "engines": [{"engine": "queues_tokens", "state": "STOPPED", "can_start": can_start}]
        },
    )
    if not site_ready:
        assert "SITE_URL" in page.text["queues_tokens-start-reason"]
        assert "sincronizada" in page.text["queues_tokens-start-reason"]
    elif not can_start:
        assert "no permite" in page.text["queues_tokens-start-reason"]
    if members == ():
        assert "credencial activa" in page.text["browsers_members-start-reason"]
    for engine in ("queues_tokens", "browsers_members"):
        assert "activación" in page.text[f"{engine}-stop-reason"]
        for action, suffix in (("iniciar", "start"), ("detener", "stop")):
            assert (
                page.button(f"/control/motores/{engine}/{action}")["aria-describedby"]
                == f"{engine}-{suffix}-reason"
            )
