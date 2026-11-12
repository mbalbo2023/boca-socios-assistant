# R188 Retained-resource Witness and Successor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Obtain bounded, non-authorizing Boca resource evidence before changing the one-off pair-upgrade actor.

**Architecture:** Separate the READ_ONLY witness from the future effectful actor. Preserve all R186 incident coordinates and journals. Container installation identity and persistent-resource creation identity are distinct.

**Tech Stack:** Python 3.12 stdlib, pytest, existing SHA256/memfd transport and protected GitHub Action.

**Spec:** `docs/ADR/0238-r188-retained-resource-readonly-witness.md`.

## Global Constraints

- Boca-only rootless UID/GID10001; one protected manual workflow.
- No Docker/systemd/file writes, lease, provider navigation, SQLite contents or token validation in the witness.
- No R186 repin/replay; no blind second APPLY; preserve original NO_GO journal.
- `successor_apply_authorized=false` in every witness receipt.

## Review Focus

- CREATED worker may lack NetworkID/Health: use existing nullable pair observer and report no connectivity claim.
- IPC predates current containers: publish actual creator attempt, never substitute installation run.
- Volume names alone do not prove storage: Docker mountpoint plus no-follow inode metadata must match.
- Installed images cannot disagree with the pair witness: match ID, source, revision and digest.
- Unknown aliases/images do not imply disposable: redact unproven aliases and preserve unknown classification.

## Task 1 — READ_ONLY witness (implemented locally)

**Files:** `host_boca_retained_resources.py`, two matching test modules, protected bundle builder/bootstrap, existing `boca-first-deploy.yml`, ADR0238.

**Interfaces:** `snapshot(run_id, *, inventory_reader, pair_reader, identity_reader, revision_reader) -> dict[str, object]`; `observe(run_id, *, snapshot_reader) -> bytes`; `verify(raw, run_id) -> bytes`.

- [x] RED: module/transport absent; mismatched image/network and redirected mountpoint admitted before fixes.
- [x] Minimal witness and isolated read-only transport with strict canonical parser.
- [x] Tests for stable/changed captures, provenance mismatch, foreign container, aliases, inode replacement/symlink and empty-input dispatch gate.
- [ ] Exact final-SHA CI and independent review; one protected READ_ONLY dispatch only after coordination.

## Task 2 — Successor actor (NOT implemented or enabled)

**Proposed boundary:** `host_boca_pair_upgrade_backend.py`, narrow resource-provenance helper, pair-plan/transaction contract tests and existing cleanup integration. No browser/panel/SQLite schema/Porota changes.

- [ ] Authenticate the fixed prior pair, original immutable NO_GO journal and accepted R186 claim/terminal (`43237528968`) under one fresh lease; reject absent/inconsistent evidence before staging.
- [ ] Preserve actual IPC/SITE/egress creator labels, exact IDs/inodes and old container/image identities in a versioned journal. Do not infer creation provenance from current container labels.
- [ ] RED: current CREATED/PID0 pair cannot pass historical EXIT1 gate; legitimate egress UNATTACHED cannot be misclassified as historical network-none.
- [ ] RED: no create/relabel/delete of retained IPC/SITE/egress; provenance, binding, mount, inode or reference drift rejects before any effect.
- [ ] Require tests at every precommit failpoint: restore exact old pair/binding without starting worker. Postcommit uncertainty never reactivates old containers.
- [ ] Add real same-run stage and unused-image cleanup with exact source/refcounts and before/after disk/inodes; preserve forensic quarantine and all protected/uncertain resources.
- [ ] Preserve exact target dual digest/source provenance, main/owner/PR0/CI/attempt/lease gates and one Action. Only after physical witness and reviewed actor code consider a separate new upgrade.

The witness alone cannot complete Task 2 or certify installation acceptance.
