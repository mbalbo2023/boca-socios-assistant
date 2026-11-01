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
- Current dormant runtime isolation: Compose project **boca-socios**; named volume
  and bridge network; nonroot, read-only container, dropped capabilities,
  CPU/memory caps, no exposed ports and no host Docker socket. A separate
  beta Compose candidate #171 is tested only on disposable runners, with TLS
  published to host loopback and its own private owner volume.
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
The own-application panel, entrypoint and local runtime libraries are integrated
in code, without host provisioning. The private Site v10 has a disabled D1
bridge and fails closed while host credentials/poller are absent. PR #181
integrated protected ciphertext-only Site custody phases, but no host phase ran.
Telegram
transport code is integrated but has no configured bot,
verified destination or real send. None of these is claimed live in the
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

