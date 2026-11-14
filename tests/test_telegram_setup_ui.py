"""Actual WebCrypto-to-installer interoperability, using only synthetic secrets."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from boca_socios import telegram_bootstrap as bootstrap
from boca_socios.panel import telegram_setup_ui as ui
from test_private_beta_panel import _app, _login, _passkey, _request

TOKEN = "123456:synthetic_token_for_offline_test"
CHAT = "1001234567890"

# Run the delivered, unmodified script, with actual native WebCrypto and a tiny
# DOM harness. The harness rejects every accidental network/storage/console use.
_NODE_HARNESS = r"""
const {webcrypto} = require('node:crypto');
const {readFileSync} = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(readFileSync(0, 'utf8'));
const events = [];
const elements = {};
for (const id of ['telegram-token', 'telegram-chat', 'seal', 'copy', 'sealed',
                  'result', 'fingerprint', 'bot-pin', 'chat-pin', 'copy-bot', 'copy-chat']) {
  elements[id] = {value: '', disabled: true, hidden: true, textContent: '',
    addEventListener(name, fn) { this[name] = fn; },
    focus() { events.push('focus:' + id); },
    select() { events.push('select:' + id); }};
}
const location = {hash: input.fragment, origin: input.origin || 'http://localhost:8443'};
const handlers = {};
let copied = '';
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
    if (state !== null || title !== '' || path !== '/telegram/configurar') forbidden();
    if (input.mode === 'history-fails') throw Error('blocked history');
    location.hash = '';
  }},
  document: {getElementById(id) { if (!(id in elements)) forbidden(); return elements[id]; }},
  crypto: {subtle, getRandomValues: array => webcrypto.getRandomValues(array)},
  isSecureContext: input.secure !== false,
  TextEncoder, TextDecoder, Uint8Array, atob, btoa,
  addEventListener(name, fn) { handlers[name] = fn; },
  navigator: {clipboard: {async writeText(value) {
    if (input.mode === 'clipboard-denied') throw Error('permission denied');
    copied = value;
  }}},
  fetch: forbidden, XMLHttpRequest: forbidden, WebSocket: forbidden,
  localStorage: new Proxy({}, {get: forbidden, set: forbidden}),
  sessionStorage: new Proxy({}, {get: forbidden, set: forbidden}),
  console: new Proxy({}, {get: forbidden})
};
vm.runInNewContext(input.script, context, {timeout: 1000});
(async () => {
  const deadline = Date.now() + 5000;
  while (elements.seal.disabled && !elements.result.textContent.startsWith('No se pudo')) {
    if (Date.now() > deadline) throw Error('UI did not initialize');
    await new Promise(resolve => setTimeout(resolve, 1));
  }
  const enabled = !elements.seal.disabled;
  if (enabled && input.token !== null) {
    elements['telegram-token'].value = input.token;
    elements['telegram-chat'].value = input.chat;
    const seal = elements.seal.click();
    if (input.mode === 'pagehide-during-seal') handlers.pagehide();
    await seal;
    if (input.mode === 'copy-bot' && !elements['copy-bot'].disabled)
      await elements['copy-bot'].click();
    else if (input.mode === 'copy-chat' && !elements['copy-chat'].disabled)
      await elements['copy-chat'].click();
    else if (!elements.copy.disabled) await elements.copy.click();
    if (input.mode === 'pagehide-after-seal') handlers.pagehide();
  }
  process.stdout.write(JSON.stringify({enabled, hash: location.hash, events, copied,
    output: elements.sealed.value, status: elements.result.textContent,
    token: elements['telegram-token'].value, chat: elements['telegram-chat'].value,
    locked: elements.seal.disabled, copyDisabled: elements.copy.disabled,
    fingerprint: elements.fingerprint.textContent,
    botPin: elements['bot-pin'].value, chatPin: elements['chat-pin'].value,
    copyBotDisabled: elements['copy-bot'].disabled, copyChatDisabled: elements['copy-chat'].disabled}));
})().catch(() => { process.exitCode = 1; });
"""


def _recipient(state: str = "PREPARED") -> tuple[bytes, bootstrap.RecipientReceipt, str]:
    # No files, accounts, Telegram API or private material outside this test.
    private = os.urandom(32)
    receipt = bootstrap._receipt(private, state)
    return private, receipt, _fragment(asdict(receipt))


def _fragment(value: dict[str, object] | bytes) -> str:
    encoded = value if isinstance(value, bytes) else bootstrap._canonical(value)
    return "#recipient=" + bootstrap._b64(encoded)


def _run(
    fragment: str,
    *,
    token: str | None = TOKEN,
    chat: str = CHAT,
    mode: str = "",
    origin: str = "http://localhost:8443",
    secure: bool = True,
) -> dict[str, Any]:
    node = shutil.which("node")
    assert node is not None, "Node with native X25519 WebCrypto is required; never skip this proof"
    completed = subprocess.run(  # noqa: S603 - fixed Node harness; synthetic data via stdin
        [node, "-e", _NODE_HARNESS],
        input=json.dumps(
            {
                "script": ui.SCRIPT,
                "fragment": fragment,
                "token": token,
                "chat": chat,
                "mode": mode,
                "origin": origin,
                "secure": secure,
            }
        ),
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    result = json.loads(completed.stdout)
    assert isinstance(result, dict)
    assert "FORBIDDEN" not in result["events"]
    assert result["events"][0] == "replace"
    return result


@pytest.mark.parametrize("state", ["PREPARED", "ALREADY_PREPARED"])
@pytest.mark.parametrize("chat", [CHAT, "1", "4503599627370495"])
def test_actual_webcrypto_ciphertext_decrypts_with_existing_installer(
    state: str, chat: str
) -> None:
    private, receipt, fragment = _recipient(state)
    result = _run(fragment, chat=chat)
    assert result["enabled"] and result["locked"] and not result["copyDisabled"]
    assert result["hash"] == result["token"] == result["chat"] == ""
    assert result["copied"] == result["output"]
    assert result["fingerprint"] == receipt.fingerprint
    assert result["botPin"] == TOKEN.split(":")[0]
    assert result["chatPin"] == hmac.new(TOKEN.encode(), chat.encode(), hashlib.sha256).hexdigest()
    envelope = bootstrap._unb64(result["output"], maximum=bootstrap.MAX_ENVELOPE)
    assert bootstrap._decrypt(envelope, private, receipt) == (TOKEN.encode(), chat.encode())
    assert TOKEN.encode() not in envelope
    assert "bot_token" not in json.loads(envelope) and "chat_id" not in json.loads(envelope)
    assert "telegram_envelope" in result["status"]


def test_each_envelope_has_fresh_ephemeral_key_salt_nonce_and_authenticates_header() -> None:
    private, receipt, fragment = _recipient()
    first = json.loads(bootstrap._unb64(_run(fragment)["output"], maximum=4096))
    second = json.loads(bootstrap._unb64(_run(fragment)["output"], maximum=4096))
    for key in ("ephemeral_public_key", "salt", "nonce", "ciphertext"):
        assert first[key] != second[key]
    for key, value in (
        ("repository", "different/repository"),
        ("purpose", "different-purpose"),
        ("uid", 10002),
        ("nonce", bootstrap._b64(os.urandom(12))),
        ("salt", bootstrap._b64(os.urandom(16))),
        ("ciphertext", bootstrap._b64(b"tampered-ciphertext")),
    ):
        with pytest.raises(bootstrap.BootstrapError, match="invalid_envelope"):
            bootstrap._decrypt(bootstrap._canonical({**first, key: value}), private, receipt)


@pytest.mark.parametrize(
    "token,chat",
    [
        ("", CHAT),
        ("123:short", CHAT),
        ("123:" + "a" * 129, CHAT),
        ("1" * 21 + ":synthetic", CHAT),
        (TOKEN + "\n", CHAT),
        (TOKEN, ""),
        (TOKEN, "0"),
        (TOKEN, "-0"),
        (TOKEN, "01"),
        (TOKEN, "-01"),
        (TOKEN, "+1"),
        (TOKEN, "1\n"),
        (TOKEN, "1" * 21),
        (TOKEN, "-1"),
        (TOKEN, "4503599627370496"),
        ("4503599627370496:synthetic", CHAT),
        ("0:synthetic", CHAT),
        ("0123:synthetic", CHAT),
    ],
)
def test_invalid_secret_material_is_cleared_without_an_envelope(token: str, chat: str) -> None:
    _, _, fragment = _recipient()
    result = _run(fragment, token=token, chat=chat)
    assert result["enabled"] and not result["locked"]
    assert result["output"] == result["copied"] == result["token"] == result["chat"] == ""
    assert result["copyDisabled"] and result["copyBotDisabled"] and result["copyChatDisabled"]
    assert result["botPin"] == result["chatPin"] == ""
    assert "No se generó" in result["status"]


def test_public_receipt_is_strict_canonical_bounded_and_fingerprint_checked() -> None:
    _, receipt, fragment = _recipient()
    fields = asdict(receipt)
    invalid = [
        "",
        "#recipient=",
        fragment + "=",
        fragment + "&other=value",
        "#recipient=" + "a" * 1025,
        _fragment({**fields, "extra": "value"}),
        _fragment({**fields, "state": "INSTALLED"}),
        _fragment({**fields, "fingerprint": "0" * 64}),
        _fragment({**fields, "public_key": "a" * 42}),
        _fragment(json.dumps(fields, indent=2).encode()),
        _fragment(b'{"state":"PREPARED",' + bootstrap._canonical(fields)[1:]),
        _fragment(b"null"),
        _fragment(b"[]"),
        _fragment(b"\xff"),
    ]
    # A canonical zero-point receipt matches its fingerprint but X25519 rejects
    # the shared secret before any credential field is enabled.
    zero = bytes(32)
    invalid.append(
        _fragment(
            {
                **fields,
                "public_key": bootstrap._b64(zero),
                "fingerprint": hashlib.sha256(zero).hexdigest(),
            }
        )
    )
    for value in invalid:
        result = _run(value)
        assert not result["enabled"] and result["locked"] and result["copyDisabled"]
        assert result["hash"] == result["output"] == result["token"] == result["chat"] == ""
        assert "No se pudo habilitar" in result["status"]


@pytest.mark.parametrize(
    "options",
    [
        {"mode": "unsupported"},
        {"mode": "history-fails"},
        {"origin": "http://127.0.0.1:8443"},
        {"origin": "https://outside.example.test"},
        {"secure": False},
    ],
)
def test_unsupported_or_wrong_context_stays_disabled(options: dict[str, Any]) -> None:
    _, _, fragment = _recipient()
    result = _run(fragment, **options)
    assert not result["enabled"] and result["locked"] and result["copyDisabled"]
    assert result["output"] == result["token"] == result["chat"] == ""


@pytest.mark.parametrize("mode", ["pagehide-during-seal", "pagehide-after-seal"])
def test_navigation_clears_fields_and_prevents_late_ciphertext_repopulation(mode: str) -> None:
    _, _, fragment = _recipient()
    result = _run(fragment, mode=mode)
    assert result["output"] == result["token"] == result["chat"] == ""
    assert result["locked"] and result["copyDisabled"]
    assert result["copyBotDisabled"] and result["copyChatDisabled"]
    assert result["botPin"] == result["chatPin"] == ""
    assert "Vuelva a abrir" in result["status"]


def test_clipboard_denial_selects_only_ciphertext_without_plaintext_fallback() -> None:
    private, receipt, fragment = _recipient()
    result = _run(fragment, mode="clipboard-denied")
    assert result["copied"] == result["token"] == result["chat"] == ""
    assert "select:sealed" in result["events"]
    assert bootstrap._decrypt(
        bootstrap._unb64(result["output"], maximum=4096), private, receipt
    ) == (TOKEN.encode(), CHAT.encode())


def test_private_route_requires_owner_and_uses_strict_route_specific_csp(tmp_path: Path) -> None:
    provider, key, credential = _passkey([0.0])
    app, _ = _app(tmp_path / "boca.sqlite3", provider)
    assert _request(app, "/telegram/configurar")[0] == 401
    cookie = _login(app, key, credential)
    status, headers, body = _request(app, "/telegram/configurar", cookie=cookie)
    assert status == 200 and body == ui.page()
    assert headers["Content-Security-Policy"] == ui.CSP
    assert "connect-src 'none'" in ui.CSP and "form-action 'none'" in ui.CSP
    assert "'unsafe-inline'" not in ui.CSP and "'self'" not in ui.CSP
    assert headers["Cache-Control"] == "no-store"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["X-Frame-Options"] == "DENY"
    expected = base64.b64encode(hashlib.sha256(ui.SCRIPT.encode()).digest()).decode()
    assert f"script-src 'sha256-{expected}'" in ui.CSP
    assert b"<script>" + ui.SCRIPT.encode() + b"</script>" in body
    assert b"<form" not in body and b"name=" not in body.replace(b'name="viewport"', b"")
    assert b'role="status" aria-live="polite"' in body
    assert b"min-height: 52px" in body and b'type="password"' in body
    assert b'href="/telegram/configurar"' in _request(app, "/", cookie=cookie)[2]


def test_versioned_pairing_route_requires_owner_and_keeps_v1_separate(tmp_path: Path) -> None:
    provider, key, credential = _passkey([0.0])
    app, _ = _app(tmp_path / "boca.sqlite3", provider)
    assert _request(app, "/telegram/emparejar")[0] == 401
    cookie = _login(app, key, credential)
    status, headers, body = _request(app, "/telegram/emparejar", cookie=cookie)
    assert status == 200
    assert body == ui.pairing_page()
    assert headers["Content-Security-Policy"] == ui.PAIRING_CSP
    assert "connect-src 'none'" in ui.PAIRING_CSP
    assert "form-action 'none'" in ui.PAIRING_CSP
    assert "'unsafe-inline'" not in ui.PAIRING_CSP
    assert headers["Cache-Control"] == "no-store"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert b"esta pantalla no instala ni activa el emisor" in body
    assert b'<input id="pairing-token" type="password"' in body
    assert b"enlace" in body and b"recibo" in body
    assert _request(app, "/telegram/configurar", cookie=cookie)[2] == ui.page()
    assert _request(app, "/telegram/emparejar", cookie=cookie, method="POST")[0] == 404


def test_private_route_does_not_read_or_reflect_posted_secrets(tmp_path: Path) -> None:
    provider, key, credential = _passkey([0.0])
    app, _ = _app(tmp_path / "boca.sqlite3", provider)
    cookie = _login(app, key, credential)

    class ForbiddenRead(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            raise AssertionError("Telegram setup must never read submitted plaintext")

    for method, extra in (
        ("POST", {}),
        ("GET", {"CONTENT_LENGTH": "1"}),
        ("GET", {"QUERY_STRING": "token=" + TOKEN}),
        ("GET", {"HTTP_HOST": "evil.example.test"}),
        ("GET", {"HTTP_ORIGIN": "https://evil.example.test"}),
    ):
        status, _, body = _request(
            app,
            "/telegram/configurar",
            cookie=cookie,
            method=method,
            extra={"wsgi.input": ForbiddenRead(TOKEN.encode()), **extra},
        )
        assert status in (400, 403, 404)
        assert TOKEN.encode() not in body and b"telegram-token" not in body


def _offline_smoke_module() -> Any:
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts/run_telegram_setup_ui_offline_chromium.py"
    spec = importlib.util.spec_from_file_location("telegram_ui_offline_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_offline_smoke_verifies_actual_js_ciphertext_and_rejects_false_receipts() -> None:
    smoke = _offline_smoke_module()
    fixture = smoke.make_fixture()
    assert fixture["html"] == ui.page().decode() and fixture["csp"] == ui.CSP
    result = _run(fixture["fragment"], token=smoke.TOKEN, chat=smoke.CHAT)
    receipt = {
        "mode": "offline_telegram_setup_ui",
        "state": "PASS",
        "document_requests": 1,
        "other_requests": 0,
        "csp_connect_blocked": True,
        "fields_cleared": True,
        "history_cleared": True,
        "ciphertext_copied": True,
        "ciphertext": result["output"],
        "bot_pin": result["botPin"],
        "chat_pin": result["chatPin"],
    }
    smoke.verify_receipt(receipt)
    for key, value in (
        ("mode", "public"),
        ("state", "SKIPPED"),
        ("document_requests", True),
        ("document_requests", 2),
        ("other_requests", False),
        ("other_requests", 1),
        ("csp_connect_blocked", False),
        ("fields_cleared", False),
        ("history_cleared", False),
        ("ciphertext_copied", False),
        ("ciphertext", "bad"),
        ("bot_pin", "different"),
        ("chat_pin", "0" * 64),
    ):
        with pytest.raises(ValueError):
            smoke.verify_receipt({**receipt, key: value})
    with pytest.raises(ValueError):
        smoke.verify_receipt({**receipt, "extra": True})


def test_offline_smoke_refuses_networked_or_wrong_identity_before_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke = _offline_smoke_module()
    for function in ("getuid", "geteuid", "getgid", "getegid"):
        monkeypatch.setattr(smoke.os, function, lambda: 10002)
    monkeypatch.setattr(smoke.socket, "if_nameindex", lambda: [(1, "lo")])
    smoke._offline_identity()
    monkeypatch.setattr(smoke.socket, "if_nameindex", lambda: [(1, "lo"), (2, "eth0")])
    with pytest.raises(RuntimeError, match="offline_network_namespace_unverified"):
        smoke._offline_identity()
    monkeypatch.setattr(smoke.os, "geteuid", lambda: 0)
    with pytest.raises(RuntimeError, match="offline_browser_identity_unverified"):
        smoke._offline_identity()


@pytest.mark.parametrize(
    "mode,key,target",
    [
        ("copy-bot", "botPin", "BOCA_TELEGRAM_EXPECTED_BOT_ID"),
        ("copy-chat", "chatPin", "BOCA_TELEGRAM_EXPECTED_CHAT_HMAC"),
    ],
)
def test_owner_pins_copy_separately_to_the_exact_protected_secrets(
    mode: str,
    key: str,
    target: str,
) -> None:
    _, _, fragment = _recipient()
    result = _run(fragment, mode=mode)
    assert result["copied"] == result[key]
    assert result["copied"] not in (TOKEN, CHAT, result["output"])
    assert result["token"] == result["chat"] == ""
    assert target in result["status"]
