# Boca G16 — Compact, voice-friendly Activity sessions

**Owner:** Tincho. **Exact source baseline:** merged G15 main `aec2d37d793c96b3b063dab1ed10a030e6c35551`.
**Canonical continuity:** [issue #417](https://github.com/mbalbo2023/boca-socios-assistant/issues/417).
**Evidence:** G15 [CI run #44195329090](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/44195329090) PASS, [synthetic Chromium screenshot artifact #14377893915](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/44195329090/artifacts/14377893915), specialist UX review recorded in #417. G15 is **merged, not installed**; G14 is the last technically accepted physical deployment and must not be repeated.

## Demonstrated UX problems

1. `engine_view._SESSION_LABELS` contains **20** technical fields per session. The SSR `_session_rows` and JS `updateSessions` render all 20 immediately for each row. Three synthetic rows make Activity **6341px** tall at 800×1280 and **6824px** at 412×915. Fields repeat `Sin dato` and make Voice Access scrolling cumbersome.
2. With zero worker records, `private_ui.worker_activity` shows three equivalent absence messages in status, latest-event line, and the empty list. This does **not** prove that the external site has no event.
3. The page has multiple refresh actions for **distinct** sources. Their labels must identify worker history versus motor/session state.

This is a presentation/accessibility defect, not evidence of broken browser, missing external event or Telegram sender. No new data source, DB, worker, auth capability, endpoint or host action is needed.

## One-row-per-session design

- Each valid session remains one stable `li.engine-session[data-session-id="<UUID>"]` inside its existing motor-specific `ol`. Keep `h4[data-field=title]` with session ordinal and browser, and the existing permission-checked `a[data-field=inspect]` visible **without** expanding technical details.
- Keep an always-visible compact evidence summary using **only received fields** and their existing safe label functions: state, phase, observation timestamp, event evidence, queue evidence, access-link evidence and authentication response. Use `data-summary-field` to avoid colliding with the 20 existing `dd[data-field]` selectors; never show a complete queue token, bearer, URL query or credentials. When unavailable, say it is unverified; never equate no observation with observed absence.
- Put the original **20 distinct `dt/dd[data-field]` technical pairs** in **one native `<details>` per session**, closed by default. Its unique `<summary>` identifies session ordinal and browser, e.g. `Ver observaciones de sesión 1 · Chromium`; minimum target height 52px and usable through Enter/Space and Voice Access. No interactive link nested in `<summary>`.
- A closed/historical session's summary must explain that its observation is **historical**, even if it once observed a queue; a received authentication response does not prove logged-in state or a ticket. The Motor B member identity remains **member of the activation**, not falsely a unique member per browser session.
- New rows start collapsed. For rows retained across five-second polling, reuse their existing `li`, `details` node, `open` state, focus and inspector link; only update text if it changed. Removed UUIDs disappear. No extra GET or new browser session is created by expanding details.
- Preserve all current IDs, member labels, CSS semantics, safe escaped SSR rendering, CSP, owner ACL and per-session private reveal POST. Deep Motor A/B pages may keep the same detail component; do not create a second session renderer.

## Worker activity copy

- In the zero-record case, show **one** truthful message in existing `#worker-activity-status[role=status]`: `Todavía no hay registros del worker. Esto no permite concluir si hay eventos o cola en el sitio.` Keep `#worker-events` in DOM but empty, and keep `#worker-activity-observed` in DOM with `hidden` until a real event is received.
- When records appear, expose actual event time separately from latest query time. When a fetch fails, preserve the last sample as historical, clearly mark the failed query, and recover on the next valid sample; do not announce unchanged data every five seconds.
- Keep the distinct Chromium telemetry/advisory channel (it is not a duplicate of the absence of events). Label the two refresh controls by source: `Actualizar registro del worker` and `Actualizar motores y sesiones`. No change in endpoints or 5-second polling.

## Objective acceptance gates

1. **DOM:** one session LI and one native `details` per UUID; exactly 20 technical `data-field` terms per session, all accessible when open; summary + inspector visible when closed; no duplicate IDs or sensitive values.
2. **Keyed refresh:** preserve row identity, open state, scroll/focus and user-edited controls across polls; new/removed sessions work, no false claims for UNKNOWN/`WORKER_RECEIPT_UNVERIFIED`; zero sessions remain correctly empty.
3. **Accessibility:** native summary Enter/Space, 52px touch targets, focus ring, three global navigation destinations, no horizontal overflow, Voice Access names distinguish each session.
4. **Synthetic visual reduction at identical A_STOPPED/B_RUNNING three-session state:** initial fully **collapsed** full-page screenshot height **≤3170px** at 800×1280 (G15 6341) and **≤3412px** at 412×915 (G15 6824), both at least 50% shorter. Expanded details may make the page longer by user choice.
5. **Horizontal:** additionally run **1536×960** synthetic Chromium in the SAME single CI build, with no overflow, clipped controls or changed CSP. This is not a substitute for Samsung physical Voice Access/200% browser zoom, which remain unverified.
6. **Security/protocol:** all pre-existing SSR/JS DOM fields, private links, labels, owner permissions, POST/303/GET, CSRF/Origin/nonce, fixed fixtures, sha/CSP and offline fixture bounds remain intact. No outside network access or real booking in synthetic QA.
7. **Full candidate:** independent Root/Architecture/QA/Ops + UX reviews of one exact diff; one PR, one consolidated CI; no duplicated builds, release or droplet operations before integration/operational gates.

**Evidence publication microdecision:** The third Chromium screenshot must be included in the **same** existing CI `engine_ui_upload` artifact, which previously enumerated only two screenshots. After separate Architecture, QA, Operations and UX `GO_DESIGN`, a single path `engines-landscape-1536x960.png` is authorized in `.github/workflows/ci.yml`; the offline test must check that the named paths agree with `VIEWPORTS` and `report.json`. Do not add a job, another upload or another build. A test-driven defect found in G16 additionally requires deduplicating valid repeated session UUIDs in the **presentation projection only**; the underlying worker/session records are untouched.

## Explicit exclusions and handoff

No actual Boca/Queue-it browsing, login, queue bypass, ticket reservation, Docker permission fix, worker change, Telegram activation, data migration, PPI/Porota touch, or security-policy relaxation. G15+G16 should reach the droplet in **one future Boca-only GitHub Actions release/deploy**, only after post-merge CI and **separate** GO_OPERATION. Tincho's visual/device/functional acceptance is still required before calling the BETA certified.
