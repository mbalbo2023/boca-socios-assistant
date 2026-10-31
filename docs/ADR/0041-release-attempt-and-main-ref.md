# ADR 0041: refuse stale or repeated manual image publication

**Status:** Proposed for issue #98, 2026-10-29. No image publication.

## Incident class

The proposed manual release job checked owner, default-branch ref and the
release environment, but a GitHub run can be re-executed with its original
actor and dispatch SHA. The branch can also move while a queued environment
job waits or while the image scans. A rerun or stale publish could rebuild
and push the same SHA tag, using registry space without a new reviewed
decision. The immutable digest artifact protects a later install, but does
not justify duplicate or stale image publication.

## Decision

The publish job requires the first run attempt before it checks out source.
After checkout, it queries the current `main` Git ref with a read-only
`GITHUB_TOKEN` and reuses the bounded strict verifier from issue #90 to
match that commit with `GITHUB_SHA`. It repeats the query after vulnerability
scanning immediately before registry login and push. GitHub API failure,
malformed JSON or a moved branch is NO-GO. A new dispatch after a diagnosed
failure is a distinct run with fresh exact coordinates; GitHub's rerun
button is not a deploy recovery mechanism.

This check is not atomic with GitHub branch updates; a change in the narrow
interval after the second query could still publish an older image. The
first-install workflow independently requires current `main` and an exact
digest/release manifest before SSH, so that stale image cannot pass its
install gate. PR validation builds and scans only a disposable runner image;
it never logs in to GHCR or publishes. Nothing here changes the dedicated
host workflow, SSH settings, runtime motor or external-source policy.
