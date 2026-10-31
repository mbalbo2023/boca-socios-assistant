# ADR 0044: retain executed regressions from accepted RCA lessons

**Status:** Proposed for issue #112, 2026-10-31. CI-only; no host or release
operation.

## Problem and decision

RCA findings already led to concrete fixes for rootless key custody (#80),
release digest provenance (#88) and the dedicated host identity and storage
capacity gate (#90). A later refactor could remove the corresponding tests
while general lint and type checks remain green. A written lesson alone does
not make that regression detectable.

Maintain a small, reviewed, machine-readable register under
`docs/quality/rca-lessons.json`. Each entry cites the issue, fixing PR,
root cause, prevention and exact pytest selectors. The quality job runs the
full suite once, records JUnit XML, and validates that every accepted selector
was actually executed and passed. Skipped, xfailed, duplicate or malformed
results fail the job. The checker compares the register with `HEAD^1`: for a
pull request merge candidate that is the base branch; on a main push it is
the prior main commit. Accepted IDs and regression selectors cannot be
silently removed. Checkout retains two commits for this local comparison;
the job does not need a token, external service or runtime credential.

After a reproduced defect, record its cause and a failing test before the
fix, then add the verified selector to this register in the reviewed PR.
CI prints a compact lesson/test count. A failure yields a specific lesson
and selector for a new RCA or fix-forward PR. This is an automatic check of
retained learning, not an agent that writes or merges code unattended.

## Boundaries

The register is bounded and accepts only test selectors inside this repository.
It contains no secrets, host addresses, account data or runtime traces. A PR
that edits this checker itself still requires technical review and exact-SHA
checks; the checker cannot prove its own implementation is honest. The first
commit introducing the register has no accepted baseline. The gate proves
that listed regressions passed in CI, not that every possible defect has a
test or that a runner reproduces the rootless production host. No deployment
or third-party traffic is triggered by this decision.
