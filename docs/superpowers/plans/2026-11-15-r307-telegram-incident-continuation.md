# R307 Telegram Incident Continuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Execute the single scoped task below; root owns documentation and integration.

**Goal:** Observe prepare1167 using the existing read-only observer without changing historical1156 APIs.

**Architecture:** The existing CLI selects1167 explicitly for acquisition and verification. Imported APIs retain1156 defaults for R305; transport and receipt V1 remain unchanged.

**Tech Stack:** Existing Python, pytest, Ruff, mypy, protected GitHub Action.

**Spec:** `docs/superpowers/specs/2026-11-15-r307-telegram-incident-continuation-design.md`.

## Global Constraints

- Base e16bfb78bc16b9f7554c76191c50f354e61fcbbc; INCIDENT43705714873 remains historical; CURRENT_INCIDENT43738415332 is fixed in both CLI branches.
- Only those two incident IDs; no mutable globals or payload-derived selection.
- Preserve all1156 behavior, including CAP_CHOWN mismatch and publish-status outside the historical profile.1167 accepts current capabilities and both existing status-publication operations.
- Keep workflow/builder/bootstrap/recovery/backend/SQL/images/BLACKBOX untouched.
- Module<=24000 bytes;29 ZIP entries; source900000/ZIP320000; receipt4096; field8192. Factor fixed templates only, with exact item order and values.
- No new receipt fields/reasons. Complete uses NONE; helper ABSENT is not historical causality or permission to retry.
- No host/provider/Telegram operations. Preserve data/passkeys, R installed and recovery1166.
- Root owns docs and GitHub. Author changes only the three paths below. Never stage other files.

## Review Focus

- Same observation run/SHA with wrong incident must still reject.
- Defaults called by R305 must retain1156 and its profile.
- Invalid/mixed helpers must reject before inspecting their fields.
- Fixed-template factoring must preserve state-field ordering, not merely dict equality.
- Helper absence is a complete present observation, never proof of failed phase or PREPARED.

## Task 1: Continue the existing observer with finite incident selection

**Files:**
- Modify `src/boca_socios/host_telegram_incident_readonly.py`.
- Create `tests/test_r307_telegram_incident_continuation.py`.
- Modify `tests/test_r304_telegram_incident_bundle.py` only for current CLI fixtures and cross-rejection expectations.

**Interfaces:** Preserve positional callers. Add optional `incident_id: str = INCIDENT` to `_inventory`, `_snapshot`, `_profile`, `_base`, `observe`, `_verify_helper`, `verify` as needed; propagate it explicitly. Main keeps its existing three arguments and selects CURRENT_INCIDENT for both host and verify. Validate selection before any Docker access. Keep existing error/result structure.

- [x] Write causal regressions proving existing CLI cannot observe/verify1167; capture RED before product edits. Prefer existing fixture/transport helpers.
- [x] Implement finite propagation, per-incident helper name/profile and explicit current CLI selection. Factor `_TEMPLATES` from a fixed ordered key list plus exact overrides; compare against immutable base items and derived orders.
- [x] Preserve1156 API observations/verification and R305 real imports; reject both cross-incident directions with identical run/SHA; reject invalid IDs and alien/multiple helpers before field inspection.
- [x] Exercise actual acquisition for present/absent/drift, finite profile/reason output and synthetic token-like redaction. Treat1167 absent helper as reasonNONE with no permissions.
- [x] Update actual ZIP/CLI/workflow-tail test fixtures to1167; old1156 must reject through current CLI while default API still accepts it. Keep rc0/3 and transport discrepancy checks.
- [x] Run new and affected R304/R305/R306 tests once after GREEN, plus Ruff/format on changed Python and mypy on the module. No complete local suite or image build; CI covers the required exact candidate gates.
- [x] Measure source and both affected bundles against unchanged limits and verify unrelated product paths unchanged. If the module cannot fit without another semantic change, report the exact delta before broadening scope.
- [x] Self-review, stage only the three owned paths and commit. Report RED/GREEN commands/results, file sizes, commit and limitations in the assigned report file.

## Root integration

- [ ] Record implementation evidence and four independent final votes; resolve concrete findings without repeating completed gates.
- [ ] Publish one candidate from this issue; verify exact SHA CI, merge with expected head, verify main checks and PR0.
- [ ] Reconcile latest physical evidence and runs; execute at most one existing protected read-only incident observation. Verify original receipt and document what it does and does not establish in417/45.
