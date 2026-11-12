# Issue #12 Member Sector Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task; each item follows RED → GREEN.

**Goal:** Record a registered member's reusable synthetic sector priorities in that member's existing private profile.

**Architecture:** Reuse existing member identity and private owner route. Store only preference defaults in an independent SQLite sibling in the same Boca data volume, because legacy migration 0008 is forbidden; derive event-specific `SectorPreference` from that default. Never initialize storage during a GET or login.

**Tech Stack:** Python 3.12, sqlite3, pytest, existing WSGI panel and session guards.

**Spec:** `docs/superpowers/specs/2026-11-11-issue12-member-sector-profile-design.md`.

## Global Constraints

- No real Boca/Queue-it operations; no genuine reservations.
- Only own branch, no edit to main/worker/IPC/Docker/SITE_URL/migration ledger of `boca.sqlite3`.
- No duplicate member enrollment or storage of email/password in sidecar.
- Preserve CSRF, origin, permission, replay, UUID and one-ticket invariants.

## Review Focus

- Member deleted in the legacy DB → cannot save or display orphan preference.
- Sidecar missing, symlinked, corrupted, wrong file mode → no implicit repair.
- Ordered allowlist whitespace/duplicate IDs/too many sectors → rejects without data loss.
- Two different members → isolated settings and no duplicate registration.
- Unauthorized/CSRF/replayed POST → existing settings unchanged.

---

### Task 1: Typed defaults and isolated persistence

**Files:** Create `src/boca_socios/panel/member_sector_store.py`, `tests/test_member_sector_store.py`.

**Interfaces:** `MemberSectorDefaults(member_id, mode, sector_ids, version, updated_at).for_event(event_id)` → existing `SectorPreference`; `MemberSectorStore.for_database(path)`, `.migrate()`, `.load(member_id)`, `.save(member_id, mode, sector_ids, updated_at)`.

- [x] RED: tests for explicit migration, pre-existing member linkage, defaults, persistence/reload, validation, isolation and unsafe sidecar.
- [x] Run `PYTHONPATH=src python -m pytest -q tests/test_member_sector_store.py` and observe missing feature failure.
- [x] GREEN: implement an exact-owned private sidecar SQLite with schema checksum; no runtime auto-create.
- [x] Run new and existing DB/sector tests; type/lint new files.

### Task 2: Integrate existing profile form

**Files:** Modify `src/boca_socios/panel/private_ui.py`, `src/boca_socios/panel/private_http.py`, `tests/test_private_beta_panel.py`.

**Interfaces:** Existing `/socios/{id}` GET appends owner-only preferences section; POST `/socios/{id}/sectores` uses existing one-time operation/CSRF and `MemberSectorStore.save`.

- [x] RED: user who already enrolled sees/saves/reloads settings without re-enrollment; unauthorized/invalid POST denied; preserved old credential actions.
- [x] Run `PYTHONPATH=src python -m pytest -q tests/test_private_beta_panel.py::test_member_sector_preferences_in_existing_profile` and verify expected failure.
- [x] GREEN: smallest handler/UI change, no new route for enrollment, no startup migration.
- [x] Run panel + sector suite, ruff, mypy, full test command and report exceptions.

### Task 3: Preserve evidence without Cutover interference

**Files:** Existing spec, this plan and issue #12 comment.

- [ ] Reconcile remote branch, base commit, and exact changed filenames.
- [ ] Publish to dedicated branch only, no PR, no merge, no host changes.
- [ ] Record tests and unverified physical integration in issue #12.
