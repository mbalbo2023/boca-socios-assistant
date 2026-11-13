# ADR 0251 — R247: protected current Boca pair V2 provenance

**Date:** 2026-11-12. **Decision:** CODE_ONLY, physical deploy **NO_GO**.
**Scope:** existing `boca-pair-upgrade-apply` selector; no new workflow/input,
host credential, host network, Docker operation or bypass.

## RCA: why historical R188 cannot represent the next live pair

R188's immutable receipt is explicitly pinned to the original R186 resource
creation source, install attempt and containers. The first successor release
changes the controller/worker CIDs and installed SHA, but it does not change
the identity of the original IPC, site and egress resource creators. R244's
old `host_boca_upgrade_retained_bridge._coordinates()` required R188's fixed
`installed_source_sha`/attempt to be equal to the dynamically observed pair.
That equality can only hold for one generation and deterministically fails
on B→C. Removing it without independent provenance would be unsafe.

The previous design carried seven release evidence files and performed
authentication before a single protected SSH command; that network and
transport boundary is retained. R247 adds one runner-authenticated V2 file,
preserving the seven other members and their exact names. The old R188 V1
receipt stays byte-for-byte unchanged; the former `retained-proof.json` is
**strictly** `{"state":"NO_GO"}\n` to prevent treating it as a current-pair
grant. Current V2 has `apply_authorized=false` and
`requires_fresh_same_lease_reproof=true`.

## Trusted runner sequence

1. The existing R244 pair-observation bridge authenticates the separate
   `boca-installed-pair-observation` run, first attempt, correct main,
   protected job/steps and sole bounded ZIP member. It writes pair receipt
   and proof only after REST checks.
2. The existing R242 target-release bridge authenticates **both** original
   target controller/browser release ZIPs and writes their two manifests plus
   canonical digest proof. It does not repeat Docker builds.
3. New runner-only `scripts/attest_current_pair_v2.py` verifies those five
   private files; discovers the prior release only through the exact
   `actions/workflows/release-image.yml/runs?head_sha=<observed_old_sha>&event=workflow_dispatch&per_page=100`
   endpoint. Any zero/multiple run, malformed record, wrong actor/source,
   rerun, failed job, expired/wrong artifact or ambiguity is NO_GO; after
   authenticating both prior release ZIPs it queries the listing **again**.
4. It separately authenticates the **historical** R188 observation run,
   approved steps, artifact ZIP digest and original creator receipt under
   its own historical commit SHA. R188 does not have to equal current main.
5. `authenticate_current_pair_v2` links prior release, current pair and
   R188 creator pins and independently rechecks current main. After all
   checks, three private O_EXCL/0600/fsync writes create R188 raw, exact
   retained NO_GO sentinel and `current-pair-v2.receipt`.
6. Existing `scripts/build_protected_boca_bundle.py` requires the exact
   eight-file private directory, checks V2 canonical integrity and consistency
   with pair, historical raw and target manifests, and creates one checksum-
   pinned ZIP. `boca_protected_memfd_bootstrap.py` independently requires
   exact `release/current-pair-v2.receipt` and both host V2 integrations.
7. Only the **existing** one SHA-pinned SSH path could see that ZIP. The new
   host successor adapter (separately reviewed) treats runner proof as
   integrity, never GitHub authority, and keeps the effectful backend
   `requires_persistent_receipt=False` behind the original hard NO_GO.

## Limits, speed and hard boundaries

- **25 dispatch inputs** still; no invented historical release input and no
  reuse of `legacy_release_run_id` which has other selector semantics.
- One target dual release authentication, one pair observation, one historical
  R188 authentication, one additional prior release lookup (read twice against
  race), **one** bundle and **one** existing SSH. No duplicate build/image.
- Runner REST token is never included in ZIP or SSH arguments. Every host
  path/source/archive member remains strictly allowlisted, size-bounded;
  no shared Docker cleanup, TLS relaxation, real ticket attempts or Porota.
- The historical R188 ZIP is a time-limited GitHub artifact (48-hour observer
  freshness). Expiration or missing prior release artifact means NO_GO,
  not guessed identifiers. Sustained custody across B→C needs its separately
  reviewed durable journal and same-lease evidence, outside this ADR.
- The older R188 V1 source and `host_boca_retained_resources.py` remain
  **untouched**. This is fix-forward, not a historical rewrite.

## Offline verification and negatives

- R246 tests already cover two sequential upgrades with distinct current
  identities but common historical creator pins.
- R247 runner fakes cover original R188 corruption/expiry/rerun/actor/job,
  previous dual release failure/ZIP mismatch, zero/multiple and concurrent
  source listing, preexisting output and both sequential pair generations.
- Builder rejects seven or nine evidence entries, missing/extra package
  members even with a recomputed SHA, old V1 proof in V2 slot, changed
  creator pins, changed CIDs/target SHA and symlinks.
- Workflow tests pin the **same 25 inputs**, one existing observer, target
  release bridge, new runner proof, and exactly one downstream SSH.

## Exact bundle membership and incremental integration budget

The eight authenticated **evidence** members are exactly:

1. `release/boca-release-manifest.json`
2. `release/boca-browser-release-manifest.json`
3. `release/runner-proof.json`
4. `release/boca-pair-observation.receipt`
5. `release/observation-proof.json`
6. `release/boca-retained-observation.receipt`
7. `release/retained-proof.json` (the literal `NO_GO` sentinel)
8. `release/current-pair-v2.receipt`

Measured on the current code-only R247 runner candidate with the offline,
authenticated fixture: the complete ZIP is **332,085 / 480,000 bytes**;
the aggregate uncompressed allowlisted source plus evidence is
**1,287,795 / 1,300,000 bytes**, only **12,205 bytes** below the existing
ceiling. This transport includes `host_boca_current_pair_v2.py` and
`host_boca_successor_integrations.py` but **does not** currently include
`host_boca_upgrade_failure_cleanup_v2.py` or a successor physical postflight
source adapter. Their independent code-only implementation and tests do not
make them executable through the protected host ZIP; effectful promotion
remains `NO_GO`.

Before any later integration wires those modules into the effectful CLI,
the single bundle owner must calculate the actual Python import closure,
eliminate only proven-unreachable packaged files if possible, and remeasure
the **integrated** exact-source ZIP. In particular, the proposed failure
cleanup V2 module alone is approximately 22 KiB and would exceed today's
uncompressed ceiling. If no provably unused module can be removed, a narrowly
measured, explicitly reviewed bound adjustment covering the required import
closure (with regression tests for archive and uncompressed limits) is
necessary; never simply omit an imported module or declare host readiness.
The existing one SSH, protected-action signature, 25 inputs, and lack of
host effects are unchanged regardless of that later sizing decision.

**No production claim:** passing these offline checks does not prove that the
current protected repo, release artifacts, newly installed CIDs, passkey,
SITE_URL, worker/monitor or SQLite actually changed. No workflow was
dispatched or physical host mutation performed in R247 code-only work. The
effectful pair upgrade remains **NO_GO** until separately reviewed persistent
same-lease intent/receipt gates, postflight and source/attempt verification.
