# A45-R245 — Parallel blockers and physical acceptance plan

Date: 2026-11-12 ART. Canonical source: issue #417, R244 comment 6836566308.
Start point: upstream `main=3e0d6e6adbf372316aa07685575a3ed3cf3c1a98`, 0 open PR at first reconciliation; main CI run 43310658142 and image security 43310658077 succeeded attempt 1. The known installed predecessor is `b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72`, attempt 43217075287, not the candidate. All development remains CODE_ONLY / physical deploy NO_GO.

## Invariants

- The only effectful remote operation is the existing protected Boca workflow, never a parallel SSH/Action or re-run of historical R186.
- Preserve PR0 immediately before release, immutable current-main controller+worker digests, R108 historical image, SQLite, passkey, Chrome session, IPC and site volumes, port 8443 and unrelated Docker workloads.
- Simulated interactions only. No real ticket purchases/reservations, queue bypass, disabled TLS or global Docker cleanup.
- Final receipt requires exact IDs and disk/inodes before/after under the same rootless lease; a typed callback or stale step summary cannot prove host state.
- Existing `requires_persistent_receipt=False` remains ineligible until an independent physical/authority review proves genuine protected adapters and acceptance.

## Independent development owners

1. **Release/auth** (`boca-r245-release`): replace release ZIP extraction-before-auth with bounded GitHub REST bytes verification, exclusive file creation and fsync, retain existing protected workflow and <=25 dispatch inputs. No host dispatch.
2. **Physical adapters** (`boca-r245-physical`): supply same-lease, exact-ID, before/after and postflight interfaces tied to real host measurements; reject synthetic callback evidence.
3. **Cleanup V2** (`boca-r245-cleanup`): durable Boca-only positive-ID cleanup, pre/post inventories and explicit R108 quarantine without unknown deletion or foreign resources.
4. **Panel/worker** (`boca-r245-dashboard`): SITE_URL native POST/passkey/CSRF, durable setting applied on demand, monitor truthful metadata, accessible START/STOP, offline contract tests and physical checklist.
5. **CI performance** (`boca-r245-speed`): time and classify redundant jobs/layers, evaluate cache hit/miss and path-aware feedback without changing required check names or protected release; do not reintroduce measured R244 slower concurrency or R240 safe6 polling.
6. **Integrator** (`boca-r245-integration`): independent review, select compatible commits, one PR and exact-SHA CI, final protected release/deploy only after evidence, #417 RCA/handoff.

## Critical gates and evidence

- Every owner follows TDD, targeted regression, Ruff/mypy/policy as relevant, commits in its isolated worktree and reports exact SHA plus limitations. No individual PRs, pushes or host modifications.
- Integrator verifies remote PR count and Actions, tests the combined code and independent reviews. Failed tests get reproducible RCA; no blanket skip.
- Before any physical mutation: current-main and dual-release bytes/digests and attempt-1 attestations, existing Action authorization, fresh Boca-only rootless inventory, same-lease witness and independent READ_ONLY host receipt. If any unavailable, remain NO_GO; do not repeat a failed operation.
- Protected physical test, if and only if eligible: one controller+worker release and one protected operation, postflight in same lease verifying passkey, loopback 8443, SITE_URL persistence, on-demand worker, monitor, SQLite and positive-ID cleanup. Retain exact artifact and run links.
- Update #417 with observed facts and missing checks. A green CI is not a green droplet.

## Implemented code-only checkpoint (before remote PR)

Five independent owner commits were cherry-picked into the R245 candidate.
Integrated `pytest -q -n 4` returned 7753 PASS, one local AF_UNIX/EPERM
skip and 34 passing subtests (48.75 s); Ruff check/format, mypy for all 187
source modules and policy passed. The updated Cutover ZIP pin was retested
after physical adapter integration while preserving historical R244.
An independent reviewer found no new P0 in the candidate but confirmed
effectful successor CLI is deliberately NO_GO. Separate parallel R246 work
owns versioned R188 current-pair custody and conservative failure cleanup;
neither is represented as shipped or as authorization for host deployment.
Proceed to one PR and GitHub-hosted checks, then document #417 without
claiming a completed droplet BETA.

