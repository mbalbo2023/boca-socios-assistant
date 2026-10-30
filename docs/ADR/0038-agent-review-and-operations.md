# ADR 0038: agent review and objective Boca operation gates

**Status:** Accepted by owner direction, 2026-10-29. Policy-only; no host
operation, image publication or merge occurred in this decision.

## Decision

The owner assigned technical review to the agent and removed the requirement
for another human's approval. Each scoped PR still needs a recorded review of
code, tests, threat boundaries and limitations, exact-SHA required checks and
resolved findings. GitHub's ruleset can require zero approving reviews while
keeping PRs, checks, linear history and conversation resolution. An agent's
review under the owner's GitHub account must never be called an independent
human approval.

The owner's standing direction permits autonomous dispatch of the sole manual
Boca Actions workflow when it is integrated on main and exact inputs, pinned
SSH, protected environment, rootless isolation, capacity and resource limits
are proven. Release and install remain separate recorded decisions; merging
cannot trigger host work. This delegation does not enable live login, Queue-it
interaction or ticket purchases. Failure is NO_GO for the failing operation;
no automatic retry or concurrent host writer is allowed.

Parallel read-only audits and nonoverlapping scoped writers are preferred.
Only one Boca deployment operation holds the host lock. After a failed
operation, Actions should inventory and clean only identifiable unused Boca
artifacts, measure disk/inodes before and after and preserve volumes, keys,
data and uncertain resources. No broad prune or unrelated workload access.

An external-source incident first gets a bounded, read-only Actions check.
Source health appears as a timestamped green/yellow/red/unknown alert. A
source outage neither blocks a safe simulation-only deployment nor justifies
a new one. A proven code defect receives a scoped fix and fresh exact-SHA CI.
The live integration remains disabled, and a source-health alarm cannot
override security, release provenance, rootless or capacity gates.

Historical ADRs remain evidence of their earlier decisions. This ADR
supersedes their human-approval wording for future work; it does not claim
that the proposed Actions workflow, cleanup or source diagnostic is already
integrated or that the droplet has passed a preflight.
