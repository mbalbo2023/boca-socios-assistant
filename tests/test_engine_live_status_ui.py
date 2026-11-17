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
      const key = selector.match(/data-field="([^"]+)"/)[1];
      const search = item => item.dataset.field === key ? item :
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


def _poll(engine, cycles):
    page, body, _ = render(snapshot=_snapshot(engine), engine=engine)
    node = shutil.which("node")
    assert node
    result = subprocess.run(  # noqa: S603 - fixed offline runtime and the actual static UI script
        [node, "-e", _HARNESS],
        input=json.dumps(
            {
                "engine": engine,
                "elements": [attrs for _, attrs in page.elements if attrs.get("id")],
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
