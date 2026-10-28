# Queue-it / Boca Socios: evidence and performance research (2026-10-28)

**Scope:** public-documentation research and a no-traffic architecture proposal.
The findings below are not a live-session trace or evidence that Boca has enabled
any particular Queue-it configuration. This repository must not automate queue
evasion, issue Queue-it credentials, guess access passes or create artificial
visitor identities. No real credentials, queue links, cookies or token values
belong in source control, issues, Actions logs or notifications.

## Evidence hierarchy

1. **Official Queue-it:** product behavior and documented integration options.
2. **Observed in public Boca client:** the separately documented, publicly
   available JavaScript integration in [QUEUEIT_AUDIT.md](QUEUEIT_AUDIT.md).
3. **Unknown for Boca:** vendor configuration, identity binding, actual login
   order, token TTL, retry semantics, anti-bot policy and inventory endpoints.

Do not promote a Queue-it capability or forum anecdote to a fact about Boca.
The October 2026 screenshots of third-party tools are unverified marketing or
user reports, not proof that hundreds of independent queue positions work.

## Queue credentials: three distinct objects

| Object | Official purpose | What it does **not** prove |
| --- | --- | --- |
| **Enqueue Token** | Optional signed, sometimes encrypted entry credential created by a **site operator/integrator**; may bind a visitor key to a waiting room. | It is not a pass through the queue, and the assistant is not an issuer. |
| **Queue ID** | Identifies a visitor's queue instance; a pre-queue can assign it before any numerical position exists. | It is not a reservation, ticket or necessarily an independent queue position when identities are linked. |
| **Connector/return token (`queueittoken`)** | Signed proof returned after Queue-it permits access; a server-side connector validates it and may set `QueueITAccepted...` cookie. | It does not log in to Boca, hold inventory or confirm payment. A token can represent `safetynet`/`idle`/`disabled`, without a wait. |

Queue-it describes identifiers such as `ti` on entry tokens, `q` on queue
passes, and a configurable unique visitor key. The exact contents, allowed
headers, cookies and lifetimes are **integration-specific** and must not be
reverse-engineered into forged credentials.

References:

- [Official Queue-it Queue Token JavaScript SDK](https://github.com/queueit/QueueToken.V1.JavaScript)
- [Official server-side connector documentation](https://github.com/queueit/Documentation/blob/main/serverside-connectors/README.md)
- [Queue-it bot/abuse-management options](https://queue-it.com/developers/bots-abuse-management/)
- [Queue-it mobile integration technical paper](https://queue-it.com/media/m4pjcxau/queue-it-mobile-app-integration-white-paper.pdf)

### HTTP integration distinctions

Queue-it mobile/API documentation illustrates `x-queueit-ajaxpageurl` on a
request, `x-queueit-redirect` on a response and `x-queueittoken` or URL
`queueittoken` for a permitted return. A response may be `HTTP 200` yet
signal **redirect to waiting room**, not successful business operation.
The exact Boca client string `queueittoken` should be recorded with its
request/response direction, and not presumed to follow every SDK example.

The public Boca JS mentions an `errorCode=50000` branch. Queue-it's
September 2026 technical paper lists waiting-room error IDs **1 through 11**,
not `50000`. The origin of Boca's `50000` is **unknown**: it could be an
application or gateway convention. It must not be relabeled as an official
Queue-it error without a redacted, authorized HTTP trace.

References:

- [Queue-it Technical Integration White Paper, pp. 38–40](https://queue-it.com/media/qwpmrzxi/queue-it-technical-integration-white-paper.pdf)
- [Queue-it Mobile App Integration White Paper, p. 12](https://queue-it.com/media/m4pjcxau/queue-it-mobile-app-integration-white-paper.pdf)

## Queue order: random pre-queue versus FIFO

| Situation | Queue-it documentation | Boca evidence |
| --- | --- | --- |
| Visitors in a **scheduled pre-queue** | Random order is assigned at opening; entering much earlier does not confer a better rank among the randomized set. | Screenshots show pre-queue and countdown; actual ranking algorithm unverified. |
| Visitors joining **after** opening | Normally FIFO. | Unverified for the specific event. |
| Queue triggered by unexpected traffic | Can be FIFO without a scheduled pre-queue. | Unverified for Boca. |
| Invite-only/identified rooms | Operator can limit multiple IDs using a unique visitor identifier. | No proof whether Boca enables this per account, member ID, cookie or event. |

References:

- [Queue-it Scheduled Waiting Room](https://queue-it.com/product/scheduled)
- [Queue-it Virtual Waiting Room guide](https://www.queue-it.com/blog/virtual-waiting-room/)
- [Queue-it Technical Integration White Paper, p. 40](https://queue-it.com/media/qwpmrzxi/queue-it-technical-integration-white-paper.pdf)

Queue-it explicitly advises buyers to use one browser/device, avoid multiple
tabs for the same sale and not refresh the waiting page. Creating many browser
contexts can consume memory and trigger abuse defenses without yielding extra
valid ranks. **There is no evidence-based multiplier for position or available
ticket inventory.**

## State machine proposal (offline first)

Each authorized member/event has one durable purchase intent. Queue sessions
are *observations* and never equal extra ticket quantity.

| State | Evidence required for transition |
| --- | --- |
| `PREPARED` | Consent, eligibility metadata and valid local intent. |
| `PREQUEUE` | Official waiting page indicates pre-queue; no queue rank yet. |
| `QUEUED` | Authorized waiting state with queue identifier/status. |
| `QUEUE_ADMITTED` | Validated passage via normal site integration, or documented idle/safety-net flow distinguished in metadata. |
| `BOCA_AUTHENTICATED` | App confirms member authorization; this can occur **before** `PREQUEUE` depending on actual site flow. |
| `RESERVATION_PENDING` | A single idempotent logical operation is in flight. |
| `CONFIRMED` | External booking confirmation obtained and reconciled, not merely a Queue-it pass or HTTP 200. |
| `UNKNOWN_PENDING_RECONCILIATION` | Timeout or ambiguous outcome; **do not auto-repeat purchase**. |
| `FAILED`, `EXPIRED`, `CANCELLED` | Explicit evidence, recovery policy and audit record. |

The exact sequence between `BOCA_AUTHENTICATED` and `PREQUEUE` remains an
integration question. Model it as independently evidenced states instead of
hard-coding an unverified login-first or queue-first order.

At the local DB boundary, enforce uniqueness `(member_id, event_id)` and
quantity one; return existing intent on retries. This **cannot** guarantee
at-most-once checkout at Boca without an external idempotency contract and a
reconciliation mechanism.

## Performance: reliable operations, not queue-rank manipulation

Our attainable improvements are in readiness, session continuity, fast
notifications, conflict-free state transitions and recovery after interruption.
Examples: preflight member eligibility, an event timer, keeping the original
authorized page state, no unnecessary refresh, bounded reconnect/backoff,
correct interpretation of redirect headers, and a manual purchase handoff
when admission is confirmed. Do **not** spam the service or change IP/device
identities to collect Queue IDs.

### Worker design options

| Model | Pros | Risks | Decision |
| --- | --- | --- | --- |
| Several tabs in one browser context | Lowest apparent overhead | Shared cookies, localStorage and account identity; cross-member confusion | Reject for distinct member accounts. |
| One Chromium process; independent `BrowserContext` per authorized session | Isolation of cookies/storage with lower process overhead; easier lifecycle control | Single process failure domain; incremental CPU/RAM/PIDs still unknown | Preferred **future benchmark** on synthetic local pages. |
| One Chromium process/container per session | Greater fault/resource isolation | Highest overhead, cost and orchestration complexity | Require measurements and an explicit need. |

Playwright calls BrowserContexts isolated and inexpensive to create, but does
not publish an unconditional RAM-per-context figure. No capacity claim may
be made before measuring with 1, 2, 4 and 8 local synthetic contexts.
Each benchmark must record memory (current and peak), CPU throttle, PIDs,
`/dev/shm`, browser errors, event-loop lag and p95/p99 latency. Stop the
experiment at measured resource limits.

The existing `compose.yaml` only budgets a **lightweight controller**; its
256 MiB limit is not a browser-worker sizing estimate. Docker recommends
resource caps. Playwright's `--ipc=host` advice for Chromium conflicts with
the project's host isolation requirement; investigate a container-private
`shm_size` in a separate controlled environment before choosing any option.
Do not change host IPC or containers belonging to other projects.

References:

- [Playwright BrowserContexts](https://playwright.dev/docs/browser-contexts)
- [Playwright Docker](https://playwright.dev/python/docs/docker)
- [Docker Compose service memory and `shm_size`](https://docs.docker.com/reference/compose-file/services/)
- [Docker resource constraints](https://docs.docker.com/engine/containers/resource_constraints)

### Synthetic tests before any live integration

1. Deterministic queue model with seedable random pre-queue, post-opening
   FIFO and **configurable** uniqueness by member ID. This is a model, not
   proof of Boca's real configuration.
2. Test independent member intents, duplicated internal messages and
   concurrent workers; assert zero duplicated *logical* ticket intents.
3. Fault-inject 429/5xx/timeouts, disconnects, expired sessions, controlled
   restarts and ambiguous checkout responses into a local fake service.
4. Benchmark local Chromium BrowserContexts and watch controller + worker
   resource isolation, no Boca/Queue-it traffic.
5. Ensure that queue state, credentials and access passes are never printed
   in logs, pull requests, screenshots or Telegram notifications.
6. Require a human-governed change request before enabling any actual login,
   queue navigation or reservation adapter; confirm applicable terms and
   service capabilities then.

### Measuring alert quality

Prefer a durable outbox: record event -> enqueue notification -> retry with
bounded exponential backoff -> mark API acceptance. Delivery to Telegram is
*not* proof of user reading it. A proposed, unvalidated target for critical
alerts is p95 <= 10 seconds and p99 <= 30 seconds from internally detected
event to Telegram API acceptance when Telegram is healthy. Only report actual
performance from synthetic tests; respect `retry_after` when returned.

References: [Telegram Bot API](https://core.telegram.org/bots/api),
[Telegram FAQ](https://core.telegram.org/bots/faq).

## Explicit decision gates

- **GO now:** queue simulator, idempotent DB operations, safe local credential
  enrollment, governance CI, synthetic browser benchmarks and accessibility.
- **NO-GO today:** many live sessions, token harvesting, queue-position claims,
  bot-defense bypass, live checkout, deployment to the shared host and
  collection/publication of session secrets.
- **Evidence missing:** redacted legitimate live flow showing Boca's precise
  login/queue order and the underlying response of `errorCode=50000`; event
  rules for member eligibility and identity uniqueness; provider-accepted
  reservation idempotency; measured worker resource budget.

**Source policy:** forum posts and commercial screenshots are hypotheses only;
peer-reviewed/current official vendor specifications determine implementation
choices. This document should be revalidated before every live event.
