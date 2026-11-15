"""Owner engine controls keep their form and private inspection boundaries."""

from __future__ import annotations

import copy
import json
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
        self.feed(body.decode())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        self.elements.append((tag, attributes))
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
    )
    return Page(body), body, operations


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

    links = [attrs["href"] for tag, attrs in page.elements if tag == "a"]
    assert f"/control/sesiones/{session_id}" in links
    assert not any(str(link).startswith("https:") or "../" in str(link) for link in links)
    assert b"bearer=secret" not in body
    assert b"#pass" not in body
    assert b"https://queue.example.invalid/path" in body


@pytest.mark.parametrize("session_count", [0, 2, 50])
def test_both_engine_controls_precede_all_session_histories(session_count: int) -> None:
    engines = ("queues_tokens", "browsers_members")
    identities = {engine: [str(uuid4()) for _ in range(session_count // 2)] for engine in engines}
    page, body, _ = render(
        snapshot={
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
    )

    controls = [
        body.index(f'id="{engine}-{suffix}"'.encode())
        for engine in engines
        for suffix in ("state", "start", "stop")
    ]
    histories = [
        body.index(f'id="{engine}-{suffix}"'.encode())
        for engine in engines
        for suffix in ("sessions", "no-sessions")
    ]
    assert max(controls) < min(histories)
    common_heading = b"<h2>Sesiones observadas</h2>"
    assert body.count(common_heading) == 1
    assert max(controls) < body.index(common_heading) < min(histories)
    for engine, label in zip(engines, ("colas y tokens", "navegadores de socios"), strict=True):
        heading = f"<h3>Sesiones de {label}</h3>".encode()
        assert body.index(common_heading) < body.index(heading)
        assert body.index(heading) < body.index(f'id="{engine}-sessions"'.encode())
    rows = [attrs["data-session-id"] for tag, attrs in page.elements if tag == "li"]
    assert rows == [identity for engine in engines for identity in identities[engine]]
    links = [
        attrs["href"]
        for tag, attrs in page.elements
        if tag == "a" and attrs.get("data-field") == "inspect"
    ]
    assert links == [f"/control/sesiones/{identity}" for identity in rows]
    assert sum(tag == "h4" for tag, _ in page.elements) == session_count
    assert len(page.forms) == 4


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
        }
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
        }
    )
    assert b'data-field="queue_size">2034</dd>' in body
    assert (
        b'data-field="expected_service_time">2030-01-01T13:45:00Z &lt;dato recibido&gt;</dd>'
        in body
    )


def _run_poll_script(snapshots, *, present=True, session_id=None):
    from boca_socios.panel import engine_view

    node = shutil.which("node")
    assert node is not None
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
let clipboard = 0;
let selects = 0;
const context = {
  document: {hidden: true, activeElement: count, getElementById: element, addEventListener() {},
    createElement() { throw new Error('existing row replaced'); }},
  navigator: {clipboard: {writeText() { clipboard++; }}},
  select() { selects++; },
  setInterval() {}, URL,
  fetch: async (url, options) => {
    requests.push({url, options});
    return {ok: true, json: async () => snapshot};
  }
};
vm.runInNewContext(input.script, context, {timeout: 1000});
(async () => {
  const results = [];
  for (snapshot of input.snapshots) {
    await element('engines-refresh').click();
    const section = element('legacy-worker-recovery');
    const result = {recovery: section ? {hidden: section.hidden,
      disabled: element('legacy-worker-recovery-button').disabled} : null,
      status: element('engines-live').textContent};
    if (row) for (const field of ['outcome', 'queue_state', 'phase', 'event_state', 'event_id',
      'reason', 'configured_url', 'navigation_attempt', 'display_url', 'inspect']) {
      result[field] = row.querySelector('[data-field="' + field + '"]').textContent;
    }
    results.push(result);
  }
  process.stdout.write(JSON.stringify({results, operation: operation.value,
    status: element('engines-live').textContent, requests, clipboard, selects,
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
                "script": engine_view._SCRIPT,
                "present": present,
                "session_id": session_id,
                "snapshots": snapshots,
            }
        ),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return json.loads(completed.stdout)


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
        page, body, _ = render(snapshot=_evidence_snapshot(session))
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
    _, body, _ = render(snapshot=_evidence_snapshot(base))
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
        (True, False, "Ver token de cola de la sesión 1 de colas y tokens"),
        (False, True, "Ver tokens de autenticación de la sesión 1 de colas y tokens"),
        (True, True, "Ver tokens de cola y autenticación de la sesión 1 de colas y tokens"),
    )
    snapshots = [
        _evidence_snapshot({"session_id": session_id, "has_target_url": queue, "has_auth": auth})
        for queue, auth, _ in cases
    ]
    actual = _run_poll_script(snapshots, session_id=session_id)
    for snapshot, result, (_, _, label) in zip(snapshots, actual["results"], cases, strict=True):
        assert result["status"] == "Estados y sesiones actualizados."
        assert result["inspect"] == label
        _, body, _ = render(snapshot=snapshot)
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
            snapshot=_evidence_snapshot({"session_id": session_id, "event_id": value})
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
        page, body, _ = render(snapshot=_evidence_snapshot(session))
        assert f'data-field="navigation_attempt">{escape(label)}</dd>'.encode() in body
        assert not any(tag == "path" for tag, _ in page.elements)
    snapshot = _evidence_snapshot({"session_id": session_id, "has_auth": True})
    snapshot["engines"][0]["engine"] = "browsers_members"
    _, body, _ = render(snapshot=snapshot)
    assert b"Ver tokens de autenticaci" in body
    assert b"de la sesi" in body and b"1 de navegadores de socios</a>" in body
