# Single-dispatch Boca deployment V3

Goal: replace manual Cutover GO_B with one owner-authenticated dispatch.
Architecture: runner admission + explicit V3 token/entrypoint, reusing existing
release discovery, read-only inventory, single-lease backend and finalizer.
Tech Stack: Python stdlib, GitHub Actions, pytest, existing rootless Docker.
Spec: [ADR0206](../../ADR/0206-single-dispatch-cutover-v3.md).
Global Constraints: no blackbox inspection; no external writes/host actions;
SIMULATION_ONLY; preserve Environment, passkey, UID10001 and foreign resources.
Review Focus: incomplete API pages/cap, foreign same-name checks, branch/run
drift, protocol downgrade, actual OBSERVE→ACK→POSTFLIGHT grammar and SSH loss.

Owner-authorized replacement of manual GO_B/PREPARE→APPLY. Scope: code only;
no dispatch, host access, publication or blackbox inspection.

- [x] RED→GREEN: test authenticated owner/main dispatch, rerun/replay rejection and
   missing/failed required checks/PR0. Implement a runner-only verifier.
- [x] RED→GREEN: test V3 invocation without PREPARE and mandatory detailed postflight.
   Add explicit protocol version/entrypoint; reuse the existing single-lease
   backend, durable O_EXCL intent, terminal reconciliation and finalizer.
- [x] Wire the existing cutover-a-apply selector to V3. Reuse exact release and
   read-only inventory discovery. Remove only this route's separate GO_B and
   PREPARE artifact requirements. Revalidate immediately before effect.
- [x] Run focused tests, formatting/lint/type checks and full in-scope suite.
   Hand off code and evidence to root for independent review/publication.

Review fixes: adjacent paginated JSON support (without gh --slurp), API cap
below 1000, and checks bound to authentic ci.yml push/main check_suite all have
regressions. Existing historical workflow expectations now explicitly separate
V3 Cutover from unchanged official-import/lifecycle GO_B contracts.

Local verification: 5369 passed + 34 subtests; Ruff check/format, MyPy src
(136 files), offline frozen lock check and repository policy PASS. RCA gate:
45 lessons, 156 executed selectors and 11 owner-attested blackbox selectors.
Final post-format focused run: 41 passed. Independent Security and receipt QA
reviewed the frozen implementation favorably CODE_ONLY; external exact-SHA CI
and physical deployment remain separate evidence, not inferred from these tests.

Ruling: reuse the existing selector rather than introduce a duplicate route.
The dispatch is authorization; the generated hash is only exact-byte binding,
not independently granted approval. Keep Environment secrets/branch controls.
No automatic retries; no real navigation/login/tickets; no foreign workloads.
V3 acceptance always needs terminal ACK plus detailed same-attempt cleanup.
