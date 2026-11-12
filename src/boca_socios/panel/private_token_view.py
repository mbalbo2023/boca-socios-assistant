"""Small accessible owner-only HTML bodies for two unrelated observations.

These fragments are rendered only after the current panel's passkey/session
checks. They never originate a login, queue request or browser navigation.
"""

from __future__ import annotations

from html import escape

from boca_socios.queue.pass_observation import QueuePassSummary
from boca_socios.security.member_auth_contract import BocaAuthSummary

COPY_SCRIPT = """
for (const button of document.querySelectorAll('[data-copy-target]')) {
  button.addEventListener('click', async () => {
    const source = document.getElementById(button.dataset.copyTarget);
    const message = document.getElementById('copy-status');
    if (!source || !message) return;
    try {
      await navigator.clipboard.writeText(source.value);
      message.textContent = 'Copiado al portapapeles privado.';
    } catch (_) {
      source.focus(); source.select();
      message.textContent = 'Seleccione el texto y use Copiar del dispositivo.';
    }
  });
}
"""

LIVE_SCRIPT = """
const state = document.getElementById('token-monitor-live');
const checked = document.getElementById('token-monitor-checked');
const refresh = document.getElementById('token-monitor-refresh');
let lastSignature = null;
let pending = false;
async function updateTokenMonitor() {
  if (pending) return;
  pending = true;
  try {
    const response = await fetch('/monitor/tokens.json', {
      credentials: 'same-origin', cache: 'no-store', redirect: 'error'});
    if (!response.ok) throw new Error('snapshot unavailable');
    const data = await response.json();
    if (data.version !== 1 ||
        !['IN_MEMORY', 'NOT_CONNECTED'].includes(data.queue_source) ||
        !['IN_MEMORY', 'NOT_CONNECTED'].includes(data.boca_source) ||
        !Number.isInteger(data.queue_observations) || data.queue_observations < 0 ||
        !Number.isInteger(data.boca_observations) || data.boca_observations < 0 ||
        !(data.last_observed_at === null || typeof data.last_observed_at === 'string')) {
      throw new Error('invalid snapshot');
    }
    const signature = JSON.stringify([
      data.queue_source, data.boca_source, data.queue_observations,
      data.boca_observations, data.last_observed_at]);
    if (signature !== lastSignature) {
      state.textContent =
        'Queue-it: ' + data.queue_observations + ' observaciones (' +
        (data.queue_source === 'IN_MEMORY' ?
          'vista local disponible; conexión externa no acreditada' :
          'fuente no conectada') +
        '). Boca: ' + data.boca_observations + ' observaciones (' +
        (data.boca_source === 'IN_MEMORY' ?
          'vista local disponible; conexión externa no acreditada' :
          'fuente no conectada') +
        '). Para ver detalles nuevos, pulse Actualizar listado.';
      lastSignature = signature;
    }
    const when = new Date(data.observed_at);
    checked.textContent = Number.isNaN(when.getTime()) ?
      'Última consulta: hora no verificable.' :
      'Última consulta: ' + when.toLocaleString('es-AR',
        {timeZone: 'America/Argentina/Buenos_Aires'});
  } catch (_) {
    state.textContent = 'Monitor temporalmente no verificable. No confirma tokens nuevos.';
    checked.textContent = 'Última consulta fallida.';
    lastSignature = null;
  } finally {
    pending = false;
  }
}
refresh.addEventListener('click', updateTokenMonitor);
setInterval(() => { if (!document.hidden) updateTokenMonitor(); }, 5000);
updateTokenMonitor();
"""


def _hidden(name: str, value: str) -> str:
    return f'<input type="hidden" name="{name}" value="{escape(value, quote=True)}">'


def _reveal_form(
    *,
    kind: str,
    member_id: str,
    event_id: str,
    session_id: str,
    csrf: str,
    operation_id: str,
) -> str:
    return (
        '<form method="post" action="/monitor/tokens/revelar">'
        + _hidden("csrf", csrf)
        + _hidden("operation_id", operation_id)
        + _hidden("kind", kind)
        + _hidden("member_id", member_id)
        + _hidden("event_id", event_id)
        + _hidden("session_id", session_id)
        + '<button type="submit">Mostrar completo</button></form>'
    )


def overview(
    queue: tuple[QueuePassSummary, ...],
    auth: tuple[BocaAuthSummary, ...],
    *,
    csrf: str,
    operation_id: str | None,
    can_reveal: bool,
    queue_connected: bool,
    boca_connected: bool,
) -> str:
    """Safe overview: only IDs, time and state, never bearer values or URL."""
    queue_rows = []
    for item in queue:
        fields = (
            _reveal_form(
                kind="queue",
                member_id=item.member_id,
                event_id=item.event_id,
                session_id=item.session_id,
                csrf=csrf,
                operation_id=operation_id,
            )
            if can_reveal and operation_id is not None
            else ""
        )
        label = {
            "not_observed": "no_observado",
            "observed_unverified": "observado_no_validado",
            "expired": "caducado",
            "unknown": "desconocido",
        }[item.state.value]
        queue_rows.append(
            "<li>Socio "
            + escape(item.member_id)
            + " · Evento "
            + escape(item.event_id)
            + " · Sesión "
            + escape(item.session_id)
            + " · "
            + label
            + fields
            + "</li>"
        )
    auth_rows = []
    for auth_item in auth:
        fields = (
            _reveal_form(
                kind="boca",
                member_id=auth_item.member_id,
                event_id="",
                session_id="",
                csrf=csrf,
                operation_id=operation_id,
            )
            if can_reveal and operation_id is not None
            else ""
        )
        auth_rows.append(
            "<li>Socio "
            + escape(auth_item.member_id)
            + " · observado_no_validado · respuesta externa no comprobada por este panel"
            + fields
            + "</li>"
        )
    return (
        "<h1>Monitor privado de tokens</h1>"
        "<p>Observaciones independientes. No se valida ninguna URL ni token; "
        "nunca se inicia el navegador o una reserva desde este monitor.</p>"
        '<section aria-labelledby="monitor-live-title"><h2 id="monitor-live-title">'
        "Estado en tiempo real</h2>"
        '<p id="token-monitor-live" role="status" aria-live="polite">'
        + (
            "Vista Queue-it en memoria disponible; origen externo no acreditado. "
            if queue_connected
            else "Fuente Queue-it no conectada. "
        )
        + (
            "Vista Boca en memoria disponible; origen externo no acreditado."
            if boca_connected
            else "Fuente Boca no conectada."
        )
        + '</p><p id="token-monitor-checked">Aún no hay consulta reciente.</p>'
        '<button id="token-monitor-refresh" type="button">Actualizar ahora</button>'
        '<p><a href="/monitor/tokens">Actualizar listado de observaciones</a></p>'
        "<p>Se actualizan solo cantidades y horas cada cinco segundos. Los tokens y sus "
        "URLs nunca se transmiten en esta consulta. Si aparecen nuevas observaciones, "
        "actualizá el listado para elegir cuál revelar.</p></section>"
        '<section aria-labelledby="queue-observations"><h2 id="queue-observations">'
        "Queue-it · URL y queueittoken observados</h2>"
        + (
            "<ul>" + "".join(queue_rows) + "</ul>"
            if queue_rows
            else "<p>Sin observaciones de cola.</p>"
        )
        + '</section><section aria-labelledby="boca-observations"><h2 id="boca-observations">'
        "Boca · token y refreshToken</h2>"
        + (
            "<ul>" + "".join(auth_rows) + "</ul>"
            if auth_rows
            else "<p>No hay credenciales de sesión observadas.</p>"
        )
        + "</section><p>Sin observaciones significa que no hay un origen auténtico conectado, "
        "no que la fila o el inicio de sesión estén habilitados.</p>"
    )


def _copy_field(field_id: str, label: str, value: str) -> str:
    return (
        f'<label for="{field_id}">{escape(label)}</label>'
        f'<textarea id="{field_id}" rows="4" cols="38" readonly spellcheck="false" '
        'autocomplete="off">' + escape(value) + "</textarea>"
        f'<button type="button" data-copy-target="{field_id}">Copiar {escape(label)}</button>'
    )


def queue_reveal(token: str, target_url: str | None) -> str:
    return (
        "<h1>Queue-it · observación privada completa</h1>"
        "<p>Se observó un valor, pero no se comprobó su validez ni acceso a Boca. "
        "No se navega a la URL.</p>"
        + _copy_field("queue-token-full", "token completo", token)
        + (
            _copy_field("queue-url-full", "URL completa", target_url)
            if target_url is not None
            else "<p>URL completa no observada.</p>"
        )
        + '<p id="copy-status" role="status" aria-live="polite"></p>'
        '<p><a href="/monitor/tokens">Volver al monitor</a></p>'
    )


def boca_reveal(token: str, refresh_token: str) -> str:
    return (
        "<h1>Boca · respuesta privada completa</h1>"
        "<p>Recibida por un transporte externo inyectado; este panel no verifica "
        "su vigencia ni realiza autenticación por sí mismo.</p>"
        + _copy_field("boca-token-full", "token completo", token)
        + _copy_field("boca-refresh-full", "refreshToken completo", refresh_token)
        + '<p id="copy-status" role="status" aria-live="polite"></p>'
        '<p><a href="/monitor/tokens">Volver al monitor</a></p>'
    )
