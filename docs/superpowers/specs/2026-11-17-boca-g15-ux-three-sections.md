# Boca G15 — Three-section owner dashboard UX design

**Owner:** Tincho; **source baseline:** `fc4b482053468b0b29004bdb663a82cfe1da585c` (G14 installed).
**Evidence:** [issue #417, G14 canonical handoff](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6961564016), [G15 UX audit](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6962319412), Samsung screenshot 17-Nov 18:50 ART, previously approved [G2 three-page spec](2026-11-16-boca-three-page-qa-design.md).

## Problem and scope

G14 renders five links in its primary navigation and seven permanent secondary links, despite G2 requiring **Control / Actividad / Configuración**. On the Motor A screen the last worker events are below the first viewport. The root Control page has no live event/queue/token projection; Activity repeats the motor summaries; `/configuracion` hides the already implemented direct Telegram form behind several unrelated pages. The screenshot shows `FAILED / WORKER_RECEIPT_UNVERIFIED`, 25 requested/0 created/0 active, but supplies no understandable reason or account of what was **not** observed. The inspection link is visible with no session because CSS can override `[hidden]`.

Only redesign **presentation, owner navigation and an authenticated `/ingresar` redirect**. No new engine, worker, monitoring backend, token source, table, API, authorization capability, mail sender, or actual Boca/Queue-it operation. Keep existing POST payloads, private endpoints, operation nonces, scope checks, CSRF, Origin, encrypted owner session, and G14 deployment as-is. No real bookings or queue bypass.

## Information architecture

1. **Control — `/control` and owner home `/`:** exactly two readily visible motor panels, A “Colas y tokens” and B “Navegadores y socios”. Each shows status, phase, last **real** observation, contexts requested/created/active, and concise evidence of site/event/queue/tokens/error. Start/Stop actions remain independent; B has its required active member selection; next-start browser distribution is under a labelled disclosure, not an operation count. A single contextual link leads to detailed Activity. No long worker chronology in Control.
2. **Actividad — `/control/actividad`:** the **common worker's** latest event and chronological feed at the top of the first viewport, with source, real event time, query time and stale/failure state. Below, A and B inspection areas link to session details and show browser/member, navigation, event/queue/token/auth evidence. Provide in-page A/B jump links, not more top-level menus. Reuse `/control/motores.json` and `/control/actividad.json` polling every five seconds; do not introduce parallel feeds or fabricate events. Technical detail can be disclosed.
3. **Configuración — `/configuracion`:** SITE_URL existing form, clear access to Socios (including add/edit), prominent direct **Telegram Token + Chat ID** setup at `/telegram/configurar` and separate status view, and secondary utilities in an explicit “Más herramientas” disclosure. Do not clone Telegram's existing form or grant read-only users write permissions. `PENDING_INSTALLATION` must never be phrased as connected/working.

Top navigation is exactly **three large, individually labelled targets**, consistently placed and showing `aria-current="page"`. Deep links `/control/colas`, `/control/socios`, `/telegram`, `/socios`, `/monitor/tokens`, `/comandos`, `/estado`, `/avisos`, `/avisos-oficiales` and the private session inspector stay functional with their existing authorization contracts, but do not become permanent duplicated menus. Guest/read-only variations retain allowed information and authentication calls to action.

## Login and accessibility

- Existing durable owner cookie is valid for a rolling 400-day browser window and persists over restarts. A GET `/ingresar` **with an already-authorized owner session** must redirect to Control instead of needlessly showing another passkey challenge; absent/revoked/limited sessions retain the current owner authentication boundary. This is a navigation fix, **not** removal or bypass of passkey verification for a new browser.
- The owner home `/` already renders Control with a valid cookie; use Control as the primary owner destination. No redirect loops from guest home/login.
- Samsung Android Voice Access, horizontal and vertical orientation, iPhone voice control, keyboard focus and zoom 200% are first-class. Visible tap targets at least 48px; no horizontal overflow on 1536×960, 800×1280, 412×915; only three permanent nav voice targets; proper focus, headings, landmark and status semantics; do not announce an unchanged status every five seconds.
- The shared `[hidden]` rule must actually suppress disabled/absent links and rows, including from keyboard focus and Voice Access. Change dashboard width only in a panel-scoped class so login and enrollment form layout is preserved.

## Truthfulness of status

- `WORKER_RECEIPT_UNVERIFIED` plus zero created means **browser opening was not confirmed; no page inspection has been accredited**. Never claim “no event”, “no queue”, “no token exists”, Docker failure or bad credentials on that basis. For Motor A snapshot, show 25 requested, 0 created, 0 active. Distinguish **not observed**, **observed absence**, **undetermined/failed**, and **observed token**.
- A fresh JSON fetch is not a fresh worker event. Display the time of the last real event and query separately; preserve last observation as **historical** when one endpoint fails. Two logical engines share a single physical worker; do not label common events as motor-specific.
- Tokens/URLs are only counted when real session evidence flags say so, and full values remain in pre-existing authorized private inspection. No raw tokens, credentials, URLs with secrets or private member information in logs, issue comments, Action output or general timeline.

## Acceptance and exclusions

Automated contracts: (a) nav 3/3 and accessible active state; (b) authentic A/B status refresh, no duplicate worker feed; (c) 25/0/0 failure renders honest cause and hides inspection; (d) known-session link appears and uses existing permission; (e) still-valid-cookie `/ingresar` redirect, invalid session passkey retained; (f) Telegram form reachable and owner-only, pending state truthful; (g) ACL/CSP/CSRF/Origin/nonce controls unchanged; (h) G14 restricted guest/status-only views unchanged. Visual/device QA must check four viewports, zoom and Voice Access after the code-only tests.

**Not included:** diagnosing the physical `WORKER_RECEIPT_UNVERIFIED` cause, starting a motor, installing Telegram, changing owner verification policy, modifying backend workers/blackboxes, touching Porota, new release or deployment. These require their own evidence and independent operation gate. BETA functional certification remains pending the user's live QA.
