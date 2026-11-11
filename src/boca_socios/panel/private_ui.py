"""Owner-only HTML views. No credential or member data enters the public Site."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from html import escape

from boca_socios.events.official_catalog import OfficialNotice
from boca_socios.events.official_presentation import render_observed_catalog_html
from boca_socios.notify.projection import LocalNoticeView
from boca_socios.panel.enrollment_form import STYLE
from boca_socios.panel.lifecycle_intents import LifecycleIntent
from boca_socios.panel.member_sector_store import MemberSectorDefaults
from boca_socios.panel.members import CommandView, MemberView
from boca_socios.panel.worker_activity import WorkerActivitySnapshot

_LOGIN_SCRIPT = """
const button = document.getElementById('passkey');
const result = document.getElementById('result');
function bytes(value) {
  const base64 = value.replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from(atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, '=')),
    character => character.charCodeAt(0));
}
function base64url(value) {
  let text = '';
  for (const byte of new Uint8Array(value)) text += String.fromCharCode(byte);
  return btoa(text).replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=+$/, '');
}
button.addEventListener('click', async () => {
  button.disabled = true;
  result.textContent = 'Verificando llave de acceso…';
  try {
    const credential = await navigator.credentials.get({publicKey: {
      challenge: bytes(document.body.dataset.challenge),
      allowCredentials: [{type: 'public-key', id: bytes(document.body.dataset.credential)}],
      userVerification: 'required', timeout: 60000
    }});
    const response = await fetch('/sesion', {
      method: 'POST', credentials: 'same-origin', redirect: 'error',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({credential_id: credential.id,
        client_data_json: base64url(credential.response.clientDataJSON),
        authenticator_data: base64url(credential.response.authenticatorData),
        signature: base64url(credential.response.signature)})
    });
    if (!response.ok) throw new Error('authentication failed');
    location.assign('/');
  } catch (_) {
    result.textContent = 'No se pudo verificar. Vuelva a abrir Ingresar e intente otra vez.';
    button.disabled = false;
  }
});
"""

_ACTIVITY_SCRIPT = """
const list = document.getElementById('worker-events');
const summary = document.getElementById('worker-activity-status');
const telemetry = document.getElementById('chromium-telemetry-status');
const refreshed = document.getElementById('worker-activity-refreshed');
const toggle = document.getElementById('worker-activity-toggle');
const manual = document.getElementById('worker-activity-refresh');
const labels = {owner: 'Panel', host: 'Ejecutor',
  simulation: 'Simulación', chromium: 'Chromium'};
let paused = false;
let pending = false;
let lastEvents = '';
async function updateActivity() {
  if (pending) return;
  pending = true;
  try {
    const response = await fetch('/control/actividad.json', {
      credentials: 'same-origin', cache: 'no-store', redirect: 'error'});
    if (!response.ok) throw new Error('status unavailable');
    const data = await response.json();
    if (!Array.isArray(data.events)) throw new Error('invalid activity');
    const signature = JSON.stringify([data.events, data.chromium_telemetry]);
    if (lastEvents !== signature) {
      const children = data.events.map((event) => {
        const item = document.createElement('li');
        const time = new Date(event.at);
        const when = Number.isNaN(time.getTime()) ? 'Hora no disponible' :
          time.toLocaleString('es-AR', {timeZone: 'America/Argentina/Buenos_Aires'});
        item.textContent = when + ' · ' + (labels[event.source] || 'Evento') +
          ' · ' + event.message;
        return item;
      });
      if (children.length === 0) {
        const item = document.createElement('li');
        item.textContent = 'Todavía no hay eventos registrados.';
        children.push(item);
      }
      list.replaceChildren(...children);
      const latest = data.events.at(-1);
      summary.textContent = latest ? 'Último evento: ' + latest.message :
        'Sin eventos registrados.';
      lastEvents = signature;
    }
    telemetry.textContent = data.chromium_telemetry === 'available' ?
      'Etapas de Chromium disponibles (sin texto interno de la página).' :
      data.chromium_telemetry === 'missing' ?
      'Chromium todavía no emitió etapas de actividad.' :
      'Telemetría de Chromium no verificable; consultar estado protegido.';
    refreshed.textContent = 'Última consulta: ' +
      new Date(data.observed_at).toLocaleString('es-AR',
        {timeZone: 'America/Argentina/Buenos_Aires'});
  } catch (_) {
    telemetry.textContent = 'No se pudo consultar la actividad. Revise su sesión.';
  } finally {
    pending = false;
  }
}
manual.addEventListener('click', updateActivity);
toggle.addEventListener('click', () => {
  paused = !paused;
  toggle.textContent = paused ? 'Reanudar actualizaciones' : 'Pausar actualizaciones';
  toggle.setAttribute('aria-pressed', String(paused));
  if (!paused) updateActivity();
});
setInterval(() => {
  if (!paused && !document.hidden) updateActivity();
}, 5000);
updateActivity();
"""


def _hash(value: str) -> str:
    return base64.b64encode(hashlib.sha256(value.encode()).digest()).decode("ascii")


CSP = (
    "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'self'; connect-src 'self'; "
    f"style-src 'sha256-{_hash(STYLE)}'; "
    f"script-src 'sha256-{_hash(_LOGIN_SCRIPT)}' 'sha256-{_hash(_ACTIVITY_SCRIPT)}'"
)


def _page(title: str, content: str, *, body_attributes: str = "", script: str = "") -> bytes:
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · Boca Socios Assistant</title><style>{STYLE}</style></head>
<body{body_attributes}><nav aria-label="Secciones"><a href="/">Inicio</a> ·
<a href="/socios">Socios</a> · <a href="/comandos">Simulación</a> ·
<a href="/control">Control</a> ·
<a href="/control/actividad">Actividad del worker</a> ·
<a href="/configuracion">Configuración</a> ·
<a href="/estado">Estado</a> · <a href="/avisos">Avisos</a> ·
<a href="/avisos-oficiales">Eventos oficiales</a></nav>
<main>{content}</main>{script}</body></html>""".encode()


def login(challenge: str, credential_id: str) -> bytes:
    attributes = (
        f' data-challenge="{escape(challenge, quote=True)}"'
        f' data-credential="{escape(credential_id, quote=True)}"'
    )
    return _page(
        "Ingresar",
        "<h1>Ingresar al panel privado</h1><p>Use la llave de acceso del dueño. "
        "No se envían credenciales de Boca.</p>"
        '<button id="passkey" type="button">Ingresar con llave de acceso</button>'
        '<p id="result" role="status" aria-live="polite"></p>',
        body_attributes=attributes,
        script=f"<script>{_LOGIN_SCRIPT}</script>",
    )


def site_url_configuration(csrf: str, operation_id: str, site_url: str | None) -> bytes:
    """Owner-only navigation target; never display tokens, arbitrary env or URLs from logs."""
    if site_url is None:
        state = (
            '<p role="status">SITE_URL no configurada. El destino permanece deshabilitado; '
            "el próximo arranque requiere una configuración verificada.</p>"
        )
        value = ""
    else:
        state = (
            '<p role="status">Guardada en el volumen privado de Boca. '
            "El próximo arranque verifica la configuración; no prueba una conexión "
            "al sitio.</p>"
        )
        value = escape(site_url, quote=True)
    return _page(
        "Configuración",
        "<h1>Configuración del sitio</h1>"
        "<p>Cambiá la URL de destino sin editar archivos Python. "
        "Se admiten URLs públicas o privadas HTTP(S); no se admiten credenciales "
        "dentro de la URL.</p>"
        + state
        + '<form method="post" action="/configuracion">'
        + f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">'
        + f'<input type="hidden" name="operation_id" value="{escape(operation_id, quote=True)}">'
        + '<label for="site-url">SITE_URL · sitio de pruebas</label>'
        + f'<input id="site-url" name="SITE_URL" type="url" value="{value}" '
        + 'placeholder="https://ensayo.boca.internal" inputmode="url" '
        + 'autocomplete="off" spellcheck="false" maxlength="512" required>'
        + '<p><button type="submit">Guardar SITE_URL</button></p></form>'
        + "<p>Guardar no inicia ni detiene el worker. En la simulación local, "
        + "SITE_URL no se visita; no hay login, cola ni reserva en Boca.</p>",
    )


def home(
    csrf: str,
    *,
    bot: tuple[LifecycleIntent | None, str, str] | None = None,
    bot_unavailable: bool = False,
) -> bytes:
    if bot is not None:
        intent, start_id, stop_id = bot
        controls = "<h2>Control del bot</h2>" + _bot_controls(intent, csrf, start_id, stop_id)
    elif bot_unavailable:
        controls = '<p role="status">Control del bot no disponible. <a href="/control">Consultar estado</a></p>'
    else:
        controls = '<p><a href="/control">Pausar o reanudar nuevas simulaciones</a></p>'
    return _page(
        "Inicio",
        "<h1>Boca Socios Assistant</h1><p>Modo de simulación. "
        "Ninguna acción reserva ni compra entradas en Boca.</p>"
        f"{controls}"
        '<p><a href="/socios">Consultar o agregar socios</a></p>'
        '<p><a href="/comandos">Iniciar, detener o consultar simulaciones</a></p>'
        '<p><a href="/estado">Consultar estado local</a></p>'
        '<p><a href="/avisos">Consultar avisos locales y estado Telegram</a></p>'
        '<p><a href="/avisos-oficiales">Consultar avisos públicos oficiales observados</a></p>'
        '<p><a href="/telegram/configurar">Configurar Telegram con un recibo aprobado</a></p>'
        '<section aria-labelledby="pending"><h2 id="pending">Funciones no habilitadas</h2><ul>'
        "<li>Los avisos oficiales son informativos y requieren observaciones cargadas; "
        "no hay fuente en vivo ni comprobación de disponibilidad.</li>"
        "<li>Varias sesiones de navegador y sus límites: fuera de alcance por decisión "
        "del propietario.</li>"
        "<li>Rotación de clave maestra y eliminación completa: fuera de alcance por "
        "decisión del propietario.</li>"
        "<li>Backup y restauración: excluidos de esta BETA.</li>"
        "<li>Login, fila, elegibilidad, reserva y compra reales en Boca: no habilitados "
        "y fuera de alcance.</li>"
        "</ul></section>"
        '<form action="/salir" method="post">'
        f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">'
        '<button type="submit">Cerrar sesión</button></form>',
    )


def official_events(notices: tuple[OfficialNotice, ...], *, at: datetime) -> bytes:
    """Private read-only official notice view, separate from simulation commands."""
    return _page(
        "Eventos oficiales observados",
        render_observed_catalog_html(notices, at=at)
        + '<p><a href="/avisos-oficiales.json">Descargar observaciones JSON</a></p>',
    )


def global_simulation_control(
    accepting: bool,
    host_ready: bool,
    csrf: str,
    operation_id: str,
    *,
    lifecycle: LifecycleIntent | None = None,
) -> bytes:
    """Explain that the control governs admission, not process or provider lifecycle."""
    state = "Admitiendo nuevas simulaciones locales" if accepting else "Pausada"
    availability = (
        "El servicio de simulación local está disponible."
        if host_ready
        else "El servicio de simulación local no está disponible."
    )
    action = "pausar" if accepting else "reanudar"
    label = "Pausar nuevas simulaciones" if accepting else "Reanudar nuevas simulaciones"
    return _page(
        "Control de simulaciones",
        "<h1>Control de simulaciones</h1>"
        f'<p role="status">Estado: {state}. {availability}</p>'
        "<p>Este control sólo acepta o bloquea nuevas simulaciones locales. "
        "No inicia ni apaga el contenedor, el panel, Telegram ni el navegador; "
        "tampoco detiene simulaciones en curso. Para detener una, abra "
        "el detalle del comando.</p>"
        "<p>El acceso al panel permanece disponible durante la pausa. "
        "La decisión queda registrada localmente y se conserva tras reiniciar el panel; "
        "si aún no existe una decisión registrada, las nuevas simulaciones empiezan pausadas.</p>"
        f'<form method="post" action="/control/{action}">'
        f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">'
        f'<input type="hidden" name="operation_id" value="{escape(operation_id, quote=True)}">'
        f'<button type="submit">{label}</button></form>'
        '<p><a href="/comandos">Consultar simulaciones y detener una en curso</a></p>'
        + _lifecycle_controls(lifecycle, csrf, operation_id),
    )


def _lifecycle_controls(intent: LifecycleIntent | None, csrf: str, operation_id: str) -> str:
    """Accessible owner-only host *intents*, never executable Docker controls."""
    if intent is None:
        observed = "No hay confirmación de inicio o parada del motor del bot ni Chromium."
    else:
        component = "motor del bot" if intent.component == "bot" else "Chromium"
        requested = "inicio" if intent.target == "start" else "detención"
        states = {
            "REQUESTED": "PENDIENTE. Sin confirmación del host.",
            "CLAIMED": "EN PROCESO. El host tomó la solicitud; aún no confirmó el resultado.",
            "APPLIED": "CONFIRMADA mediante recibo protegido del host; no es monitoreo continuo.",
            "REFUSED": "RECHAZADA sin efecto según recibo protegido del host.",
            "FAILED": "FALLO confirmado mediante recibo protegido del host.",
            "UNCERTAIN": "INDETERMINADA. Prohibido repetir sin reconciliación protegida.",
        }
        observed = (
            f"Última solicitud: {requested} de {component}, "
            + states[intent.status]
            + f" Registrada en SQLite: {intent.requested_at} UTC."
        )
    # A single outstanding request is global, even across bot and Chromium.
    # The future protected host workflow must ACK or refuse it first.
    blocked = intent is not None and intent.status in ("REQUESTED", "CLAIMED", "UNCERTAIN")
    disabled = " disabled" if blocked else ""
    entries = (
        ("bot", "iniciar", "Solicitar inicio del motor del bot"),
        ("bot", "detener", "Solicitar detención del motor del bot"),
        ("chromium", "iniciar", "Solicitar inicio de Chromium"),
        ("chromium", "detener", "Solicitar detención de Chromium"),
    )
    forms = "".join(
        f'<form method="post" action="/control/{component}/{action}">'
        f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">'
        f'<input type="hidden" name="operation_id" value="{escape(operation_id, quote=True)}">'
        f'<button type="submit"{disabled}>{label}</button></form>'
        for component, action, label in entries
    )
    return (
        '<section aria-labelledby="host-lifecycle"><h2 id="host-lifecycle">'
        "Solicitudes de inicio y detención del bot y Chromium</h2>"
        '<p role="status" aria-live="polite">' + escape(observed) + "</p>"
        "<p>Estas acciones sólo registran una solicitud durable. No apagan este panel, "
        "no arrancan ni detienen Docker desde Chrome y no envían órdenes a Boca. "
        "El único workflow protegido de GitHub Actions deberá confirmar el resultado "
        "después de verificar la identidad de los servicios Boca. "
        "Hasta recibir ese recibo no se considera iniciada ni detenida ninguna operación. "
        "El motor del bot se refiere a las simulaciones, no al servidor del panel.</p>"
        + forms
        + '<p><a href="/control">Actualizar solicitudes y recibos</a></p></section>'
    )


def bot_control(intent: LifecycleIntent | None, csrf: str, start_id: str, stop_id: str) -> bytes:
    return _page(
        "Control del bot",
        "<h1>Control del bot</h1>" + _bot_controls(intent, csrf, start_id, stop_id),
    )


def worker_activity(snapshot: WorkerActivitySnapshot) -> bytes:
    """Voice-friendly live view of fixed, redacted events only."""
    rows = "".join(
        "<li>"
        + escape(item.at)
        + " UTC · "
        + escape(item.source)
        + " · "
        + escape(item.message)
        + "</li>"
        for item in snapshot.events
    )
    health = {
        "available": "Etapas reportadas por Chromium disponibles.",
        "missing": "Chromium todavía no emitió etapas de actividad.",
        "degraded": "Telemetría de Chromium no verificable; consultar estado protegido.",
    }[snapshot.chromium_telemetry]
    return _page(
        "Actividad del worker y Chromium",
        "<h1>Actividad del worker y Chromium</h1>"
        "<p>Eventos comprobables de inicio, ejecución y cierre, actualizados cada cinco segundos "
        "mientras esta pantalla está visible. No es una consola Docker ni muestra credenciales, "
        "datos de socios o pasos internos de una web real.</p>"
        "<p>Los recibos del ejecutor acreditan sólo el momento en que fueron emitidos; "
        "las etapas de Chromium son señales del proceso aislado, no pruebas de salud del host.</p>"
        f'<p id="chromium-telemetry-status">{escape(health)}</p>'
        '<button id="worker-activity-refresh" type="button">Actualizar ahora</button>'
        '<button id="worker-activity-toggle" type="button" aria-pressed="false">'
        "Pausar actualizaciones</button>"
        '<p id="worker-activity-refreshed">Consulta inicial: '
        + escape(snapshot.observed_at)
        + " UTC</p>"
        '<p id="worker-activity-status" role="status" aria-live="polite">'
        "Actividad cargada.</p>"
        '<ol id="worker-events" aria-label="Eventos recientes" aria-live="off">'
        + (rows or "<li>Todavía no hay eventos registrados.</li>")
        + "</ol><noscript>Actualice esta página para consultar los eventos nuevos.</noscript>"
        '<p><a href="/control">Volver al control del bot</a></p>',
        script=f"<script>{_ACTIVITY_SCRIPT}</script>",
    )


def _bot_controls(intent: LifecycleIntent | None, csrf: str, start_id: str, stop_id: str) -> str:
    """Voice-friendly simulation controls. Only a protected receipt establishes outcome."""
    observed = "Todavía no hay un recibo de inicio o detención del bot."
    available = {"start", "stop"}
    receipt_id = ""
    if intent is not None and not intent.on_demand:
        observed = "Todavía no hay una solicitud del perfil bajo demanda."
        if intent.status in ("CLAIMED", "UNCERTAIN"):
            observed = "Una orden del perfil anterior requiere verificación en el servidor. Los controles están bloqueados."
            available.clear()
    elif intent is not None:
        component = "bot" if intent.component == "bot" else "Chromium"
        action = ("Inicio" if intent.target == "start" else "Detención") + " de " + component
        if intent.work_start_id is not None:
            action = "Detención automática del bot al finalizar la simulación"
        states = {
            "REQUESTED": "Pendiente de ejecución. Puede reenviar el aviso con el mismo botón.",
            "CLAIMED": "En proceso. El ejecutor tomó la solicitud.",
            "APPLIED": "El ejecutor confirmó sólo esta orden de control. "
            "No acredita una simulación completada ni una reserva.",
            "REFUSED": "El ejecutor rechazó la solicitud antes de aplicar cambios.",
            "FAILED": "Fallo confirmado por el ejecutor.",
            "UNCERTAIN": "Resultado incierto. Hace falta verificar el estado en el servidor.",
        }
        observed = f"Última solicitud, {intent.requested_at} UTC. {action}. {states[intent.status]}"
        if (intent.target, intent.status) == ("start", "APPLIED"):
            observed += " Si el servicio se reinició desde entonces, pulse Detener bot antes de iniciar otra sesión."
        receipt_id = (
            "<details><summary>Identificador de solicitud</summary><code>"
            + escape(intent.operation_id)
            + "</code></details>"
        )
        if intent.status in ("REQUESTED", "CLAIMED", "UNCERTAIN"):
            available.clear()
            if intent.component == "bot" and intent.status == "REQUESTED":
                available.add(intent.target)  # Re-deliver a wake lost after commit.
            if (intent.component, intent.target) == ("bot", "start") and intent.status in (
                "REQUESTED",
                "CLAIMED",
            ):
                available.add("stop")
        elif intent.component == "bot" and intent.status == "APPLIED":
            available.discard(intent.target)
    buttons = []
    for target, path, title, operation_id in (
        ("start", "iniciar", "Iniciar bot", start_id),
        ("stop", "detener", "Detener bot", stop_id),
    ):
        disabled = "" if target in available else " disabled"
        buttons.append(
            f'<form method="post" action="/control/bot/{path}">'
            f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">'
            f'<input type="hidden" name="operation_id" value="{escape(operation_id, quote=True)}">'
            f'<button type="submit"{disabled}>{title}</button></form>'
        )
    return (
        '<p role="status" aria-live="polite">'
        + escape(observed)
        + "</p>"
        + receipt_id
        + "".join(buttons)
        + '<p><a href="/control">Actualizar estado del bot</a></p>'
        '<p><a href="/control/actividad">Ver actividad del worker y Chromium en vivo</a></p>'
        '<p><a href="/comandos">Elegir una simulación</a></p>'
    )


def members(items: tuple[MemberView, ...]) -> bytes:
    rows = []
    for item in items:
        label = escape(item.display_name or "Socio local")
        state = "Credencial local activa" if item.credential_active else "Credencial revocada"
        rows.append(
            "<li><strong>"
            + label
            + "</strong> · "
            + escape(item.masked_email)
            + " · "
            + state
            + '<br><a href="/socios/'
            + escape(item.member_id, quote=True)
            + '">Ver acciones del socio</a></li>'
        )
    return _page(
        "Socios",
        "<h1>Socios locales</h1><p>Sólo datos de simulación; el alta no verifica "
        "elegibilidad ni inicia una reserva.</p>"
        '<a href="/socios/nuevo">Agregar socio</a><ul>'
        + "".join(rows or ["<li>No hay socios locales.</li>"])
        + "</ul>",
    )


def member_detail(
    item: MemberView,
    csrf: str,
    rotate_id: str,
    revoke_id: str,
    sector_operation_id: str,
    sector_defaults: MemberSectorDefaults | None,
    *,
    sector_storage_ready: bool,
) -> bytes:
    identifier = escape(item.member_id, quote=True)
    all_selected = sector_defaults is None or sector_defaults.mode.value == "ALL"
    sector_values = ",".join(sector_defaults.sector_ids) if sector_defaults else ""
    status = (
        "Almacenamiento local pendiente de habilitación."
        if not sector_storage_ready
        else "Configuración general para las simulaciones futuras de este socio."
    )
    disabled = " disabled" if not sector_storage_ready else ""
    sector_form = (
        '<section aria-labelledby="sector-preferences-heading">'
        '<h2 id="sector-preferences-heading">Preferencias de sectores</h2>'
        '<p>Se guardan en el mismo perfil de socio, sin repetir el alta. '
        'Solo se usan en simulaciones locales: no reservan entradas.</p>'
        f'<p role="status">{escape(status)}</p>'
        f'<form method="post" action="/socios/{identifier}/sectores">'
        f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">'
        f'<input type="hidden" name="operation_id" '
        f'value="{escape(sector_operation_id, quote=True)}">'
        f'<fieldset{disabled}><legend>Selección de sectores</legend>'
        '<label><input type="radio" name="mode" value="ALL"'
        + (" checked" if all_selected else "")
        + '>Todos los sectores disponibles de la simulación</label>'
        '<label><input type="radio" name="mode" value="ORDERED_ALLOWLIST"'
        + ("" if all_selected else " checked")
        + '>Solo mis sectores preferidos, en orden</label>'
        '<label for="member-sector-ids">Sectores ficticios por prioridad, separados por coma</label>'
        '<textarea id="member-sector-ids" name="sector_ids" rows="3" maxlength="2000">'
        + escape(sector_values)
        + '</textarea><p>Ejemplo: sector_sur, sector_norte. '
        'El orden es el de prioridad cuando se elige la segunda opción.</p>'
        '<button type="submit">Guardar preferencias de este socio</button>'
        '</fieldset></form></section>'
    )
    return _page(
        "Socio local",
        "<h1>Socio local</h1><p>"
        + escape(item.display_name or "Socio local")
        + " · "
        + escape(item.masked_email)
        + "</p>"
        "<p>Rotar o revocar la credencial afecta sólo la bóveda local. "
        "No modifica la cuenta Boca ni borra la cuota histórica.</p>"
        f'<form method="post" action="/socios/{identifier}/credencial">'
        f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">'
        f'<input type="hidden" name="operation_id" value="{escape(rotate_id, quote=True)}">'
        '<label for="new-password">Nueva contraseña sintética</label>'
        '<input id="new-password" name="password" type="password" '
        'autocomplete="new-password" required><button type="submit">Rotar credencial local</button>'
        "</form>"
        f'<form method="post" action="/socios/{identifier}/revocar">'
        f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">'
        f'<input type="hidden" name="operation_id" value="{escape(revoke_id, quote=True)}">'
        '<button type="submit">Revocar credencial local</button></form>'
        + sector_form,
    )


def commands(
    items: tuple[CommandView, ...],
    members_list: tuple[MemberView, ...],
    events: dict[str, str],
    csrf: str,
    operation_id: str,
) -> bytes:
    options = "".join(
        f'<option value="{escape(item.member_id, quote=True)}">'
        f"{escape(item.display_name or item.masked_email)}</option>"
        for item in members_list
        if item.credential_active
    )
    event_options = "".join(
        f'<option value="{escape(event_id, quote=True)}">{escape(label)}</option>'
        for event_id, label in events.items()
    )
    rows = "".join(
        '<li><a href="/comandos/'
        + escape(item.command_id, quote=True)
        + '">'
        + escape(item.state)
        + " · "
        + escape(datetime.fromtimestamp(item.updated_at, UTC).isoformat())
        + "</a></li>"
        for item in items
    )
    form = (
        (
            '<form method="post" action="/comandos">'
            f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">'
            f'<input type="hidden" name="operation_id" value="{escape(operation_id, quote=True)}">'
            '<label for="member">Socio local</label><select id="member" name="member_id" required>'
            + options
            + '</select><label for="event">Evento sintético</label>'
            '<select id="event" name="event_id" required>'
            + event_options
            + '</select><button type="submit">Iniciar simulación local</button></form>'
        )
        if options and event_options
        else "<p>Necesita un socio activo y un evento sintético configurado.</p>"
    )
    return _page(
        "Simulación",
        "<h1>Simulación local</h1><p>Una intención por socio y evento, cantidad uno. "
        "Un resultado local nunca confirma una entrada Boca.</p>"
        + form
        + "<h2>Comandos recientes</h2><ul>"
        + (rows or "<li>Sin comandos.</li>")
        + "</ul>",
    )


def command_detail(command_id: str, state: str, updated_at: float, csrf: str) -> bytes:
    timestamp = datetime.fromtimestamp(updated_at, UTC).isoformat()
    return _page(
        "Comando local",
        "<h1>Comando local</h1><p>Estado: " + escape(state) + "</p>"
        "<p>Actualizado: " + escape(timestamp) + " (UTC). "
        "Sin confirmación externa de Boca.</p>"
        f'<form method="post" action="/comandos/{escape(command_id, quote=True)}/detener">'
        f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">'
        '<button type="submit">Detener simulación local</button></form>'
        '<p><a href="/comandos">Volver a consultar estado</a></p>',
    )


def status(snapshot: dict[str, object]) -> bytes:
    counts = snapshot.get("counts")
    if not isinstance(counts, dict):
        counts = {}
    rows = "".join(
        f"<li>{escape(key)}: {int(value)}</li>"
        for key, value in counts.items()
        if isinstance(value, int)
    )
    return _page(
        "Estado local",
        "<h1>Estado local</h1><p>Fuente: SQLite local. "
        "Confirmación externa: no observada.</p><ul>" + rows + "</ul>"
        "<p>Observado: "
        + escape(str(snapshot.get("observed_at", "desconocido")))
        + "</p><p>Edad de los datos: "
        + escape(str(snapshot.get("local_data_age", "desconocida")))
        + ".</p>",
    )


def notices(items: tuple[LocalNoticeView, ...]) -> bytes:
    rows = []
    for item in items:
        local = f"Aviso local {item.kind.value}: {item.state.value}; intentos {item.attempts}."
        telegram = (
            "Telegram no configurado o sin intento registrado."
            if item.telegram_state is None
            else "Telegram: API aceptó el pedido; no acredita recepción humana."
            if item.telegram_state == "api_accepted"
            else "Telegram: resultado ambiguo, requiere revisión."
            if item.telegram_state in ("ambiguous", "needs_review")
            else "Telegram: estado local pendiente."
        )
        rows.append(f"<li>{escape(local)} {escape(telegram)}</li>")
    return _page(
        "Avisos",
        "<h1>Avisos de simulación</h1><p>Estado local; nunca confirma una entrada Boca. "
        "La aceptación de Telegram por su API no prueba lectura o entrega al destinatario.</p>"
        "<ul>" + "".join(rows or ["<li>Sin avisos locales.</li>"]) + "</ul>",
    )


def message(title: str, detail: str) -> bytes:
    return _page(title, "<h1>" + escape(title) + "</h1><p>" + escape(detail) + "</p>")
