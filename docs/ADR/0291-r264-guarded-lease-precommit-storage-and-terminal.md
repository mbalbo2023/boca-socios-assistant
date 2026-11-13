# ADR 0291 — R264: one-way same-lease successor admission and terminal readback

**Date:** 13-NOV-2026 UTC. **Issue:** #417. **Base:** `main`
`ecdf30a0bc890c7c8f03e6f0ecd350405b0df1f3` (#506 merged). **State:** CODE_ONLY;
physical `APPLY` and BETA deployment remain **NO_GO**.

## Evidence-backed root causes

R259's `GuardedTechnicalSuccessorBackend` checked that a `PreParkExpectedSeed`
was the correct Python type, bound to the same plan and lease. However, the
dataclass is public. A caller could assign an unproduced typed instance to
`backend.prepark_seed` and reach `stage()` without the backend's own `attest()`
having captured genuine old-pair evidence. Likewise, a second `attest()` could
replace the seed within one transaction. Offline tests first proved both
failures: an injected seed reached the effectful delegate, and the attestation
delegate executed twice.

After the new pair's temporary binding was installed but **before** the
irreversible commit marker, the R259 gate rechecked both SITE_URL sources but
did not repeat the exact structural-V2 custody of the three retained Boca
data/key/owner inodes. An inode/UID-mapping or master-key identity change
could therefore first be discovered by postflight **after** the old pair was
retired, when rollback is forbidden. Three further RED tests demonstrated
that changed, second-capture-drifted and unavailable metadata were accepted
by `replace_binding()` instead of refusing the marker.

Finally, the private CLI helper `_execute_reviewed_successor()` accepted an
engine-level `ACCEPTED` return value without independently checking the
`OneShotTechnicalTerminalBridge`'s durable technical terminal object. A
synthetic engine return skipping the terminal had previously passed.

## Minimal bounded change

1. `attest()` is now a one-way operation. It consumes its own attestation
   attempt before the first external callback and records the **exact seed
   object** only on successful production capture. Every effectful phase
   requires that same produced object; assigning an arbitrary typed seed or
   replacing it after capture is NO_GO. Failed/interrupted captures cannot be
   retried on that backend instance.
2. `replace_binding()` retains R259's genuine two-source SITE_URL check and
   additionally reads the reviewed `_before_park_storage()` producer **twice**
   under the original lease, comparing both values to the previously captured
   `PreParkExpectedSeed.storage_before`. The producer already verifies the
   dedicated Boca rootless storage path and exact volumes; it reads inode
   metadata, not SQLite/owner/key file contents. A missing, remapped-UID,
   changed or inconsistent read is fixed-category NO_GO, before engine
   `commit_marker()` can execute. This is a necessary gate, not a complete
   authority grant: the underlying strict host UID mapping remains subject
   to R262's independent physical review.
3. After the one-lease engine returns, `_execute_reviewed_successor()`
   re-encodes its canonical terminal. An `ACCEPTED` outcome is rejected unless
   the same technical bridge exposes the exact attempt-bound, same-byte
   `TechnicalTerminalEvidence` with matching SHA-256 and state
   `TECHNICAL_ACCEPTED_OWNER_PENDING`. That state explicitly retains
   `beta_deploy=NO_GO` and `passkey_attested=False`. A non-accepted outcome
   carrying a contradictory technical-success object also fails closed.

## Non-authority and remaining blockers

The public protected `main apply` selector still raises
`SuccessorPreflightIneligible` after authenticating the bound ZIP; the helper
is **not called by that selector**. No workflow, ZIP allowlist, image,
Compose, SSH dispatch, host Docker, browser or owner data changes here. The
R186 postcommit NO_GO and its resources are immutable and cannot be replayed.
This change neither chooses WebAuthn host↔panel channel A/B nor claims a real
Chrome passkey. The technical terminal never equals full BETA acceptance.

Before enabling a single protected successor APPLY: R262 must positively
bind actual host subuid/inode custody; R263 exact-origin and remaining
same-lease pre/postflight must be integrated and reviewed; the final current
`main` must have exact-SHA CI, dual immutable manifest/release and authenticated
runner bundle; the one protected Boca Action needs fresh host preflight and
physical SUCCESS/FAILURE receipts. Then owner passkey, worker on-demand,
SITE_URL, monitor, SQLite and Boca-only cleanup need independent acceptance.
Until that evidence, **DEPLOY NO_GO** and no external/real reservation.

## TDD and verification

Seven new RED observations preceded the fixes: false `ACCEPTED` from an
engine stub without terminal; three precommit storage drift/no-reader cases;
absence of double storage recheck; unproduced typed seed allowed into STAGE;
and repeated attestation. The focal guarded actor suite then passed 26/26.
Further verification, full-suite count, bundle budget and exact candidate
SHA belong to the R264 integration record; passing tests alone do not prove
droplet state or authorize installation.

**Scope:** only guarded actor, private CLI helper, focal tests and this ADR.
No changes to R262 rootless reader, R263 exact-origin observer, workflows,
SITE_URL/blackbox modules, R186 logic, Porota or unrelated applications.
