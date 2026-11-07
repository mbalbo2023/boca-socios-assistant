# R87 implementation plan — one stopped Boca probe #819

1. Reconcile GitHub #45/#417, main/PR0, prior observer #821 typed receipt and existing R80/R82 code/tests/ZIP; preserve ownership and no duplicate issue/workflow.
2. **TDD RED:** write R87 tests for immutable target and host/verify modes, old-mode preservation, exact stopped-only snapshot/remove, seccomp SHA, runner admission and REST history/jobs/PR0, private bounded receipt, package seven-entry constraints.
3. **TDD GREEN:** minimally extend existing recovery, dispatch gate, workflow choice/route, ZIP `__main__` and memfd mode. No host access or calls to real Boca/Telegram/blackbox/other Docker.
4. Run focused regressions plus full pytest/Ruff/mypy/repo policy, protected package hashes/entry bounds. Independent QA, Architecture, Infra and code review with 0 Critical/Important before PR.
5. Publish one atomic draft PR on exact main; wait all required exact-SHA Actions; merge only with checked lease; verify `main`, PR0 and postmerge CI/Security; document every milestone in #45/#417.
6. Only after **independent 3/3 GO for one physical recovery**, use GitHub Actions guarded `cutover-a-worker-recover-819` once, with all optional dispatch inputs blank. Validate success receipt/one write/no retry and preferably independent subsequent READ_ONLY #819 observation. On any ambiguous outcome stop effects, record RCA, fix-forward in code without blind retry.
7. Reassess worker preflight STOP root cause and next Cutover gates from physical evidence; no deployment claim until genuine protected PREPARE/GO_B/APPLY terminal ACK and postflight.
