# R299 Telegram runner import implementation plan

> **For agentic workers:** Use superpowers:subagent-driven-development for the
> scoped implementation and independent review. The owner already authorized
> autonomous completion of this delivery; do not request the same project GO.

**Goal:** Let the existing pre-SSH main-ref guard run from the exact checkout
without changing its rejection behavior or the installed BETA.

**Architecture:** Add `PYTHONPATH: src` only to the installed Telegram step.
Keep its shell body and checker unchanged. The protected ZIP still runs with
`-I -S -B`; workflow source W and installed source M remain separate.

**Tech stack:** GitHub Actions YAML, Bash, Python standard library and existing
pytest. Reuse the test module's stdlib step extraction; no new dependency or image.

**Spec:** [RCA-519](https://github.com/mbalbo2023/boca-socios-assistant/issues/519),
[incident](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6890465743)
and [four pre-code votes](https://github.com/mbalbo2023/boca-socios-assistant/issues/417#issuecomment-6890476164).
ADR0301 remains the installed Telegram transaction contract.

## Global constraints

- Base N: `2581e23bbbb8b4a05fb2470a23b3c71866378151`.
- Installed M: `5281efae7dafe89be047073796b3e0a7e19785ed`, release866
  `43680526402`; retain both immutable image references and CIDs.
- SIMULATION_ONLY; BLACKBOX unread/unmodified; no provider navigation/messages.
- Preserve main-only, exact SHA/ancestry, gates, lease, SSH identity, timeouts,
  isolated verifier, caps, data and unrelated Porota/PPI workloads.
- No second release/APPLY/admin/STATUS. TG1139/1140 remain failed before SSH.
- Only protected serialized Actions may perform the eventual prepare.

## Review focus

1. A clean runner must not inherit pytest's installed/editable package.
2. Current main W must pass even when installed M differs.
3. Stale main must fail semantically before the next effect boundary.
4. Invalid JSON must fail through the real checker, not an import failure.
5. An invalid main-ref object must also fail before that boundary.

## Task 1: Restore the step-local import and retain the guard

**Author files:** `.github/workflows/boca-first-deploy.yml` and
`tests/test_main_ref_gate.py` only.

**Interface:** Consume the actual step named
`Execute installed Telegram transaction under one protected lease`, its env,
`set -e` and checker command. Execute the unchanged checker in a clean child
process with main-ref fixtures and a harmless marker after the check; never
execute SSH or replace the checker with a mock.

- [x] Add one parametrized regression covering the five review concerns.
  Current-main: exit0, `BOCA_MAIN_REF_PASS`, marker reached. Stale, malformed
  JSON and malformed object: exit1, `BOCA_NO_GO`, marker absent. Every case
  excludes `ModuleNotFoundError` as an acceptable result.
- [x] Run the new regression against the unchanged workflow and record RED.
- [x] Add only `PYTHONPATH: src` to that step's env. Preserve all other bytes
  of the step and the checker.
- [x] Run the new regression and affected main-ref module with the existing
  frozen environment; record GREEN. Check scoped lint/format/diff.
- [x] Return exact paths, hashes and results; do not commit or operate host.

## Task 2: Review, document and continue the installed phase

**Root files:** factual current headers in AGENTS, README, development policy,
operations, delivery plan, integration status and roadmap; this plan and
`docs/quality/rca-lessons.json`. Preserve historical cuts under explicit labels.

- [x] Add RCA-519 with actual regression selectors. Record STATUS1138 accepted,
  ENV_READY configuration and distinct pre-SSH failures1139/1140 accurately.
- [ ] Obtain final Product/Security, Architecture, QA and Operations votes on
  the actual delta; the author does not approve their own implementation.
- [ ] Publish one atomic maintenance commit and convert issue519 into its PR.
  Complete required CI on the exact candidate, then protected expected-head
  merge. Verify main checks and zero open PRs before the next host action.
- [ ] Dispatch one new `telegram-prepare` with installed M/release866/digests,
  service controller and `1.5cpu-1024m-192pids`; all other text inputs blank.
- [ ] Accept only the real strict receipt: PREPARED,
  CONTROLLER_HEALTHY_ENGINE_OFF, sender OFF, human receipt UNVERIFIED.
  Another failure requires evidence/RCA, never an automatic retry.
- [ ] Update GitHub with the actual outcome and private acceptance still
  pending. Do not claim Samsung acceptance or physical capacity of 50 from CI.

## Execution evidence

The author recorded four RED cases against the unchanged workflow, then all
13 affected main-ref cases PASS after the single env line. Scoped Ruff,
format and diff checks passed. The implementation adds no dependency;
the regression never executes SSH. Four pre-code votes are recorded. Final independent
review, exact-SHA CI and physical prepare remain pending at this source cut;
subsequent immutable GitHub evidence records results.
