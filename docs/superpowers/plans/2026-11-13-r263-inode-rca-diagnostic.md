# R263 Rootless Inode RCA Diagnostic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the authenticated physical `INODES` refusal into a safe, fixed-category metadata diagnosis so that the next Boca-only fix-forward is based on host evidence.

**Architecture:** Preserve the original Boca lease, Docker pair/census, systemd binding, UID/GID mapping, private O_PATH inode checks, rootless ZIP, SSH and schema-1 success. Only rejected metadata checks carry a fixed internal reason into the existing schema-2 failure receipt. The existing protected Action whitelists and reports a refusal without raw stderr or any writes.

**Tech Stack:** Python 3.12, pytest, Ruff, mypy, protected GitHub Actions Bash, rootless Docker metadata (read-only).

**Spec:** [ADR0288](../../ADR/0288-r263-rootless-inode-refusal-categories.md).

## Global Constraints

- `main` baseline `01bb7d6ca1f7c933adbbad5aefc204bf981e122c` and genuine physical refusal [#43364745527](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/43364745527).
- No host writes, Docker mutations, `chown`, data reads, external browser, Porota operations, release dispatch, R186 replay, or effectful upgrade.
- Protected rootless source ZIP remains below 1,400,000 uncompressed bytes and 480,000 compressed bytes, with 62 reviewable files.
- Keep rootless success receipt schema 1 byte-identical and NO_GO schema 2 canonical.

## Review Focus

1. Mapped owner differs from host service owner; distinguish fixed `INODES_OWNER_HOST` without printing numeric owners.
2. Only one mapped ownership component matches; produce fixed `INODES_OWNER_PARTIAL` instead of a false host-owner conclusion.
3. Missing, symlinked, hardlinked, world-readable private data; keep fail closed with fixed outcomes.
4. Unexpected exception string contains secrets; never serialize it, always map to `INODES_OTHER` or `INTERNAL`.
5. Forged/malformed host receipt; independent runner verifier must refuse it before public Job Summary.

---

### Task 1: Metadata refusal classifier

**Files:** `src/boca_socios/host_boca_rootless_mapped_custody.py`, `tests/test_host_boca_rootless_mapping_cli.py`.

**Interface:** `MappedCustodyNoGo.reason` is a fixed literal; `_file_identity()` reads only existing metadata and raises a fixed-class exception, preserving positive checksum output.

- [x] Add tests for owner host/partial/other, absent, mode, link and symlink with literal expected boundaries.
- [x] Capture RED: existing `INODES` generic differs from expected `INODES_OWNER_HOST`.
- [x] Add minimal fixed reason classification and preserve all no-follow and file-identity predicates.
- [x] Confirm 62 focused rootless tests GREEN.

### Task 2: Canonical bridge and Action whitelist

**Files:** `src/boca_socios/host_boca_rootless_mapping_cli.py`, `.github/workflows/boca-first-deploy.yml`, `tests/test_host_boca_rootless_mapping_cli.py`.

**Interface:** fixed `failed_boundary=INODES_...` in schema-2 only, accepted by the existing strict verifier; never mark a refusal as success.

- [x] Restrict bridge and shell to the same enumerated failure values.
- [x] Test rejection of arbitrary reason strings with identifiers or private words.
- [x] Verify rootless ZIP: 62 files, 1,396,654 uncompressed and 358,281 compressed bytes.
- [x] Peer review Bash whitelist, exception containment and safe classifications (`GO_CODE_ONLY`, no host GO).

### Task 3: Quality, evidence and responsible promotion

**Files:** `docs/ADR/0288-r263-rootless-inode-refusal-categories.md`, issue #417, final PR.

- [x] Document initial `INODES` refusal without conjectured RCA and ownership boundaries.
- [x] Full local pytest via `uv run`: 8.193 PASS, 1 SKIP AF_UNIX EPERM; Ruff, mypy and repo policy GREEN. Local RCA-selector correctly reports red on the sandbox skip.
- [ ] Obtain hosted exact-SHA quality/image-build, RCA-selector and First Deploy validation GREEN (no AF_UNIX sandbox skip).
- [ ] Reconcile main, PR list and reviews; merge only exact-green reviewed PR, not a draft or stale candidate.
- [ ] Perform a single fresh protected READ_ONLY mapping observation on final `main` and record its fixed result in #417.
- [ ] Based on the observed subreason, define a separate minimal remedy; no effectful APPLY/release without genuine GREEN prerequisites.
