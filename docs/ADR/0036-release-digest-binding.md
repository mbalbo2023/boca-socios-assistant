# ADR 0036: bind first-install digest to the scanned image release

**Status:** Proposed for issue #88, 2026-10-29. No image publication or host operation.

## RCA

The first-install workflow checked that a manual image release run succeeded
for the current source SHA. It did not establish that the operator-supplied
`image_ref` was the digest **published by that run**. The host helper later
verified the pulled digest and source revision label, but a different image
could carry the same revision label. This is an evidence gap before SSH, not
an observed malicious image or deployment.

## Decision

After scanning and pushing the image, the release job writes a bounded JSON
manifest with its exact OCI digest, commit SHA and Actions run ID. The same
successful run uploads that file as an immutable named artifact. First-install
and diagnostic fetch it by the validated run ID and compare every field to
the dispatch inputs **before SSH is configured**. Absent, expired, malformed,
oversized, symlinked or mismatched evidence is NO-GO. The run still must be a
successful manual owner release from main; the host still verifies the pulled
digest and source label. Preflight requires no image and never downloads this
artifact.

The manifest contains public coordinates, never a key, password or token.
It expires after 30 days; a fresh reviewed release is then needed. The
upload action is pinned to its full commit SHA. This gate does not replace
independent PR review, protected environments, host-key pinning, rootless
isolation or a real capacity preflight.
