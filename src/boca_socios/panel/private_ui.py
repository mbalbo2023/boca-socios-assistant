"""Owner-only HTML views. No credential or member data enters the public Site."""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from html import escape

from boca_socios.notify.projection import LocalNoticeView
from boca_socios.panel.enrollment_form import STYLE
from boca_socios.panel.members import CommandView, MemberView

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


def _hash(value: str) -> str:
    return base64.b64encode(hashlib.sha256(value.encode()).digest()).decode("ascii")


CSP = (
    "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'self'; connect-src 'self'; "
    f"style-src 'sha256-{_hash(STYLE)}'; "
    f"script-src 'sha256-{_hash(_LOGIN_SCRIPT)}'"
)


def _page(title: str, content: str, *, body_attributes: str = "", script: str = "") -> bytes:
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · Boca Socios Assistant</title><style>{STYLE}</style></head>
<body{body_attributes}><nav aria-label="Secciones"><a href="/">Inicio</a> ·
<a href="/socios">Socios</a> · <a href="/comandos">Simulación</a> ·
<a href="/estado">Estado</a> · <a href="/avisos">Avisos</a></nav>
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


def home(csrf: str) -> bytes:
    return _page(
        "Inicio",
        "<h1>Boca Socios Assistant</h1><p>Modo de simulación. "
        "Ninguna acción reserva ni compra entradas en Boca.</p>"
        '<p><a href="/socios">Consultar o agregar socios</a></p>'
        '<p><a href="/comandos">Iniciar, detener o consultar simulaciones</a></p>'
        '<p><a href="/estado">Consultar estado local</a></p>'
        '<p><a href="/avisos">Consultar avisos locales y estado Telegram</a></p>'
        '<form action="/salir" method="post">'
        f'<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">'
        '<button type="submit">Cerrar sesión</button></form>',
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


def member_detail(item: MemberView, csrf: str, rotate_id: str, revoke_id: str) -> bytes:
    identifier = escape(item.member_id, quote=True)
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
        '<button type="submit">Revocar credencial local</button></form>',
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
