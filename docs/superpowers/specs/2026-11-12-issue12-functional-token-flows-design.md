# Issue #12 — two independent token flows (CODE_ONLY)

## Intent and boundaries

Keep the existing member enrollment, private passkey dashboard and synthetic
queue. Add an owner-only token monitor without invoking the legacy browser.
Recover the isolated member/sector work and queue-pass value object already
committed on 2026-11-11; do not replace them or touch #417's worker, IPC,
Docker, Actions or deployment artifacts. No token-bearing URL validation or
live Boca/Queue-it request is possible or authorized in this cut.

## Approaches considered

1. **New scraper/second dashboard:** duplicates the worker and opens an
   unreviewed site/credential path; rejected.
2. **Store tokens in the main SQLite:** unnecessarily persists bearer secrets,
   collides with migrations/legacy and may leak them to backups; rejected.
3. **In-memory observed-only contracts and private panel projection:** selected.
   Uses the existing member identities, owner passkey/session, CSRF and
   deliberate reveal/copy; no external traffic, persistence or default tokens.

## Queue-it observation

An authorized *future* observation source may supply a complete, unchanged
target URL containing exactly one nonempty `queueittoken` query parameter. A
pure parser extracts that parameter without DNS, HTTP, Queue-it validity
checks, admission claims or navigation; the URL remains unchanged for copying.
The observation is tied to a member/event/session identity, with
`not_observed`, `observed_unverified`, `expired`, `unknown` states. A bounded
ephemeral registry owns current observations; no token goes to logs, status
JSON, public preview, SQLite, Telegram or diagnostics. Ingestion from the
real worker is NOT wired by this PR.

## Boca authentication

A separately injected, explicitly authorized transport receives an existing
member's email and decrypted password from `boca.sqlite3` and the existing
external-key AES-GCM vault. The credential lookup is read-only and fails
closed on absent/revoked member, wrong key or malformed schema. Its login
result accepts **only** an actual caller-supplied provider JSON object with
nonempty `token` and `refreshToken` strings; it must not synthesize, infer
or assume these fields. Avoid guessed endpoints, payload fields and network
clients while the service is unavailable. The transport is disabled/absent
by default and no panel action invokes a provider login. An independent
ephemeral result channel can expose a successful response privately; a
failed/unavailable response remains unobserved, not simulated success.

## Private panel

Provide a separate `/monitor/tokens` view in the existing localhost:8443
application. Authentication and explicit `local-status:read` permission are
mandatory. The overview shows only safe status/identity metadata, never
secrets. Reveal/copy requires a same-origin POST, session CSRF, one-use
operation and `simulation:write` permission; the revealed page uses
no-store, escaped full values, accessible controls and intentional browser
clipboard buttons. No token in URLs, links, static HTML, logs or responses
to unauthenticated users. Two flows have distinct state, never exchange
tokens. Browser restart clears ephemeral observations. Unsupported or
unobserved states are explained truthfully.

## Non-goals and negative tests

- No real Boca login, Queue-it admission check, site traversal, CAPTCHA/WAF
  bypass, TLS disablement, queue skipping, ticket reservation, checkout,
  deployment, migrations or background worker.
- No change to legacy navigation lifecycle; it remains stopped unless the
  owner explicitly starts it using existing protected controls.
- Offline tests assert 401/403, origin/CSRF/replay rejection, exact copies,
  missing/duplicate query token rejection, no network, no raw secrets in
  summaries/representations and strict parsing of `token`/`refreshToken`.

## Delivery and reality check

One focused feature branch and PR to #12, with recovered commits and tests,
quality gates and an explicit handoff to #417. The integration owner must
later supply a verified observation source and the actual login transport,
plus an explicit sidecar SQLite provisioning step for member preferences.
CI green does not validate those sources, token URLs or the droplet.
