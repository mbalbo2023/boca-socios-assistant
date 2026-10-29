# ADR 0011: Opt-in Chromium worker on a fake ticket journey

Status: Proposed for F3 issue #25, 2026-10-28.

## Problem and scope

The architecture needs an actual Playwright-driven browser boundary, but the
behavior and permitted automation of the real Boca Socios/Queue-it journey
remain unverified. A fake, deterministic UI is sufficient for the first
adapter contract and cannot be mistaken for an external reservation.

## Decision

- `boca_socios.browser.synthetic` contains self-contained HTML with exactly
  five artificial transitions: prequeue -> waiting -> admitted ->
  authenticated -> general_selected -> simulated_reserved. Its fake login
  has no credential form, real member identity or payment side effect.
- `SyntheticTicketScenario` accepts a structural `PagePort`, uses role-based
  buttons and stage assertions with finite timeouts, and never calls goto,
  fetch, Queue-it endpoints or HTTP clients.
- `SyntheticBrowserWorkflow` validates `TicketIntent(quantity=1)` before
  calling injected `IntentRepositoryPort`, `SyntheticBrowserPort` and
  `NotificationPort`. A `SimulationOutcome.RESERVED_IN_SIMULATOR` is **not**
  an externally confirmed ticket. Errors propagate; no success notice is
  emitted after a browser failure.
- `scripts/run_synthetic_ticket_flow.py` is an **opt-in, separate** lab smoke.
  It starts one headless Chromium context, blocks page requests, drives the
  embedded synthetic HTML and closes the context/browser on every path.
  The script has no URL/credentials/Queue ID arguments or runtime wiring.
- Playwright is not a dependency of the controller image or default CI.
  For this optional lab tool, use Playwright **1.64.1** (checked in official
  PyPI release), paired with its matching Chromium build.

## Intended integration contracts, not yet wired

- `IntentRepositoryPort` -> idempotent `Database.request_ticket` from PR #22,
  with a future durable single-flight reservation guard before live use.
- A future queue/identity abstraction -> `OfflineQueueSimulator` from PR #21
  for fake events; **not** a transport to Queue-it.
- `NotificationPort` -> safe, durable notification event in PR #20 and the
  persistent outbox task #16; no tokens, cookies or email values.
- Member onboarding/rotation/deletion -> separate protected private admin
  interface issue #17; **do not paste credentials in chat or public GitHub**.
- Combined branch integration, CI and cross-module regressions -> issue #24.

The synthetic HTML has an intentionally fixed order for testability. No
live Boca ordering, Queue-it configuration, pass transferability, account
eligibility or inventory behavior is inferred from it. The browser candidate
which receives an actual admission would need the original valid session;
live behavior requires a separately authorized observation and ADR.

## Optional laboratory verification

Only on a separate **nonproduction test environment**, with browser download
before any no-egress namespace/container confinement:

```sh
uv run --with playwright==1.64.1 -- python -m playwright install chromium
uv run --with playwright==1.64.1 -- python scripts/run_synthetic_ticket_flow.py
```

Expected output is a single JSON object containing
`"mode": "synthetic_only"`, `"result": "reserved_in_simulator"`, and a
local notice count of 1. No real confirmation number exists.

The Playwright route handler blocks **page** requests, not Chromium's
entire background network access. Strong no-egress verification requires
OS-level network isolation; the script is not automatically run in CI and
does not measure the shared droplet's capacity. See ADR 0008 and issue #11.
Do not deploy it to the Porota host, enable host IPC, or infer scalability.

## Acceptance and failure handling

Unit tests with a fake page exercise the exact UI order, failures, finite
timeouts, one logical intent per member/event and redacted notices.
Live checkout is intentionally absent, and a duplicate synthetic run may
produce another **fake** result; this is not an exactly-once purchase API.
Before any real interaction, require human review, confirmed site terms,
resource budget and a durable external-reservation reconciliation plan.

References: [Playwright BrowserContexts](https://playwright.dev/python/docs/browser-contexts),
[Playwright Locators](https://playwright.dev/python/docs/locators),
[Playwright Docker security](https://playwright.dev/python/docs/docker).
