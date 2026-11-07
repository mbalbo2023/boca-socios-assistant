# R87 design — exact stopped-only recovery of worker #819

**Owner:** issue #417; continuity issue #45. **Date:** 2026-11-07 ART.
**Status:** CODE_ONLY design; physical cleanup remains NO_GO pending exact-SHA tests, reviews and independent GO.

## Evidence and decision

Preflight #819 / run `42353468231` at source `0538b3fb29cc0245a8387b7023c394883d0ea9a8` exited with `CLEANUP/INDETERMINATE` at `STOP`. The protected, single read-only inventory #821 / run `42355552701` at main `2859b9d31621e3cbec70b1aec649cc281ba130f5` found:

- `probe=PRESENT_PIN_MATCH`, `probe_running=false`, `probe_id=4c2c40eaa7183e83440792466e844093a29c8b977e72c098c7be6a469f066547`;
- `socket=PRESENT_OWNED`, `docker=OBSERVED`, probe list/inspect stages `OK`, full JSON below cleanup limit, `seccomp=ABSENT`;
- original legacy CID `27ef39ed49d2b258526d4f9d24d1fc50bdb7567279e20f977ef9cd69a0a40793` `RUNNING_HEALTHY`, `LOOPBACK_8443`, `observer_writes=0`, `foreign_resources_touched=false`.

This is consistent with an eventual stop effect but does not prove why STOP originally failed. Historical #819 remains NO_GO.

Reuse the existing R80/R82 stopped-only recovery module, **not** a duplicate cleanup service. Add one immutable `TARGET_819` object and one distinct protected `cutover-a-worker-recover-819` workflow choice. No free-form host coordinates or new release/build/privilege surface.

## Exact identity and isolation

- Failed attempt `42353468231`, witness `42355552701`, release #732 `42352641660`.
- Worker CID `4c2c40eaa7183e83440792466e844093a29c8b977e72c098c7be6a469f066547`, name `boca-socios-cutover-preflight-42353468231`, source SHA `0538b3fb29cc0245a8387b7023c394883d0ea9a8`.
- Worker OCI `ghcr.io/mbalbo2023/boca-socios-assistant-browser@sha256:d740c610d032aa20fecff1602cc96e49fd63c597c49855990a9bc081a6998619`.
- Legacy CID, SHA and image pinned to their R86 values; full seccomp profile SHA256 `cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849` required for **both** #807 and #819.

The existing recovery acquires a Boca-only rootless lease, executes two full independent snapshots and full JSON Docker isolation checks, then at most **one** `docker container rm <pinned 64-hex CID>` (no force, no stop, no volume, network, image or foreign workload operations). It requires a CID absence check, new namespace/legacy observation and canonical verified receipt before declaring cleanup. Any error or lost acknowledgement is indeterminate with **no retry**.

## Protected dispatch and receipt

Runner checks owner/main/attempt1/environment/PR0 and current HEAD before host SSH; hard-pins a failed #819, successful read-only #821, successful dual release #732, their exact jobs/steps and a unique one-time R87 dispatch. Other input fields must be empty; service controller, budget 1.5cpu-1024m-192pids. Extend the seven-file `--worker-recovery` ZIP/memfd mode (caps unchanged) and terminal verifier; exclude blackbox and full Cutover sources.

Harden the runner recovery receipt like R85/R86: random private capture directory, `umask 077`, enforced file-size limit **before** SSH, no stdout/stderr leak, terminal verification and point-specific cleanup. The only published artifact is the independently verified bounded receipt.

## Functional QA obligations

1. Exact stopped #819 + healthy legacy + seccomp absent → a single non-force `docker container rm` by full CID and postcheck.
2. Running/renamed/foreign/wrong label/image/source/CID, extra mounts, unexpected privileges/security opt, unhealthy legacy, seccomp residual, oversize or malformed JSON → **zero writes**, fail closed.
3. Failed/missing/ambiguous remove acknowledgement or absent postflight → `INDETERMINATE`, exactly one or fewer writes, **no automatic retry**.
4. Recovery R80/R82 historical targets and terminal verification remain unchanged; fabricated target rejected. Bundle remains exactly seven files within caps.
5. GitHub gate rejects wrong/missing/duplicate history, wrong actor/sha/release, any nonread-only witness step, open PR, second attempt, wrong main or any extra input **before SSH**.
6. Runner capture withstands forged paths, oversized output, SSH errors and cleanup failures without secrets or unsafe fallback.

GO CODE_ONLY for implementation requires full local checks and independent Architecture/Infra/QA review; physically removing the one stopped container requires a **new exact GO**, 0 open PR, successful push CI/Security and fixed Action provenance. Even verified cleanup does not authorize worker preflight, PREPARE, GO_B or Cutover.
