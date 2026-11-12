# R189 — retained observer fix-forward

Initial base: `95591d33134cf055f73f8739d51f9bb742064ee9`. Scope #417, code only.
Integration base after PR #491: `1089de83492d517ca67979dba9c7a34436ffc376`.
The two local R189 commits were rebased without conflicts; the retired CI
runtime-smoke job remains absent. Only the existing validation catalog and
the retained-observer step differ from the protected workflow on that base.
R188 run `43274319171`, job `131378566255`, failed after main verification.
The discarded host diagnostics do not prove the first failed host predicate.

1. RED: reproduce DockerRootDir JSON plus trailing LF against real temporary
   directories; reject wrong roots, malformed JSON and symlink ancestors.
2. GREEN: decode only the DockerRootDir JSON scalar and compare the exact path.
   Keep mountpoint, rootless boundary and no-follow metadata-only access.
3. RED/GREEN: fixed typed failure phases, bound to the observation run, with
   canonical bounded serialization. Never serialize exception text or values.
4. RED/GREEN: runner consumes bounded stdout/stderr and remote status. Recognize
   only canonical host failure or the exact existing bootstrap failure marker;
   otherwise report transport unverified. A nonzero remote status never passes.
5. Execute the actual workflow step offline with controlled SSH failures,
   forged success, secret-bearing error noise and success receipts.
6. Run focused/full tests, lint, format, types, policy and diff checks. Commit
   locally for independent review; no push, PR, host dispatch or retries here.

No R186, actor, resource ownership, image alias, network peer, credentials,
navigation or successor-authorization changes. CI fastpath has another owner.
New physical observation can occur only after reviewed PR and exact-SHA gates.

Protected validation catalog follow-up: include the R189 failure regressions
in the existing installed-pair offline step. A test executes pytest collection
from that actual catalog command and fails when the LF/typed-host-summary
regressions are absent. The catalog is a plain pytest argv list, not a hashed
manifest. No additional workflow, host operation or selector is introduced.
