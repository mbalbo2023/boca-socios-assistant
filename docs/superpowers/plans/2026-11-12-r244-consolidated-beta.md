# R244 — Consolidated Boca BETA delivery plan

> **For agentic workers:** Implement with scoped worktrees, tests first, independent review, and one protected release transaction. Record every actual run/SHA/receipt; never infer physical success from source checks.

**Goal:** Replace the current Boca controller+worker as one authenticated pair, prove the physical private BETA on port 8443, and reduce redundant builds without weakening release provenance.

**Architecture:** Integrate the R243 successor actor/monitor and R242 dual-release authenticator into the existing protected Boca Action. Maintain the same rootless lease, immutable source/release/retained-resource identities, journal and bounded Boca-only cleanup. The historical R186 operation and original NO_GO receipt are immutable.

**Tech stack:** Python 3.12, pytest, Ruff, mypy, Docker/Compose rootless, GitHub Actions/GHCR, passkey-protected private panel.

**Specs:** `docs/ADR/0240-reusable-upgrade-unwired-contract.md`, `docs/ADR/0242-token-monitor-readonly-live-metadata.md`, `docs/ADR/0209-r108-attested-historical-quarantine.md`, issue #417 R243. Existing R240 candidate is an independent CI optimization, not deployment authority.

## Global constraints

- Boca-only; do not touch Porota, host-level services or unrelated networks, volumes, ports or images.
- No real tickets, reservations, purchases, Queue-it bypass, live navigation, or TLS downgrade.
- Preserve SQLite, session/passkey/key, IPC/SITE volume creator pins and R108 forensic image.
- No reuse of R186/one-shot predecessor `03df9a...` or old attempt `42806447101` as the current pair.
- The existing `boca-pair-upgrade-apply` is the only permitted selector; no direct host shell or new deployment workflow.
- 0 open PR before the final release; one reviewed exact-main SHA, dual release manifests, one protected APPLY, no blind retry.
- Unknown ownership, missing same-lease evidence, missing cleanup receipt or stale source always remains NO_GO.
- Include source-visible Queue-it/Boca token contracts; unavailable external providers are NOT a release gate, and absent tokens are never fabricated.

## Review focus

1. Installed pair differs from historical predecessor: refuse a stale single-use recipe before any mutation.
2. Old resources survive temporary 2-to-4-to-2 CID topology: require only journal-listed Boca IDs, stable volume/network pins, no foreign peers.
3. Interruption before/after commit: rollback only precommit; terminal receipt remains NO_GO on lost ACK/uncertain fsync.
4. Cleanup still retains active images, stage/config, SQLite/passkey/Chrome, unknown resources and R108; no global prune.
5. Dashboard on Android/Chrome: same-origin POST and one-use controls, voice-distinguishable actions, truthful `NOT_CONNECTED` state, UTC observation metadata.

## Task A — Authenticated reusable installation (exclusive release/wiring ownership)

**Files:** successor actor/journal/release-auth bridge/CLI, protected bundle/bootstrap, `.github/workflows/boca-first-deploy.yml`, integration tests.

- [ ] Add a failing test for stale predecessor or unauthenticated release being refused before host effects.
- [ ] Verify RED for lack of same-lease witness and missing durable receipt.
- [ ] Consume genuine current-main release job, two ZIP artifacts and digests on Actions; transfer only bounded proof via authenticated bundle, never GH token to host.
- [ ] Wire only the existing protected selector and journal O_EXCL/fsync, preserving R186 history.
- [ ] Verify RED/GREEN for 2→4→2 graph, replay, wrong run/SHA, interruption and terminal ACK.
- [ ] Run ZIP under isolated Python and assert exact imports/allowlist/size before considering interlock removal.

## Task B — Scoped cleanup V2 (exclusive cleanup ownership)

**Files:** separate V2 helper and own tests; keep existing historical cleanup untouched unless reviewed separately.

- [ ] Test positive immutable ID ownership and references against independent before/after inventories.
- [ ] Test R108 `KNOWN_HISTORICAL_QUARANTINE` retention and reject unknown or foreign resources.
- [ ] Produce a bounded canonical receipt including disk/inode counts, exact actions, and same-lease witness.
- [ ] Integration cannot map partial image-only evidence to installation `ACCEPT`.

## Task C — Private dashboard usability (exclusive panel ownership)

**Files:** `panel/private_*` and corresponding UI tests.

- [ ] Test SITE_URL POST under passkey/origin/CSRF/nonce and pending-until-worker-restart indication.
- [ ] Test token monitor 5s refresh, no raw tokens in default JSON, UTC timestamp, clear disconnection.
- [ ] Test voice-distinguishable action labels, idle→start→stop indicators with no synthetic success claims.

## Task D — Faster CI/CD (exclusive CI ownership)

**Files:** CI/security workflows, small attestation scripts/tests, caching plan.

- [ ] Verify R240 removes exactly the duplicate main security rebuild pair without removing Trivy evidence.
- [ ] Bound wait by real CI job result rather than treating delay, cancellation or missing run as GREEN.
- [ ] Check BuildKit/GitHub Actions cache scopes and layer reuse for each role, with immutability and final scan.
- [ ] Investigate four-build lifecycle (PR2+release2) and conditional one/zero PR builds for scoped changes; document SHA/branch-protection dependencies before implementing.

## Task E — Final integration and physical acceptance (one coordinator)

- [ ] Integrate non-overlapping diffs; run full local suite, Ruff/format/mypy/policy and ZIP/dry-run host contracts.
- [ ] Create one reviewed PR, obtain exact-SHA required Actions and technical review, merge only after verification.
- [ ] Reconcile 0 PR OPEN and new main SHA, then produce exactly one controller+worker release with two immutable manifests.
- [ ] Obtain fresh Boca-only preflight; dispatch one protected operation with terminal and cleanup receipts from the same lease.
- [ ] Confirm port 8443/passkey, SITE_URL persisted and applied on restart, worker idle/start/stop, monitor metadata, SQLite inode and select cleanup physically.
- [ ] Post #417 checkpoint containing main, run/attempt, image digests, physical outcomes, RCA, pending gaps, and no claims beyond evidence.

**As of 2026-11-12 R244 initial recovery:** main `032990875feec8cd3715fb9e201277362656dd4a`, 0 PR initially, R189 READ_ONLY successful but no deploy; installed source `b61ca3e58d4f8ce69cd6d7575f2a8e1ce59bda72`/attempt `43217075287`. These are historical reference coordinates, not frozen authority for later effects.
