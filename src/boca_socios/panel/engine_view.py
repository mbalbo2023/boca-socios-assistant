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
    "countdown": "Cuenta regresiva recibida",
    "event_state": "Estado del evento observado",
    "event_id": "ID de evento observado en la página",
    "reason": "Motivo de la observación",
    "configured_url": "URL configurada",
    "navigation_attempt": "Última navegación intentada",
    "display_url": "Última URL final recibida",
    "has_target_url": "Enlace de acceso",
    "has_auth": "Respuesta de autenticación",
}
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
_STYLE = """
[data-engine] { border: 1px solid #aab4c1; border-radius: .5rem;
  padding: 1rem; margin-block: 1.5rem; }
.engine-metrics { display: grid; grid-template-columns: 1fr 1fr; gap: .4rem 1rem; }
.engine-metrics dt, .engine-session dt { font-weight: 600; }
.engine-metrics dd { margin: 0; }
.engine-session { border-top: 1px solid #aab4c1; padding-block: .7rem; }
.engine-session dd { margin: 0 0 .7rem; overflow-wrap: anywhere; }
[data-engine] fieldset { margin-block: 1rem; min-width: 0; }
[data-engine] h2, [data-engine] p { overflow-wrap: anywhere; }
"""

_SCRIPT = (
    ART_TIME_SCRIPT
    + "\nconst engineNames = "
    + json.dumps(_ENGINES, ensure_ascii=False)
    + ";\nconst browserNames = "
    + json.dumps(_BROWSERS)
    + ";\nconst stateNames = "
    + json.dumps(_STATES, ensure_ascii=False)
    + ";\nconst phaseNames = "
    + json.dumps(_PHASES, ensure_ascii=False)
    + ";\nconst metricNames = "
    + json.dumps(_METRICS, ensure_ascii=False)
    + ";\nconst evidenceNames = "
    + json.dumps(_EVIDENCE_NAMES, ensure_ascii=False)
    + ";\nconst sessionLabels = "
    + json.dumps(_SESSION_LABELS, ensure_ascii=False)
    + ";\nconst legacyRecoveryLabels = "
    + json.dumps(_LEGACY_RECOVERY, ensure_ascii=False)
    + ";\n"
    + """
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
    const prefix = queue && auth ? 'Ver tokens de cola y autenticación de la sesión ' :
      queue ? 'Ver token de cola de la sesión ' : auth ?
      'Ver tokens de autenticación de la sesión ' : 'Inspeccionar sesión ';
    return prefix + index + ' de ' + engineNames[engine];
  }
  function fieldValue(item, field) {
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
  function emptyEngine(engine) {
    return {engine, state: 'STOPPED', activation_id: null, generation: 0,
      requested_contexts: 0, created: 0, active: 0, closed: 0, failed: 0,
      sessions: [], counts: {chromium: 0, firefox: 0, webkit: 0}};
  }
  function updateSessions(engine, sessions) {
    const list = document.getElementById(engine + '-sessions');
    const existing = new Map(Array.from(list.children).map(item => [item.dataset.sessionId, item]));
    const retained = new Set();
    sessions.forEach((session, index) => {
      if (!uuid.test(session.session_id)) return;
      retained.add(session.session_id);
      let row = existing.get(session.session_id);
      if (!row) {
        row = document.createElement('li');
        row.className = 'engine-session';
        row.dataset.sessionId = session.session_id;
        const heading = document.createElement('h4');
        heading.dataset.field = 'title';
        row.append(heading);
        const fields = document.createElement('dl');
        for (const [name, label] of Object.entries(sessionLabels)) {
          const term = document.createElement('dt');
          term.textContent = label;
          const detail = document.createElement('dd');
          detail.dataset.field = name;
          fields.append(term, detail);
        }
        row.append(fields);
        const link = document.createElement('a');
        link.dataset.field = 'inspect';
        link.href = '/control/sesiones/' + session.session_id;
        row.append(link);
        list.append(row);
      }
      setText(row.querySelector('[data-field="title"]'), 'Sesión ' + (index + 1) +
        ' · ' + (browserNames[session.browser] || 'Navegador desconocido'));
      for (const name of Object.keys(sessionLabels)) {
        setText(row.querySelector('[data-field="' + name + '"]'), fieldValue(session, name));
      }
      setText(row.querySelector('[data-field="inspect"]'),
        inspectionLabel(session, index + 1, engine));
    });
    for (const [id, row] of existing) { if (!retained.has(id)) row.remove(); }
    document.getElementById(engine + '-no-sessions').hidden = retained.size > 0;
  }
  function updateEngine(item) {
    const engine = item.engine;
    setText(document.getElementById(engine + '-state'), state(item.state));
    setText(document.getElementById(engine + '-phase'), phase(item.phase));
    setText(document.getElementById(engine + '-updated'), item.updated_at ?
      formatPrivateTime(item.updated_at) : 'Sin observación');
    for (const name of Object.keys(metricNames)) {
      setText(document.getElementById(engine + '-' + name), number(item[name]));
    }
    setText(document.getElementById(engine + '-counts'), Object.entries(browserNames)
      .map(([name, label]) => label + ': ' + number((item.counts || {})[name])).join(' · '));
    const sessions = item.sessions;
    const queues = new Set(sessions.map(session => session.queue_id)
      .filter(id => typeof id === 'string' && id.trim() && id !== 'UNKNOWN'));
    setText(document.getElementById(engine + '-queues'), String(queues.size));
    const stop = document.getElementById(engine + '-stop');
    const hasActivation = uuid.test(item.activation_id) &&
      Number.isInteger(item.generation) && item.generation > 0;
    stop.elements.namedItem('activation_id').value = hasActivation ? item.activation_id : '';
    stop.elements.namedItem('generation').value = hasActivation ? String(item.generation) : '0';
    document.getElementById(engine + '-stop-button').disabled =
      !hasActivation || item.state === 'STOPPED';
    const start = document.getElementById(engine + '-start-button');
    const canStart = typeof item.can_start === 'boolean' ? item.can_start :
      ['STOPPED', 'FAILED'].includes(item.state);
    start.disabled = start.dataset.ready !== 'true' || !canStart;
    if (engine === 'browsers_members') {
      const current = document.getElementById(engine + '-current-member');
      const member = uuid.test(item.member_id) ? item.member_id : '';
      if (current.dataset.memberId !== member) {
        const option = Array.from(document.getElementById(engine + '-member').children)
          .find(candidate => candidate.value === member);
        setText(current, !member ? 'Sin socio asociado' : option ? option.textContent :
          'Socio no disponible en la lista actual');
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
    } catch (_) {
      setText(live, 'No se pudo actualizar. Los estados y sesiones anteriores son históricos; '
        + 'el estado actual no está verificado.');
      setText(checked, 'Última consulta fallida.');
    } finally { pending = false; }
  }
  document.getElementById('engines-refresh').addEventListener('click', refreshEngines);
  setInterval(() => { if (!document.hidden) refreshEngines(); }, 5000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshEngines(); });
  if (!document.hidden) refreshEngines();
})();
"""
)
# Each native redirect includes this script; omit indentation in the emitted bytes.
_SCRIPT = "\n".join(line.strip() for line in _SCRIPT.splitlines())


def csp() -> str:
    """Extend the shared page policy without introducing an import cycle."""
    from boca_socios.panel.private_ui import CSP, _hash

    return CSP.replace("script-src ", f"script-src 'sha256-{_hash(_SCRIPT)}' ").replace(
        "style-src ", f"style-src 'sha256-{_hash(_STYLE)}' "
    )


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
        "Ver tokens de cola y autenticación de la sesión "
        if queue and auth
        else "Ver token de cola de la sesión "
        if queue
        else "Ver tokens de autenticación de la sesión "
        if auth
        else "Inspeccionar sesión "
    )
    return f"{prefix}{index} de {_ENGINES[engine]}"


def _session_value(session: Mapping[str, object], field: str) -> str:
    value = session.get(field)
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


def _session_rows(engine: str, sessions: tuple[Mapping[str, object], ...]) -> str:
    rows = []
    for index, session in enumerate(sessions, 1):
        session_id = _uuid(session.get("session_id"))
        if session_id is None:
            continue
        browser = _BROWSERS.get(str(session.get("browser")), "Navegador desconocido")
        fields = "".join(
            f'<dt>{label}</dt><dd data-field="{field}">'
            + escape(_session_value(session, field))
            + "</dd>"
            for field, label in _SESSION_LABELS.items()
        )
        rows.append(
            f'<li class="engine-session" data-session-id="{session_id}">'
            f'<h4 data-field="title">Sesión {index} · {browser}</h4><dl>{fields}</dl>'
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
    can_start = item.get("can_start")
    if type(can_start) is not bool:
        can_start = item.get("state") in {"STOPPED", "FAILED"}
    start_disabled = "" if ready and can_start else " disabled"
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
    return (
        f'<form id="{engine}-start" method="post" action="/control/motores/{engine}/iniciar">'
        + _hidden("csrf", csrf)
        + _hidden("operation_id", operations[f"{engine}:start"])
        + f"<fieldset><legend>Configurar el próximo inicio de {name}</legend>"
        + fields
        + member_selection
        + f'<button id="{engine}-start-button" type="submit" '
        f'data-ready="{str(ready).lower()}"{start_disabled}>Iniciar motor de {name}</button>'
        "</fieldset></form>"
        f'<form id="{engine}-stop" method="post" action="/control/motores/{engine}/detener">'
        + _hidden("csrf", csrf)
        + _hidden("operation_id", operations[f"{engine}:stop"])
        + _hidden("activation_id", activation or "")
        + _hidden("generation", generation if can_stop else 0)
        + f'<button id="{engine}-stop-button" type="submit"{stop_disabled}>'
        f"Detener motor de {name}</button></form>"
    )


def _section(
    engine: str,
    item: Mapping[str, object],
    csrf: str,
    operations: Mapping[str, str],
    members: tuple[MemberView, ...],
    site_url_ready: bool,
) -> str:
    state = escape(_STATES.get(str(item.get("state")), "Estado desconocido"))
    metrics = "".join(
        f'<dt>{label}</dt><dd id="{engine}-{name}">{_number(item.get(name))}</dd>'
        for name, label in _METRICS.items()
    )
    counts = item.get("counts")
    counts = counts if isinstance(counts, Mapping) else {}
    distribution = " · ".join(
        f"{label}: {_number(counts.get(browser))}" for browser, label in _BROWSERS.items()
    )
    sessions = _entries(item.get("sessions"))
    queue_ids = {
        value
        for session in sessions
        if isinstance(value := session.get("queue_id"), str)
        and value.strip()
        and value != "UNKNOWN"
    }
    current_member = ""
    if engine == "browsers_members":
        identifier = _uuid(item.get("member_id"))
        member = next((member for member in members if member.member_id == identifier), None)
        label = (
            (member.display_name or "Socio local") + " · " + member.masked_email
            if member is not None
            else "Socio no disponible en la lista actual"
            if identifier
            else "Sin socio asociado"
        )
        current_member = (
            f'<p>Socio de esta activación: <span id="{engine}-current-member" '
            f'data-member-id="{identifier or ""}">{escape(label)}</span></p>'
        )
    return (
        f'<section data-engine="{engine}" aria-labelledby="{engine}-heading">'
        f'<h2 id="{engine}-heading">Motor de {_ENGINES[engine]}</h2>'
        f'<p>Estado observado: <strong id="{engine}-state">{state}</strong></p>'
        f'<p>Etapa: <span id="{engine}-phase">'
        + escape(_PHASES.get(str(item.get("phase")), _text(item.get("phase"))))
        + "</span><br>"
        f'Última observación: <span id="{engine}-updated">{_time(item.get("updated_at"))}</span></p>'
        + current_member
        + f'<dl class="engine-metrics">{metrics}<dt>Queue ID distintos observados</dt>'
        f'<dd id="{engine}-queues">{len(queue_ids)}</dd></dl>'
        f'<p>Distribución solicitada: <span id="{engine}-counts">{distribution}</span></p>'
        + _forms(engine, item, csrf, operations, members, site_url_ready)
        + "</section>"
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


def page(
    snapshot: Mapping[str, object],
    csrf: str,
    operations: Mapping[str, str],
    members: tuple[MemberView, ...],
    *,
    site_url_ready: bool,
) -> bytes:
    """Render owner controls; only their authenticated POST routes create effects."""
    from boca_socios.panel.private_ui import _page

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
    content = (
        "<h1>Control de motores</h1>"
        "<p>Modo de simulación (SIMULATION_ONLY). No se reservan ni compran entradas reales.</p>"
        "<p>Cada motor se inicia y se detiene por separado. Detener uno permite que el otro continúe.</p>"
        '<p>Límite conjunto de solicitudes: <span id="engines-limit">'
        + _number(snapshot.get("context_limit", 50))
        + "</span> contextos. La capacidad efectiva del servidor se comprueba al crearlos.</p>"
        "<p>Los formularios proponen 25 contextos por motor: 15 Chromium, 5 Firefox y 5 WebKit. "
        "Puede cambiar las cantidades antes de iniciar.</p>"
        "<p>Solicitudes, contextos creados y Queue ID distintos son medidas diferentes. "
        "Varias sesiones pueden compartir un Queue ID; no demuestran posiciones de cola independientes.</p>"
        '<p id="engines-live" role="status" aria-live="polite">Último estado disponible.</p>'
        f'<p id="engines-checked">Última consulta: {_time(snapshot.get("observed_at"))}</p>'
        '<button id="engines-refresh" type="button">Actualizar motores y sesiones</button>'
        "<h2>Totales observados</h2><p>" + " · ".join(totals) + "</p>"
    )
    if not site_url_ready:
        content += '<p>Configure la URL de destino antes de iniciar. <a href="/configuracion">Abrir configuración</a></p>'
    content += _legacy_recovery(snapshot, csrf, operations)
    content += "".join(
        _section(name, item, csrf, operations, members, site_url_ready)
        for name, item in engines.items()
    )
    content += "<h2>Sesiones observadas</h2>" + f"<p>{_SAMPLE_NOTICE}</p>"
    content += "".join(_history(name, item) for name, item in engines.items())
    content += (
        '<p><a href="/monitor/tokens">Abrir monitor privado de tokens</a></p>'
        "<noscript>La página conserva el estado de la última consulta. "
        "Recargue para consultar cambios; los formularios funcionan sin JavaScript.</noscript>"
    )
    return _page("Motores", content, script=f"<style>{_STYLE}</style><script>{_SCRIPT}</script>")
