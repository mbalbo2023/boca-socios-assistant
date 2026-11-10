# Boca W1: one physical worker diagnosis, no Cutover

Owner scope: one owner-dispatched protected Boca GitHub Action, no new release,
no host install, no Cutover, no changes to the live controller or engine.
The only authorized effect is a single start of the *already installed* worker,
followed by exact-CID stop if necessary. No navigation, reservations, Telegram,
or Docker operations against Porota or the rootful daemon.

## Evidence and separation

- Run #890 verified Boca's dedicated UID 10001/rootless daemon.
- Run #899 started a worker that exited with `ExitCode=1`, OOM false and
  `MODULE_NOT_FOUND_ERROR`. The module name was not retained.
- Cutover #926 installed source `03df9a14bdd78cf768386a865876fed9d5656911`.
- #927/#928 confirmed a healthy controller, engine stopped and worker created.
- A later workflow-only SHA is **not** the installed image's source SHA.
  Require both independently, never infer that a permission error caused the
  process exception.

## W1 protocol

1. Only `mbalbo2023` manually selects `worker-diagnose-once` on current `main`,
   first run attempt, with all extra pins/envelopes blank and a bounded budget.
   GitHub REST must prove the historical successful #926 run and no earlier W1
   run before SSH. The protected `boca-first-deploy` concurrency lease applies.
2. Reuse the existing pinned SSH `boca-deploy` identity, strict known_hosts,
   digest-checked memfd ZIP. No arbitrary SSH command, no sudo.
3. Host verifies UID/GID 10001, dedicated rootless daemon, installed binding,
   original #926 source and run, exact worker CID/image/config and the whole
   Boca pair. Check controller HEALTHY, engine STOPPED, worker created/PID0,
   no pending operation. Fail closed if any part differs.
4. Use the already reviewed `start_worker()` attachment (pre-armed before the
   exact Docker start). Preserve its categorical failure evidence and extract
   *only* a syntactically bounded Python dotted module name from the last
   physical stderr line; no raw logs, stdout, paths or environment variables.
5. Always stop that exact CID if running, and verify an unchanged healthy
   controller, engine STOPPED, and worker PID0 under the same Boca-only lease.
   A missing postcondition is **UNCERTAIN**, never green. One dispatch means
   one start, no automatic retry.
6. Return a bounded JSON receipt (category, safe module identifier if certain,
   exit code/OOM, poststate), independently verified on the runner. No raw
   Docker or process output crosses the SSH boundary.

## Tradeoff

The host may be unreachable after a runner timeout; in that case do not claim
cleanup or repeat startup. Continue only with a separate authorized targeted
recovery after new evidence. Avoid creating files in the strict
`.boca-on-demand` allowlisted directory. Blackbox `synthetic.py` and
`ipc_worker.py` remain uninspected and unchanged.
