# R186 · Postcommit-only finalizer of Boca incident 43217075287

Scope: fixed Boca rootless UID/GID 10001, no Docker/systemd mutation, no new
container create/remove, no Queue-it/Boca network, no credentials, no ticket
actions. The historical APPLY receipt remains NO_GO and immutable.

## Observed gates before design

- R185 code merged main `b07947602d49148067ba4ce09191b680d2811301`.
- `boca-postcommit-observe` #43229793525: exact new pair PASS, old IDs absent,
  parked backup and intent present, no host/foreign writes.
- `boca-binding-observe` #43230025523: exact binding MATCHED_EXACT, SHA256
  archive VERIFIED, systemd VERIFIED_LISTENING, zero writes.
- `boca-sqlite-inode-observe` #43230212167: VERIFIED_STABLE, zero writes.

## Design and tests (TDD)

1. Keep the existing `commit_binding(old,new,incident,lease)` interface for
   same-run upgrades. Refactor its checks/retirement into a helper whose
   caller has already verified the lease; a new `commit_binding_postcommit`
   verifies **recovery run ID**, distinct from fixed incident ID.
2. Build a new narrow host actor. Under one fresh rootless lease, double
   attest the exact installed pair, systemd binding, SQLite identity, original
   journal `.intent/.commit/.terminal`, old archived installation, five
   archived files and absent socket node. Pin all observed new immutable IDs,
   digests and historical source in code.
3. Before unlink, create one durable `O_EXCL` claim keyed by incident ID in
   `/srv/boca-socios` (mode 0600, no symlinks, fsync), containing only bounded
   non-secret IDs and journal digest. Replaying or interrupted claims FAIL
   CLOSED without automatic retry. Keep the original three journal files.
4. Under same lease, invoke the existing narrow retire routine: only the old
   parked Boca systemd fragments, archive, binding, marker, socket directory,
   parked directory and intent. No globs, recursive removal or foreign paths.
5. Postflight checks exact pair and binding, SQLite identity unchanged, parked
   and intent absent. Write a separate terminal under the claim; return one
   bounded `BOCA_POSTCOMMIT_FINALIZE` accepted/indeterminate receipt. Any
   ambiguous I/O after claim is INDETERMINATE and requires new RCA.
6. Add one dedicated SHA-verified protected memfd bundle and one manual
   `boca-postcommit-finalize` workflow operation. Protect main exact-SHA,
   owner actor, first attempt, no open PR, empty submitted pins, Boca-only
   environment, fixed CPU/memory and runner receipt verification.
7. TDD: missing/duplicate/wrong journal; wrong CIDs/digests; absent/changed
   binding, SQLite, archive or socket; lease mismatch; no effects preclaim;
   claim-before-delete; replay denied; stopped worker remains stopped; one
   accepted receipt; simulated filesystem interruption is INDETERMINATE.
8. CI exact SHA, technical review, then merge and one effectful protected
   dispatch after physical/lease reconfirmation. Finally independent READ_ONLY
   reobservation and private panel acceptance. No second APPLY.

One incident, one finalizer, one deploy; no escalation of provider gates for
Queue-it/Boca #12. Those contracts remain included without live token testing.
