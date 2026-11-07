# R86 — Exact #819 worker READ_ONLY inventory (design)

**Date:** 2026-11-07 ART. **Owner:** #417, continuity #45. **Scope:** CODE_ONLY until reviewed PR/merge and independently dispatched protected observation.

## Intent and evidence

The one-shot [worker preflight #819](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42353468231) on `main=0538b3fb29cc0245a8387b7023c394883d0ea9a8` failed with the bounded claim `phase=CLEANUP cleanup=INDETERMINATE primary_failed_phase=NONE cleanup_failed_stage=STOP`. It does not prove that the temporary worker was removed or that the original controller remained healthy. The protected runner explicitly marked the host claim `UNVERIFIED`. No retry of #819, worker preflight, GO_B, PREPARE, APPLY or recovery is permitted before exact physical inventory.

## Alternatives considered

1. The general `cutover-a-observe` requires worker absence and would conceal a surviving probe's identity. Insufficient.
2. A new ad hoc Docker inspector/workflow duplicates validated code and expands the trusted surface. Rejected.
3. **Chosen:** extend `cutover-a-worker-inspect` and `scripts/host_cutover_worker_inspect.py` with a third *hardcoded* failed-attempt mapping. Preserve all R78/R81 read-only operations, bounded receipts and previous incident behavior.

## Fixed inputs and implementation boundary

- Attempt `42353468231`, probe name `boca-socios-cutover-preflight-42353468231`, image source SHA `0538b3fb29cc0245a8387b7023c394883d0ea9a8`.
- Browser digest from paired [release #732](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42352641660): `ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:d740c610d032aa20fecff1602cc96e49fd63c597c49855990a9bc081a6998619`.
- Legacy original CID `27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793`, source `cabce9f1e452e63ded115f447559a358dc0f4d1b`, controller digest `ghcr.io/mbalbo2023/boca-socios-assistant@sha256:cf6e4266cfcfea0c07fa31301d59c7aaa3b9c2fefb9f6843baddd208cacd3b59`.
- Existing protected manual GitHub Actions workflow, only `cutover-a-worker-inspect`, `protected_action_context=42353468231`, `service=controller`, `resource_budget=1.5cpu-1024m-192pids`; no other inputs. No operator host shell.
- Preserve UID/GID `10001`, its sole rootless Docker socket, exact-name `ps`, compact `inspect`, full inspect **length only**, `lstat` of one seccomp file, immutable legacy inspection, bounded stdout/stderr/deadlines, canonical receipt v3 of at most 2048 bytes. Never expose Env/Mounts, secrets, extra namespace, network data or an arbitrary CID.
- All outputs remain `READ_ONLY_NO_GO`, `observer_writes=0`, `cutover_authorized=false`, even with absent probe and healthy legacy. No `docker stop`, `rm`, `start`, `pull`, `exec` or `prune` and no touches to foreign Docker or BLACKBOX.

## Acceptance and ownership

QA/Architecture/Infra independently supported this exact minimal diagnostic after #819. Tests must demonstrate `RUNNING`, `STOPPED`, `ABSENT`, mismatch, fault/timeout, seccomp and legacy independence, rejection of unrelated IDs, and preservation of #795/#807 behavior. The inspector module is also packaged by the historical *recovery* bundle: acknowledge its ZIP digest change, recertify its allowlist/tests and **never** add #819 to any effectful recovery target.

After PR, exact-SHA gates and a zero-open-PR merge, a separate single READ_ONLY Actions dispatch may record host evidence. The physical outcome selects a later design; an absent probe is not retroactive PASS for #819, nor authorization for another worker preflight or Cutover.
