# Implementation plan — R108 exact historical quarantine

Date: 2026-11-07 ART. Owner: #417/#45. Source base tree:
`11dafc511729e2ab521ea2c7975d2cd3c26d3be5` on main `8134a042`.

1. Write failing regressions in `tests/test_host_boca_cleanup.py`,
   `tests/test_host_boca_cutover_backend.py` and
   `tests/test_cutover_a_go.py`: exact only, drift/no-ref, V1 compatibility,
   canonical V2 good/tampered. Run focused suite, capture RED.
2. Implement proof/receipt in `src/boca_socios/host_boca_cleanup.py`,
   precommit+finalizer wiring in `src/boca_socios/host_boca_cutover_backend.py`,
   and independent runner validation in `scripts/check_cutover_a_go.py`.
   Keep a single original controller and all foreign resources untouched.
3. Document approved one-image exception and actual limitations in AGENTS.md,
   `docs/DEVELOPMENT_POLICY.md`, `docs/ADR/0209-r108-attested-historical-quarantine.md`,
   and README. Update the exact host ZIP pin only after final source content.
4. Run focused GREEN, full suite, Ruff, formatting, MyPy, policy, bundle,
   source-diff. Independent architecture/QA/security review and one PR.
5. Confirm exact-SHA Actions, merge and PR0. Publish a fresh dual image
   release tied to new main SHA, then one protected V3 Cutover operation.
   Check typed terminal, final cleanup proof and app health in the droplet.
6. Record physical outcomes and RCA in #45/#417. Do not certify install from
   CI or release alone. If physical NO_GO, preserve old service and reconcile
   fresh read-only evidence; no same-run retry.

Implementation remains simulation-only. No real site automation, tickets,
other Docker projects, host shell or blackbox module inspection.
