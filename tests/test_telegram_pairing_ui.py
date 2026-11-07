"""Offline, actual native-WebCrypto V2 Telegram pairing: no Bot API or secrets."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import asdict
from typing import Any

import pytest

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios import telegram_pairing_bootstrap as pairing
from boca_socios.panel import telegram_setup_ui as ui

TOKEN = "123456:synthetic_token_for_offline_test"

_NODE_HARNESS = r"""
const {webcrypto} = require('node:crypto');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(readFileSync(0, 'utf8'));
const events = [];
const elements = {};
for (const id of ['pairing-token', 'pairing-command', 'pairing-generate',
                  'pairing-copy-command', 'pairing-seal', 'pairing-sealed',
                  'pairing-copy-envelope', 'pairing-result', 'pairing-fingerprint',
                  'pairing-stage', 'pairing-csrf', 'pairing-operation']) {
  elements[id] = {value: '', disabled: true, hidden: true, textContent: '',
    addEventListener(name, fn) { this[name] = fn; },
    focus() { events.push('focus:' + id); },
    select() { events.push('select:' + id); }};
}
if (input.stage) {
  elements['pairing-csrf'].value = 'x'.repeat(43);
  elements['pairing-operation'].value = '123e4567-e89b-42d3-a456-426614174000';
}
const location = {hash: input.fragment, origin: input.origin || 'http://localhost:8443'};
const handlers = {};
const copies = [];
let stagedPayload = null;
function forbidden() { events.push('FORBIDDEN'); throw Error('forbidden side effect'); }
const subtle = new Proxy(webcrypto.subtle, {get(target, property) {
  if (input.mode === 'unsupported' && property === 'importKey')
    return async () => { throw Error('unsupported'); };
  const value = Reflect.get(target, property);
  if (typeof value !== 'function') return value;
  return (...args) => { events.push('crypto:' + property); return value.apply(target, args); };
}});
const context = {
  location, history: {replaceState(state, title, path) {
    events.push('replace');
    if (state !== null || title !== '' || path !== '/telegram/emparejar') forbidden();
    if (input.mode === 'history-fails') throw Error('blocked history');
    location.hash = '';
  }},
  document: {getElementById(id) { if (!(id in elements)) forbidden(); return elements[id]; }},
  crypto: {subtle, getRandomValues: array => webcrypto.getRandomValues(array)},
  isSecureContext: input.secure !== false,
  TextEncoder, TextDecoder, Uint8Array, atob, btoa,
  URLSearchParams,
  addEventListener(name, fn) { handlers[name] = fn; },
  navigator: {
    clipboard: {async writeText(value) {
      if (input.mode === 'clipboard-denied') throw Error('clipboard denied');
      copies.push(value);
    }},
    credentials: {async get(options) {
      if (!input.stage || !options.publicKey
          || options.publicKey.rpId !== 'localhost'
          || options.publicKey.userVerification !== 'required'
          || options.publicKey.timeout !== 120000) forbidden();
      events.push('owner-webauthn-uv');
      const rawId = new Uint8Array(32).fill(7);
      return {type: 'public-key', rawId, response: {
        clientDataJSON: new TextEncoder().encode('{"type":"webauthn.get"}'),
        authenticatorData: new Uint8Array(37).fill(9),
        signature: new Uint8Array(70).fill(10)
      }};
    }}
  },
  fetch: async (path, options) => {
    if (!input.stage || options.method !== 'POST'
        || options.credentials !== 'same-origin' || options.cache !== 'no-store'
        || options.redirect !== 'error'
        || options.headers['Content-Type'] !== 'application/x-www-form-urlencoded') forbidden();
    if (path === '/telegram/emparejar/desafio') {
      const request = Object.fromEntries(new URLSearchParams(options.body));
      if (Object.keys(request).sort().join(',') !== 'csrf,envelope_sha256,operation_id'
          || !/^[0-9a-f]{64}$/.test(request.envelope_sha256)) forbidden();
      events.push('private-challenge');
      const b64 = data => Buffer.from(data).toString('base64url');
      return {status: 200, async json() {
        return {version: 1, challenge: b64(new Uint8Array(32).fill(3)),
          request_nonce: 'c'.repeat(64), challenged_at: 1772700000,
          credential_id: b64(new Uint8Array(32).fill(7)), rp_id: 'localhost'};
      }};
    }
    if (path !== '/telegram/emparejar') forbidden();
    stagedPayload = Object.fromEntries(new URLSearchParams(options.body));
    if (!stagedPayload.envelope || Object.keys(stagedPayload).sort().join(',')
        !== 'authenticator_data,challenged_at,client_data_json,credential_id,csrf,envelope,operation_id,request_nonce,signature'
        || JSON.stringify(stagedPayload).includes(input.token)) forbidden();
    events.push('private-stage');
    return {status: input.stageStatus || 202};
  }, XMLHttpRequest: forbidden, WebSocket: forbidden,
  localStorage: new Proxy({}, {get: forbidden, set: forbidden}),
  sessionStorage: new Proxy({}, {get: forbidden, set: forbidden}),
  console: new Proxy({}, {get: forbidden})
};
vm.runInNewContext(input.script, context, {timeout: 1000});
(async () => {
  // Native WebCrypto initializes asynchronously. Under a parallel CI suite,
  // scheduler pressure may delay this test subprocess without changing the UI.
  const deadline = Date.now() + 15000;
  while (elements['pairing-generate'].disabled
         && !elements['pairing-result'].textContent.startsWith('Recibo público inválido')) {
    if (Date.now() > deadline) throw Error('UI did not initialize');
    await new Promise(resolve => setTimeout(resolve, 1));
  }
  const enabled = !elements['pairing-generate'].disabled;
  let generatedCommand = '';
  let sealedBeforeStage = '';
  if (enabled && input.token !== null) {
    elements['pairing-generate'].click();
    generatedCommand = elements['pairing-command'].value;
    if (input.mode === 'pagehide-after-generate') handlers.pagehide();
    if (!elements['pairing-copy-command'].disabled)
      await elements['pairing-copy-command'].click();
    if (input.mode !== 'pagehide-after-generate')
      elements['pairing-token'].value = input.token;
    if (!elements['pairing-seal'].disabled) {
      const result = elements['pairing-seal'].click();
      if (input.mode === 'pagehide-during-seal') handlers.pagehide();
      await result;
    }
    if (!elements['pairing-copy-envelope'].disabled)
      await elements['pairing-copy-envelope'].click();
    sealedBeforeStage = elements['pairing-sealed'].value;
    if (input.stage && !elements['pairing-stage'].disabled)
      await elements['pairing-stage'].click();
    if (input.mode === 'pagehide-after-seal') handlers.pagehide();
  }
  process.stdout.write(JSON.stringify({enabled, hash: location.hash, events, copies,
    command: generatedCommand, currentCommand: elements['pairing-command'].value,
    output: elements['pairing-sealed'].value,
    status: elements['pairing-result'].textContent,
    token: elements['pairing-token'].value,
    generateDisabled: elements['pairing-generate'].disabled,
    sealDisabled: elements['pairing-seal'].disabled,
    copyDisabled: elements['pairing-copy-envelope'].disabled,
    stageDisabled: elements['pairing-stage'].disabled, stagedPayload, sealedBeforeStage,
    fingerprint: elements['pairing-fingerprint'].textContent}));
})().catch(() => { process.exitCode = 1; });
"""


def _recipient() -> tuple[bytes, bootstrap.RecipientReceipt, str]:
    private = os.urandom(32)
    receipt = bootstrap._receipt(private, "PREPARED")
    fragment = "#recipient=" + bootstrap._b64(bootstrap._canonical(asdict(receipt)))
    return private, receipt, fragment


def _run(
    fragment: str,
    *,
    token: str | None = TOKEN,
    mode: str = "",
    origin: str = "http://localhost:8443",
    secure: bool = True,
    stage: bool = False,
    stage_status: int = 202,
) -> dict[str, Any]:
    node = shutil.which("node")
    assert node is not None, "Node with native X25519 WebCrypto is required"
    completed = subprocess.run(  # noqa: S603 - fixed harness and synthetic local inputs
        [node, "-e", _NODE_HARNESS],
        input=json.dumps(
            {
                "script": ui.PAIRING_SCRIPT,
                "fragment": fragment,
                "token": token,
                "mode": mode,
                "origin": origin,
                "secure": secure,
                "stage": stage,
                "stageStatus": stage_status,
            }
        ),
        capture_output=True,
        text=True,
        check=True,
        # Bound a real stall, but allow CPU-starved CI runners enough time for
        # Node WebCrypto startup and the synthetic browser initialization.
        timeout=30,
    )
    result = json.loads(completed.stdout)
    assert isinstance(result, dict)
    assert "FORBIDDEN" not in result["events"]
    assert result["events"][0] == "replace"
    return result


def test_actual_browser_stages_only_encrypted_v2_to_same_origin_without_sender_ack() -> None:
    private, receipt, fragment = _recipient()
    result = _run(fragment, stage=True)
    staged = result["stagedPayload"]
    assert staged is not None and "private-stage" in result["events"]
    assert staged["csrf"] == "x" * 43
    assert staged["operation_id"] == "123e4567-e89b-42d3-a456-426614174000"
    assert staged["envelope"] == result["sealedBeforeStage"]
    assert "private-challenge" in result["events"]
    assert "owner-webauthn-uv" in result["events"]
    assert staged["request_nonce"] == "c" * 64
    assert TOKEN not in json.dumps(staged)
    sealed = bootstrap._unb64(staged["envelope"], maximum=4096)
    code = result["command"].removeprefix("/start ")
    assert pairing.unseal_pairing(sealed, private, receipt) == (TOKEN.encode(), code)
    assert result["output"] == result["token"] == result["currentCommand"] == ""
    assert result["stageDisabled"] and result["copyDisabled"]
    assert "NO está conectado" in result["status"]


def test_browser_private_staging_failure_keeps_ciphertext_without_claiming_install() -> None:
    _, _, fragment = _recipient()
    result = _run(fragment, stage=True, stage_status=503)
    assert result["stagedPayload"] is not None
    assert result["output"] == result["sealedBeforeStage"]
    assert "No se confirmó" in result["status"]
    assert "sigue detenido" in result["status"]
    assert TOKEN not in json.dumps(result["stagedPayload"])


def test_inert_v2_browser_has_no_submission_network_or_authority() -> None:
    _, _, fragment = _recipient()
    result = _run(fragment)
    assert result["stagedPayload"] is None
    assert "private-stage" not in result["events"]
    assert result["stageDisabled"]


def test_actual_owner_webcrypto_emits_v2_envelope_decryptable_only_by_v2() -> None:
    private, receipt, fragment = _recipient()
    result = _run(fragment)
    assert result["enabled"] and result["generateDisabled"]
    assert result["sealDisabled"] and not result["copyDisabled"]
    assert result["token"] == result["hash"] == ""
    assert result["fingerprint"] == receipt.fingerprint
    assert result["command"].startswith("/start ")
    code = result["command"][7:]
    assert len(code) == 32
    assert result["currentCommand"] == result["command"]
    assert result["copies"] == [result["command"], result["output"]]
    assert "futuro instalador V2 copiado" in result["status"]
    envelope = bootstrap._unb64(result["output"], maximum=4096)
    assert pairing.unseal_pairing(envelope, private, receipt) == (TOKEN.encode(), code)
    assert TOKEN.encode() not in envelope and code.encode() not in envelope
    assert json.loads(envelope)["purpose"] == pairing.PURPOSE
    with pytest.raises(bootstrap.BootstrapError, match="invalid_envelope"):
        bootstrap._decrypt(envelope, private, receipt)


def test_generated_codes_are_fresh_and_no_token_in_code_copy() -> None:
    _, _, fragment = _recipient()
    first, second = _run(fragment), _run(fragment)
    assert first["command"] != second["command"]
    assert TOKEN not in first["command"] and TOKEN not in second["command"]


@pytest.mark.parametrize(
    "payload",
    [
        b"{}",
        b'{"bot_token":"1:sometoken"}',
        b'{"bot_token":"1:sometoken","pairing_code":"x"}',
        b'{"bot_token":"123456:sometoken","pairing_code":""}',
        b'{"bot_token":"123456:sometoken","pairing_code":"A2345678901234567890123456789012","more":true}',
        b'{"bot_token":"123456:sometoken","pairing_code":"A2345678901234567890123456789012","pairing_code":"A2345678901234567890123456789012"}',
    ],
)
def test_plaintext_contract_rejects_missing_bad_or_duplicate_fields(payload: bytes) -> None:
    with pytest.raises(pairing.PairingEnvelopeError, match="invalid_pairing_envelope"):
        pairing._pairing_payload(payload)


def test_fingerprint_must_come_from_approved_prepared_recipient() -> None:
    private, receipt, fragment = _recipient()
    envelope = bootstrap._unb64(_run(fragment)["output"], maximum=4096)
    with pytest.raises(pairing.PairingEnvelopeError, match="invalid_pairing_envelope"):
        pairing.unseal_pairing(
            envelope,
            private,
            bootstrap.RecipientReceipt(
                state="CONFIGURED",
                public_key=receipt.public_key,
                fingerprint=receipt.fingerprint,
            ),
        )


@pytest.mark.parametrize(
    "key,value",
    [
        ("version", 1),
        ("version", True),
        ("purpose", "boca-telegram-bot-v1"),
        ("repository", "another/repository"),
        ("uid", 10002),
        # Collection must be identical across pytest-xdist workers. The
        # encrypted envelope itself still receives fresh random bytes in _run.
        ("nonce", bootstrap._b64(b"n" * 12)),
        ("salt", bootstrap._b64(b"s" * 16)),
        ("ciphertext", bootstrap._b64(b"wrong-authentication-tag")),
    ],
)
def test_v2_tamper_rejected_without_partial_secret_return(key: str, value: object) -> None:
    private, receipt, fragment = _recipient()
    envelope = json.loads(bootstrap._unb64(_run(fragment)["output"], maximum=4096))
    with pytest.raises(pairing.PairingEnvelopeError, match="invalid_pairing_envelope"):
        pairing.unseal_pairing(bootstrap._canonical({**envelope, key: value}), private, receipt)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "123:short",
        "0:synthetic_longer",
        "0123:synthetic_longer",
        "123456:synthetic_token_for_offline_test\n",
        "123456:" + "x" * 129,
        "4503599627370496:synthetic_longer",
    ],
)
def test_bad_bot_token_never_sealed_or_preserved(token: str) -> None:
    _, _, fragment = _recipient()
    result = _run(fragment, token=token)
    assert result["enabled"] and result["output"] == ""
    assert result["token"] == "" and result["copies"] == [result["command"]]
    assert "No se generó" in result["status"]


@pytest.mark.parametrize(
    "mode,origin,secure",
    [
        ("history-fails", "http://localhost:8443", True),
        ("unsupported", "http://localhost:8443", True),
        ("", "http://127.0.0.1:8443", True),
        ("", "https://localhost:8443", True),
        ("", "http://localhost:8443", False),
    ],
)
def test_wrong_context_fails_closed(mode: str, origin: str, secure: bool) -> None:
    _, _, fragment = _recipient()
    result = _run(fragment, mode=mode, origin=origin, secure=secure)
    assert not result["enabled"] and result["output"] == ""
    assert result["token"] == result["currentCommand"] == ""
    assert "Recibo público inválido" in result["status"]


@pytest.mark.parametrize("fragment", ["", "#recipient=bad", "#token=secret"])
def test_receipt_missing_fails_closed(fragment: str) -> None:
    result = _run(fragment)
    assert not result["enabled"] and result["output"] == ""


@pytest.mark.parametrize(
    "mode",
    ["pagehide-after-generate", "pagehide-during-seal", "pagehide-after-seal"],
)
def test_navigation_clears_sensitive_values(mode: str) -> None:
    _, _, fragment = _recipient()
    result = _run(fragment, mode=mode)
    assert result["currentCommand"] == result["output"] == result["token"] == ""
    assert result["generateDisabled"] and result["sealDisabled"] and result["copyDisabled"]


def test_clipboard_denied_selects_command_or_ciphertext_only() -> None:
    _, _, fragment = _recipient()
    result = _run(fragment, mode="clipboard-denied")
    assert result["enabled"] and result["output"] and not result["copies"]
    assert "select:pairing-command" in result["events"]
    assert "select:pairing-sealed" in result["events"]
    assert result["token"] == ""


def test_separate_unrouted_v2_page_has_hash_csp_no_transport_and_v1_is_preserved() -> None:
    page = ui.pairing_page()
    assert b"<script>" + ui.PAIRING_SCRIPT.encode() + b"</script>" in page
    assert b"pairing-token" in page and b"pairing-command" in page
    expected_script_hash = base64.b64encode(hashlib.sha256(ui.PAIRING_SCRIPT.encode()).digest())
    assert f"script-src 'sha256-{expected_script_hash.decode()}'" in ui.PAIRING_CSP
    assert "connect-src 'none'" in ui.PAIRING_CSP
    assert "form-action 'none'" in ui.PAIRING_CSP
    assert "'unsafe-inline'" not in ui.PAIRING_CSP
    assert b'<input id="telegram-chat"' in ui.page()
    assert "boca-telegram-bot-v1" in ui.SCRIPT
    assert "boca-telegram-pairing-v2" not in ui.SCRIPT
