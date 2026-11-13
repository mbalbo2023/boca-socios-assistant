# ADR 0271 — R255 two-phase physical postflight expectation, CODE_ONLY

**Date:** 2026-11-13. **Issue:** #417. **Status:** candidate CODE_ONLY / `DEPLOY NO_GO`.

## Temporal root cause

The successor transaction needs three preexisting, durable Boca storage
identities and the owner's currently saved `SITE_URL` fingerprint **before**
the old controller is parked. The new controller/worker CIDs and OCI image IDs
cannot be known before their containers are created. Constructing a complete
`PostflightExpected` from form fields or predicting those IDs would invent a
physical witness. The R253 same-lease assembly remains inert, and its
technical health receipt is not a fresh owner passkey ceremony.

## Decision

`host_boca_prepark_expected_v2` exposes two deliberately unconnected,
read-only steps:

1. `capture_prepark_expected_seed` accepts only a typed
   `BoundSuccessorInputs` value previously authenticated by the protected
   runner and the **same held** `BocaJobLease`. A production
   `SuccessorCurrentPairCapture` compares the current controller/worker,
   systemd binding, historic resource owners and exact CIDs with a fresh
   physical observation. The three Boca-only data/key/owner volumes are
   checked by the existing rootless validators, and their file metadata is
   captured twice. A fixed, isolated Python command in the exact existing
   controller reads only the configured URL's SHA256 fingerprint, never its
   plaintext. The entire witness and the lease are checked again. If the
   old controller has **never saved** `SITE_URL`, the fixed read-only source
   returns an explicit `NOT_CONFIGURED` state with a `None` fingerprint:
   this does **not** fabricate a digest or block a future *technical*
   controller+CREATED worker installation merely because the old form is
   broken. Any malformed output, unsafe file, drifting storage, changing
   URL state, changed controller or ambiguous ownership instead refuses
   the seed without modifying Docker, SQLite or session state.
2. Only *after* the original one-shot SUCCESS cleanup is complete,
   `PreParkExpectedSeed.expected_after_cleanup` reads that exact bridge's
   durable V2 receipt, two genuine new-pair observations and two validated
   systemd bindings under the **identical lease object**. It derives new CIDs
   and image IDs exclusively from the physical observer, checks the target
   release source/digests and canonical `PostflightExpected`, and returns
   typed evidence for a future independent technical postflight capture.
   This URL-dependent builder refuses `NOT_CONFIGURED` even after a valid
   cleanup. A later, separately reviewed technical-cold-worker profile must
   record installation as technically pending URL and allow the owner to
   enter/attest it **after** the corrected controller is installed. The
   final BETA acceptance still requires an actual saved-and-mirrored URL.

Both phases return only data; `apply_authorized` and
`terminal_accept_authorized` stay **False**. No code path invokes the
transaction engine, backend factory, protected workflow, browser, queue,
provider, SSH deployment or owner acceptance from this module. It is not
added to the protected ZIP allowlist. The historical R186 journal is
unchanged; no retry or recovery is ordered.

**Actualización R258/R259:** la frase anterior describe únicamente el
commit aislado R255. ADR0277 añadió el módulo al ZIP protegido, ADR0280
enlazó el backend técnico y ADR0281 añadió el veto antes del marcador
irreversible. El selector CLI APPLY y la instalación física siguen NO_GO.

## Explicit physical blockers / required follow-up

- The pre-PARK reader uses the **same structural-V2 hash domain** as R253's
  postflight source (`capture_structural_storage_fingerprints`): SQLite
  size/mtime/ctime activity does not change the logical inode identity.
  Nonetheless, the reader requires host-UID ownership of SQLite/owner/key
  files. Rootless remapping may expose a subordinate UID, so a synthetic unit
  test cannot prove the physical mapping; the producer must fail closed.
  Reconcile R253's exact volume/mount attestor and obtain a positive
  READ_ONLY subuid/inode observation before enabling this code. Do **not**
  relax mode, symlink or volume owner checks on speculation.
- `SITE_URL` may still be missing because the old form rejected the mobile
  POST. Treating that fact as a **pre-PARK veto** would deadlock installation
  of the form fix. The explicit `NOT_CONFIGURED`/`None` capture is allowed
  only for future *technical* installation with the worker CREATED and cold;
  it is never interpreted as owner-accepted BETA or proof the URL is applied.
  The full URL-dependent `PostflightExpected` remains NO_GO until a genuine
  saved fingerprint exists. No default URL or external navigation is added.
- The R253 protected ZIP has extremely little uncompressed headroom; any
  inclusion of this source must recalculate AST-preserving compaction and
  both archive bounds. Do not raise the cap merely to fit it.
- A later, independently reviewed backend-factory integration must call the
  pre-PARK producer after a **durable terminal intent**, bind one journal,
  SUCCESS/FAILURE finalizers and technical O_EXCL receipt, and retain
  `NO_GO` on every incomplete path. This ADR does **not** flip
  `requires_persistent_receipt`, wire CLI `apply`, or dispatch a host action.
- A real fresh Chrome WebAuthn acceptance follows physical installation and
  cannot be simulated within a continuously held APPLY lease. Its trusted
  host→panel binding and separate READ_ONLY verifier are addressed by
  ADR0267 (R254); global `DEPLOY NO_GO` remains until those later proofs.

## Verification scope

`tests/test_host_boca_prepark_expected_v2.py` tests double capture and rejects
the legacy size/mtime-sensitive V1 fingerprint producer outright,
constant-category failures for malformed URL/storage/old-pair drift, and an
explicit `NOT_CONFIGURED` result when the old URL is absent, source-
derived new CIDs/images, official-cleanup mismatch and foreign lease. The
tests use synthetic fixtures and explicitly do not contact Docker or GitHub.
They establish a local contract only, **not** a production-ready route.

**Security and scope:** no secrets or URL values emitted, no real ticket,
Queue-it bypass, TLS relaxation, foreign Docker, Port/Porota changes or
navigation. No new host operation, workflow selector, image release or
acceptance claim.
