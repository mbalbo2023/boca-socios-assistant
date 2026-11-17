# Boca G14-T Direct Telegram Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tincho configura token y Chat ID desde 8443 con un formulario sencillo, sin recibo X25519; el backend guarda un staging privado pendiente de instalación y el emisor permanece detenido.

**Architecture:** Un nuevo adaptador de stage directo, aislado del V2 existente, acepta exactamente un par token/chat y lo escribe una sola vez en DATA Boca. El panel privado valida sesión, Origin, CSRF y one-use; no transmite secretos por URL, GitHub ni logs. Una operación protegida y separada de GitHub Actions podrá instalar el par en la custodia final, con recibo ligado a source/UID/lease y sender OFF. No convertir el POST en una activación.

**Tech Stack:** Python/WSGI, SQLite owner sessions, POSIX dirfd/atomic stage, pytest, GitHub Actions Boca.

**Spec:** `docs/superpowers/specs/2026-11-17-boca-telegram-direct-private-configuration.md`.

## Global Constraints

- Interfaz `http://localhost:8443` owner-only, sin X25519 ni recibo/huella en el flujo directo; token+chat ID en BODY de POST exclusivamente.
- Mantener sesión/passkey de acceso, Origin, CSRF, operación one-use, validadores existentes y redacción; no introducir passkey adicional para simplemente guardar.
- Escenario `SIMULATION_ONLY`, Telegram sender OFF; sin llamadas Telegram Bot API desde el formulario, sin reservas reales, sin modificaciones Porota.
- Staging DATA validado UID y 0600 exclusivo, sin symlinks/overwrite; instalado final en volumen Telegram exclusivamente por Action protegida Boca bajo lease, nunca RW desde controlador.
- V2 anterior preservado, no afirmar instalado/conectado hasta obtener evidencias específicas; no secrets en HTML, log, excepción, diff, Actions summary, artefactos, URI o clipboard automático.
- La excepción explícita del titular al cifrado de staging consta en la especificación; no convertir este detalle interno en bloqueo del formulario. No relajar identidad, no filtrar secretos. La custodia directa tiene que usar nombres propios, no `bot_token`/`chat_id` que `telegram_bootstrap.verify()` V1 marcaría CONFIGURED sin esperar nuestro commit.

## Review Focus

- HTTP GET viejo `/telegram/emparejar` desde marcador de tablet: mostrar formulario nuevo si está habilitado; no dejar entrada grisada (tests Task 1).
- POST con cookie/sesión/Origin/CSRF/op inválido, concurrente o replay: 401/403/409 sin escribir (tests Task 1).
- Excepción de disco, archivo preexistente, symlink, modo incorrecto: respuesta redactada NO_GO y preservación de contenido (tests Task 1).
- Stage válido no modifica volumen custodio ni activa sender ni emite petición Telegram; estado `PENDIENTE_INSTALACIÓN` real (tests Task 1).
- Workflow host si tiene identidad/fuentes parciales/UID/marker distintos: fail closed, nunca repetir ni instalar/activar a medias (tests Task 2).

---

### Task 1: Owner form and private direct stage (CODE_ONLY)

**Files:**
- Create: `src/boca_socios/panel/telegram_direct_staging.py` (fixed stage schema, redacted request/receipt and exclusive local storage)
- Modify: `src/boca_socios/panel/telegram_setup_ui.py` (new simple form function without changing V2 script contract)
- Modify: `src/boca_socios/panel/private_http.py` (GET+POST exact private endpoint using existing session/one-use)
- Modify: `src/boca_socios/runtime.py` (direct stager derived from verified private BETA origin and existing DATA identity; **no new settings toggle**); `src/boca_socios/config.py` only if a tested schema necessity emerges, not as a flag
- Test: `tests/test_telegram_direct_owner_stage.py` (new)

**Interfaces:**
- Consumes: `telegram_bootstrap._token/_chat`, `OwnerSessions.reserve/finish`, `_form(environ,expected=...)`, existing `_response/_error`, `Settings.telegram_pairing_stage_mode`.
- Produces: `DirectStageRequest(bot_token: str, chat_id: str, source_sha: str)` repr=False; `DirectStageReceipt(state='PENDING_INSTALLATION')`; `stage_private_direct_telegram(path: Path, request: DirectStageRequest) -> DirectStageReceipt` producing `boca_telegram_direct_stage_v1.json` exact canonical fields `version=1,purpose=boca-telegram-direct-owner-stage-v1,repository=mbalbo2023/boca-socios-assistant,uid=10001,source_sha,stage_id(64hex),staged_at,bot_token,chat_id`; `source_sha` sourced exclusively from `Settings.source_sha`, never client. POST `/telegram/configurar` redacted, GET owner-only. Keep old V2 route only when direct staging not enabled; GET `/telegram/emparejar` points to simple config when direct is enabled.

- [ ] **RED tests:** two editable inputs and big Guardar button, no huella; **Inicio y `/telegram` deben llevar al formulario directo sin copy del recibo cifrado**; invalid credentials/CSRF/Origin/replay fail without write; private positive chat ID and bot ID canonical in `(0,2**52)` (negative/group, leading zero, zero, oversized rejected); stage includes correct current source SHA/stage_id/time and rejects source mismatch; `Referrer-Policy:same-origin` with a real native POST Origin correct and wrong-origin 403; `O_NOFOLLOW|O_EXCL` and fsync atomic staging; duplicate direct/V2 stage/symlink/permission failure; **temp huérfano antes de `link`, después de `link`/antes de `unlink` y antes de fsync del directorio => NO_GO sin segundo POST ni borrado automático**; redacted response; sender/Telegram not invoked; owner status pending. Use only synthetic token+ID.
- [ ] **Observe RED:** `.venv/bin/python -m pytest -q tests/test_telegram_direct_owner_stage.py` must fail for absent feature.
- [ ] **GREEN implementation:** implement narrowly, limit field sizes before `reserve`, stage exactly once, never echo/repr secrets. Preserve V2 APIs and tests; do NOT add a toggle/manual flag, and do not interpret `encrypted-only` as authority for plaintext: eligibility must follow verified BETA localhost owner path and DATA identity alone.
- [ ] **Verify:** `.venv/bin/python -m pytest -q tests/test_telegram_direct_owner_stage.py tests/test_telegram_pairing_ui.py tests/test_telegram_setup_ui.py tests/test_private_http.py` (if last filename absent, select existing private HTTP tests); run format/lint. Expected PASS.
- [ ] **Commit:** implementation and new test, no Docker/host writes.

### Task 2: Read-only contract and host install-direct (separate GO_OPERATION later)

**Files:**
- Create: `src/boca_socios/telegram_direct_custody.py` (read/verify direct stage, source/UID/lease checks, exclusive token/chat writes and commit-last marker)
- Modify: `src/boca_socios/telegram_maintenance_contract.py`, `src/boca_socios/telegram_maintenance.py`, `src/boca_socios/host_telegram_backend.py`, `src/boca_socios/host_telegram_cli.py` (operation allowlist/dispatch/receipt), `scripts/build_protected_telegram_bundle.py` (closure/INSTALLED_SOURCES), `.github/workflows/boca-first-deploy.yml` (dispatch options, source/ancestry, budget, bundle, exec, expected_state and separately gated operation; no secret input/summary)
- Test: `tests/test_telegram_direct_custody.py` (new, offline no-network)

**Interfaces:**
- Consumes: stage schema/receipt Task 1, protected host Boca lease + existing path/UID identity gates, existing exclusive token/chat writer. Does NOT consume env input with token or ID.
- Produces: redact-only receipt `INSTALLED_SENDER_OFF` after final marker; independent schema/host observer for pending/installed state; never reconfigure existing V2 custody silently.

- [ ] **RED tests:** read exact stage (source SHA, stage_id, age, DATA UID/inode), reject stale/source/UID/symlink/duplicate/partial paths and wrong lease; accept only empty/explicitly recognized pre-existing KEY-only custodian state, reject unknown V1/V2 token/chat/marker. Helper no-network with DATA RO + Telegram RW, UID10001, logger none; no stdout/argv/env secrets. Test injection of crash after first token write, after chat write and before/after final marker; no valid receipt, no retry/overwrite. **Escribir en nombres exclusivos DIRECT, nunca los `bot_token`/`chat_id` del lector V1**, que darían falso CONFIGURED tras una caída previa al commit; no adaptar sender ni verificador V1 para aceptar direct sin marcador. Verify both direct files via O_NOFOLLOW/fstat/mode0400/nlink1 before final marker; verify-direct read-only checks source/stage/bot binding and full pair independently, no falsely healthy mere marker. Model stage cleanup after success: if DATA mounted read-only, separate exact authorized cleanup; on cleanup failure report `INSTALLED_SENDER_OFF_STAGE_CLEANUP_PENDING`, do not delete custody/retry install. Workflow/bundle closure and fixed allowlist cover operation with no secret input, sender OFF always.
- [ ] **Observe RED:** `.venv/bin/python -m pytest -q tests/test_telegram_direct_custody.py` fails for absent helper.
- [ ] **GREEN:** smallest fixed host adapter/Action branch (no dynamic arbitrary commands). Reuse `resolve_installed_context` and lease/identity guards; keep V1/V2 immutable and ensure activation remains separately gated; if reader/sender cannot trust direct marker yet, report NOT_ACTIVATABLE rather than claiming connected. Any ambiguous commit/ACK => INDETERMINATE, preserve files and stop.
- [ ] **Verify:** targeted custody suites, workflow YAML and host security tests, full project suite; commit with evidence.

### Task 3: End-to-end contract review and owner status

**Files:**
- Modify as necessary: `src/boca_socios/panel/private_ui.py`, `src/boca_socios/panel/private_http.py`, `tests/test_telegram_direct_owner_stage.py` (only if Task 1 status not already visible), related documentation.

**Interfaces:**
- Consumes: Task 1 staging state + Task 2 host receipt; Produces UI states `Sin configurar`, `Pendiente de instalación`, `Instalado — emisor detenido`, `Verificado — emisor detenido` (only with evidence), `Activo` (only sender evidence).

- [ ] **RED tests:** old Telegram menu links to working direct configuration, status never exposes token nor confuses stage with connected/active; 800px Samsung and keyboard focus.
- [ ] **GREEN minimal changes**, check source compatibility and run fast + full CI suite.
- [ ] **Commit, independent code review, one consolidated PR**. No release/APPLY until complete CI/security, four reviews and physical resource preflight.

## Runtime boundary

The design/coding GO is distinct from host GO. For G13, run #1213 returned TRANSPORT_UNVERIFIED; old observer has historical coordinates. Do not run telegram-prepare/install/activate without a freshly authorized Action contract for installed source/CIDs. This plan never treats 8443 HTTP200 as proof of custody, Telegram chat verification or delivery.
