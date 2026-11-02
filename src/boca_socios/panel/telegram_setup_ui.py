"""Owner-only, browser-local sealing of the existing Telegram bootstrap envelope.

No token or destination is posted to the private panel. The fixed script accepts
only a public recipient receipt in the URL fragment and emits ciphertext for the
already protected install workflow. It neither installs nor enables Telegram.
"""

from __future__ import annotations

import base64
import hashlib

from boca_socios.panel.enrollment_form import STYLE

_SETUP_STYLE = (
    STYLE
    + """
textarea { box-sizing: border-box; width: 100%; min-height: 8rem; font: inherit; }
#fingerprint { overflow-wrap: anywhere; }
"""
)

SCRIPT = r"""
'use strict';
(() => {
  const fragment = location.hash;
  let cleared = false;
  try {
    history.replaceState(null, '', '/telegram/configurar');
    cleared = location.hash === '';
  } catch (_) {}
  const tokenInput = document.getElementById('telegram-token');
  const chatInput = document.getElementById('telegram-chat');
  const sealButton = document.getElementById('seal');
  const copyButton = document.getElementById('copy');
  const output = document.getElementById('sealed');
  const botPin = document.getElementById('bot-pin');
  const chatPin = document.getElementById('chat-pin');
  const copyBot = document.getElementById('copy-bot');
  const copyChat = document.getElementById('copy-chat');
  const result = document.getElementById('result');
  const fingerprintOutput = document.getElementById('fingerprint');
  const encoder = new TextEncoder();
  let active = true;
  let recipient = null;
  let recipientKey = null;
  function cleanInputs() {
    tokenInput.value = '';
    chatInput.value = '';
  }
  function lockInputs(locked) {
    tokenInput.disabled = locked;
    chatInput.disabled = locked;
    sealButton.disabled = locked;
  }
  function canonical(value) {
    return JSON.stringify(value, Object.keys(value).sort());
  }
  function base64url(value) {
    let text = '';
    for (const byte of new Uint8Array(value)) text += String.fromCharCode(byte);
    return btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function bytes(value, length, maximum) {
    if (typeof value !== 'string' || !/^[A-Za-z0-9_-]+$/.test(value)
        || value.length > maximum * 2) throw new Error('invalid public receipt');
    const base64 = value.replace(/-/g, '+').replace(/_/g, '/');
    const decoded = Uint8Array.from(
      atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, '=')),
      character => character.charCodeAt(0));
    if (decoded.length > maximum || (length !== null && decoded.length !== length)
        || base64url(decoded) !== value) throw new Error('invalid public receipt');
    return decoded;
  }
  function readReceipt(value) {
    if (!/^#recipient=[A-Za-z0-9_-]{1,1024}$/.test(value))
      throw new Error('public receipt required');
    const raw = new TextDecoder('utf-8', {fatal: true}).decode(
      bytes(value.slice(11), null, 512));
    const parsed = JSON.parse(raw);
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)
        || Object.keys(parsed).sort().join(',') !== 'fingerprint,public_key,state'
        || !['PREPARED', 'ALREADY_PREPARED'].includes(parsed.state)
        || typeof parsed.fingerprint !== 'string'
        || !/^[0-9a-f]{64}$/.test(parsed.fingerprint)
        || canonical(parsed) !== raw) throw new Error('invalid public receipt');
    bytes(parsed.public_key, 32, 32);
    return parsed;
  }
  async function initialize() {
    try {
      if (!cleared || location.origin !== 'http://localhost:8443'
          || !isSecureContext || !globalThis.crypto || !crypto.subtle)
        throw new Error('private crypto unavailable');
      recipient = readReceipt(fragment);
      const publicBytes = bytes(recipient.public_key, 32, 32);
      const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', publicBytes));
      const fingerprint = Array.from(digest, byte => byte.toString(16).padStart(2, '0')).join('');
      if (fingerprint !== recipient.fingerprint) throw new Error('public receipt mismatch');
      recipientKey = await crypto.subtle.importKey('raw', publicBytes, 'X25519', false, []);
      // Detect unsupported X25519 and reject low-order points before enabling inputs.
      const probe = await crypto.subtle.generateKey('X25519', false, ['deriveBits']);
      const shared = new Uint8Array(await crypto.subtle.deriveBits(
        {name: 'X25519', public: recipientKey}, probe.privateKey, 256));
      shared.fill(0);
      if (!active) return;
      fingerprintOutput.textContent = fingerprint;
      result.textContent = 'Destinatario cargado. Use solo el enlace de la ejecución aprobada.';
      lockInputs(false);
    } catch (_) {
      cleanInputs();
      lockInputs(true);
      result.textContent = 'No se pudo habilitar el cifrado. Abra el enlace del recibo aprobado '
        + 'en Chrome actualizado, con el túnel activo y la sesión iniciada.';
    }
  }
  sealButton.addEventListener('click', async () => {
    if (!active || sealButton.disabled || !recipient || !recipientKey) return;
    let token = tokenInput.value;
    let chat = chatInput.value;
    cleanInputs();
    lockInputs(true);
    copyButton.disabled = true;
    copyBot.disabled = true;
    copyChat.disabled = true;
    output.value = '';
    botPin.value = '';
    chatPin.value = '';
    result.textContent = 'Cifrando en este dispositivo…';
    let plaintext = null;
    let shared = null;
    let tokenBytes = null;
    let chatBytes = null;
    let succeeded = false;
    try {
      if (!/^[1-9][0-9]{0,15}:[A-Za-z0-9_-]{8,128}$/.test(token)
          || !/^[1-9][0-9]{0,15}$/.test(chat)) throw new Error('invalid secret material');
      const botId = token.split(':', 1)[0];
      const limit = 4503599627370496n;
      if (BigInt(botId) >= limit || BigInt(chat) >= limit)
        throw new Error('private identity required');
      plaintext = encoder.encode(canonical({bot_token: token, chat_id: chat}));
      tokenBytes = encoder.encode(token);
      chatBytes = encoder.encode(chat);
      token = '';
      chat = '';
      const pinKey = await crypto.subtle.importKey(
        'raw', tokenBytes, {name: 'HMAC', hash: 'SHA-256'}, false, ['sign']);
      tokenBytes.fill(0);
      const pin = new Uint8Array(await crypto.subtle.sign('HMAC', pinKey, chatBytes));
      chatBytes.fill(0);
      const chatHmac = Array.from(pin, byte => byte.toString(16).padStart(2, '0')).join('');
      const ephemeral = await crypto.subtle.generateKey('X25519', false, ['deriveBits']);
      const publicBytes = await crypto.subtle.exportKey('raw', ephemeral.publicKey);
      const salt = crypto.getRandomValues(new Uint8Array(16));
      const nonce = crypto.getRandomValues(new Uint8Array(12));
      const header = {
        version: 1, repository: 'mbalbo2023/boca-socios-assistant',
        purpose: 'boca-telegram-bot-v1', uid: 10001,
        recipient_public_key: recipient.public_key,
        recipient_fingerprint: recipient.fingerprint,
        ephemeral_public_key: base64url(publicBytes), salt: base64url(salt),
        nonce: base64url(nonce)
      };
      const aad = encoder.encode(canonical(header));
      shared = new Uint8Array(await crypto.subtle.deriveBits(
        {name: 'X25519', public: recipientKey}, ephemeral.privateKey, 256));
      const material = await crypto.subtle.importKey('raw', shared, 'HKDF', false, ['deriveKey']);
      shared.fill(0);
      const prefix = encoder.encode('boca-telegram-bot-envelope-v1:');
      const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', aad));
      const info = new Uint8Array(prefix.length + digest.length);
      info.set(prefix);
      info.set(digest, prefix.length);
      const key = await crypto.subtle.deriveKey(
        {name: 'HKDF', hash: 'SHA-256', salt: salt, info: info}, material,
        {name: 'AES-GCM', length: 256}, false, ['encrypt']);
      const ciphertext = await crypto.subtle.encrypt(
        {name: 'AES-GCM', iv: nonce, additionalData: aad, tagLength: 128}, key, plaintext);
      plaintext.fill(0);
      const envelope = encoder.encode(canonical({...header, ciphertext: base64url(ciphertext)}));
      if (envelope.length > 4096) throw new Error('invalid envelope');
      if (!active) return;
      output.value = base64url(envelope);
      output.hidden = false;
      botPin.value = botId;
      chatPin.value = chatHmac;
      botPin.hidden = false;
      chatPin.hidden = false;
      copyButton.disabled = false;
      copyBot.disabled = false;
      copyChat.disabled = false;
      result.textContent = 'Valores listos para la configuración autorizada en GitHub. '
        + 'Telegram todavía no está instalado ni activado.';
      output.focus();
      succeeded = true;
    } catch (_) {
      if (active) result.textContent = 'No se generó el texto cifrado. Revise los datos '
        + 'y el recibo antes de volver a intentarlo.';
    } finally {
      token = '';
      chat = '';
      if (plaintext) plaintext.fill(0);
      if (shared) shared.fill(0);
      if (tokenBytes) tokenBytes.fill(0);
      if (chatBytes) chatBytes.fill(0);
      cleanInputs();
      if (active && !succeeded) lockInputs(false);
    }
  });
  function copyHandler(button, field, destination) {
    button.addEventListener('click', async () => {
      if (!active || button.disabled || !field.value) return;
      try {
        await navigator.clipboard.writeText(field.value);
        if (active) result.textContent = 'Valor copiado para ' + destination + '.';
      } catch (_) {
        if (!active) return;
        field.focus();
        field.select();
        result.textContent = 'Seleccione Copiar para copiar el valor marcado para '
          + destination + '.';
      }
    });
  }
  copyHandler(copyButton, output, 'telegram_envelope de la instalación autorizada');
  copyHandler(copyBot, botPin, 'el secreto BOCA_TELEGRAM_EXPECTED_BOT_ID');
  copyHandler(copyChat, chatPin, 'el secreto BOCA_TELEGRAM_EXPECTED_CHAT_HMAC');
  addEventListener('pagehide', () => {
    active = false;
    cleanInputs();
    output.value = '';
    botPin.value = '';
    chatPin.value = '';
    lockInputs(true);
    copyButton.disabled = true;
    copyBot.disabled = true;
    copyChat.disabled = true;
    recipient = null;
    recipientKey = null;
    result.textContent = 'Vuelva a abrir el enlace del recibo aprobado.';
  });
  cleanInputs();
  lockInputs(true);
  void initialize();
})();
"""


def _hash(value: str) -> str:
    return base64.b64encode(hashlib.sha256(value.encode()).digest()).decode("ascii")


CSP = (
    "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
    "form-action 'none'; connect-src 'none'; "
    f"style-src 'sha256-{_hash(_SETUP_STYLE)}'; script-src 'sha256-{_hash(SCRIPT)}'"
)


def page() -> bytes:
    """Fixed HTML: no credential, recipient or request data is rendered by Python."""
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Configurar Telegram · Boca Socios Assistant</title><style>{_SETUP_STYLE}</style></head>
<body><nav aria-label="Secciones"><a href="/">Inicio</a> · <a href="/avisos">Avisos</a></nav>
<main><h1>Configurar Telegram</h1>
<p>Abra el enlace del recibo preparado para esta instalación, después de ingresar con su passkey.
El token y el destino se cifran en esta pestaña. El panel no los recibe.</p>
<p>Complete la instalación y la prueba de Telegram antes de iniciar la primera simulación.</p>
<p>Huella del destinatario: <output id="fingerprint">Sin recibo</output></p>
<label for="telegram-token">Token del bot dedicado a Boca</label>
<input id="telegram-token" type="password" autocomplete="off" autocapitalize="none"
spellcheck="false" maxlength="149" disabled>
<label for="telegram-chat">Número del chat privado autorizado</label>
<input id="telegram-chat" type="text" autocomplete="off" autocapitalize="none"
spellcheck="false" maxlength="16" disabled>
<button id="seal" type="button" disabled>Crear texto cifrado</button>
<p id="result" role="status" aria-live="polite">Comprobando el recibo público…</p>
<label for="sealed">Texto cifrado para GitHub Actions</label>
<textarea id="sealed" readonly autocomplete="off" spellcheck="false" hidden></textarea>
<button id="copy" type="button" disabled>Copiar texto cifrado</button>
<p>Destino: campo <code>telegram_envelope</code> de la instalación autorizada.</p>
<label for="bot-pin">Identificador esperado del bot</label>
<input id="bot-pin" type="text" readonly autocomplete="off" spellcheck="false" hidden>
<button id="copy-bot" type="button" disabled>Copiar identificador del bot</button>
<p>Destino: secreto <code>BOCA_TELEGRAM_EXPECTED_BOT_ID</code> del entorno
<code>boca-first-deploy</code>.</p>
<label for="chat-pin">Verificación del chat</label>
<input id="chat-pin" type="text" readonly autocomplete="off" spellcheck="false" hidden>
<button id="copy-chat" type="button" disabled>Copiar verificación del chat</button>
<p>Destino: secreto <code>BOCA_TELEGRAM_EXPECTED_CHAT_HMAC</code> del mismo entorno.</p>
<p>Copie estos valores únicamente a los destinos indicados en GitHub.
Nunca pegue el token ni el número del chat en una conversación o en GitHub Actions.</p>
<noscript>Active JavaScript en Chrome para cifrar sin enviar los datos al panel.</noscript>
</main><script>{SCRIPT}</script></body></html>""".encode()
