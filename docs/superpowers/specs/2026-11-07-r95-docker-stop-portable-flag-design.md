# R95 — Docker STOP timeout flag portability (design)

**Date:** 2026-11-07 ART. **Owner:** RCA #417; continuation #45. **Boundary:** R94 #839 exact recovery is CLEANED/VERIFIED; R95 remains CODE_ONLY until fresh physical preflight evidence is reviewed separately.

**Intent:** avoid deprecation-related stdout noise during the one protected worker cleanup STOP, while keeping its fail-closed full-CID ACK and one-shot behavior intact. The R92 #834 stdout bytes and physical Docker CLI version have **not** been measured. This is a compatibility correction, not a claimed RCA closure.

**Approaches evaluated:**

1. Keep `--time` and parse/drop warning lines: **rejected**; accepting partial output would weaken the exact ACK invariant and creates another ambiguous cleanup path.
2. Use `--timeout 5`: standard in Docker CLI v28, but requires a preflight minimum-client-version check and is not as portable to earlier clients.
3. Use short `-t 5`: **selected**; documented shorthand for STOP timeout on Docker CLI versions before and after v28, avoids a long deprecated alias. One token change, no daemon changes, no new Docker calls.

**Goals:** same timeout 5s and subprocess deadline 20s, same full 64-character CID match, exactly one STOP and one RM only with clean ACK. Any multiline/short/missing/wrong ACK remains `NO_GO/INDETERMINATE` with zero RM. Preserve host/runner receipt bytes and exact recovery bindings.

**Non-goals:** prove the host's #834 failure, change warning handling, repeat any previous SHA, repair running unknown containers, relax Cutover/GO_B, operate against the real Boca site, alter Telegram or other applications/Porota.

**Verification:** turn five existing synthetic command-shape assertions RED, add a TDD regression for a modern CLI fake where the deprecated long name yields `warning\nCID` but `-t` yields a single CID; implement only the STOP flag; include tests in the protected FirstDeploy selector, run full suite and four GitHub PR gates. No new physical preflight solely from the R94 recovery or code tests.
