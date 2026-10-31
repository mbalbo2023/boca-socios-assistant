# Boca Socios Assistant

Public, simulation-first engineering project for a consent-based Boca Juniors
membership and ticket-assistance workflow. This repository is owned by
**mbalbo2023** and remains isolated from **all unrelated applications and
infrastructure**.

> **Current release: FOUNDATION / SIMULATION ONLY.** No live integration,
> automated checkout, production deployment or Queue-it client exists yet.
> Repository creation, tests and image builds must not change any production host.

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
5. GitHub Actions is the only channel for any future authorized host operations.
   Production deploy is **not implemented** in this foundation.
6. No other project is a dependency, Compose service, networking peer, image
   registry, volume, credential source or deployment target.

## Architectural overview

- Runtime: Python 3.12, typed modules, no unsafe live action implementation.
- Persistence: dedicated SQLite WAL database with migrations and DB-level
  uniqueness; future orchestration must use explicit transactions.
- Security: AES-256-GCM credential vault with per-record random nonce,
  authenticated member-specific binding, external key volume, and key version.
- Runtime isolation: Compose project **boca-socios**; named volume and bridge
  network; nonroot, read-only container, dropped capabilities, CPU/memory caps,
  no exposed ports and no host Docker socket.
- CI: pinned checkout/setup actions, frozen dependency lock, lint, format,
  strict typing, tests, image build and repository-isolation checks.
- Delivery: small PRs, recorded agent technical review, exact-SHA status
  checks and immutable release artifacts. Future Boca-only host operations
  use the manual Actions workflow under the owner's standing direction once
  its exact-input and isolation gates are proven.

## Read before contributing

- [AGENTS.md](AGENTS.md): binding instructions for all coding agents.
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
instructions. Future host operations use only the gated Boca Actions workflow.

## Lifecycle

**Foundation → simulation → controlled test → recorded technical review →
gated Actions operation.** This initial work is foundation-only. A green CI
run is necessary but **not sufficient** evidence for deployment.

**Public-repository governance:** GitHub Free supports enforced branch rules
and free standard GitHub-hosted Actions runners on public repositories. The
ruleset must be **created and verified in GitHub Settings**; the existence of
this documentation never proves it is active. See GITHUB_SETUP.md.

