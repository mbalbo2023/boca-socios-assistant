"""Exercise the motor card's rendered HTML and actual polling script."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from test_engine_view import render

QUEUES = "queues_tokens"
MEMBERS = "browsers_members"
SESSION = "11111111-2222-4333-8444-555555555555"
SECOND = "22222222-2222-4333-8444-555555555555"
SECRET = "private-fixture-bearer"
HOST_MESSAGE = "Ejecutor: solicitud recibida, verificando el servicio Boca."
STALE_MESSAGE = "Chromium: sólo hay telemetría antigua; no confirma un proceso activo."


def _snapshot(engine=QUEUES, **fields):
    return {
        "version": 1,
        "context_limit": 50,
        "observed_at": "2026-11-17T18:00:00Z",
        "engines": [
            {
                "engine": engine,
                "state": "FAILED",
                "phase": "WORKER_RECEIPT_UNVERIFIED",
                "updated_at": "2026-11-17T17:00:00Z",
                "requested_contexts": 25,
                "created": 0,
                "active": 0,
                "closed": 0,
                "failed": 0,
                "sessions": [],
                **fields,
            }
        ],
    }


@pytest.mark.parametrize(("engine", "label"), [(QUEUES, "Motor A"), (MEMBERS, "Motor B")])
def test_unverified_start_card_precedes_forms_without_claiming_no_event(engine, label):
    page, _, _ = render(snapshot=_snapshot(engine), engine=engine)
    nodes = {attrs.get("id"): (i, attrs) for i, (_, attrs) in enumerate(page.elements)}
    card_index, card = nodes.get(engine + "-live-card", (-1, {}))
    assert card.get("aria-label") == f"Estado del bot · {label}"
    assert card_index < min(i for i, (tag, _) in enumerate(page.elements) if tag == "form")
    summary = page.text[engine + "-live-card"]
    assert "Arranque del navegador sin confirmar" in summary
    assert "no hay evento" not in summary.lower()
    assert page.text[engine + "-live-event"] == page.text[engine + "-live-queue"] == "No comprobado"
    assert "25 solicitados · 0 creados · 0 activos" in summary
    assert page.text[engine + "-live-page-time"] == "Sin observación"
    assert "2026-11-17 14:00:00 ART" in page.text[engine + "-live-motor-time"]
    assert "worker compartido" in summary.lower()
    assert "Aún no hay actividad verificable" in summary
    assert any(
        tag == "a" and attrs.get("href") == "/control/actividad"
        for tag, attrs in page.elements[card_index : nodes[engine + "-start"][0]]
    )


@pytest.mark.parametrize("engine", [QUEUES, MEMBERS])
def test_motor_a_card_explains_unverified_start_without_navigation(engine):
    """No worker receipt and zero sessions cannot attest a URL, HTTP or provider response."""
    snapshot = _snapshot(engine)
    page, body, _ = render(snapshot=snapshot, engine=engine)
    prefix = f"{engine}-live-"

    assert page.text[prefix + "configured-url"] == (
        "No disponible en observación; ver Configuración"
    )
    assert page.text[prefix + "navigation"] == "Sin intento observado"
    assert page.text[prefix + "final-url"] == "Sin URL final observada"
    assert "Causa técnica específica no registrada" in page.text[prefix + "error"]
    assert "No se confirmó la apertura del navegador" in page.text[prefix + "error"]
    assert page.text[prefix + "contexts"] == "25 solicitados · 0 creados · 0 activos"
    assert page.text[prefix + "event"] == page.text[prefix + "queue"] == "No comprobado"
    assert page.text[prefix + "tokens"] == "Sin tokens ni enlaces comprobados"
    assert "HTTP " not in page.text[prefix + "card"]
    assert SECRET not in body.decode()

    fresh = _poll(engine, [{"engine": snapshot, "activity": _activity()}])["results"][0]
    for name in ("configured-url", "navigation", "final-url", "error", "event", "queue"):
        assert fresh[name]["text"] == page.text[prefix + name]


@pytest.mark.parametrize("engine", [QUEUES, MEMBERS])
def test_failed_logical_snapshot_and_later_stop_do_not_claim_current_physical_failure(engine):
    """The last logical FAILED can survive a STOP; neither GET proves worker health."""
    old = _snapshot(engine)
    page, _, _ = render(snapshot=old, engine=engine)
    prefix = f"{engine}-live-"
    card = page.text[prefix + "card"]
    assert "Último estado lógico registrado:" in card
    assert "Último cambio lógico:" in card
    assert "Consulta del motor:" in card
    assert page.text[prefix + "physical-status"] == "No comprobada en esta vista"
    assert page.text[prefix + "status-scope"] == (
        "El resultado lógico no acredita un worker activo ni un fallo físico actual."
    )
    assert "No se confirmó la apertura del navegador" in page.text[prefix + "error"]
    assert "No se verificó navegación ni URL visitada" in page.text[prefix + "error"]
    assert page.text[prefix + "motor-time"] == "2026-11-17 14:00:00 ART"
    assert page.text[prefix + "motor-query"] == "2026-11-17 15:00:00 ART"

    # The earliest visible detail after context counts must be the actual unknown cause,
    # not speculative URL/event/token assertions far above the fold on a tablet.
    indexes = {attrs.get("id"): index for index, (_, attrs) in enumerate(page.elements)}
    assert indexes[prefix + "contexts"] < indexes[prefix + "error"]
    for name in ("configured-url", "navigation", "final-url", "event", "queue", "tokens"):
        assert indexes[prefix + "error"] < indexes[prefix + name]

    # A later failed GET leaves the previous logical result historical, not physical.
    updated, stale = _poll(
        engine,
        [{"engine": old, "activity": _activity()}, {"engine": "offline", "activity": _activity()}],
    )["results"]
    assert updated["state"]["text"].startswith("Falló")
    assert stale["state"] == updated["state"]
    assert (
        updated["physical-status"]["text"]
        == stale["physical-status"]["text"]
        == ("No comprobada en esta vista")
    )
    assert updated["status-scope"]["text"] == stale["status-scope"]["text"]
    assert updated["motor-time"]["text"] == "2026-11-17 14:00:00 ART"
    assert updated["motor-query"]["text"] == "2026-11-17 15:00:00 ART"
    assert "histórico" in stale["motor-status"]["text"]


def _session(session_id=SESSION, **fields):
    return {
        "session_id": session_id,
        "browser": "chromium",
        "state": "ACTIVE",
        "phase": "QUEUE_ACTIVE",
        "observed_at": "2026-11-17T17:20:00Z",
        "event_state": "EVENT_VERIFIED",
        "queue_state": "QUEUE_ACTIVE",
        **fields,
    }


def test_authentication_card_preserves_evidence_scope_and_private_link():
    snapshot = _snapshot(
        MEMBERS,
        state="RUNNING",
        phase="AUTH_TOKENS_OBSERVED_DOM_UNVERIFIED",
        created=2,
        active=2,
        sessions=[
            _session(event_state="NO_EVENT_CONFIRMED", queue_state="UNKNOWN"),
            _session(
                SECOND,
                has_auth=True,
                observed_at="2026-11-17T17:30:00Z",
                navigation_attempt={
                    "purpose": "SITE_URL",
                    "result": "RETURNED",
                    "display_url": f"https://credentials:{SECRET}@example.invalid/?secret={SECRET}",
                },
            ),
        ],
    )
    page, _, _ = render(snapshot=snapshot, engine=MEMBERS)
    summary = page.text.get(MEMBERS + "-live-card", "")
    assert "Sesión 1 informa que no hay evento" in summary
    assert "Sesión 2: evento identificado" in summary
    assert "2026-11-17 14:30:00 ART" in summary
    assert "Carga de SITE_URL" in summary
    assert "sesión en la página sin confirmar" in summary
    assert "Respuesta de autenticación" in page.text[MEMBERS + "-live-tokens"]
    link = next(attrs for _, attrs in page.elements if attrs.get("id") == MEMBERS + "-live-inspect")
    assert link["href"] == "/control/sesiones/" + SECOND
    assert SECRET not in summary


@pytest.mark.parametrize("engine", [QUEUES, MEMBERS])
@pytest.mark.parametrize("result", ["FAILED", "RETURNED"])
def test_navigation_evidence_shows_safe_url_time_result_and_proven_http_only(engine, result):
    session = _session(
        configured_url=f"https://example.invalid/configurada?pass={SECRET}#fragment",
        navigation_attempt={
            "purpose": "SITE_URL",
            "result": result,
            "display_url": f"https://example.invalid/navegacion?pass={SECRET}#fragment",
            "started_at": "2026-11-17T17:22:00Z",
            "http_status": 403,
        },
        display_url=f"https://example.invalid/final?pass={SECRET}#fragment",
        final_url_observed_at="2026-11-17T17:23:00Z",
        has_target_url=True,
        target_url=f"https://example.invalid/pase?pass={SECRET}",
    )
    snapshot = _snapshot(
        engine, state="RUNNING", phase="QUEUE_ACTIVE", created=1, active=1, sessions=[session]
    )
    page, body, _ = render(snapshot=snapshot, engine=engine)
    prefix = f"{engine}-live-"

    assert page.text[prefix + "configured-url"] == "Sesión 1: https://example.invalid/configurada"
    assert page.text[prefix + "navigation"].startswith(
        "Sesión 1 · Carga de SITE_URL · https://example.invalid/navegacion · "
        "2026-11-17 14:22:00 ART · "
    )
    assert ("HTTP 403" in page.text[prefix + "navigation"]) is (result == "RETURNED")
    assert page.text[prefix + "final-url"] == (
        "Sesión 1: https://example.invalid/final · 2026-11-17 14:23:00 ART"
    )
    link = next(attrs for _, attrs in page.elements if attrs.get("id") == prefix + "inspect")
    assert link["href"] == "/control/sesiones/" + SESSION
    assert SECRET not in body.decode()

    actual = _poll(engine, [{"engine": snapshot, "activity": _activity()}])["results"][0]
    for field in ("configured-url", "navigation", "final-url", "event", "queue", "tokens"):
        assert actual[field]["text"] == page.text[prefix + field]
    assert actual["inspect"]["href"] == link["href"]
    assert SECRET not in json.dumps(actual)


@pytest.mark.parametrize("engine", [QUEUES, MEMBERS])
@pytest.mark.parametrize("sequence", [1, 3, 0, 4, True, "2", None])
def test_navigation_attempt_number_is_only_a_valid_per_session_sequence(engine, sequence):
    snapshot = _snapshot(
        engine,
        state="RUNNING",
        phase="QUEUE_ACTIVE",
        created=1,
        active=1,
        sessions=[
            _session(
                navigation_attempt={
                    "sequence": sequence,
                    "purpose": "SITE_URL",
                    "result": "RETURNED",
                    "display_url": f"https://example.invalid/path?token={SECRET}",
                    "started_at": "2026-11-17T17:22:00Z",
                    "http_status": 200,
                }
            )
        ],
    )
    page, body, _ = render(snapshot=snapshot, engine=engine)
    navigation = page.text[f"{engine}-live-navigation"]
    if type(sequence) is int and 1 <= sequence <= 3:
        assert f"Último intento de navegación n.º {sequence} de esta sesión" in navigation
    else:
        assert "n.º" not in navigation
    assert "HTTP 200" in navigation
    assert SECRET not in body.decode()

    observed = _poll(engine, [{"engine": snapshot, "activity": _activity()}])["results"][0]
    assert observed["navigation"]["text"] == navigation

    no_session = _snapshot(engine)
    assert (
        "n.º" not in render(snapshot=no_session, engine=engine)[0].text[f"{engine}-live-navigation"]
    )


@pytest.mark.parametrize("engine", [QUEUES, MEMBERS])
def test_closed_session_evidence_is_historical_and_userinfo_is_not_disclosed(engine):
    session = _session(
        state="CLOSED",
        configured_url=f"https://user:{SECRET}@example.invalid/configurada?pass={SECRET}",
        navigation_attempt={
            "purpose": "SITE_URL",
            "result": "FAILED",
            "display_url": f"https://user:{SECRET}@example.invalid/navegacion?pass={SECRET}",
            "started_at": "2026-11-17T17:22:00Z",
            "http_status": 502,
        },
        display_url=f"https://example.invalid/final?pass={SECRET}",
        final_url_observed_at="2026-11-17T17:23:00Z",
        event_state="UNRECOGNIZED",
        queue_state="UNKNOWN",
    )
    snapshot = _snapshot(
        engine, state="STOPPED", phase="STOPPED", created=1, closed=1, sessions=[session]
    )
    page, body, _ = render(snapshot=snapshot, engine=engine)
    prefix = f"{engine}-live-"
    assert page.text[prefix + "configured-url"] == "Sesión 1: Dato no recibido (muestra histórica)"
    assert page.text[prefix + "navigation"].startswith(
        "Sesión 1 · Carga de SITE_URL · Dato no recibido · 2026-11-17 14:22:00 ART · "
    )
    assert page.text[prefix + "navigation"].endswith("(muestra histórica)")
    assert "HTTP 502" not in page.text[prefix + "navigation"]
    assert page.text[prefix + "final-url"].endswith("(muestra histórica)")
    assert page.text[prefix + "event"] == page.text[prefix + "queue"] == "No comprobado"
    assert SECRET not in body.decode()

    fresh = _poll(engine, [{"engine": snapshot, "activity": _activity()}])["results"][0]
    for field in ("configured-url", "navigation", "final-url", "event", "queue"):
        assert fresh[field]["text"] == page.text[prefix + field]


def test_multiple_sessions_keep_navigation_and_tokens_tied_to_real_session():
    snapshot = _snapshot(
        state="RUNNING",
        phase="QUEUE_ACTIVE",
        created=2,
        active=1,
        sessions=[
            _session(
                state="CLOSED",
                observed_at="2026-11-17T17:40:00Z",
                event_state="NO_EVENT_CONFIRMED",
                queue_state="UNKNOWN",
                configured_url="https://example.invalid/antes",
                navigation_attempt={
                    "purpose": "SITE_URL",
                    "result": "FAILED",
                    "display_url": "https://example.invalid/antes",
                    "started_at": "2026-11-17T17:39:00Z",
                },
            ),
            _session(
                SECOND,
                event_state="EVENT_VERIFIED",
                queue_state="QUEUE_ACTIVE",
                configured_url="https://example.invalid/ahora",
                has_target_url=True,
            ),
        ],
    )
    page, _, _ = render(snapshot=snapshot, engine=QUEUES)
    prefix = QUEUES + "-live-"
    assert (
        page.text[prefix + "configured-url"]
        == "Sesión 1: https://example.invalid/antes (muestra histórica)"
    )
    assert page.text[prefix + "navigation"].startswith("Sesión 1 · Carga de SITE_URL")
    assert "Sesión 1 informa que no hay evento (muestra histórica)" in page.text[prefix + "event"]
    assert "Sesión 2: evento identificado" in page.text[prefix + "event"]
    assert page.text[prefix + "queue"].startswith("Sesión 2: Cola activa observada")
    assert page.text[prefix + "tokens"] == "Enlaces observados: 1"
    assert (
        next(attrs for _, attrs in page.elements if attrs.get("id") == prefix + "inspect")["href"]
        == "/control/sesiones/" + SECOND
    )


@pytest.mark.parametrize("engine", [QUEUES, MEMBERS])
def test_worker_feed_is_collapsed_and_controls_do_not_repeat_visible_engine_status(engine):
    page, _, _ = render(snapshot=_snapshot(engine), engine=engine)
    prefix = f"{engine}-live-"
    details = next(
        attrs
        for tag, attrs in page.elements
        if tag == "details" and attrs.get("id") == prefix + "worker-details"
    )
    assert "open" not in details  # Only owner interaction expands shared diagnostics.
    assert "details" in page.ancestors[prefix + "worker-status"]
    assert "details" in page.ancestors[prefix + "record-0"]
    assert "no corresponde a navegación del motor" in page.text[prefix + "worker-details"]

    assert page.text[f"{engine}-heading"].startswith("Acciones del motor ")
    advanced = next(
        attrs
        for tag, attrs in page.elements
        if tag == "details" and attrs.get("id") == f"{engine}-advanced-status"
    )
    assert "open" not in advanced
    assert "details" in page.ancestors[f"{engine}-state"]
    assert "details" in page.ancestors[f"{engine}-phase"]
    assert f"{engine}-start" in {attrs.get("id") for tag, attrs in page.elements if tag == "form"}


def test_shared_worker_records_keep_source_without_duplicate_prefix_after_poll():
    actual = _poll(QUEUES, [{"engine": _snapshot(), "activity": _activity(_event(1))}])
    record = actual["results"][0]["record-0"]["text"]
    assert (
        record
        == "2026-11-17 15:01:00 ART · Ejecutor: solicitud recibida, verificando el servicio Boca."
    )
    assert actual["results"][0]["worker-status"]["text"] == (
        "Registros del worker compartido disponibles."
    )
    assert [request["url"] for request in actual["requests"]] == [
        "/control/motores.json",
        "/control/actividad.json",
    ]


def test_negative_engine_phase_alone_does_not_confirm_absence_of_event():
    snapshot = _snapshot(state="RUNNING", phase="NO_EVENT_OBSERVED")
    page, _, _ = render(snapshot=snapshot, engine=QUEUES)
    assert "no hay evento" not in page.text[QUEUES + "-live-card"].lower()
    assert page.text[QUEUES + "-live-event"] == "No comprobado"
    current = _poll(QUEUES, [{"engine": snapshot, "activity": _activity()}])["results"][0]
    assert "no hay evento" not in current["phase"]["text"].lower()
    assert current["event"]["text"] == "No comprobado"


_HARNESS = r"""
const vm = require('node:vm');
const fixture = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
function element(attrs={}, content='') {
  return {textContent: content, href: attrs.href, hidden: Object.hasOwn(attrs, 'hidden'),
    dataset: {ready: 'true'}, children: [], fields: new Map(),
    events: {}, addEventListener(name, callback) { this.events[name] = callback; },
    append(...children) { this.children.push(...children); },
    setAttribute(name, value) { this[name] = value; },
    getAttribute(name) { return this[name] ?? null; },
    removeAttribute(name) { delete this[name]; },
    remove() {},
    querySelector(selector) {
      const [,summary,key] = selector.match(/data-(summary-)?field="([^"]+)"/);
      const search = item => item.dataset[summary ? 'summaryField' : 'field'] === key ? item :
        item.children.map(search).find(Boolean);
      return search(this);
    },
    get elements() { return {namedItem: name => {
      if (!this.fields.has(name)) this.fields.set(name, {value: 'owner-' + name});
      return this.fields.get(name);
    }}; }
  };
}
const elements = new Map(fixture.elements.map(attrs =>
  [attrs.id, element(attrs, fixture.text[attrs.id] || '')]));
const requests = [], intervals = [];
const prefix = fixture.engine + '-live-';
const form = elements.get(fixture.engine + '-start');
const operation = form.elements.namedItem('operation_id');
const member = elements.get(fixture.engine + '-member');
if (member) member.value = 'selected-member';
let input;
vm.runInNewContext(fixture.script, {
  URL, document: {hidden: true, addEventListener() {},
    getElementById: id => elements.get(id) || null, createElement: () => element()},
  setInterval(_callback, ms) { intervals.push(ms); },
  fetch: async (url, options) => {
    requests.push({url, options});
    const data = url === '/control/motores.json' ? input.engine : input.activity;
    if (data === 'offline') throw Error('offline fixture');
    return {ok: data !== 503, json: async () => data};
  },
}, {timeout: 1000});
(async () => {
  const results = [];
  for (input of fixture.cycles) {
    await elements.get('engines-refresh').events.click();
    results.push(Object.fromEntries([...elements.entries()].filter(([id]) => id.startsWith(prefix))
      .map(([id, node]) => [id.slice(prefix.length), {
        text: node.textContent, hidden: node.hidden, href: node.href,
      }])));
  }
  process.stdout.write(JSON.stringify({results, requests, intervals,
    sameForm: form === elements.get(fixture.engine + '-start'),
    operation: operation.value, member: member && member.value}));
})().catch(error => { process.stderr.write(String(error)); process.exitCode = 1; });
"""


def _poll(engine, cycles, *, combined=False, projected_fields=()):
    page, body, _ = render(snapshot=_snapshot(engine), engine=None if combined else engine)
    node = shutil.which("node")
    assert node
    result = subprocess.run(  # noqa: S603 - fixed offline runtime and the actual static UI script
        [node, "-e", _HARNESS],
        input=json.dumps(
            {
                "engine": engine,
                "elements": [attrs for _, attrs in page.elements if attrs.get("id")]
                + [{"id": f"{engine}-live-{field}"} for field in projected_fields],
                "text": page.text,
                "script": "\n".join(re.findall(r"<script>(.*?)</script>", body.decode(), re.S)),
                "cycles": cycles,
            }
        ),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return json.loads(result.stdout)


def _activity(*events):
    return {
        "observed_at": "2026-11-17T19:00:00Z",
        "browser_detail": "fixed_stages_only",
        "chromium_telemetry": "available",
        "events": events,
    }


@pytest.mark.parametrize("engine", [QUEUES, MEMBERS])
def test_control_refreshes_both_motor_summaries_once_without_worker_timeline(engine):
    snapshot = _snapshot()
    snapshot["engines"] += _snapshot(MEMBERS, state="RUNNING", created=2, active=1)["engines"]
    parsed, _, _ = render(snapshot=snapshot)
    assert parsed.text.get(QUEUES + "-live-error", "").startswith(
        "No se confirmó la apertura del navegador"
    )
    assert parsed.text.get(MEMBERS + "-live-contexts") == "25 solicitados · 2 creados · 1 activos"
    assert not any("record-0" in str(attrs.get("id")) for _, attrs in parsed.elements)
    links = [attrs.get("href") for tag, attrs in parsed.elements if tag == "a"]
    assert links.count("/control/actividad#" + engine + "-heading") == 1
    changed = _snapshot(state="RUNNING", requested_contexts=7, created=5, active=3)
    changed["engines"] += _snapshot(MEMBERS, requested_contexts=4, created=0, active=0)["engines"]
    result = _poll(
        engine, [{"engine": changed}, {"engine": 503}, {"engine": changed}], combined=True
    )
    fresh, stale, recovered = result["results"]
    expected = (
        "7 solicitados · 5 creados · 3 activos"
        if engine == QUEUES
        else "4 solicitados · 0 creados · 0 activos"
    )
    assert (
        fresh["contexts"]["text"]
        == stale["contexts"]["text"]
        == recovered["contexts"]["text"]
        == expected
    )
    assert "histórico" in stale["motor-status"]["text"]
    assert "histórico" not in recovered["motor-status"]["text"]
    assert [item["url"] for item in result["requests"]] == ["/control/motores.json"] * 3
    assert result["intervals"] == [5000]


@pytest.mark.parametrize("engine", [QUEUES, MEMBERS])
def test_combined_home_poll_preserves_real_session_url_navigation_and_final_evidence(engine):
    """HOME's shared motor projection must load its existing safe URL helpers."""
    session = _session(
        configured_url=f"https://example.invalid/configurada?token={SECRET}",
        navigation_attempt={
            "purpose": "SITE_URL",
            "result": "RETURNED",
            "display_url": f"https://example.invalid/navegar?token={SECRET}",
            "started_at": "2026-11-17T17:21:00Z",
            "http_status": 403,
        },
        display_url=f"https://example.invalid/final?token={SECRET}",
        final_url_observed_at="2026-11-17T17:22:00Z",
    )
    snapshot = _snapshot(
        engine, state="RUNNING", phase="QUEUE_ACTIVE", created=1, active=1, sessions=[session]
    )
    initial, body, _ = render(snapshot=snapshot, engine=None)
    prefix = f"{engine}-live-"
    assert initial.text[prefix + "navigation"] == (
        "Sesión 1 · Carga de SITE_URL · https://example.invalid/navegar · "
        "2026-11-17 14:21:00 ART · La llamada de navegación retornó · HTTP 403"
    )
    assert SECRET not in body.decode()

    current = _poll(
        engine,
        [{"engine": snapshot}],
        combined=True,
        projected_fields=("configured-url", "final-url"),
    )
    detail, _, _ = render(snapshot=snapshot, engine=engine)
    assert current["results"][0]["configured-url"]["text"] == detail.text[prefix + "configured-url"]
    assert current["results"][0]["final-url"]["text"] == detail.text[prefix + "final-url"]
    assert current["results"][0]["navigation"]["text"] == initial.text[prefix + "navigation"]
    assert current["results"][0]["tokens"]["text"] == initial.text[prefix + "tokens"]
    assert current["results"][0]["event"]["text"] == initial.text[prefix + "event"]
    assert current["results"][0]["queue"]["text"] == initial.text[prefix + "queue"]
    assert SECRET not in json.dumps(current["results"])
    assert [request["url"] for request in current["requests"]] == ["/control/motores.json"]


def _event(minute, message=HOST_MESSAGE):
    return {
        "at": f"2026-11-17T18:{minute:02d}:00Z",
        "source": "host",
        "level": "progress",
        "message": message,
    }


def test_same_poll_updates_card_and_admits_only_five_allowlisted_worker_records():
    running = _snapshot(
        MEMBERS,
        state="RUNNING",
        phase="AUTH_TOKENS_OBSERVED_DOM_UNVERIFIED",
        created=1,
        active=1,
        sessions=[_session(has_target_url=True, target_url=f"https://example.invalid/{SECRET}")],
    )
    result = _poll(
        MEMBERS,
        [
            {"engine": _snapshot(MEMBERS), "activity": _activity()},
            {
                "engine": running,
                "activity": _activity(*[_event(i) for i in range(6)], _event(6, SECRET)),
            },
        ],
    )
    before, after = result["results"]
    assert "Falló" in before.get("state", {}).get("text", "")
    assert after["state"]["text"] == "En ejecución"
    assert after["page-time"]["text"] == "2026-11-17 14:20:00 ART"
    assert after["inspect"] == {
        "text": "Abrir inspección privada",
        "hidden": False,
        "href": "/control/sesiones/" + SESSION,
    }
    timeline = [after[f"record-{i}"]["text"] for i in range(5)]
    assert ["15:0" + str(i) + ":00 ART" for i in (5, 4, 3, 2, 1)] == [
        text.split(" · ", 1)[0].split(" ", 1)[1] for text in timeline
    ]
    assert all("Ejecutor" in text and HOST_MESSAGE in text for text in timeline)
    assert after["worker-time"]["text"] == "2026-11-17 16:00:00 ART"
    assert SECRET not in json.dumps(after)
    assert result["intervals"] == [5000]
    assert result["sameForm"] and result["operation"] == "owner-operation_id"
    assert result["member"] == "selected-member"
    assert [item["url"] for item in result["requests"]] == [
        "/control/motores.json",
        "/control/actividad.json",
    ] * 2
    assert all(
        item["options"] == {"credentials": "same-origin", "cache": "no-store", "redirect": "error"}
        for item in result["requests"]
    )


@pytest.mark.parametrize("bad_snapshot", ["offline", {"version": 2}, None])
def test_either_get_can_fail_without_discarding_other_feed_or_historical_values(bad_snapshot):
    running = _snapshot(state="RUNNING", phase="QUEUE_ACTIVE")
    result = _poll(
        QUEUES,
        [
            {"engine": _snapshot(), "activity": _activity(_event(1))},
            {"engine": running, "activity": 503},
            {"engine": bad_snapshot, "activity": _activity(_event(2))},
        ],
    )
    first, second, third = result["results"]
    assert "15:01:00" in first.get("record-0", {}).get("text", "")
    assert second["state"]["text"] == "En ejecución"
    assert "histórico" in second["worker-status"]["text"].lower()
    assert second["record-0"]["text"] == first["record-0"]["text"]
    assert third["state"]["text"] == "En ejecución"
    assert "histórico" in third["motor-status"]["text"].lower()
    assert "15:02:00" in third["record-0"]["text"]
    assert "histórico" not in third["worker-status"]["text"].lower()


def test_motor_b_reports_session_authentication_even_when_aggregate_phase_is_unknown():
    authenticating = _snapshot(
        MEMBERS,
        state="RUNNING",
        phase="UNKNOWN",
        sessions=[_session(phase="AUTHENTICATING")],
    )
    observed = _snapshot(
        MEMBERS,
        state="RUNNING",
        phase="UNKNOWN",
        sessions=[_session(phase="AUTH_TOKENS_OBSERVED_DOM_UNVERIFIED", has_auth=True)],
    )
    for snapshot, text in [
        (authenticating, "Autenticación en curso"),
        (observed, "sesión en la página sin confirmar"),
    ]:
        page, _, _ = render(snapshot=snapshot, engine=MEMBERS)
        assert text in page.text[MEMBERS + "-live-card"]
    first, second = _poll(
        MEMBERS,
        [{"engine": snapshot, "activity": _activity()} for snapshot in (authenticating, observed)],
    )["results"]
    assert "Autenticación en curso" in first["authentication"]["text"]
    assert "sesión en la página sin confirmar" in second["authentication"]["text"]
    assert "Autenticación en curso" not in second["authentication"]["text"]


def test_repeated_worker_diagnostic_does_not_replace_real_records_or_refresh_their_times():
    real_records = [_event(i) for i in range(1, 6)]
    cycles = []
    for seconds in (0, 5):
        checked = f"2026-11-17T19:00:0{seconds}Z"
        diagnostic = {
            "at": checked,
            "source": "chromium",
            "level": "warning",
            "message": STALE_MESSAGE,
        }
        cycles.append(
            {
                "engine": _snapshot(),
                "activity": {**_activity(*real_records, diagnostic), "observed_at": checked},
            }
        )
    first, second = _poll(QUEUES, cycles)["results"]
    assert first["record-0"]["text"].startswith("2026-11-17 15:05:00 ART")
    assert first["record-4"]["text"].startswith("2026-11-17 15:01:00 ART")
    assert all(second[f"record-{i}"] == first[f"record-{i}"] for i in range(5))
    assert second["worker-advisory"] == first["worker-advisory"]
    assert "Diagnóstico de" in second["worker-advisory"]["text"]
    assert STALE_MESSAGE in second["worker-advisory"]["text"]
    assert second["worker-time"]["text"] == "2026-11-17 16:00:05 ART"


@pytest.mark.parametrize(
    ("old_state", "old_time"),
    [
        ("CLOSED", "2026-11-17T17:20:00Z"),
        ("CLOSED", "2026-11-17T17:40:00Z"),
        ("ACTIVE", "2026-11-17T17:20:00Z"),
    ],
)
def test_event_and_queue_evidence_prefer_active_then_newest_sample(old_state, old_time):
    snapshot = _snapshot(
        state="RUNNING",
        phase="QUEUE_ACTIVE",
        created=2,
        active=1 if old_state == "CLOSED" else 2,
        sessions=[
            _session(state=old_state, observed_at=old_time),
            _session(SECOND, observed_at="2026-11-17T17:30:00Z"),
        ],
    )
    page, _, _ = render(snapshot=snapshot, engine=QUEUES)
    actual = _poll(QUEUES, [{"engine": snapshot, "activity": _activity()}])["results"][0]
    for field in ("event", "queue"):
        expected = page.text[f"{QUEUES}-live-{field}"]
        assert expected.startswith("Sesión 2:")
        assert "histórica" not in expected
        assert actual[field]["text"] == expected
