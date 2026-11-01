"""Accessible synthetic enrollment presentation; never render submitted values."""

import base64
import hashlib
from html import escape

STYLE = """
body { font: 1.1rem system-ui; max-width: 42rem; margin: auto; padding: 1.5rem; }
label { display: block; margin-top: 1.2rem; }
input:not([type=checkbox]), button { box-sizing: border-box; width: 100%;
  min-height: 48px; padding: .7rem; font: inherit; }
input[type=checkbox] { width: 28px; height: 28px; vertical-align: middle; }
a { display: inline-block; min-height: 44px; padding-top: .5rem; }
button { margin-top: 1.5rem; cursor: pointer; }
:focus-visible { outline: 3px solid #064bc5; outline-offset: 3px; }
#result { min-height: 3rem; margin-top: 1rem; }
"""

SCRIPT = """
const form = document.getElementById('enrollment');
if (form) {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = document.getElementById('save');
    const result = document.getElementById('result');
    const password = document.getElementById('password');
    button.disabled = true;
    result.textContent = 'Guardando…';
    try {
      const response = await fetch('/socios', {
        method: 'POST', credentials: 'same-origin', redirect: 'error',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: new URLSearchParams(new FormData(form))
      });
      const data = await response.json();
      result.textContent = data.message;
      if (response.ok) {
        form.reset();
        button.hidden = true;
        document.getElementById('another').hidden = false;
      }
    } catch (_) {
      result.textContent = 'No se pudo confirmar el alta. No vuelva a enviarla '
        + 'automáticamente: revise el estado antes de intentarlo de nuevo.';
    } finally {
      password.value = '';
      button.disabled = false;
      result.focus();
    }
  });
}
"""


def _hash(value: str) -> str:
    return base64.b64encode(hashlib.sha256(value.encode()).digest()).decode("ascii")


CSP = (
    "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'self'; connect-src 'self'; "
    f"style-src 'sha256-{_hash(STYLE)}'; script-src 'sha256-{_hash(SCRIPT)}'"
)


def render_form(csrf: str, operation_id: str) -> bytes:
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agregar socio · Boca Socios</title><style>{STYLE}</style></head>
<body><nav aria-label="Secciones"><a href="/socios">Socios</a></nav>
<main><h1>Agregar socio</h1>
<p>Alta privada. No inicia sesión ni solicita entradas en Boca.</p>
<form id="enrollment" method="post" action="/socios">
<input type="hidden" name="csrf" value="{escape(csrf, quote=True)}">
<input type="hidden" name="operation_id" value="{escape(operation_id, quote=True)}">
<label for="alias">Alias (opcional)</label>
<input id="alias" name="alias" maxlength="200" autocomplete="nickname">
<label for="email">Correo electrónico</label>
<input id="email" name="email" type="email" maxlength="254" autocomplete="off" required>
<label for="password">Contraseña del socio</label>
<input id="password" name="password" type="password" maxlength="4096"
 autocomplete="new-password" aria-describedby="password-help" required>
<p id="password-help">Se guarda cifrada y no se muestra después del alta.</p>
<label for="consent"><input id="consent" name="consent" type="checkbox" value="yes" required>
 Confirmo el consentimiento individual de esta persona para registrar sus datos.</label>
<button id="save" type="submit">Guardar socio</button>
</form><p id="result" role="status" aria-live="polite" tabindex="-1"></p>
<a id="another" href="/socios/nuevo" hidden>Agregar otro socio</a>
<noscript>Para conservar alias y correo si vence la sesión, active JavaScript.
 Nunca guarde una contraseña en una URL.</noscript>
</main><script>{SCRIPT}</script></body></html>""".encode()


def render_members() -> bytes:
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Socios · Boca Socios</title><style>{STYLE}</style></head>"
        '<body><main><h1>Socios</h1><a href="/socios/nuevo">Agregar socio</a>'
        "<p>El alta no verifica elegibilidad ni inicia una reserva.</p></main></body></html>"
    ).encode()
