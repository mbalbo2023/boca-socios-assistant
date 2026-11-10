# Boca Worker Volume Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one guarded rootless physical probe reproduce the installed worker's IPC volume contract and preserve exact cleanup and categorical proof.

**Architecture:** Keep the existing `worker-physical-once` workflow, digest, release and owner authorization; extend only its Python host harness with uniquely labeled one-use ephemeral volume creation, trusted UID10002 initialization, positive identity inspection and compensation. The worker's immutable image and BLACKBOX remain untouched.

**Tech Stack:** Python 3.12, Docker rootless UID10001, GitHub Actions, offline Python regression tests.

**Spec:** `docs/superpowers/specs/2026-11-10-boca-worker-volume-proof-design.md`

## Global Constraints

- No source inspection/import/testing/modification of `synthetic.py` or `ipc_worker.py`.
- No host operations except the dedicated Boca Action, with explicit UID10001 socket and one-shot owner gate.
- No installed volume, controller, worker, port, app data or unrelated resource changes.
- Preserve `boca.socios.physical-*` labels, immutable image digest, seccomp, memory/CPU/PIDs, healthcheck and prearmed capture.
- No blind retry and no Cutover until physically HEALTHY and exact stop prove P0.

## Review Focus

1. Existing volume with probe-like name but wrong labels must be preserved and prevent START.
2. Lost create/start ACK must trigger only positively identified resource cleanup; never attempt a second worker START.
3. The named volume must be initialized UID/GID10002 mode0711 through bounded rootless helper and validated before worker create.
4. Failed worker health must still remove owned CID, initializer and dedicated volume and retain image cache.
5. A successful worker start with a non-equivalent tmpfs, bind or rootful mount must be rejected before reporting health.

---

### Task 1: Volume-equivalent Docker contract

**Files:** Modify `src/boca_socios/host_worker_physical.py`; test `tests/test_host_worker_physical.py` and new stdlib-only `tests/test_r158_volume_proof.py`.

**Interfaces:** `create_argv(run_id, seccomp_path)` retains its public signature. Add private helpers `_volume_name`, `_check_volume`, `_create_volume`, `_initialize_volume`, `_cleanup_volume`.

- [x] Write tests asserting named volume mount, absence of IPC tmpfs, exact labels/identity, and fail-closed preexisting-resource behavior.
- [x] Run stdlib tests: observe RED due to absent `_volume_name`/contract.
- [x] Implement ephemeral volume lifecycle and equivalent Docker create/inspect contract without changing protected blackbox files.
- [x] Run stdlib tests: observe GREEN. Validate syntax.

### Task 2: One-shot cleanup and receipt

**Files:** Modify `src/boca_socios/host_worker_physical.py`; test `tests/test_r158_volume_proof.py`, `tests/test_host_worker_physical.py`.

**Interfaces:** `_diagnose(run_id)` preserves entrypoint and categorical receipt; `_claim_once` creates a distinct volume-differential marker, never deletes #937 claim. `_exact_cleanup` and volume compensation operate on positive identities only.

- [x] Write tests for both success and failure of exact-CID worker cleanup, initializer compensation, volume removal, and new claim anti-replay.
- [x] Verify RED; implement minimal guarded logic; verify GREEN and run all available relevant tests.
- [x] Keep receipt schema parseable by host/runner verification and do not expose raw worker output.

### Task 3: CI and physical evidence

**Files:** Modify `tests/test_host_worker_physical.py` (existing contract assertions), this plan and spec; no new workflow or unapproved command input.

- [x] Verify changed files are limited to preapproved `check_worker_physical_dispatch.py` ancestry allowlist or `docs/superpowers/**`.
- [ ] Review exact diff and anti-replay/cleanup scope; publish one short-lived feature PR and run required exact-SHA Actions gates.
- [ ] Merge only after review and exact-SHA CI success; verify PR0; dispatch exactly one `worker-physical-once` under owner gate from new main SHA.
- [ ] Read physical categorical receipt and rootless stop/cleanup; document H1 outcome, SHA/run and next gate in #417 and delivery state #45, without inventing HEALTHY.
