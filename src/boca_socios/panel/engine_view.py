"""Private, read-only projection and scoped forms for the two owner engines.

The snapshot contains observations, never bearer values. Inspecting a session
uses its existing private view; this module cannot navigate a worker page.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from html import escape
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID
from zoneinfo import ZoneInfo

from boca_socios.panel.members import MemberView
from boca_socios.panel.private_token_view import ART_TIME_SCRIPT
from boca_socios.panel.worker_activity import _GUEST_PUBLIC_LABELS

_ENGINES = {
    "queues_tokens": "colas y tokens",
    "browsers_members": "navegadores de socios",
}
_BROWSERS = {"chromium": "Chromium", "firefox": "Firefox", "webkit": "WebKit"}
_STATES = {
    "STOPPED": "Detenido",
    "REQUESTED": "Inicio solicitado",
    "STARTING": "Iniciando",
    "RUNNING": "En ejecución",
    "STOP_REQUESTED": "Detención solicitada",
    "STOPPING": "Deteniéndose",
    "FAILED": "Falló; consulte la última observación",
    "INDETERMINATE": "Estado no verificable",
    "UNCERTAIN": "Cierre no verificado",
    "CREATED": "Creada",
    "OPENING": "Abriendo",
    "ACTIVE": "Activa",
    "CLOSING": "Cerrando",
    "CLOSED": "Cerrada",
    "CANCELLED": "Cancelada",
}
_PHASES = {
    "WAITING_FOR_WORKER": "Esperando el arranque del navegador",
    "WORKER_RECEIPT_UNVERIFIED": "Arranque del navegador sin confirmar",
    "OPENING": "Abriendo sesiones",
    "PREQUEUE": "Prefila observada",
    "QUEUE_ACTIVE": "Cola activa observada",
    "QUEUE_INACTIVE": "La página informa que la cola no está activa",
    "NO_EVENT_OBSERVED": "La página informa que no hay eventos disponibles",
    "TARGET_OBSERVED": "Enlace de acceso recibido",
    "CHALLENGE": "La página requiere intervención del titular",
    "CHECK_FAILED": "No se pudo completar la comprobación",
    "UNKNOWN": "Sin señales suficientes para determinar evento o cola",
    "AUTHENTICATING": "Autenticación en curso",
    "AUTH_TOKENS_OBSERVED_DOM_UNVERIFIED": "Tokens recibidos; sesión en la página sin confirmar",
    "ENGINE_FAILED": "El motor informó un fallo",
    "SESSION_FAILED": "La sesión informó un fallo",
    "STOPPING": "Cerrando sesiones",
    "CLOSE_UNVERIFIED": "Cierre de sesiones sin confirmar",
    "STOPPED": "Detenido",
    "COLD": "Sin activación en este arranque",
    "PHYSICAL_STOP_CONFIRMED_PENDING_RECONCILIATION": "Worker detenido; listo para iniciar una activación nueva",
}
_PHASES["ACCESS_OBSERVED"] = _PHASES["TARGET_OBSERVED"]
_EVIDENCE_NAMES = {
    "event_state": {
        "EVENT_ANNOUNCED": "Identificador de evento recibido; faltan señales de cola o acceso",
        "EVENT_VERIFIED": "Evento identificado en la observación de la página",
        "NO_EVENT_CONFIRMED": "La página informa explícitamente que no hay eventos",
        "UNRECOGNIZED": "No se pudo identificar un evento con esta muestra",
    },
    "reason": {
        "VISIBLE_CHALLENGE": "Intervención requerida",
        "CHECK_FAILED": "Comprobación fallida",
        "HTTP_FAILURE": "Respuesta HTTP de error",
        "INVALID_OBSERVATION": "Muestra no interpretable",
        "CONTRADICTORY_EVIDENCE": "Señales contradictorias",
        "RECEIVED_TARGET": "Enlace de acceso recibido",
        "OBSERVED_IDLE": "Cola inactiva observada",
        "OBSERVED_PREQUEUE": "Prefila observada",
        "OBSERVED_QUEUE": "Cola observada",
        "EXPLICIT_NO_EVENTS": "Ausencia declarada por la página",
        "EVENT_ID_OBSERVED": "ID recibido sin otras señales",
        "NO_RECOGNIZED_EVIDENCE": "Sin señales reconocidas",
    },
    "purpose": {
        "SITE_URL": "Carga de SITE_URL",
        "QUEUE_BRIDGE": "Enlace de cola recibido",
        "RECEIVED_TARGET": "Enlace de acceso recibido",
    },
    "result": {
        "STARTED": "Inicio del intento registrado",
        "RETURNED": "La llamada de navegación retornó",
        "FAILED": "El intento falló",
        "CANCELLED": "El intento fue cancelado",
    },
}
_EVIDENCE_MISSING = "Dato no recibido"
_EVIDENCE_UNKNOWN = "Dato no recibido o no reconocido"
_EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SAMPLE_NOTICE = (
    "Cada fila conserva la última muestra recibida. "
    "Si la sesión falla o se cierra, esos datos son históricos."
)
_METRICS = {
    "requested_contexts": "Solicitados",
    "created": "Creados",
    "active": "Activos",
    "closed": "Cerrados",
    "failed": "Fallidos",
}
_SESSION_LABELS = {
    "state": "Estado observado",
    "phase": "Etapa",
    "observed_at": "Última observación",
    "outcome": "Resultado observado",
    "queue_state": "Estado de cola",
    "queue_id": "Queue ID recibido",
    "position": "Posición recibida",
    "ahead": "Personas delante, según la página",
    "queue_size": "Personas en cola, según la página",
    "expected_service_time": "Hora de acceso estimada por la página",
    "queue_opening_at": "Fecha de apertura informada por la página",
    "countdown": "Tiempo estimado hasta la apertura informada",
    "event_state": "Estado del evento observado",
    "event_id": "ID de evento observado en la página",
    "reason": "Motivo de la observación",
    "configured_url": "URL configurada",
    "navigation_attempt": "Última navegación intentada",
    "display_url": "Última URL final recibida",
    "has_target_url": "Enlace de acceso",
    "has_auth": "Respuesta de autenticación",
}
_SUMMARY_FIELDS = (
    "state",
    "phase",
    "observed_at",
    "event_state",
    "queue_state",
    "has_target_url",
    "has_auth",
)
_LEGACY_RECOVERY = {
    "NONE": {
        "button": "Confirmar cierre previo del worker",
        "status": "Sin cierre anterior pendiente.",
    },
    "REQUIRED": {
        "button": "Confirmar cierre previo del worker",
        "status": "El cierre anterior está pendiente.",
    },
    "REQUESTED": {
        "button": "Reenviar cierre previo del worker",
        "status": "El cierre fue solicitado y todavía no fue tomado. Puede reenviarlo.",
    },
    "CLAIMED": {
        "button": "Reconfirmar cierre pendiente",
        "status": "La solicitud fue tomada y el cierre sigue sin confirmar. "
        "Puede pedir otra confirmación de cierre.",
    },
}
_LIVE_EVENT = {
    "NO_EVENT_CONFIRMED": "informa que no hay evento",
    "EVENT_VERIFIED": ": evento identificado",
    "EVENT_ANNOUNCED": ": evento anunciado; sin verificar",
}
_LIVE_PHASE = {
    **_PHASES,
    # Only the per-session event field may assert that the source reported absence.
    "NO_EVENT_OBSERVED": "Comprobación de evento registrada; consulte las sesiones",
}
_LIVE_QUEUE = {
    name: _PHASES[name]
    for name in ("QUEUE_ACTIVE", "PREQUEUE", "QUEUE_INACTIVE", "ACCESS_OBSERVED")
}
_LIVE_ERRORS = {
    name: _PHASES[name]
    for name in (
        "WORKER_RECEIPT_UNVERIFIED",
        "ENGINE_FAILED",
        "SESSION_FAILED",
        "CLOSE_UNVERIFIED",
        "CHALLENGE",
        "CHECK_FAILED",
    )
}
_UNCONFIRMED_OPEN = (
    "No se confirmó la apertura del navegador. No hay una inspección de página acreditada. "
    "No se verificó navegación ni URL visitada. "
    "Causa técnica específica no registrada."
)
_LIVE_SOURCE = {
    "owner": "Panel",
    "host": "Ejecutor",
    "simulation": "Simulación",
    "chromium": "Chromium",
}
_LIVE_WORKER_ADVISORY = "Chromium: sólo hay telemetría antigua; no confirma un proceso activo."
# The activity projection emits only fixed labels. Also enforce that boundary
# here; the guest catalog covers reusable worker messages, not owner receipts.
_LIVE_WORKER_LABELS = sorted(
    {
        *_GUEST_PUBLIC_LABELS,
        "Solicitado: inicio del bot.",
        "Solicitado: detención del bot.",
        "Solicitado: inicio de Chromium.",
        "Solicitado: detención de Chromium.",
        "Bot: comprobación finalizada; detención automática solicitada.",
        "Simulación local: trabajo finalizado; detención automática solicitada.",
        "Ejecutor: solicitud recibida, verificando el servicio Boca.",
        "Ejecutor: resultado indeterminado, no repetir sin conciliación.",
        "Ejecutor: resultado físico confirmado en el momento del recibo.",
        "Ejecutor: solicitud rechazada sin aplicar cambios.",
        "Ejecutor: fallo del worker confirmado.",
    }
)
_STYLE = """
summary { min-height: 52px; padding-block: .5rem; cursor: pointer; box-sizing: border-box; }
[data-engine] { border: 1px solid #aab4c1; border-radius: .5rem;
  padding: 1rem; margin-block: 1.5rem; }
.motor-panels { display: grid; grid-template-columns: repeat(auto-fit,minmax(min(100%,21rem),1fr));
  gap: .75rem; align-items: start; }
.motor-panels > section { min-width: 0; margin-block: .25rem; }
.motor-panels dl { margin: .5rem 0; }
.motor-panels dt { font-weight: 650; }
.motor-panels dd { margin: 0 0 .35rem; }
.engine-metrics { display: grid; grid-template-columns: 1fr 1fr; gap: .4rem 1rem; }
.engine-metrics dt, .engine-session dt { font-weight: 600; }
.engine-metrics dd { margin: 0; }
.engine-session { border-top: 1px solid #aab4c1; padding-block: .7rem; }
.engine-session dd { margin: 0 0 .7rem; overflow-wrap: anywhere; }
.engine-session h4, .engine-session .session-summary { margin: .2rem 0; }
.session-summary span:not(:last-child)::after { content: " · "; }
.engine-session summary { align-content: center; }
.activity-motors { display: grid; grid-template-columns: repeat(auto-fit,minmax(min(100%,25rem),1fr));
  align-items: start; gap: 1rem; }
.activity-motors > div { min-width: 0; }
.activity-motors section { margin-block: .5rem; padding: .65rem; }
.activity-motors h2, .activity-motors h3, .activity-motors p, .activity-motors dl { margin-block: .4rem; }
.activity-motors ol { padding-inline-start: 1.45rem; }
[data-engine] fieldset { margin-block: 1rem; min-width: 0; }
[data-engine] h2, [data-engine] p { overflow-wrap: anywhere; }
.engine-live-card { border: 2px solid #64748b; border-radius: .6rem;
  padding: .85rem; margin-block: 1rem; overflow-wrap: anywhere; }
.engine-live-card h2, .engine-live-card h3 { margin: 0 0 .4rem; }
.engine-live-card p, .engine-live-card dl, .engine-live-card ol { margin: .3rem 0 .65rem; }
.engine-live-card dl { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 3fr);
  gap: .25rem .65rem; }
.engine-live-card dt { font-weight: 650; }
.engine-live-card dd { margin: 0 0 .2rem; }
.engine-live-card a:not([hidden]) { display: inline-flex; align-items: center; min-height: 52px; }
.engine-live-card a:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }
.engine-live-records { padding-inline-start: 1.35rem; }
"""

_ENGINE_CONSTANTS = (
    ART_TIME_SCRIPT
    + "\nconst engineNames = "
    + json.dumps(_ENGINES, ensure_ascii=False)
    + ";\nconst browserNames = "
    + json.dumps(_BROWSERS)
    + ";\nconst stateNames = "
    + json.dumps(_STATES, ensure_ascii=False)
    + ";\nconst phaseNames = "
    + json.dumps(_PHASES, ensure_ascii=False)
    + ";\nconst aggregateNoEvent = "
    + json.dumps(_LIVE_PHASE["NO_EVENT_OBSERVED"], ensure_ascii=False)
    + ";\nconst metricNames = "
    + json.dumps(_METRICS, ensure_ascii=False)
    + ";\nconst legacyRecoveryLabels = "
    + json.dumps(_LEGACY_RECOVERY, ensure_ascii=False)
    + ";\n"
)
_EVIDENCE_CONSTANTS = (
    "const evidenceNames = "
    + json.dumps(_EVIDENCE_NAMES, ensure_ascii=False)
    + ";\nconst sessionLabels = "
    + json.dumps(_SESSION_LABELS, ensure_ascii=False)
    + ";\nconst summaryFields = "
    + json.dumps(_SUMMARY_FIELDS)
    + ";\n"
)
_LIVE_CONSTANTS = (
    "const liveLabels = "
    + json.dumps(
        {
            "phases": _LIVE_PHASE,
            "events": _LIVE_EVENT,
            "queues": _LIVE_QUEUE,
            "errors": _LIVE_ERRORS,
            "unconfirmedOpen": _UNCONFIRMED_OPEN,
            "sources": _LIVE_SOURCE,
            "workerLabels": _LIVE_WORKER_LABELS,
            "workerAdvisory": _LIVE_WORKER_ADVISORY,
        },
        ensure_ascii=False,
    )
    + ";\n"
)
_POLL_START = """
(() => {
  const live = document.getElementById('engines-live');
  const checked = document.getElementById('engines-checked');
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
  let pending = false;
  function text(value) {
    return typeof value === 'string' && value.trim() ? value :
      Number.isFinite(value) && typeof value === 'number' && value >= 0 ?
        String(value) : 'Sin dato';
  }
  function number(value) {
    return Number.isInteger(value) && value >= 0 ? String(value) : 'Sin dato';
  }
  function state(value) {
    return Object.hasOwn(stateNames, value) ? stateNames[value] : 'Estado desconocido';
  }
  function phase(value) { return Object.hasOwn(phaseNames, value) ? phaseNames[value] : text(value); }
  function safeURL(value) {
    if (typeof value !== 'string' || value.length > 2048) return 'Sin URL observada';
    try {
      const url = new URL(value);
      if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) {
        return 'Sin URL observada';
      }
      return url.origin + url.pathname;
    } catch (_) { return 'Sin URL observada'; }
  }
  function setText(element, value) {
    if (element && element.textContent !== value) element.textContent = value;
  }
  function updateLegacyRecovery(value) {
    const section = document.getElementById('legacy-worker-recovery');
    if (!section) return;
    const labels = legacyRecoveryLabels[value];
    const button = document.getElementById('legacy-worker-recovery-button');
    section.hidden = value === 'NONE';
    button.disabled = !['REQUIRED', 'REQUESTED', 'CLAIMED'].includes(value);
    setText(button, labels.button);
    setText(document.getElementById('legacy-worker-recovery-status'), labels.status);
  }
"""
_SESSION_FIELDS_SCRIPT = """
  function evidenceName(field, value) {
    return typeof value === 'string' && Object.hasOwn(evidenceNames[field], value) ?
      evidenceNames[field][value] : 'Dato no recibido o no reconocido';
  }
  function evidenceURL(value) {
    const url = safeURL(value);
    return url === 'Sin URL observada' ? 'Dato no recibido' : url;
  }
  function navigation(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return 'Dato no recibido';
    const parts = [evidenceName('purpose', value.purpose), evidenceURL(value.display_url),
      (typeof value.started_at === 'string' && value.started_at ?
        formatPrivateTime(value.started_at) : 'Sin observación'), evidenceName('result', value.result)];
    if (value.result === 'RETURNED' && Number.isInteger(value.http_status) &&
        value.http_status >= 100 && value.http_status <= 599) parts.push('HTTP ' + value.http_status);
    return parts.join(' · ');
  }
  function inspectionLabel(item, index, engine) {
    const queue = item.has_target_url === true, auth = item.has_auth === true;
    const prefix = queue && auth ? 'Ver y copiar tokens de cola y autenticación/URL de la sesión ' :
      queue ? 'Ver y copiar token/URL de la sesión ' : auth ?
      'Ver y copiar tokens de autenticación de la sesión ' : 'Inspeccionar sesión ';
    return prefix + index + ' de ' + engineNames[engine];
  }
  function fieldValue(item, field) {
    if (field === 'queue_opening_at') return item.queue_opening_at ?
      formatPrivateTime(item.queue_opening_at) : 'Sin fecha de apertura vigente';
    if (field === 'countdown') {
      const value = item.countdown;
      if (!Number.isInteger(value) || value < 0) return 'Sin fecha de apertura vigente';
      if (value === 0) return 'Hora informada alcanzada; pendiente de confirmación de la página';
      return String(Math.floor(value / 3600)).padStart(2, '0') + ' h ' +
        String(Math.floor(value % 3600 / 60)).padStart(2, '0') + ' min ' +
        String(value % 60).padStart(2, '0') + ' s';
    }
    if (field === 'state') return state(item.state);
    if (field === 'phase') return phase(item.phase);
    if (field === 'outcome' || field === 'queue_state') {
      const value = item[field];
      return typeof value === 'string' && Object.hasOwn(phaseNames, value) ?
        phaseNames[value] : 'Sin dato';
    }
    if (field === 'observed_at') {
      return item.observed_at ? formatPrivateTime(item.observed_at) : 'Sin observación';
    }
    if (field === 'event_state' || field === 'reason') return evidenceName(field, item[field]);
    if (field === 'event_id') return typeof item.event_id === 'string' &&
      /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(item.event_id) ? item.event_id : 'Dato no recibido';
    if (field === 'configured_url') return evidenceURL(item.configured_url);
    if (field === 'navigation_attempt') return navigation(item.navigation_attempt);
    if (field === 'display_url') {
      const url = evidenceURL(item.display_url);
      return url === 'Dato no recibido' ? url : url + ' · ' +
        (item.final_url_observed_at ? formatPrivateTime(item.final_url_observed_at) : 'Sin observación');
    }
    if (field === 'has_target_url') return item.has_target_url === true ?
      'Recibido; consulte la inspección privada' : 'Sin enlace observado';
    if (field === 'has_auth') return item.has_auth === true ?
      'Respuesta recibida; no confirma una sesión autenticada en la página' :
      'Sin respuesta observada';
    return text(item[field]);
  }
"""
_EMPTY_ENGINE_SCRIPT = """
  function emptyEngine(engine) {
    return {engine, state: 'STOPPED', activation_id: null, generation: 0,
      requested_contexts: 0, created: 0, active: 0, closed: 0, failed: 0,
      sessions: [], counts: {chromium: 0, firefox: 0, webkit: 0}};
  }
"""
_SESSION_ROWS_SCRIPT = """
  function summaryValue(item, field) {
    if (field === 'state' && ['CLOSED','FAILED','STOPPED','CANCELLED'].includes(item.state))
      return fieldValue(item, field) + ' (muestra histórica)';
    if (field === 'phase') return item.phase === 'NO_EVENT_OBSERVED' ? aggregateNoEvent :
      typeof item.phase === 'string' && Object.hasOwn(phaseNames, item.phase) ? phaseNames[item.phase] : 'Etapa sin verificar';
    if (field === 'event_state' && !(typeof item.event_state === 'string' && Object.hasOwn(evidenceNames.event_state, item.event_state)))
      return 'Evento sin comprobar';
    if (field === 'queue_state' && !['QUEUE_ACTIVE','PREQUEUE','QUEUE_INACTIVE','ACCESS_OBSERVED'].includes(item.queue_state))
      return 'Cola sin comprobar';
    if (field === 'has_target_url') return item.has_target_url === true ?
      'Enlace observado' : 'Sin enlace observado';
    return fieldValue(item, field);
  }
  function updateSessions(engine, sessions) {
    const list = document.getElementById(engine + '-sessions');
    if (!list) return;
    const existing = new Map(Array.from(list.children).map(item => [item.dataset.sessionId, item]));
    const retained = new Set();
    sessions.forEach((session, index) => {
      if (!uuid.test(session.session_id) || retained.has(session.session_id)) return;
      retained.add(session.session_id);
      let row = existing.get(session.session_id);
      if (!row) {
        row = document.createElement('li');
        row.className = 'engine-session';
        row.dataset.sessionId = session.session_id;
        const heading = document.createElement('h4');
        heading.dataset.field = 'title';
        const evidence = document.createElement('p');
        evidence.className = 'session-summary';
        for (const name of summaryFields) {
          const value = document.createElement('span');
          value.dataset.summaryField = name;
          evidence.append(value);
        }
        const details = document.createElement('details');
        const summary = document.createElement('summary');
        summary.dataset.field = 'disclose';
        const fields = document.createElement('dl');
        for (const [name, label] of Object.entries(sessionLabels)) {
          const term = document.createElement('dt');
          term.textContent = label;
          const detail = document.createElement('dd');
          detail.dataset.field = name;
          fields.append(term, detail);
        }
        details.append(summary, fields);
        const link = document.createElement('a');
        link.dataset.field = 'inspect';
        link.href = '/control/sesiones/' + session.session_id;
        row.append(heading, evidence, details, link);
        list.append(row);
      }
      const name = (index + 1) + ' · ' + (browserNames[session.browser] || 'Navegador desconocido');
      setText(row.querySelector('[data-field="title"]'), 'Sesión ' + name);
      setText(row.querySelector('[data-field="disclose"]'), 'Ver observaciones de sesión ' +
        name + ' · Motor ' + (engine === 'queues_tokens' ? 'A' : 'B'));
      for (const field of summaryFields)
        setText(row.querySelector('[data-summary-field="' + field + '"]'), summaryValue(session, field));
      for (const name of Object.keys(sessionLabels)) {
        setText(row.querySelector('[data-field="' + name + '"]'), fieldValue(session, name));
      }
      setText(row.querySelector('[data-field="inspect"]'),
        inspectionLabel(session, index + 1, engine));
    });
    for (const [id, row] of existing) { if (!retained.has(id)) row.remove(); }
    document.getElementById(engine + '-no-sessions').hidden = retained.size > 0;
  }
"""
_POLL_END = """
  function updateEngine(item) {
    const engine = item.engine;
    setText(document.getElementById(engine + '-state'), state(item.state));
    setText(document.getElementById(engine + '-phase'), item.phase === 'NO_EVENT_OBSERVED' ?
      aggregateNoEvent : Object.hasOwn(phaseNames, item.phase) ? phaseNames[item.phase] : 'Etapa sin verificar');
    setText(document.getElementById(engine + '-updated'), item.updated_at ?
      formatPrivateTime(item.updated_at) : 'Sin observación');
    for (const name of Object.keys(metricNames)) {
      setText(document.getElementById(engine + '-' + name), number(item[name]));
    }
    setText(document.getElementById(engine + '-counts'),
      !uuid.test(item.activation_id) && item.requested_contexts === 0 ?
        'Sin solicitudes verificadas' : Object.entries(browserNames)
          .map(([name, label]) => label + ': ' + number((item.counts || {})[name])).join(' · '));
    const sessions = item.sessions;
    const queues = new Set(sessions.map(session => session.queue_id)
      .filter(id => typeof id === 'string' && id.trim() && id !== 'UNKNOWN'));
    setText(document.getElementById(engine + '-queues'), String(queues.size));
    const stop = document.getElementById(engine + '-stop');
    const hasActivation = uuid.test(item.activation_id) &&
      Number.isInteger(item.generation) && item.generation > 0;
    if (stop) {
      stop.elements.namedItem('activation_id').value = hasActivation ? item.activation_id : '';
      stop.elements.namedItem('generation').value = hasActivation ? String(item.generation) : '0';
      document.getElementById(engine + '-stop-button').disabled =
        !hasActivation || item.state === 'STOPPED';
      setText(document.getElementById(engine + '-stop-reason'), !hasActivation ?
        'No hay una activación identificada para detener.' : item.state === 'STOPPED' ?
        'La activación figura detenida.' : 'Detiene sólo esta activación lógica.');
    }
    const start = document.getElementById(engine + '-start-button');
    const canStart = typeof item.can_start === 'boolean' ? item.can_start :
      ['STOPPED', 'FAILED'].includes(item.state);
    if (start) {
      start.disabled = start.dataset.ready !== 'true' || !canStart;
      setText(document.getElementById(engine + '-start-reason'),
        (start.dataset.unavailable || '') + (!canStart ?
          'El estado observado no permite un nuevo inicio; consulte Actividad.' : '') ||
        'Disponible según la última consulta; el servidor vuelve a comprobar las condiciones.');
    }
    if (engine === 'browsers_members') {
      const current = document.getElementById(engine + '-current-member');
      const member = uuid.test(item.member_id) ? item.member_id : '';
      if (current && current.dataset.memberId !== member) {
        const selection = document.getElementById(engine + '-member');
        const option = Array.from(selection ? selection.children : [])
          .find(candidate => candidate.value === member);
        setText(current, !member ? 'Sin socio asociado' : option ? option.textContent :
          selection ? 'Socio no disponible en la lista actual' :
          'Socio asociado; nombre no disponible en esta vista');
        current.dataset.memberId = member;
      }
    }
    // Polling never replaces forms or changes a member/count entered by the owner.
    updateSessions(engine, sessions);
  }
  async function refreshEngines() {
    if (pending) return;
    pending = true;
    try {
      const response = await fetch('/control/motores.json', {
        credentials: 'same-origin', cache: 'no-store', redirect: 'error'});
      if (!response.ok) throw new Error('snapshot unavailable');
      const data = await response.json();
      const recoveryState = Object.hasOwn(data, 'legacy_recovery_state') ?
        data.legacy_recovery_state : 'NONE';
      if (data.version !== 1 || !Array.isArray(data.engines) || data.engines.length > 2 ||
          typeof data.observed_at !== 'string' || !Number.isInteger(data.context_limit) ||
          typeof recoveryState !== 'string' || !Object.hasOwn(legacyRecoveryLabels, recoveryState) ||
          data.context_limit < 1 || data.context_limit > 50) throw new Error('invalid snapshot');
      const seen = new Set();
      for (const item of data.engines) {
        if (!item || !Object.hasOwn(engineNames, item.engine) || seen.has(item.engine) ||
            typeof item.state !== 'string' || !Array.isArray(item.sessions) ||
            (Object.hasOwn(item, 'can_start') && typeof item.can_start !== 'boolean') ||
            item.sessions.length > 50 || item.sessions.some(session => !session ||
              typeof session !== 'object') || Object.keys(metricNames).some(name =>
              !Number.isInteger(item[name]) || item[name] < 0 || item[name] > 50)) {
          throw new Error('invalid engine');
        }
        seen.add(item.engine);
      }
      const items = Object.keys(engineNames).map(engine =>
        data.engines.find(item => item.engine === engine) || emptyEngine(engine));
      for (const item of items) updateEngine(item);
      updateLegacyRecovery(recoveryState);
      for (const name of Object.keys(metricNames)) {
        setText(document.getElementById('engines-total-' + name),
          String(items.reduce((total, item) => total + item[name], 0)));
      }
      setText(document.getElementById('engines-limit'), String(data.context_limit));
      setText(live, 'Estados y sesiones actualizados.');
      setText(checked, 'Última consulta: ' + formatPrivateTime(data.observed_at));
      return data;
    } catch (_) {
      for (const engine of Object.keys(engineNames)) {
        const state = document.getElementById(engine + '-state');
        if (state && !state.textContent.includes('histórico')) {
          setText(state, state.textContent + ' (histórico; estado actual no verificado)');
        }
        const list = document.getElementById(engine + '-sessions');
        if (!list) continue;
        for (const row of list.children) {
          const summaryState = row.querySelector('[data-summary-field="state"]');
          if (summaryState && !summaryState.textContent.includes('histórica'))
            setText(summaryState, summaryState.textContent + ' (muestra histórica; consulta fallida)');
          setText(row.querySelector('[data-field="countdown"]'), 'Sin fecha de apertura vigente');
        }
      }
      setText(live, 'No se pudo actualizar. Los estados y sesiones anteriores son históricos; '
        + 'el estado actual no está verificado.');
      setText(checked, 'Última consulta fallida.');
      return null;
    } finally { pending = false; }
  }
"""
_POLL_TRIGGER = """
  document.getElementById('engines-refresh').addEventListener('click', refreshPage);
  setInterval(() => { if (!document.hidden) refreshPage(); }, 5000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshPage(); });
  if (!document.hidden) refreshPage();
})();
"""
_LIVE_PROJECTION_SCRIPT = r"""
  const known = (labels, code) => typeof code === 'string' && Object.hasOwn(labels, code);
  function stamp(value) {
    return typeof value === 'string' &&
      /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$/.test(value)
      && Number.isFinite(Date.parse(value));
  }
  function projection(item) {
    let latest = null, lastNavigation = null, configured = null, finalURL = null, revealed = null;
    let targetCount = 0, authCount = 0, authenticating = 0, domUnverified = 0;
    const events = new Map(), queues = new Map();
    const phase = known(liveLabels.phases, item.phase) ? liveLabels.phases[item.phase] : 'Etapa sin verificar';
    let error = item.phase === 'WORKER_RECEIPT_UNVERIFIED' && item.created === 0 ?
      liveLabels.unconfirmedOpen : known(liveLabels.errors, item.phase) ? phase : '';
    item.sessions.forEach((session, index) => {
      if (!uuid.test(session.session_id)) return;
      if (!error && known(liveLabels.errors, session.phase)) error = liveLabels.errors[session.phase];
      const active = session.state === 'ACTIVE';
      if ((active || session.state === 'OBSERVED') &&
          session.phase === 'AUTHENTICATING') authenticating++;
      if (session.has_auth === true || session.phase === 'AUTH_TOKENS_OBSERVED_DOM_UNVERIFIED') {
        domUnverified++;
      }
      if (stamp(session.observed_at)) {
        const time = Date.parse(session.observed_at);
        if (!latest || time > Date.parse(latest)) latest = session.observed_at;
        const history = active ? '' : ' (muestra histórica)';
        for (const [samples, code, label] of [
          [events, session.event_state, known(liveLabels.events, session.event_state) ?
            liveLabels.events[session.event_state] : null],
          [queues, session.queue_state, known(liveLabels.queues, session.queue_state) ?
            ': ' + liveLabels.queues[session.queue_state] : null],
        ]) {
          const previous = samples.get(code);
          if (label && (!previous || (active && !previous.active) ||
              (active === previous.active && time > previous.time))) {
            samples.set(code, {active, time, text: 'Sesión ' + (index + 1) +
              (label.startsWith(':') ? label : ' ' + label) + history});
          }
        }
      }
      const observedTime = stamp(session.observed_at) ? Date.parse(session.observed_at) : -Infinity;
      if (typeof session.configured_url === 'string' && session.configured_url.trim() &&
          (!configured || observedTime > configured.time)) {
        configured = {value: session.configured_url, index, active, time: observedTime};
      }
      if (typeof session.display_url === 'string' && session.display_url.trim()) {
        const finalTime = stamp(session.final_url_observed_at) ?
          Date.parse(session.final_url_observed_at) : observedTime;
        if (!finalURL || finalTime > finalURL.time) {
          finalURL = {session, index, active, time: finalTime};
        }
      }
      const attempt = session.navigation_attempt;
      if (attempt && known(evidenceNames.purpose, attempt.purpose) &&
          known(evidenceNames.result, attempt.result) &&
          (!lastNavigation || (stamp(attempt.started_at) &&
            (!stamp(lastNavigation.attempt.started_at) ||
              Date.parse(attempt.started_at) > Date.parse(lastNavigation.attempt.started_at))))) {
        lastNavigation = {attempt, index, active};
      }
      if (session.has_target_url === true) targetCount++;
      if (session.has_auth === true) authCount++;
      if (!revealed && (session.has_target_url === true || session.has_auth === true)) {
        revealed = session.session_id;
      }
    });
    const tokens = [];
    if (targetCount) tokens.push('Enlaces observados: ' + targetCount);
    if (authCount) tokens.push('Respuesta de autenticación observada en ' + authCount + ' sesión(es)');
    const authentication = [];
    if (authenticating) authentication.push(phaseNames.AUTHENTICATING + ': ' + authenticating + ' sesión(es)');
    if (domUnverified) authentication.push(
      phaseNames.AUTH_TOKENS_OBSERVED_DOM_UNVERIFIED + ': ' + domUnverified + ' sesión(es)');
    if (!error && ['FAILED', 'INDETERMINATE', 'UNCERTAIN'].includes(item.state)) error = state(item.state);
    const historical = sample => sample.active ? '' : ' (muestra histórica)';
    return {
      state: state(item.state), phase,
      contexts: number(item.requested_contexts) + ' solicitados · ' + number(item.created) +
        ' creados · ' + number(item.active) + ' activos',
      'motor-time': stamp(item.updated_at) ? formatPrivateTime(item.updated_at) : 'Sin observación',
      'page-time': latest ? formatPrivateTime(latest) : 'Sin observación',
      event: [...events.values()].map(sample => sample.text).join(' · ') || 'No comprobado',
      queue: [...queues.values()].map(sample => sample.text).join(' · ') || 'No comprobado',
      'configured-url': configured ? 'Sesión ' + (configured.index + 1) + ': ' +
        evidenceURL(configured.value) + historical(configured) :
        'No disponible en observación; ver Configuración',
      'final-url': finalURL ? 'Sesión ' + (finalURL.index + 1) + ': ' +
        fieldValue(finalURL.session, 'display_url') + historical(finalURL) :
        'Sin URL final observada',
      tokens: tokens.join(' · ') || 'Sin tokens ni enlaces comprobados',
      authentication: authentication.join(' · ') || 'Sin observación de autenticación',
      navigation: lastNavigation ? 'Sesión ' + (lastNavigation.index + 1) + ' · ' +
        (Number.isInteger(lastNavigation.attempt.sequence) &&
        lastNavigation.attempt.sequence >= 1 && lastNavigation.attempt.sequence <= 3 ?
          'Último intento de navegación n.º ' + lastNavigation.attempt.sequence +
          ' de esta sesión · ' : '') +
        navigation(lastNavigation.attempt) + historical(lastNavigation) : 'Sin intento observado',
      error: error || 'Sin bloqueo informado', revealed
    };
  }
  function updateMotorCard(motor, data) {
    const card = field => document.getElementById(motor + '-live-' + field);
    const put = (field, value) => setText(card(field), value);
    if (data === undefined) return; // The existing motor request is still pending.
    const item = data && stamp(data.observed_at) && data.engines.find(entry => entry.engine === motor);
    if (!item) {
      put('motor-status', 'Consulta del motor no verificable. El estado mostrado es histórico.');
      return;
    }
    const {revealed, ...fields} = projection(item);
    for (const [field, value] of Object.entries(fields)) put(field, value);
    const link = card('inspect');
    if (link && revealed) {
      if (link.dataset.sessionId !== revealed) {
        link.href = '/control/sesiones/' + revealed;
        link.dataset.sessionId = revealed;
      }
      if (link.hidden) link.hidden = false;
    } else if (link && !link.hidden) {
      link.hidden = true;
      link.href = '';
      delete link.dataset.sessionId;
    }
    put('motor-query', formatPrivateTime(data.observed_at));
    put('motor-status', 'Consulta del motor disponible.');
  }
"""
_LIVE_MOTOR_SCRIPT = """
  const motor = Object.keys(engineNames).find(name =>
    document.getElementById(name + '-live-card'));
  const card = field => document.getElementById(motor + '-live-' + field);
  const put = (field, value) => setText(card(field), value);
  const workerLabels = new Set(liveLabels.workerLabels);
  let activityPending = false;
  async function refreshWorkerFeed() {
    if (activityPending) return;
    activityPending = true;
    try {
      const response = await fetch('/control/actividad.json', {
        credentials: 'same-origin', cache: 'no-store', redirect: 'error'});
      if (!response.ok) throw new Error('worker activity unavailable');
      const data = await response.json();
      if (!data || !stamp(data.observed_at) || !Array.isArray(data.events) ||
          data.events.length > 30) throw new Error('invalid activity');
      const records = data.events.filter(event => event && stamp(event.at) &&
        known(liveLabels.sources, event.source) && workerLabels.has(event.message))
        .slice(-5).reverse();
      // The snapshot stamps this diagnostic with the query time, not the time
      // of worker activity. Keep it out of the five chronological records.
      const stale = data.events.some(event => event && event.source === 'chromium' &&
        event.level === 'warning' && event.message === liveLabels.workerAdvisory);
      const advisory = card('worker-advisory');
      setText(advisory, stale ?
        'Diagnóstico de la última consulta válida: ' + liveLabels.workerAdvisory : '');
      if (advisory.hidden !== !stale) advisory.hidden = !stale;
      for (let i = 0; i < 5; i++) {
        const node = card('record-' + i);
        const item = records[i];
        if (item) {
          const source = liveLabels.sources[item.source];
          const message = item.message.startsWith(source + ':') || item.message.startsWith(source + ' ') ?
            item.message : source + ' · ' + item.message;
          setText(node, formatPrivateTime(item.at) + ' · ' + message);
        }
        if (node.hidden !== !item) node.hidden = !item;
      }
      put('worker-time', formatPrivateTime(data.observed_at));
      put('worker-status', records.length ?
        'Registros del worker compartido disponibles.' : 'Aún no hay actividad verificable.');
    } catch (_) {
      put('worker-status', 'Actividad del worker no verificable. Los registros mostrados son históricos.');
    } finally { activityPending = false; }
  }
  async function refreshPage() {
    await Promise.all([refreshEngines().then(data => updateMotorCard(motor, data)), refreshWorkerFeed()]);
  }
"""
_MOTOR_BODY = (
    _POLL_START + _SESSION_FIELDS_SCRIPT + _EMPTY_ENGINE_SCRIPT + _SESSION_ROWS_SCRIPT + _POLL_END
)
_SCRIPT = (
    _ENGINE_CONSTANTS
    + _EVIDENCE_CONSTANTS
    + _LIVE_CONSTANTS
    + _MOTOR_BODY
    + _LIVE_PROJECTION_SCRIPT
    + "async function refreshPage() { const data = await refreshEngines(); "
    + "for (const motor of Object.keys(engineNames)) updateMotorCard(motor, data); }\n"
    + _POLL_TRIGGER
)
_MOTOR_SCRIPT = (
    _ENGINE_CONSTANTS
    + _EVIDENCE_CONSTANTS
    + _LIVE_CONSTANTS
    + _MOTOR_BODY
    + _LIVE_PROJECTION_SCRIPT
    + _LIVE_MOTOR_SCRIPT
    + _POLL_TRIGGER
)
_CONTROL_SCRIPT = (
    _ENGINE_CONSTANTS
    + _LIVE_CONSTANTS
    + _EVIDENCE_CONSTANTS
    + _POLL_START
    + _SESSION_FIELDS_SCRIPT
    + _EMPTY_ENGINE_SCRIPT
    + "function updateSessions() {}\n"
    + _POLL_END
    + _LIVE_PROJECTION_SCRIPT
    + "async function refreshPage() { const data = await refreshEngines(); "
    + "for (const motor of Object.keys(engineNames)) updateMotorCard(motor, data); }\n"
    + _POLL_TRIGGER
)
# Each native redirect includes this script; omit indentation in the emitted bytes.
_SCRIPT = "\n".join(line.strip() for line in _SCRIPT.splitlines())
_MOTOR_SCRIPT = "\n".join(line.strip() for line in _MOTOR_SCRIPT.splitlines())
_CONTROL_SCRIPT = "\n".join(line.strip() for line in _CONTROL_SCRIPT.splitlines())


def csp() -> str:
    """Extend the shared page policy without introducing an import cycle."""
    from boca_socios.panel.private_ui import CSP, _hash

    return CSP.replace(
        "script-src ",
        f"script-src 'sha256-{_hash(_SCRIPT)}' 'sha256-{_hash(_CONTROL_SCRIPT)}' "
        f"'sha256-{_hash(_MOTOR_SCRIPT)}' ",
    ).replace("style-src ", f"style-src 'sha256-{_hash(_STYLE)}' ")


def _text(value: object, fallback: str = "Sin dato") -> str:
    if isinstance(value, str) and value.strip():
        return value
    if type(value) is int and value >= 0:
        return str(value)
    return fallback


def _number(value: object) -> str:
    return str(value) if type(value) is int and value >= 0 else "Sin dato"


def _time(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "Sin observación"
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            return "Hora no disponible"
        return stamp.astimezone(ZoneInfo("America/Argentina/Buenos_Aires")).strftime(
            "%Y-%m-%d %H:%M:%S ART"
        )
    except ValueError:
        return "Hora no disponible"


def _uuid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return value if str(UUID(value)) == value else None
    except ValueError:
        return None


def _url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        return "Sin URL observada"
    try:
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            return "Sin URL observada"
        return urlunsplit((url.scheme, url.netloc, url.path, "", ""))
    except ValueError:
        return "Sin URL observada"


def _entries(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value[:50] if isinstance(item, Mapping))


def _engine(snapshot: Mapping[str, object], name: str) -> Mapping[str, object]:
    for item in _entries(snapshot.get("engines")):
        if item.get("engine") == name:
            return item
    return {
        "engine": name,
        "state": "STOPPED",
        "counts": dict.fromkeys(_BROWSERS, 0),
        **dict.fromkeys(_METRICS, 0),
    }


def _hidden(name: str, value: object) -> str:
    return f'<input type="hidden" name="{name}" value="{escape(str(value), quote=True)}">'


def _legacy_recovery(
    snapshot: Mapping[str, object], csrf: str, operations: Mapping[str, str]
) -> str:
    operation = operations.get("legacy:stop")
    if not operation:
        return ""
    state = str(snapshot.get("legacy_recovery_state", "NONE"))
    labels = _LEGACY_RECOVERY.get(
        state,
        {
            "button": "Cierre previo sin verificar",
            "status": "El estado del cierre previo no está verificado.",
        },
    )
    hidden = " hidden" if state == "NONE" else ""
    disabled = "" if state in {"REQUIRED", "REQUESTED", "CLAIMED"} else " disabled"
    return (
        '<section id="legacy-worker-recovery" aria-labelledby="legacy-worker-recovery-heading"'
        + hidden
        + '><h2 id="legacy-worker-recovery-heading">Cierre de una instalación anterior</h2>'
        "<p>Esta confirmación cierra el trabajo de la instalación anterior "
        "antes de iniciar los motores nuevos.</p>"
        '<p id="legacy-worker-recovery-status" role="status" aria-live="polite">'
        + labels["status"]
        + '</p><form id="legacy-worker-recovery-form" method="post" action="/control/bot/detener">'
        + _hidden("csrf", csrf)
        + _hidden("operation_id", operation)
        + '<button id="legacy-worker-recovery-button" type="submit"'
        + disabled
        + ">"
        + labels["button"]
        + "</button></form></section>"
    )


def _evidence_name(field: str, value: object) -> str:
    return (
        _EVIDENCE_NAMES[field].get(value, _EVIDENCE_UNKNOWN)
        if isinstance(value, str)
        else _EVIDENCE_UNKNOWN
    )


def _evidence_url(value: object) -> str:
    url = _url(value)
    return _EVIDENCE_MISSING if url == "Sin URL observada" else url


def _navigation(value: object) -> str:
    if not isinstance(value, Mapping):
        return _EVIDENCE_MISSING
    parts = [
        _evidence_name("purpose", value.get("purpose")),
        _evidence_url(value.get("display_url")),
        _time(value.get("started_at")),
        _evidence_name("result", value.get("result")),
    ]
    status = value.get("http_status")
    if value.get("result") == "RETURNED" and type(status) is int and 100 <= status <= 599:
        parts.append(f"HTTP {status}")
    return " · ".join(parts)


def _inspection_label(session: Mapping[str, object], index: int, engine: str) -> str:
    queue, auth = session.get("has_target_url") is True, session.get("has_auth") is True
    prefix = (
        "Ver y copiar tokens de cola y autenticación/URL de la sesión "
        if queue and auth
        else "Ver y copiar token/URL de la sesión "
        if queue
        else "Ver y copiar tokens de autenticación de la sesión "
        if auth
        else "Inspeccionar sesión "
    )
    return f"{prefix}{index} de {_ENGINES[engine]}"


def _session_value(session: Mapping[str, object], field: str) -> str:
    value = session.get(field)
    if field == "queue_opening_at":
        return _time(value) if value else "Sin fecha de apertura vigente"
    if field == "countdown":
        if type(value) is not int or value < 0:
            return "Sin fecha de apertura vigente"
        if value == 0:
            return "Hora informada alcanzada; pendiente de confirmación de la página"
        hours, remainder = divmod(value, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d} h {minutes:02d} min {seconds:02d} s"
    if field == "state":
        return _STATES.get(str(value), "Estado desconocido")
    if field == "phase":
        return _PHASES.get(str(value), _text(value))
    if field in {"outcome", "queue_state"}:
        return _PHASES.get(value, "Sin dato") if isinstance(value, str) else "Sin dato"
    if field == "observed_at":
        return _time(value)
    if field in {"event_state", "reason"}:
        return _evidence_name(field, value)
    if field == "event_id":
        return value if isinstance(value, str) and _EVENT_ID.fullmatch(value) else _EVIDENCE_MISSING
    if field == "configured_url":
        return _evidence_url(value)
    if field == "navigation_attempt":
        return _navigation(value)
    if field == "display_url":
        url = _evidence_url(value)
        return (
            url + " · " + _time(session.get("final_url_observed_at"))
            if url != _EVIDENCE_MISSING
            else url
        )
    if field == "has_target_url":
        return (
            "Recibido; consulte la inspección privada" if value is True else "Sin enlace observado"
        )
    if field == "has_auth":
        return (
            "Respuesta recibida; no confirma una sesión autenticada en la página"
            if value is True
            else "Sin respuesta observada"
        )
    return _text(value)


def _summary_value(session: Mapping[str, object], field: str) -> str:
    value = str(session.get(field))
    if field == "state" and value in {"CLOSED", "FAILED", "STOPPED", "CANCELLED"}:
        return _session_value(session, field) + " (muestra histórica)"
    if field == "phase":
        return _LIVE_PHASE.get(value, "Etapa sin verificar")
    if field == "event_state" and value not in _EVIDENCE_NAMES[field]:
        return "Evento sin comprobar"
    if field == "queue_state" and value not in _LIVE_QUEUE:
        return "Cola sin comprobar"
    if field == "has_target_url":
        return "Enlace observado" if session.get(field) is True else "Sin enlace observado"
    return _session_value(session, field)


def _session_rows(engine: str, sessions: tuple[Mapping[str, object], ...]) -> str:
    rows = []
    seen: set[str] = set()
    for index, session in enumerate(sessions, 1):
        session_id = _uuid(session.get("session_id"))
        if session_id is None or session_id in seen:
            continue
        seen.add(session_id)
        browser = _BROWSERS.get(str(session.get("browser")), "Navegador desconocido")
        fields = "".join(
            f'<dt>{label}</dt><dd data-field="{field}">'
            + escape(_session_value(session, field))
            + "</dd>"
            for field, label in _SESSION_LABELS.items()
        )
        summary = "".join(
            f'<span data-summary-field="{field}">{escape(_summary_value(session, field))}</span>'
            for field in _SUMMARY_FIELDS
        )
        rows.append(
            f'<li class="engine-session" data-session-id="{session_id}">'
            f'<h4 data-field="title">Sesión {index} · {browser}</h4><p class="session-summary">{summary}</p>'
            f'<details><summary data-field="disclose">Ver observaciones de sesión {index} · {browser} · '
            f"Motor {'A' if engine == 'queues_tokens' else 'B'}</summary><dl>{fields}</dl></details>"
            f'<a data-field="inspect" href="/control/sesiones/{session_id}">'
            f"{_inspection_label(session, index, engine)}</a></li>"
        )
    return "".join(rows)


def _forms(
    engine: str,
    item: Mapping[str, object],
    csrf: str,
    operations: Mapping[str, str],
    members: tuple[MemberView, ...],
    site_url_ready: bool,
) -> str:
    name = _ENGINES[engine]
    active_members = tuple(member for member in members if member.credential_active)
    ready = site_url_ready and (engine == "queues_tokens" or bool(active_members))
    unavailable = ""
    if not site_url_ready:
        unavailable += "SITE_URL no está configurada o sincronizada; revise Configuración. "
    if engine == "browsers_members" and not active_members:
        unavailable += "Hace falta un socio con credencial activa. "
    can_start = item.get("can_start")
    if type(can_start) is not bool:
        can_start = item.get("state") in {"STOPPED", "FAILED"}
    start_disabled = "" if ready and can_start else " disabled"
    start_reason = unavailable + (
        "El estado observado no permite un nuevo inicio; consulte Actividad."
        if not can_start
        else ""
    )
    start_reason = (
        start_reason
        or "Disponible según la última consulta; el servidor vuelve a comprobar las condiciones."
    )
    fields = "".join(
        f'<label for="{engine}-{browser}">{label} de {name}</label>'
        f'<input id="{engine}-{browser}" name="{browser}" type="number" '
        f'inputmode="numeric" min="0" max="50" step="1" value="{count}" required>'
        for (browser, label), count in zip(_BROWSERS.items(), (15, 5, 5), strict=True)
    )
    member_selection = ""
    if engine == "browsers_members":
        options = "".join(
            f'<option value="{escape(member.member_id, quote=True)}">'
            + escape((member.display_name or "Socio local") + " · " + member.masked_email)
            + "</option>"
            for member in active_members
        )
        member_selection = (
            f'<label for="{engine}-member">Socio para el motor de {name}</label>'
            f'<select id="{engine}-member" name="member_id" required>'
            '<option value="" selected>Elegir socio</option>' + options + "</select>"
        )
        if not active_members:
            member_selection += (
                '<p>Hace falta un socio con credencial activa. <a href="/socios">Ver socios</a></p>'
            )
    activation = _uuid(item.get("activation_id"))
    generation = item.get("generation")
    can_stop = activation is not None and type(generation) is int and generation > 0
    stop_disabled = "" if can_stop and item.get("state") != "STOPPED" else " disabled"
    stop_reason = (
        "No hay una activación identificada para detener."
        if not can_stop
        else "La activación figura detenida."
        if item.get("state") == "STOPPED"
        else "Detiene sólo esta activación lógica."
    )
    return (
        f'<form id="{engine}-start" method="post" action="/control/motores/{engine}/iniciar">'
        + _hidden("csrf", csrf)
        + _hidden("operation_id", operations[f"{engine}:start"])
        + f"<fieldset><legend>Configurar el próximo inicio de {name}</legend>"
        + "<details><summary>Cantidades de navegadores: 15 / 5 / 5 por defecto</summary>"
        + fields
        + "</details>"
        + member_selection
        + f'<p id="{engine}-start-reason">{escape(start_reason)}</p>'
        + f'<button id="{engine}-start-button" type="submit" '
        f'aria-describedby="{engine}-start-reason" data-unavailable="{escape(unavailable, quote=True)}" '
        f'data-ready="{str(ready).lower()}"{start_disabled}>Iniciar motor de {name}</button>'
        "</fieldset></form>"
        f'<form id="{engine}-stop" method="post" action="/control/motores/{engine}/detener">'
        + _hidden("csrf", csrf)
        + _hidden("operation_id", operations[f"{engine}:stop"])
        + _hidden("activation_id", activation or "")
        + _hidden("generation", generation if can_stop else 0)
        + f'<p id="{engine}-stop-reason">{escape(stop_reason)}</p>'
        + f'<button id="{engine}-stop-button" type="submit" '
        f'aria-describedby="{engine}-stop-reason"{stop_disabled}>'
        f"Detener motor de {name}</button></form>"
    )


def _distribution(item: Mapping[str, object]) -> str:
    if _uuid(item.get("activation_id")) is None and item.get("requested_contexts") == 0:
        return "Sin solicitudes verificadas"
    counts = item.get("counts")
    counts = counts if isinstance(counts, Mapping) else {}
    return " · ".join(
        f"{label}: {_number(counts.get(browser))}" for browser, label in _BROWSERS.items()
    )


def _live_stamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)", value
    ):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _live_projection(item: Mapping[str, object]) -> tuple[dict[str, str], str | None]:
    event_samples: dict[str, tuple[tuple[bool, datetime], str]] = {}
    queue_samples: dict[str, tuple[tuple[bool, datetime], str]] = {}
    latest: datetime | None = None
    navigation: Mapping[str, object] | None = None
    navigation_time: datetime | None = None
    navigation_index = 0
    navigation_historical = False
    configured: tuple[int, Mapping[str, object]] | None = None
    configured_time: datetime | None = None
    final_url: tuple[int, Mapping[str, object]] | None = None
    final_url_time: datetime | None = None
    inspection = None
    targets = auth = authenticating = dom_unverified = 0
    phase = str(item.get("phase"))
    state = str(item.get("state"))
    error = _LIVE_ERRORS.get(phase)
    if phase == "WORKER_RECEIPT_UNVERIFIED" and item.get("created") == 0:
        error = _UNCONFIRMED_OPEN
    for index, session in enumerate(_entries(item.get("sessions")), 1):
        session_id = _uuid(session.get("session_id"))
        if session_id is None:
            continue
        session_phase = str(session.get("phase"))
        session_state = session.get("state")
        error = error or _LIVE_ERRORS.get(session_phase)
        active = session_state == "ACTIVE"
        if (active or session_state == "OBSERVED") and session_phase == "AUTHENTICATING":
            authenticating += 1
        has_auth = session.get("has_auth") is True
        if has_auth or session_phase == "AUTH_TOKENS_OBSERVED_DOM_UNVERIFIED":
            dom_unverified += 1
        when = _live_stamp(session.get("observed_at"))
        if when is not None:
            if latest is None or when > latest:
                latest = when
            history = "" if active else " (muestra histórica)"
            rank = (active, when)
            for samples, codes, field in (
                (event_samples, _LIVE_EVENT, "event_state"),
                (queue_samples, _LIVE_QUEUE, "queue_state"),
            ):
                code = str(session.get(field))
                label = codes.get(code)
                previous = samples.get(code)
                if label is not None and (previous is None or rank > previous[0]):
                    separator = (
                        ": " if field == "queue_state" else "" if label.startswith(":") else " "
                    )
                    samples[code] = (rank, f"Sesión {index}{separator}{label}{history}")
        configured_value = session.get("configured_url")
        if (
            isinstance(configured_value, str)
            and configured_value.strip()
            and (
                configured is None
                or (when is not None and (configured_time is None or when > configured_time))
            )
        ):
            configured, configured_time = (index, session), when
        final_value = session.get("display_url")
        final_when = _live_stamp(session.get("final_url_observed_at")) or when
        if (
            isinstance(final_value, str)
            and final_value.strip()
            and (
                final_url is None
                or (
                    final_when is not None
                    and (final_url_time is None or final_when > final_url_time)
                )
            )
        ):
            final_url, final_url_time = (index, session), final_when
        attempt = session.get("navigation_attempt")
        if (
            isinstance(attempt, Mapping)
            and str(attempt.get("purpose")) in _EVIDENCE_NAMES["purpose"]
            and str(attempt.get("result")) in _EVIDENCE_NAMES["result"]
        ):
            when = _live_stamp(attempt.get("started_at"))
            if navigation is None or (
                when is not None and (navigation_time is None or when > navigation_time)
            ):
                navigation, navigation_time = attempt, when
                navigation_index, navigation_historical = index, not active
        has_target = session.get("has_target_url") is True
        targets += has_target
        auth += has_auth
        if inspection is None and (has_target or has_auth):
            inspection = session_id
    tokens = []
    if targets:
        tokens.append(f"Enlaces observados: {targets}")
    if auth:
        tokens.append(f"Respuesta de autenticación observada en {auth} sesión(es)")
    authentication = [
        f"{_PHASES[code]}: {count} sesión(es)"
        for code, count in (
            ("AUTHENTICATING", authenticating),
            ("AUTH_TOKENS_OBSERVED_DOM_UNVERIFIED", dom_unverified),
        )
        if count
    ]
    if error is None and state in {"FAILED", "INDETERMINATE", "UNCERTAIN"}:
        error = _STATES[state]
    configured_text = "No disponible en observación; ver Configuración"
    if configured is not None:
        index, session = configured
        history = " (muestra histórica)" if session.get("state") != "ACTIVE" else ""
        configured_text = f"Sesión {index}: {_evidence_url(session.get('configured_url'))}{history}"
    final_text = "Sin URL final observada"
    if final_url is not None:
        index, session = final_url
        history = " (muestra histórica)" if session.get("state") != "ACTIVE" else ""
        final_text = f"Sesión {index}: {_session_value(session, 'display_url')}{history}"
    sequence_prefix = ""
    if navigation is not None:
        sequence = navigation.get("sequence")
        if type(sequence) is int and 1 <= sequence <= 3:
            sequence_prefix = f"Último intento de navegación n.º {sequence} de esta sesión · "
    return (
        {
            "state": _STATES.get(state, "Estado desconocido"),
            "phase": _LIVE_PHASE.get(phase, "Etapa sin verificar"),
            "contexts": (
                f"{_number(item.get('requested_contexts'))} solicitados · "
                f"{_number(item.get('created'))} creados · {_number(item.get('active'))} activos"
            ),
            "motor-time": _time(item.get("updated_at"))
            if _live_stamp(item.get("updated_at"))
            else "Sin observación",
            "page-time": _time(latest.isoformat() if latest else None),
            "event": " · ".join(text for _, text in event_samples.values()) or "No comprobado",
            "queue": " · ".join(text for _, text in queue_samples.values()) or "No comprobado",
            "configured-url": configured_text,
            "final-url": final_text,
            "tokens": " · ".join(tokens) or "Sin tokens ni enlaces comprobados",
            "authentication": " · ".join(authentication) or "Sin observación de autenticación",
            "navigation": (
                f"Sesión {navigation_index} · {sequence_prefix}{_navigation(navigation)}"
                + (" (muestra histórica)" if navigation_historical else "")
                if navigation is not None
                else "Sin intento observado"
            ),
            "error": error or "Sin bloqueo informado",
        },
        inspection,
    )


def _live_card(
    engine: str,
    snapshot: Mapping[str, object],
    *,
    include_worker_details: bool = True,
    heading_id: str | None = None,
) -> str:
    item = next(
        (item for item in _entries(snapshot.get("engines")) if item.get("engine") == engine),
        {},
    )
    values, inspection = _live_projection(item)
    prefix = f"{engine}-live-"
    label = f"Estado del bot · Motor {'A' if engine == 'queues_tokens' else 'B'}"
    href = (
        f' href="/control/sesiones/{inspection}" data-session-id="{inspection}"'
        if inspection
        else " hidden"
    )
    fields = {
        "contexts": "Contextos",
        "error": "Error o bloqueo",
        "configured-url": "URL configurada según sesión",
        "navigation": "Último intento de navegación registrado",
        "final-url": "Última URL final observada",
        "event": "Evento según sesión",
        "queue": "Cola según sesión",
        "tokens": "Tokens y enlaces",
        **(
            {
                "authentication": "Autenticación según sesión",
            }
            if engine == "browsers_members"
            else {}
        ),
    }
    worker_details = (
        f'<details id="{prefix}worker-details"><summary>Registro técnico global del worker '
        "compartido (no corresponde a navegación del motor)</summary>"
        "<p>Son registros globales, no navegaciones confirmadas de este motor.</p>"
        f'<p id="{prefix}worker-status" role="status">Aún no hay actividad verificable.</p>'
        f'<p id="{prefix}worker-advisory" hidden></p>'
        f'<ol class="engine-live-records" aria-label="Registros del worker compartido">'
        + "".join(f'<li id="{prefix}record-{index}" hidden></li>' for index in range(5))
        + "</ol>"
        f'<p>Consulta de actividad: <span id="{prefix}worker-time">Sin consultar</span></p>'
        '<p><a href="/control/actividad">Abrir actividad detallada</a></p></details>'
        if include_worker_details
        else ""
    )
    heading_attr = f' id="{heading_id}"' if heading_id else ""
    return (
        f'<section class="engine-live-card" id="{prefix}card" aria-label="{label}">'
        f"<h2{heading_attr}>{label}</h2>"
        f'<p aria-live="polite">Último estado lógico registrado: '
        f'<strong id="{prefix}state">{escape(values["state"])}</strong>'
        f' · <span id="{prefix}phase">{escape(values["phase"])}</span></p>'
        f'<p>Último cambio lógico: <span id="{prefix}motor-time">{values["motor-time"]}</span>'
        f' · Actividad física actual: <span id="{prefix}physical-status">'
        "No comprobada en esta vista</span></p>"
        f'<p id="{prefix}status-scope">El resultado lógico no acredita un worker activo '
        "ni un fallo físico actual.</p>"
        "<dl>"
        + "".join(
            f'<dt>{term}</dt><dd><span id="{prefix}{name}">{escape(values[name])}</span>'
            + (
                f' <a id="{prefix}inspect"{href}>Abrir inspección privada</a>'
                if name == "tokens"
                else ""
            )
            + "</dd>"
            for name, term in fields.items()
        )
        + "</dl>"
        f'<p>Última observación de página: <span id="{prefix}page-time">{values["page-time"]}</span><br>'
        f'Consulta del motor: <span id="{prefix}motor-query">{_time(snapshot.get("observed_at"))}</span></p>'
        f'<p id="{prefix}motor-status" role="status">'
        + ("Consulta del motor disponible." if item else "Estado del motor sin verificar.")
        + "</p>"
        + worker_details
        + "</section>"
    )


def _current_member_line(
    engine: str, item: Mapping[str, object], members: tuple[MemberView, ...]
) -> str:
    if engine != "browsers_members":
        return ""
    identifier = _uuid(item.get("member_id"))
    member = next((member for member in members if member.member_id == identifier), None)
    label = (
        (member.display_name or "Socio local") + " · " + member.masked_email
        if member is not None
        else "Socio no disponible en la lista actual"
        if identifier
        else "Sin socio asociado"
    )
    return (
        f'<p>Socio de esta activación: <span id="{engine}-current-member" '
        f'data-member-id="{identifier or ""}">{escape(label)}</span></p>'
    )


def _section(
    engine: str,
    item: Mapping[str, object],
    csrf: str,
    operations: Mapping[str, str],
    members: tuple[MemberView, ...],
    site_url_ready: bool,
    *,
    controls: bool = True,
    summary: bool = False,
    compact_controls: bool = False,
    heading_id: str | None = None,
    show_current_member: bool = True,
) -> str:
    resolved_heading_id = heading_id or f"{engine}-heading"
    state = escape(_STATES.get(str(item.get("state")), "Estado desconocido"))
    metrics = "".join(
        f'<dt>{label}</dt><dd id="{engine}-{name}">{_number(item.get(name))}</dd>'
        for name, label in _METRICS.items()
    )
    distribution = _distribution(item)
    sessions = _entries(item.get("sessions"))
    queue_ids = {
        value
        for session in sessions
        if isinstance(value := session.get("queue_id"), str)
        and value.strip()
        and value != "UNKNOWN"
    }
    current_member = _current_member_line(engine, item, members) if show_current_member else ""
    return (
        f'<section data-engine="{engine}" aria-labelledby="{resolved_heading_id}">'
        f'<h2 id="{resolved_heading_id}">'
        + (
            f"Acciones del motor {'A' if engine == 'queues_tokens' else 'B'}"
            if compact_controls
            else f"Motor {'A' if engine == 'queues_tokens' else 'B'}: {_ENGINES[engine]}"
        )
        + "</h2>"
        + (
            f'<details id="{engine}-advanced-status"><summary>Estado técnico adicional del motor</summary>'
            if compact_controls
            else ""
        )
        + f'<p>Estado observado: <strong id="{engine}-state">{state}</strong></p>'
        + f'<p>Etapa: <span id="{engine}-phase">'
        + escape(_LIVE_PHASE.get(str(item.get("phase")), "Etapa sin verificar"))
        + "</span><br>"
        + f'Última observación: <span id="{engine}-updated">{_time(item.get("updated_at"))}</span></p>'
        + ("</details>" if compact_controls else "")
        + current_member
        + (_compact_summary(engine, item) if summary else "")
        + (
            _forms(engine, item, csrf, operations, members, site_url_ready)
            if controls
            else f'<dl class="engine-metrics">{metrics}<dt>Queue ID distintos observados</dt>'
            f'<dd id="{engine}-queues">{len(queue_ids)}</dd></dl>'
            f'<p>Distribución solicitada: <span id="{engine}-counts">{distribution}</span></p>'
        )
        + "</section>"
    )


def _compact_summary(engine: str, item: Mapping[str, object]) -> str:
    values, _ = _live_projection(item)
    prefix = f"{engine}-live-"
    fields = {
        "contexts": "Contextos",
        "navigation": "Sitio",
        "event": "Evento",
        "queue": "Cola",
        "tokens": "Tokens y enlaces",
        "page-time": "Última observación de página",
        "error": "Error o bloqueo",
    }
    rows = "".join(
        f'<dt>{term}</dt><dd id="{prefix}{field}">{escape(values[field])}</dd>'
        for field, term in fields.items()
    )
    letter = "A" if engine == "queues_tokens" else "B"
    return (
        f'<dl>{rows}</dl><p id="{prefix}motor-status" role="status"></p>'
        f'<p><a href="/control/actividad#{engine}-heading">Ver actividad del motor {letter}</a></p>'
    )


def _history(engine: str, item: Mapping[str, object]) -> str:
    rows = _session_rows(engine, _entries(item.get("sessions")))
    return (
        f"<h3>Sesiones de {_ENGINES[engine]}</h3>"
        f'<p id="{engine}-no-sessions"'
        + (" hidden" if rows else "")
        + ">Sin sesiones observadas.</p>"
        f'<ol id="{engine}-sessions">{rows}</ol>'
    )


def _poll_status(snapshot: Mapping[str, object]) -> str:
    return (
        '<p id="engines-live" role="status" aria-live="polite">Último estado disponible.</p>'
        f'<p id="engines-checked">Última consulta: {_time(snapshot.get("observed_at"))}</p>'
        '<button id="engines-refresh" type="button">Actualizar motores y sesiones</button>'
    )


def activity_content(snapshot: Mapping[str, object], members: tuple[MemberView, ...]) -> str:
    """Reuse the read-only engine projection, without minting any operation."""
    engines = {name: _engine(snapshot, name) for name in _ENGINES}
    totals = []
    for field, label in _METRICS.items():
        values = [item.get(field) for item in engines.values()]
        total = (
            str(sum(value for value in values if type(value) is int))
            if all(type(value) is int and value >= 0 for value in values)
            else "Sin dato"
        )
        totals.append(f'{label}: <span id="engines-total-{field}">{total}</span>')
    technical = (
        '<details id="engines-global-technical"><summary>Datos técnicos de los motores</summary>'
        + "<p>Dos motores lógicos comparten un worker físico. Estos estados no certifican "
        "por sí solos la salud de Docker. SIMULATION_ONLY; sin reservas reales.</p>"
        '<p>Límite conjunto de solicitudes: <span id="engines-limit">'
        + _number(snapshot.get("context_limit", 50))
        + "</span> contextos. La capacidad efectiva del servidor se comprueba al crearlos.</p>"
        "<p>Solicitudes, contextos creados y Queue ID distintos son medidas diferentes. "
        "Varias sesiones pueden compartir un Queue ID; no demuestran posiciones de cola independientes.</p>"
        "<p>Una consulta reciente no es una observación nueva del worker. "
        "Arranque sin confirmar (WORKER_RECEIPT_UNVERIFIED) no significa ausencia de evento. "
        "URL configurada no acredita navegación.</p>"
        + "<h2>Totales observados</h2><p>"
        + " · ".join(totals)
        + "</p>"
        + _poll_status(snapshot)
        + "</details>"
    )
    content = (
        '<p><a href="#queues_tokens-heading">Actividad del motor A</a> · '
        '<a href="#browsers_members-heading">Actividad del motor B</a></p>'
        '<div class="activity-motors">'
        + "".join(
            "<div>"
            + _live_card(
                name,
                snapshot,
                include_worker_details=False,
                heading_id=f"{name}-heading",
            )
            + _current_member_line(name, item, members)
            + f'<details class="activity-motor-details" id="{name}-advanced">'
            + f"<summary>Sesiones y métricas del motor {'A' if name == 'queues_tokens' else 'B'}</summary>"
            + f"<p>{_SAMPLE_NOTICE}</p>"
            + _section(
                name,
                item,
                "",
                {},
                members,
                False,
                controls=False,
                heading_id=f"{name}-technical-heading",
                show_current_member=False,
            )
            + _history(name, item)
            + "</details></div>"
            for name, item in engines.items()
        )
        + "</div>"
        + technical
    )
    return content


def page(
    snapshot: Mapping[str, object],
    csrf: str,
    operations: Mapping[str, str],
    members: tuple[MemberView, ...],
    *,
    site_url_ready: bool,
    engine: str | None = None,
) -> bytes:
    """Render short owner controls; only authenticated POST routes create effects."""
    from boca_socios.panel.private_ui import _page

    engines = {
        name: _engine(snapshot, name) for name in _ENGINES if engine is None or name == engine
    }
    title = {
        "queues_tokens": "Motor A · Colas y tokens",
        "browsers_members": "Motor B · Navegadores y socios",
    }.get(engine or "", "Control de motores")
    content = (
        f"<h1>{title}</h1>"
        "<p>SIMULATION_ONLY. Sin reservas ni compras reales. "
        "Dos motores lógicos, un worker físico; inicio y detención independientes.</p>"
        + (_live_card(engine, snapshot) if engine is not None else "")
        + _poll_status(snapshot)
    )
    if not site_url_ready:
        content += '<p>Configure la URL de destino antes de iniciar. <a href="/configuracion">Abrir configuración</a></p>'
    content += _legacy_recovery(snapshot, csrf, operations)
    sections = "".join(
        _section(
            name,
            item,
            csrf,
            operations,
            members,
            site_url_ready,
            summary=engine is None,
            compact_controls=engine is not None,
        )
        for name, item in engines.items()
    )
    content += sections if engine is not None else f'<div class="motor-panels">{sections}</div>'
    if engine is not None:
        item = engines[engine]
        content += (
            "<h2>Actividad observada de este motor</h2>"
            "<p>Una consulta reciente no es un evento nuevo del worker. "
            "Arranque sin confirmar (WORKER_RECEIPT_UNVERIFIED) no significa ausencia de evento. "
            "Los contadores solicitado, creado y activo no certifican salud física. "
            "URL configurada no acredita navegación.</p>"
            "<p>Múltiples contextos concurrentes de Chromium, Firefox y WebKit comparten "
            "el presupuesto global existente. Cada sesión conserva su propia observación; "
            "no acredita posiciones de cola independientes ni entradas adicionales.</p>"
            + f"<p>{_SAMPLE_NOTICE}</p>"
            + '<dl class="engine-metrics">'
            + "".join(
                f'<dt>{label}</dt><dd id="{engine}-{name}">{_number(item.get(name))}</dd>'
                for name, label in _METRICS.items()
            )
            + "</dl>"
            + f'<p>Distribución solicitada recibida: <span id="{engine}-counts">'
            + _distribution(item)
            + "</span></p>"
            "<p>Sin desglose verificable de creados/activos por tipo de navegador. "
            "Creados y activos son totales del motor; las cantidades del formulario "
            "configuran únicamente el próximo inicio.</p>"
        )
        if engine == "queues_tokens":
            content += "<p>La revelación requiere el POST privado autorizado de la sesión; no se valida el token.</p>"
        else:
            content += "<p>Reserva real y capturas terminales no están implementadas. No se confirma ninguna entrada.</p>"
        content += _history(engine, item)
    content += (
        "<noscript>La página conserva el estado de la última consulta. "
        "Recargue para consultar cambios; los formularios funcionan sin JavaScript.</noscript>"
    )
    return _page(
        title,
        content,
        current="/control",
        script=f"<style>{_STYLE}</style><script>{_MOTOR_SCRIPT if engine else _CONTROL_SCRIPT}</script>",
    )
