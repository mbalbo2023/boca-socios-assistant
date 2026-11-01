"""Static, no-storage browser flow for the tablet-local owner ceremony."""

_CSP = (
    "default-src 'none'; script-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)

_PAGE = """<!doctype html><html lang="es"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Alta privada de la llave Boca</title>
<h1>Alta privada de la llave Boca</h1>
<p>Solo en este dispositivo. Verificá que la dirección sea https://localhost:8443 y el certificado sea confiable. No continúes ante avisos de seguridad.</p>
<label>Capacidad local de un solo uso <input id="cap" type="password" autocomplete="off" spellcheck="false"></label>
<button id="start" type="button">Crear y verificar llave</button>
<button id="copy" type="button" hidden>Copiar sobre cifrado</button>
<p id="status" role="status" aria-live="polite">Esperando autorización local.</p>
<script src="/ceremony.js" defer></script></html>""".encode()

_SCRIPT = r"""'use strict';
const cap = document.getElementById('cap');
const start = document.getElementById('start');
const copy = document.getElementById('copy');
const status = document.getElementById('status');
let sealed = null;
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
  if (session) headers['X-Boca-Ceremony'] = session;
  const response = await fetch(path, {method: 'POST', headers, body: JSON.stringify(data), cache: 'no-store', credentials: 'omit'});
  if (!response.ok) throw new Error('ceremony rejected');
  return response.json();
}
start.addEventListener('click', async () => {
  start.disabled = true;
  const capability = cap.value;
  cap.value = '';
  let session = null;
  try {
    if (location.origin !== 'https://localhost:8443') throw new Error('wrong origin');
    const begin = await post('/begin', {capability});
    session = begin.session;
    status.textContent = 'Confirmá la creación con verificación biométrica o PIN del dispositivo.';
    const created = await navigator.credentials.create({publicKey: {
      rp: {id: begin.rp_id, name: 'Boca Socios BETA'},
      user: {id: from64(begin.user_id), name: 'Dueño', displayName: 'Dueño'},
      challenge: from64(begin.challenge), pubKeyCredParams: [{type: 'public-key', alg: -7}],
      authenticatorSelection: {userVerification: 'required', residentKey: 'preferred'},
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
    status.textContent = 'Confirmá ahora la prueba de posesión de la misma llave.';
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
    sealed = result.envelope;
    copy.hidden = false;
    status.textContent = 'Prueba aprobada. Copiá el sobre cifrado; cerrá esta página y el emisor antes de iniciar el túnel.';
  } catch (_error) {
    if (session) { try { await post('/abort', {}, session); } catch (_ignored) { /* already closed */ } }
    status.textContent = 'No se completó la prueba. Cerrá esta página y revisá el motivo local sin reutilizar la capacidad.';
  }
});
copy.addEventListener('click', async () => {
  if (!sealed) return;
  try {
    await navigator.clipboard.writeText(sealed);
    sealed = null;
    copy.hidden = true;
    status.textContent = 'Sobre cifrado copiado. Verificá el portapapeles antes de usar owner-install; no lo pegues en GitHub.';
  } catch (_error) {
    status.textContent = 'No se pudo copiar automáticamente. Mantené esta página abierta para reintentar; no uses una captura.';
  }
});
""".encode()
