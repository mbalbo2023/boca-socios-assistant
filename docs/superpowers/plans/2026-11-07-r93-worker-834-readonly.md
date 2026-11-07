# R93 implementation plan — exact READ_ONLY inventory of worker #834

**Scope:** code-only extension to existing worker inspector; ownership #417/#45.
**Evidence:** failed protected run `42375050546` on `main=79da7ebe9918d98216ac7eb46ff008d7f6e62429`, STOP ACK_MULTILINE, cleanup INDETERMINATE.

1. Add failing RED test for immutable run/source/browser pins and protected workflow context. Assert recovery allowlist does *not* admit #834, and inspector remains read-only.
2. Add a single immutable mapping to the existing inspector and one shell `case` to the existing protected READ_ONLY operation. Do not modify any host mutation path or blackbox modules.
3. Run targeted tests and full repository checks, inspect diff, obtain independent QA/Architecture/Infra GO, merge a single PR, reconcile zero open PRs and postmerge CI/security.
4. Dispatch exactly one `cutover-a-worker-inspect` on new `main` with context `42375050546`, exact historical legacy pins and no optional image/release fields, via authenticated GitHub Actions only.
5. Publish canonical receipt to #417 and #45. Stop at NO_GO if probe is running or uncertain. If stopped pin-match, a separate reviewed recovery is mandatory before any new release/preflight. NEVER repeat #834.

**STOP hypothesis:** Docker CLI v28 deprecates `--time`, and Cobra may put a warning on stdout together with CID; R93 does not change STOP behavior. Version and original stdout bytes not measured on host. Follow-on independent R94 can TDD `docker stop -t 5` without altering ACK acceptance after exact physical inventory.
