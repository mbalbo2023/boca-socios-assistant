# R79 — Exact stopped-worker recovery plan

> For agentic workers: use `superpowers:executing-plans`, TDD and independent review before merging.

## Decision and evidence

- Physical receipt: [Boca first deploy #802](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/42337103473), source tree `88971f5a2cacfe90db6a622025fd5b31a96bbb64`.
- The failed #795 probe is **present and stopped** at CID `65d844edb438710f44ce83c397906932710ad7f04f3e7a52634f9eaaf1fcc504`.
- Exact historical attempt/source/browser digest matched, full JSON serialization is below 65536 bytes, temporary seccomp file is absent, rootless socket is owned, legacy CID is healthy on loopback 8443.
- These facts justify *designing* a one-shot repair; `PRESENT_PIN_MATCH` is not itself an authority to delete. R78 observer cannot write, and the historic physical RCA is still incomplete.
- Independent QA, Architecture and Infra all recommend an **isolated** `cutover-a-worker-recover` operation, never `_cleanup_exact` (it can stop a worker and re-resolves by name).

## Immutable scope

- Only GitHub Actions + the existing protected `boca-first-deploy` Environment/SSH, on exact reviewed `main` and authorized actor, run_attempt=1.
- No modification of either browser BLACKBOX; no other app, Docker daemon, image, network, volume, controller or port.
- The only container effect allowed is one `docker container rm` without force/volumes on **that full fixed CID** and only when stopped after a fresh same-lease audit. A cooperative Boca lease may create its fixed lock inode.
- Do not run the #795 preflight or Cutover as a cleanup workaround; no automatic retry after an ambiguous outcome.
- A recovery ACK only proves cleanup. It never grants Cutover GO, new PREPARE or APPLY.

## Architecture

1. Reuse the R78 narrow rootless observer and its bounded subprocess runner. Keep `_docker` strictly READ_ONLY.
2. Create `scripts/host_cutover_worker_recovery.py` with exact constants, fresh in-lease preflight and full stopped-worker isolation checks, one exact-ID `rm`, independent postflight by name+ID and healthy original, plus canonical bounded receipt.
3. Because the full legacy memfd package is already **858036/860000 bytes**, do not enlarge or weaken its cap. Create an **additional minimal, separately allowlisted recovery-only ZIP variant** using the existing SHA-verified memfd bootstrap. Retain unchanged limits and entry set for the full package, with a smaller dedicated recovery cap. No source bundle on the host filesystem.
4. Add the one new operation to the existing workflow, not a second host deployment workflow. Assert incident, original pins, environment, actor, main, budget, zero open PRs, and all other inputs blank; only then SSH the reviewed ZIP. Strict runner receipt verifier and `always()` failure summary.
5. Exercise one stopped, synthetic disposable Docker fixture only on a GitHub-hosted runner, never production. Preserve existing required contexts and all security gates.

## TDD and release checklist

- [x] RED regressions: wrong CID/name/project/source/image, running/restarting, mounts, ports, networks, privileges, seccomp/restart changes, rootless/lease failure, legacy degraded, ambiguous Docker data, late identity change.
- [x] RED regressions: no effect on any refusal, exactly one `rm` with fixed CID on positive path, no stop/force/prune, timeout/rc/ACK ambiguity, second dispatch rejected, postflight name+CID and original health.
- [x] GREEN implementation and bounded canonical receipt tests. Verify standalone minimal ZIP, SHA tamper rejection, strict entry set/size limits, BLACKBOX exclusion.
- [x] Local: 4234 pytest+34 subtests, Ruff, MyPy 138 files, repo policy, 44 RCA lessons/146 selectors/11 BLACKBOX guard all PASS. GitHub-hosted Docker fixture still needs the exact-SHA CI run.
- [ ] Independent QA, Architecture and Infra unanimously approved CODE_ONLY (0 Critical/Important); publication of PR, four exact-SHA Actions, merge, 0 PR and postmerge CI/security remain pending.
- [ ] Only then dispatch one protected recovery, inspect its real receipt and **never** turn an uncertain ACK into success or a retry.
- [ ] Update #417, #45 and ADR evidence after each material outcome; any follow-on worker preflight/release/Cutover is separately validated and gated.
