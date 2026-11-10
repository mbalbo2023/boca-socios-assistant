# Boca W1 implementation plan

1. RED: failing tests for sanitized missing-module extraction, pre/post
   attestation, single exact-CID start, cleanup, and verified host receipt.
2. GREEN: minimal extensions to the existing capture and lifecycle exception;
   a narrow host-only W1 operation and independent runner verifier.
3. Wire only the existing protected workflow selector, case, fixed-source
   pre-SSH REST gate, existing pinned SSH, and deterministic memfd source allowlist.
   Keep all other dispatch routes unchanged.
4. Run scoped tests, full Ruff, Mypy, repository policy, and relevant PR
   acceptance gates; check source bundle bounds and runtime code review.
5. Create W1-only DRAFT PR and perform review; merge only the W1 diagnostic
   after checks and the owner's GO W1. Trigger only one protected Action. Read
   actual safe receipt and document exact evidence in issue #417.
6. If the module is identified, fix forward without modifying BLACKBOX modules,
   test offline and demand independent physical validation before reporting
   the installed worker repaired. Leave Origin and Cutover frozen.
