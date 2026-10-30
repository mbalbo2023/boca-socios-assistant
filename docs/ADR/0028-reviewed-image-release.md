# ADR 0028: publish a reviewed, scanned image once by OCI digest

**Status:** Integration candidate for issue #60, 2026-10-29 (Argentina). No publication performed.

Add a Boca-only manual image release workflow on `main`. Build the controller
once on a GitHub-hosted amd64 runner, scan that local image using the same
pinned Trivy action and HIGH/CRITICAL OS/library fail gate as #55, and only
then push the scanned image to GHCR using the job-scoped `GITHUB_TOKEN` with
`packages: write`. A PR job executes the build and scan but has read-only
permissions and no registry login or push. The manual release job references
the protected `boca-image-release` environment; its actual configuration and
readiness variable must be verified in GitHub before any dispatch. Checkout
uses the repository's pinned Node 24 Action.

Tag with the full commit SHA for traceability. Parse and validate the digest
reported by the actual push; fail the pipeline if `docker push` fails before
parsing its output. Record the immutable OCI reference, commit SHA
and Actions run ID in the summary. The tag is merely a locator; a later
deploy must use the digest. The workflow does not reach any host, create
keys, visit Boca or deploy. GHCR visibility/read access and the target host's
architecture must be verified separately before a deployment candidate. The
scan covers the controller, not the separate Chromium worker image.

Limitations: the vulnerability database changes over time; the runner's
amd64 image is not a multiarch release. GitHub environment configuration,
package visibility, actual branch ruleset, exact-SHA checks and recorded
agent technical review remain gates. The first-attempt and fresh-main checks
for manual publication are being added separately in #98/#99; no dispatch is
permitted before those guards are integrated and tested. A green PR check
does not permit publication or deployment by itself.
