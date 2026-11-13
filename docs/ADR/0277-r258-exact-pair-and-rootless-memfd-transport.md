# ADR 0277 — R258 exact host sources in protected Boca memfd transports

**Date:** 2026-11-13. **Issue:** #417. **Status:** CODE_ONLY candidate;
**DEPLOY NO_GO**. This ADR describes local source changes, not an installed
controller/worker, GitHub Actions attestation or physical rootless map.

## Problem and original budget

R253's authenticated pair upgrade ZIP contained the durable technical
postflight and single-journal assembly, but did **not** contain the three
separately reviewed next-step host modules:

- `host_boca_prepark_expected_v2` (pre-PARK physical seed),
- `host_boca_rootless_mapped_custody` (UID/GID namespace and three inodes),
- `host_boca_technical_terminal_bridge_v3` (durable technical terminal).

Their absence from the exact bootstrap allowlist made imports physically
impossible even if the modules passed source-level tests. The R253 pair ZIP
had only a few kilobytes of uncompressed headroom under the unchanged
**1,400,000-byte** limit. A true authenticated release fixture adds
**8,096 bytes** compared with placeholder evidence; adding R259's guarded
backend and the cold-worker schema to that old budget would leave roughly
**450 bytes** under the cap. This is too little for legitimate changes in
bounded physical receipt sizes. Raising the cap without those measurements
would weaken the independently checked budget; they instead justify an exact,
reviewable transport-only adjustment.

## Decision and narrow authority

1. Add the three exact reviewed R255/R257 modules and R259's reviewed
   `host_boca_guarded_successor_backend_v4` adapter to **both** the builder's
   `PAIR_UPGRADE_SOURCES` and bootstrap's `PAIR_UPGRADE_ENTRIES` set. A ZIP
   with a missing/extra member is rejected even if its SHA-256 is recomputed.
2. Keep the **480,000-byte compressed ZIP** cap; increase **only the pair
   variant's uncompressed ceiling from 1,400,000 to 1,500,000 bytes**, a
   bounded 100,000-byte (7.14%) change. The 1.5 MB maximum is about 0.14%
   of a 1-GiB host memory budget and is checked independently at builder
   and protected bootstrap. It is still a hard cap: **1,500,001 bytes fails**
   even with a recomputed SHA-256. Reject aggregate expansion greater than
   **8× the ZIP bytes** (a zip-bomb guard) at both ends. Reserve **at least
   50,000 bytes** for variable authenticated receipts: crossing that reserve
   first triggers comment-only compaction, then fails closed if the margin
   remains below 50 kB. Both builder and bootstrap enforce this reserve.
   For every source, require
   exact AST, compiled-code-object and newline-count equivalence; comments
   remain untouched in repository source. No docstrings, executable tokens,
   tests, encrypted payloads or runtime behavior are removed to gain space.
3. Add a separate immutable read-only observer variant
   `--rootless-mapped-observe` producing a dedicated SHA-256 ZIP. Its sole
   fixed `__main__.py` accepts `boca-rootless-mapping-observe <RUN_ID>` and
   calls the reviewed `host_boca_rootless_mapping_cli.main(['observe',RUN_ID])`.
   The bundle includes a fixed Python-only host dependency set without
   release evidence, Compose files, TLS changes or browser/navigation code.
   The bootstrap checks a **different exact allowlist**. This observer
   retains its original smaller **1,400,000-byte source** cap, alongside
   480,000 compressed and 8× expansion limits; the pair increase does not
   silently widen it. It cannot reinterpret the ZIP as pair APPLY or
   the old observer. A new Actions selector is not acceptance by itself:
   the CLI must validate real old-pair/lease/volume evidence in the dedicated
   Boca rootless namespace and return only redacted bounded metadata.
4. This packaging change **does not** connect R255/R257 readers to the pair
   engine, flip `requires_persistent_receipt`, enable `apply`, start the
   browser or create a second host deployment. The read-only UID witness
   produces at most `PRELIMINARY_PREDEPLOY`; it does not prove technical
   postflight, final passkey/monitor acceptance or owner-authorized install.

## Local measured budget and contracts

On the initial R258 three-source candidate under the old 1.4 MB bound,
deterministic offline `pair_upgrade` with inert release placeholders produced
**81 ZIP members**, **349,728 compressed / 1,379,805 uncompressed bytes**;
the transport had stripped **48,895 comment bytes**. The separate authenticated
R247 evidence fixture produced **1,387,901 uncompressed bytes**, or only
12,099 bytes available *before* the new backend/cold-worker schema.

After the narrow 1.5 MB pair cap adjustment on the same three sources,
the intermediate offline archive measured **371,036 compressed / 1,428,700
uncompressed bytes**; the authenticated R247 fixture measured **373,551 /
1,436,796 bytes**. These were intermediate, pre-R259 measurements.

With all **four** R255/R257/R259 host modules, the R259 cold-worker schema,
and the R258 base-engine/CLI deltas from integrator HEAD
`8f783b07da61c4443cc780726f55672b691bc25c`, fresh local ZIP builds
measured:

| Transport | Entries | Compressed bytes | Uncompressed bytes | Headroom |
| --- | ---: | ---: | ---: | ---: |
| Pair, inert release placeholders | 82 | 376,061 | 1,449,012 | 50,988 |
| Pair, authenticated synthetic R247 fixture | 82 | 356,699 | 1,406,840 | 93,160 |
| Dedicated rootless predeploy | 62 | 357,994 | 1,393,662 | 6,338 |

The authenticated pair fixture crosses the 50 kB reserve *before*
compaction, so the AST/bytecode/line-preserving comment transform restores
**93 kB** of headroom; the smaller offline placeholder stays uncompacted.
Aggregate ZIP expansion ratio is below 4× in all cases, with an 8× hard
ceiling. The read-only rootless ZIP carries no release evidence/Compose, but
its fixed source set has only **6,338 bytes** of future code growth beneath
the separate 1.4 MB cap. All sizes are offline code fixtures, **not** physical
proof of any host UID map, lease, SQLite inode or deployment acceptance.

TDD RED first reproduced missing new members of the pair package and the
absence of the read-only builder variant. A separate RED test confirmed that
the old verifier admitted an intentionally high-expansion archive, and the
old builder/bootstrap still reported a 1.4 MB pair cap. More RED tests caught
missing 50-kB reserve verification and compaction. The bounded
ratio/size adjustments passed tests covering rejection of **exactly
1,500,001 bytes**, a digest-recomputed 8×-exceeding payload and
**1,450,001 bytes** consuming the reserve. The final focused pair/observer
closure passed **37/37** tests, including exact allowlist, SHA, isolated Python `-I`
imports, original-versus-bundled AST/bytecode/line equivalence and tampered
ZIP rejection. At that interim cut, the repository-wide local suite passed
**8035 tests and 34 subtests**, with one AF_UNIX smoke skipped because this
execution sandbox denied kernel socket creation (`EPERM`); the hosted runner
still must execute that required gate. The completed R259 rootless CLI is
included only in the distinct READ_ONLY archive; the corresponding real
workflow and live host still require exact-SHA CI and physical evidence.
No droplet, GitHub release, external site or Porota resource
was accessed by these local tests.

## Physical NO_GO and independent gates

The observed old controller/worker, fixed host lease, rootless subordinate
UID/GID mappings, stage and cleanup V2 receipts, release manifests, live
SQLite/owner/key inodes, panel loopback 8443, passkey, `SITE_URL`, monitor and
worker are separate evidence requirements. In particular, an old unsaved
`SITE_URL` must be represented honestly as `NOT_CONFIGURED`, never as a
fictitious SHA or full BETA acceptance. A fresh, technically authorized
successful install still needs an independently validated terminal, final
selective Boca-only cleanup and owner/browser postflight. The irreversible
R186 APPLY is not repeated. No real tickets, queue bypass, TLS disabling,
host-wide Docker operations, Porota changes or sibling-workload access.
