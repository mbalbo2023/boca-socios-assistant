# V3 stage recovery implementation plan

> Execution: implement locally with test-first cycles, preserving legacy interfaces.

**Goal:** Add generic V3 incident stage recovery to the existing protected workflow.

**Architecture:** Verify GitHub incident and per-incident replay, bind source to host records and observe twice under the existing lease; delete exactly the authenticated child and validate a third observation. Keep historic paths unchanged.

**Tech stack:** Python 3.12, GitHub Actions, pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-v3-stage-recovery-design.md`.

## Tasks

- [ ] Add failing V3 host-mode tests for source mismatch, unsafe/changed observations and canonical ACK; preserve legacy tests.
- [ ] Implement V3 mode in the existing recovery and bundle, run the focused suite.
- [ ] Add and exercise fail-closed GitHub incident, PR0 and paginated per-incident anti-replay gate; wire existing selector without new inputs or aliases.
- [ ] Update ADR and operational documentation; run frozen lint, types, tests and isolation policy; record exact limitations in a draft PR.
