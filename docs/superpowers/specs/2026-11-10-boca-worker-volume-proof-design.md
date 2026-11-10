# R158 — Boca worker volume-equivalent physical proof

## Decision and evidence

Issue #417 R155–R157 documents an actual one-start worker probe on the Boca
rootless daemon: #937 created/started corrected OCI browser image #810, then
observed `ExitCode=0`, `STDOUT_ONLY`, no `HEALTHY`, and verified exact-CID
removal. The image remained in the Boca rootless cache. The image's effective
ENTRYPOINT/CMD/PYTHONPATH were verified externally without inspecting the
owner-controlled blackbox files.

The #937 harness used a Docker `tmpfs` at `/run/boca-browser-ipc`, while the
installed Compose contract uses a separate, owner-verified Docker named volume
with UID:GID 10002:10002 and directory mode 0711. **This difference is a
falsifiable hypothesis, not a demonstrated cause of exit zero.**

## Scope and non-goals

- Prepare one new physical observation using a new, uniquely labeled **Boca-only
  disposable volume** that reproduces the installed worker's IPC mount kind.
- Match the installed Compose worker's **default volume copy-up** semantics;
  only the existing one-shot UID10002 volume initializer uses
  `volume-nocopy`, exactly as the installer does. A successful probe must not
  silently rely on a different mount option.
- Reuse corrected immutable browser image #810, rootless UID10001 socket,
  worker UID10002, seccomp/cgroup/network-none controls, and prearmed bounded
  Engine output-class capture already reviewed in PR #469.
- Enforce a new durable once-only **volume-differential** claim without erasing
  or reusing the old #937 claim. Distinguish claim from a repair or deployment.
- Stop/remove only positively identified ephemeral probe containers and the
  new probe volume. Prove the installed controller, worker, engine and data are
  unchanged. Retain image cache.
- Print only the fixed, redacted, schema-checked result. Never expose raw
  stdout, stderr, credentials or host paths in GitHub summaries.
- Do **not** open/import/test/alter `synthetic.py` or `ipc_worker.py` as source;
  production startup is the only authorized blackbox execution boundary.
- Do **not** do Cutover, change the installed worker, touch Porota, rootful
  Docker, ports, controller, app data, PPI Watch or other workloads.

## Approaches considered

1. A manual ad-hoc terminal command: no PR, but no authenticated Boca terminal
   is exposed to this session, and a safe volume-init/compensation sequence is
   not a simple command.
2. **Correct the existing physical test harness** (selected): preserve its
   reviewed Action, source/release/owner/PR0/CI gates and prearmed capture,
   while replacing its non-equivalent IPC mount with a disposable named volume,
   positive ownership checks and cleanup. A tested source change is required.
3. Introduce another workflow: duplicates owner gates and risks unreviewed
   host access; rejected.

## Acceptance and decision gate

- Exact-SHA PR CI, source/image/actor gate, zero open PRs before one owner
  workflow dispatch, one fresh volume-differential claim, rootless identity,
  volume ownership and kernel boundary verified.
- If one physical boot reaches `HEALTHY`, prove socket, exact stop and selective
  cleanup with post-state controller/worker unchanged. This settles only this
  hypothesis; next investigate Cutover/ADR0223 independently.
- If it exits zero again or fails other checks, preserve the categorical
  evidence, label H1 disproved or unconfirmed as appropriate, and do not retry,
  declare P0 solved or execute Cutover.

Owner-approved scope: R155 physical P0 RCA and the 2026-11-10 instruction to
advance and document the solution. This design does not imply owner approval
for real reservations or any other host operation.
