# R116 — Cutover IPC / Telegram staging parity design

Date: 2026-11-08 ART. Scope: #354 (integration), #417 (Cutover incident), #45 (continuity).
Status: APPROVED BETA preparation scope; CODE_ONLY. No physical host operation.

## Intent and evidence

The owner chose the integral BETA and the existing single-dispatch Cutover V3.
The approved `compose.beta.browser.yaml` enables
`BOCA_TELEGRAM_PAIRING_STAGE_MODE=encrypted-only` only in its IPC controller.
The effective V3 container is instead created by
`host_first_deploy._cutover_candidate_create_argv`, which omits that
environment entry. `Settings.from_environment` defaults staging to `off`, and the
runtime does not configure the encrypted staging callback in that mode.
`_browser_controller_postflight` also omits this setting from its inspected
environment assertions. Thus a successful worker would not imply a working
Telegram pairing stage. This gap is a **code-level inference**, not the cause
of the observed `PREPARE_WORKER/HEALTH_EXITED` / `ExitCode=1`.

## Goals and boundaries

1. Require exactly `encrypted-only` when V3 creates the IPC controller.
2. Verify that **effective Docker Config.Env**, not merely the Compose model,
   has the exact value, failing closed if absent, invalid or duplicated.
3. Preserve all existing runtime and isolation fields, loopback 8443, key/data/
   owner/IPC mounts, simulation engine OFF, sender OFF and rootless gates.
4. Prove the behavior with deterministic Docker-command and inspect-record
   regressions; no host, Docker or website execution in this change.

Out of scope: blackbox `browser/synthetic.py` and `browser/ipc_worker.py`
contents or execution; worker crash RCA; Telegram sender activation, Bot API,
owner pairing, new infrastructure, host read/write, real reservations,
additional ports or unrelated workload cleanup. The existing legacy
`compose.beta.yaml` must keep staging disabled.

## Approaches

- **Compose-only:** already present, insufficient because V3 uses direct
  `docker create`, not Compose to create this controller. Rejected.
- **V3 argv + inspect parity (selected):** add the one literal opt-in to
  the real creation path and assert it in the existing postflight. Reuse
  current parsing and isolation gates; no new deploy path.
- **New wrapper or activation workflow:** duplicates a trusted entrypoint and
  adds orchestration/authority risk. Rejected.

## Acceptance and failure behavior

The candidate Docker argv contains the exact environment opt-in. For a
complete, otherwise valid synthetic Docker inspection, postflight accepts
`encrypted-only` and rejects absent, `off`, any other value, or duplicated
keys with `PreflightError`. Existing Compose and runtime opt-in regressions
remain green. Any actual host Cutover remains NO_GO until the worker has
independently evidenced startup health, all existing gates pass and terminal
cleanup/host ACK is verified. No retry of a failed Cutover.
