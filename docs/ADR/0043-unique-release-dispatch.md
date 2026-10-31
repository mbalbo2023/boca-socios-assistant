# ADR 0043: reject duplicate fresh image-release dispatches

**Status:** Proposed for issue #115, 2026-10-31. No GHCR publication or host
operation was performed for this change.

## Root cause and decision

Issue #98 rejects reruns and stale `main`, but two newly dispatched release
workflow runs for the same SHA each have attempt 1. The existing concurrency
group serializes their publish jobs, yet the second could repush the mutable
`sha-<SHA>` tag and consume registry space. The image digest manifest binds a
later first-install to a scanned release; it does not make tag publication
idempotent.

Before build and again after scanning, before registry login, query the GitHub
Actions history of the exact `release-image.yml` workflow with filters
`event=workflow_dispatch` and `head_sha=$GITHUB_SHA`, requesting at most two
runs. The bounded verifier accepts only `total_count=1` and a sole run with
the current ID, SHA, event, branch `main` and attempt 1. A duplicate, absent
current run, delayed indexing, malformed response, API error or unavailable
Actions read permission is NO-GO. The publish job has `actions: read` and
continues to use a checkout without persisted credentials. No GHCR auth or
push can occur after a failed check. A new dispatch following a failed run
of the same SHA is also denied; fix forward with a reviewed source SHA.

The second query narrows the race if another dispatch is created during build
or scan. The main-ref check from ADR 0041 is still separate. This history
gate is not a compare-and-swap on GHCR tags, cannot exclude an external push
to the same tag, and is not atomic with a later movement of `main`. A
registry-side authenticated tag check may add defense once it can be proven
under an isolated test; an unauthenticated 404 cannot establish absence.
First-install keeps its independent exact digest, release-run and main gates.

PR validation builds and scans only a disposable runner image. Unit tests
exercise 0/1/2 results, mismatches, malformed or oversized responses, and
workflow ordering. No host, backup, real credentials or live reservation is
part of this decision.
The accepted RCA is also registered with its exact duplicate and workflow
ordering regressions for the CI learning gate in ADR 0044.
