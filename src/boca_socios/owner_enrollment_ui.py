"""No-storage Chrome UI for the SSH-loopback, single-use first-owner enrollment."""

_CSP = (
    "default-src 'none'; script-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)

_PAGE = """<!doctype html><html lang="es"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Activar passkey de Boca</title>
<h1>Activar passkey de Boca</h1>
<p>Esta página es privada y funciona únicamente en Chrome mediante el túnel SSH de Termius: <strong>http://localhost:8443</strong>.</p>
<p>La llave quedará en el administrador de credenciales de Android que elijas. El dispositivo puede pedir tu PIN, patrón o biometría para crearla y luego comprobarla.</p>
<button type="button" id="activate" disabled>Crear y verificar mi passkey</button>
<p id="status" role="status" aria-live="polite">Comprobando enlace privado…</p>
<script src="/activar.js" defer></script></html>""".encode()

_SCRIPT = r"""'use strict';
const activate = document.getElementById('activate');
const status = document.getElementById('status');
let fragment = /^#key=([A-Za-z0-9_-]{43})$/.exec(location.hash);
// Clear the fragment before any asynchronous operation. It is not sent in an
// HTTP GET or Referer; removal from the URL requires JavaScript to run.
history.replaceState(null, '', '/activar');
let capability = fragment && fragment[1];
fragment = null;
if (location.origin === 'http://localhost:8443' && capability) {
  activate.disabled = false;
  status.textContent = 'Enlace listo. Activá la passkey una sola vez.';
} else {
  capability = null;
  status.textContent = 'Enlace privado inválido o vencido. Solicitá uno nuevo.';
}
function from64(value) {
  const raw = atob(value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4));
  return Uint8Array.from(raw, ch => ch.charCodeAt(0));
}
function to64(value) {
  const raw = String.fromCharCode(...new Uint8Array(value));
  return btoa(raw).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}
async function post(path, data, session) {
  const headers = {'Content-Type': 'application/json'};
  if (session) headers['X-Boca-Enrollment'] = session;
  const response = await fetch(path, {
    method: 'POST', headers, body: JSON.stringify(data),
    cache: 'no-store', credentials: 'omit', redirect: 'error'
  });
  if (!response.ok) throw new Error('enrollment rejected');
  return response.json();
}
activate.addEventListener('click', async () => {
  if (!capability) return;
  activate.disabled = true;
  const key = capability;
  capability = null;
  let session = null;
  try {
    if (location.origin !== 'http://localhost:8443') throw new Error('wrong origin');
    const begin = await post('/begin', {capability: key});
    session = begin.session;
    status.textContent = 'Autorizá la creación en el administrador de credenciales de Android.';
    const created = await navigator.credentials.create({publicKey: {
      rp: {id: begin.rp_id, name: 'Boca Socios BETA'},
      user: {id: from64(begin.user_id), name: 'Dueño', displayName: 'Dueño'},
      challenge: from64(begin.challenge), pubKeyCredParams: [{type: 'public-key', alg: -7}],
      authenticatorSelection: {
        authenticatorAttachment: 'platform', userVerification: 'required',
        residentKey: 'required', requireResidentKey: true
      },
      timeout: begin.timeout_ms, attestation: 'none'
    }});
    if (!created || !created.response.getAuthenticatorData || !created.response.getPublicKey ||
        !created.response.getPublicKeyAlgorithm) throw new Error('unsupported authenticator');
    const proof = await post('/creation', {operation_id: begin.operation_id, response: {
      credential_id: to64(created.rawId), client_data_json: to64(created.response.clientDataJSON),
      authenticator_data: to64(created.response.getAuthenticatorData()),
      public_key_der: to64(created.response.getPublicKey()),
      public_key_algorithm: created.response.getPublicKeyAlgorithm()
    }}, session);
    status.textContent = 'Autorizá la comprobación de esta misma passkey.';
    const assertion = await navigator.credentials.get({publicKey: {
      rpId: begin.rp_id, challenge: from64(proof.challenge),
      allowCredentials: [{type: 'public-key', id: from64(proof.credential_id)}],
      userVerification: 'required', timeout: 120000
    }});
    if (!assertion) throw new Error('assertion unavailable');
    const result = await post('/proof', {operation_id: begin.operation_id, assertion: {
      credential_id: to64(assertion.rawId),
      client_data_json: to64(assertion.response.clientDataJSON),
      authenticator_data: to64(assertion.response.authenticatorData),
      signature: to64(assertion.response.signature)
    }}, session);
    if (result.state !== 'verified_for_install') throw new Error('not verified');
    status.textContent = 'Passkey creada y verificada. Esperá la confirmación de instalación privada antes de usar Boca.';
  } catch (_error) {
    if (session) { try { await post('/abort', {}, session); } catch (_ignored) { /* closed */ } }
    status.textContent = 'El alta no se completó. No reutilices este enlace; solicitá uno nuevo.';
  }
});
""".encode()
