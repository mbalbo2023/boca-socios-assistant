# R252 — strict current-base-only stage custody under one Boca lease

**Issue:** #417, checkpoint A45-R252. **Base:** main
`87df6dca6622b02b16e6ec643da6b3e726bf418a` (R251).
**Scope:** pure integration adapter in `host_boca_successor_integrations.py`
and isolated tests; no workflow, SSH, Docker or effect activation.

## Design decision

The protected R251 memfd ZIP freezes the three reviewed target stage files
and hashes, but its evidence does not directly prove the *old* persisted
Compose SHA. In this specific update, repo `compose.beta.yaml` still has
the same hash as the historically reviewed installed root Compose. Use a
restrictive, current-base-only contract: only if the actual Boca-owned
persisted root Compose matches `preflight.base_sha` (target file) under the
one protected lease may it be used as `PairSources.original_compose_sha`.

This is not a general original-Compose discovery algorithm. A future release
changing `compose.beta.yaml` must authenticate previous source separately.
Never fall back to a hardcoded historical hash or user-supplied path/digest.

## Planned TDD steps

1. Construct synthetic `BoundSuccessorPreflight` from the already tested V2
   release/observation fixtures and three stage bytes. Assert that the
   new adapter creates a valid `PairSources` with SHA-256 values coming from
   these bytes, not fabricated source values; no host reads on construction.
2. Use a temporary owner-only Boca stage root and the repository's real
   `protected_boca_job_lease` fixture to prove a same-lease double read of
   only `compose.beta.yaml` through `_root_fd` and `_read_file(...,
   historical_compose=True)`. Revalidate exact byte content and device/inode,
   size, mtime and ctime before invoking existing journal.intent. Ensure no
   second lease or second transaction.
3. RED tests: mismatched Compose SHA, symlink/wrong owner/mode, missing file,
   modified inode/timestamp between reads, wrong target plan, already-used
   attempt, or loss of lease => fail before any journal intent or Docker.
4. Implement a narrowly typed `CurrentBaseOnlyStageCustody` callback used
   as the future `terminal_preflight` composition seam. Do not change the
   backend class interlock, CLI `main apply`, SUCCESS/FAILURE cleanup,
   journal implementation or physical workflow.
5. Run focal/full pytest, Ruff, mypy, policy, exact protected ZIP tests;
   independent review. Integrate into later single R252 PR only with the
   separate cleanup/postflight work complete and all gates GREEN.

## Conditions not proved by this work

Technical installation, cleanup, passkey/Chrome, real worker START/STOP,
SITE_URL consumption, monitor, SQLite persistence and owner BETA acceptance.
**DEPLOY NO_GO**, no R186 replay and no Porota resources touched.
