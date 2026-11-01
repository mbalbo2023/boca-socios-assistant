# Boca Socios Assistant

Public, simulation-first engineering project for a consent-based Boca Juniors
membership and ticket-assistance workflow. This repository is owned by
**mbalbo2023** and remains isolated from **all unrelated applications and
infrastructure**.

> **Current release: SIMULATION ONLY; BETA application not installed.**
> The manual Boca workflow inspected the host and prepared its dedicated
> rootless service (#120), then passed a read-only preflight for the dormant
> controller (#124). The protected stop-test #156/41272785626 subsequently
> stopped the dedicated daemon, with no Boca container left running and data
> preserved. Its `containers=0` field counts containers stopped in that run;
> exited containers, if any, remain preserved.
> None of these receipts is application readiness.
> The protected [image release 41312460820](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41312460820) published `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:67d8f59487632f117ec8c22d307481c1a9ba340502212d9bafe582309624301f`
> for the pre-change #214 main `8fdbec97262a525821eb87f3fbc27f1841a5d2ec`
> (manifest 13086161844). Earlier releases 41301618285/#208 and
> 41302342233/`3ef7aff8...` are historical. This is GHCR publication only,
> with no droplet pull/install. This code change requires a new exact-main
> release before a future host install; recheck the [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).
> The controller was never installed; no live login, Queue-it client or automated
> checkout is enabled. See [current integration status](docs/BETA_INTEGRATION_STATUS.md)
> and [continuity issue #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).

## Non-negotiable product rules

1. One requested ticket per verified member, **per match**. Database constraint:
   unique member + event, with ticket quantity exactly 1.
2. The database may store membership usernames and recoverable passwords, but
   password values are **AES-256-GCM encrypted** with a key held **outside**
   the database, GitHub repository and image. No credentials from chat are
   committed or imported automatically.
3. Multiple browser sessions are a future configurable capability, not proof
   of multiple Queue-it positions or a way to bypass admission rules.
4. No scraping spikes, Queue-it token fabrication, CAPTCHA bypass, proxy
   rotation or unauthorized endpoint testing. A simulator is used until a
   specifically authorized live observation is possible.
5. The dedicated manual GitHub Actions workflow is the only host-operation
   channel. Release/install code exists; its exact image and host gates must
   pass before an installation can be considered validated.
6. No other project is a dependency, Compose service, networking peer, image
   registry, volume, credential source or deployment target.

## Architectural overview

- Runtime: Python 3.12, typed modules, no unsafe live action implementation.
- Persistence: dedicated SQLite WAL database with migrations and DB-level
  uniqueness. Compose configures `/data/boca.sqlite3` in the persistent
  `boca-socios_boca_data` volume; this describes the intended mount, not proof
  that a Boca database or volume already exists on the droplet.
- Security: AES-256-GCM credential vault with per-record random nonce,
  authenticated member-specific binding, external key volume, and key version.
- Default dormant runtime isolation: Compose project **boca-socios**; named volume
  and bridge network; nonroot, read-only container, dropped capabilities,
  CPU/memory caps, no exposed ports and no host Docker socket. A separate
  beta Compose candidate #171 and protected `beta-install` #191/
  `beta-acceptance` #200 contracts were tested on disposable runners. The
  model was integrated in PR #224/ADR0091 with certificate-free HTTP only
  on Boca host loopback behind SSH, with a private owner volume; no droplet
  install occurred. The isolated one-use browser enrollment #225/PR #229
  uses a separate disposable named Docker staging volume for encrypted
  envelopes, not the private owner volume. Its protected host operation is
  integrated **in code only**;
  no real owner link, Chrome passkey or host installation has been verified.
- CI: pinned checkout/setup actions, frozen dependency lock, lint, format,
  strict typing, tests, image build and repository-isolation checks.
- Delivery: small PRs, recorded agent technical review, exact-SHA status
  checks and immutable release artifacts. Boca-only host operations
  use the manual Actions workflow under the [current scoped authorization](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326)
  and proof of exact-input and isolation gates. Infrastructure and business
  choices outside the approved delivery plan require options, a recommendation
  and the owner's decision; routine work within that scope proceeds.

## Functional BETA being prepared

The [delivery plan](docs/BETA_DELIVERY_PLAN.md) makes private member enrollment
(**Socios > Agregar socio**) part of acceptance, together with simulation
start/stop/status, durable local notices and restart/idempotency tests. Reuse
the existing encrypted enrollment service; tests use synthetic credentials.
The own-application panel, entrypoint, owner preflight #189, and local
runtime libraries are integrated in code, without application installation.
PR #208 integrated a separate protected, sealed owner passkey/TLS custody
path in code. Its synthetic checks do not enroll the owner or make the
tablet's exact HTTPS origin reachable; those remain deployment gates.
The protected `port-check` choice in the manual workflow tests only the fixed
host-loopback `127.0.0.1:8443` by a short bind/close; a FREE receipt does not
reserve a port or establish tablet access.
The later protected [run 41310958281](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41310958281)
on `main=3ec1096fb5dce8a01af5c8060f0be056bf44fb9d` reported
`FREE reserved=no` at that instant. The owner chose a private tablet forward
to the local panel on 8443. **Merged PR #224/ADR0091 supersedes
the HTTPS-localhost route:** the only proposed BETA Compose origin is
`http://localhost:8443` (WebAuthn RP `localhost`) through Termius SSH, with
**no device certificate/CA installation**. The actual
forward and physical passkey remain untested;
the single stored credential also needs cross-device proof for Android/iOS.
The former tablet-local TLS WebAuthn emitter (#215, ADR0089) remains only as
historical code and is **not** the owner's enrollment procedure. The requested
one-time activation URL must instead be served from the droplet on the same
isolated Boca port, with a privately delivered single-use key. The #225/ADR0092
core candidate implements the **unserved** `/activar#key=…` browser flow and
WebAuthn proof, producing a v2 encrypted envelope in a separate disposable
staging volume without mounting the owner's X25519 private key. The #225
`owner-enroll` operation, positive rootless/volume checks, offline
`install-staged` and mandatory same-job selective cleanup after attempted
staging were integrated in PR #229 into the **existing** protected Actions
workflow, with disposable-runner smoke tests. This code is not evidence of a
completed host run: the single-use private URL has **not** been delivered,
nor has physical Chrome passkey creation, private handoff, iOS use or owner
install been verified.
The #217 correction requires a discoverable passkey during local enrollment.
The chosen Android credential manager holds its private key, not a Chrome
cookie. The panel session cookie is temporary (15-minute idle, 8-hour absolute
limit, and invalidated by process restart); Android storage/sync and iOS use
still require physical proof in #209. Chrome localhost cookie acceptance must
be tested on the actual tablet; Safari support remains unverified. No renewal
or generation of TLS certificates is required for the chosen SSH-only route.
Site decommission is deferred until the local replacement is validated.
Merged PR #220 (RCA #219) strengthens the existing Boca-only failed
deploy recovery: a failed staged `beta-install` invokes immediate selective
cleanup via the same protected Actions job. It can remove only verified
disposable controller/network/image/staged-Compose artifacts, while preserving
owner/key/data volumes and retaining the failed deploy status. This is
integrated code/test behavior, **not** proof of a cleanup or BETA installation on the droplet;
unknown or interrupted cleanup remains NO_GO and forbids blind retries.
The entirely synthetic Chromium journey (#25) and its on-demand and Unix IPC
contracts (#227, ADR0093/0094) are integrated for offline tests, never real
Boca navigation. This code cut adds optional `BOCA_BROWSER_BACKEND=ipc` for a
separately isolated, UID10002 Browser Worker with a local Unix socket;
**the default `off` keeps the existing in-process simulation stub**. The
opt-in setting has no usable worker until a separately reviewed image,
Compose/host isolation and selective cleanup are approved, released and
installed. It never enables real tickets or login. Chromium sandboxing,
network isolation, 30-second coordinator budget and worker identity gates
are code-level safety requirements, **not** proof of deployed safeguards.
The command/restart/notification regression suite (#228/PR #231) is merged
and synthetic; Telegram #168 still needs dedicated bot custody, verified
destination and a protected one-message host/owner receipt. Both are
operationally unverified, and no other droplet workload may be affected.
The private Site v10 has a disabled D1 bridge and fails closed while host
credentials/poller are absent. PRs #181/#196 integrated protected ciphertext
custody and global daemon inventory checks, but no Site host phase ran.
Telegram's opt-in worker #188, safe stop recognition #194, sealed helper #199,
protected schema/custody #203 and one-shot Bot API test #204 are integrated,
with no host dispatch, configured bot, verified destination or real send.
The offline #25 Playwright CI smoke (PR #232), #227 synthetic adapter and
IPC/STOP guards (PRs #233/#236), #228 restart/notice regressions (PR #231),
and #168 Telegram identity pinning (PR #230) **are merged as code/tests**.
This new optional Browser Worker runtime/image cut remains a separate
unmerged candidate until its own exact-SHA CI and review. None proves a
running browser sidecar, real Telegram dispatch or BETA installation on the
droplet; see the [status table](docs/BETA_INTEGRATION_STATUS.md).

`/data/boca.sqlite3` in `boca-socios_boca_data` is the delegated logical storage
decision for this BETA, not proof that a database exists on the droplet. Actual
global location remains UNVERIFIED; existing data must never be replaced by
inference. Real credentials and Boca actions remain outside this delivery.

## Read before contributing

- [AGENTS.md](AGENTS.md): binding instructions, including Rule 84: keep affected
  documentation factual and current in the same PR and reconcile continuity
  before closing the task.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): modules and threat boundaries.
- [docs/DEVELOPMENT_POLICY.md](docs/DEVELOPMENT_POLICY.md): branch/PR/CI gates.
- [docs/SECURITY.md](docs/SECURITY.md): password, key and session policy.
- [docs/OPERATIONS.md](docs/OPERATIONS.md): Docker isolation and deployment gate.
- [docs/ROADMAP.md](docs/ROADMAP.md): bounded development backlog.
- [docs/GITHUB_SETUP.md](docs/GITHUB_SETUP.md): branch rulesets and GitHub settings.
- [docs/QUEUEIT_AUDIT.md](docs/QUEUEIT_AUDIT.md): known vs. unknown Boca infrastructure.

## Development check

The canonical CI command sequence (from a separate development environment):

~~~sh
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
uv run python scripts/check_repo_policy.py
~~~

No manual terminal commands on a production host are required by these
instructions. Host operations use only the gated Boca Actions workflow.

## Lifecycle

**Foundation → simulation → controlled test → recorded technical review →
gated Actions operation.** Offline and local components and the private Site
are integrated in different scopes, but the installed controller remains
absent. The Compose controller still initializes storage and waits with
its engine off. A green CI run is necessary but **not sufficient**
evidence for deployment or a functional BETA.

**Public-repository governance:** GitHub Free supports enforced branch rules
and free standard GitHub-hosted Actions runners on public repositories. The
ruleset must be **created and verified in GitHub Settings**; the existence of
this documentation never proves it is active. See GITHUB_SETUP.md.

