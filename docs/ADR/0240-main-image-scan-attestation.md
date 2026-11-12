# ADR0240 — Attest once-scanned main images instead of rebuilding for a second scan

Date: 2026-11-12 ART. Scope: Boca #417. Status: CODE_ONLY candidate; no
GitHub promotion or host effect in this worktree.

## Root cause and measured build multiplicity

After ADR0239, the current pipeline builds controller plus browser in each of
three unprivileged contexts and the protected publication: PR CI (2), main
push CI (2), main push Image security (2), and manual protected image release
(2): **8 builds per complete normal PR-to-release lifecycle**. Every full CI
`image-build` already executes both actual pinned Trivy OS/library vulnerability
scans, plus image-ID alias and immutable revision checks. The two main
`Image security` builds repeat scans of the identical source SHA with another
disposable runner. That duplication does not publish or install anything.

## R240a choice and controls

For **main push only**, `Image security / controller-scan` and `/ browser-scan`
replace redundant Docker builds and second Trivy invocations with an authenticated
GitHub API read of the one exact `CI` **push/main** run and its `image-build`
job. The verifier requires canonical source/head repository, complete 40-hex-character
commit identity, first attempt, one unique CI run/job, exact same job/run SHA,
successful completed CI image job, and completed successful individual steps:

- `Require scan aliases to identify the exact built pair`;
- `Scan before any image publication`;
- `Scan browser image before any publication`.

Missing, duplicate, malformed, stale, skipped or unsuccessful evidence is
`NO_GO`. GitHub API errors, scheduling races and timeouts also fail closed.
Both attestation jobs poll independently, with at most 80 checks at ten-second
intervals (about 13 minutes of intentional waiting, plus bounded API delays).
This is a **distinct timeout from main CI**, whose image job permits up to
45 minutes; a genuine slow CI can therefore fail the security checkpoint.
The required RCA is `BOCA_MAIN_SCAN_ATTESTATION state=NO_GO
reason=ci_image_scan_timeout` in either Image security job log. For this
condition, inspect the source-SHA `CI / image-build` outcome and schedule
before retrying via the existing protected workflow; do not mark success,
raise the timeout silently or bypass the finalizer. A longer wait or a
workflow-run dependency needs a separate safe deployment-gate design.
It polls only the canonical repository via the built-in runner `GH_TOKEN`
with `actions:read`, bounded response sizes and no host SSH, registry write,
new image or secret logging. Both existing security job names and aggregate
`image-security-scan` remain; the two certified scans still occur physically
in main `CI / image-build`, not in the attestor job. The manual `Image
security` workflow continues building/scanning an **independent pair** for
diagnostic use, with no change to the protected image release.

The protected manual release separately rebuilds the exact merged SHA,
reruns independent controller and browser Trivy scans, validates labels,
publishes dual immutable digests and retains all prior gates. The existing
historical physical Finalizer/Deploy requirements for successful `CI` **and**
`Image security` **push/main** still hold because both genuine workflows run
and must report SUCCESS. This change does not alter `boca-first-deploy.yml`,
the installed droplet, branch protection, passkey, CSRF, rootless identity or
ticket simulation. It does not reuse PR artifacts, remote registry images,
Docker cache or untrusted PR layers.

## Trade-offs and measured promises

Normal lifecycle build count falls from **8 to 6**; this is a count from
workflow declarations, **not** a measured wall-clock improvement. The
attestation job waits for main CI to complete, without an additional image
build; its polling makes the security workflow depend on CI's availability
and GitHub API, and removes the independently scheduled second main scan.
The protected release provides another actual independent scan. Whether this
is acceptable to the release owner and exact GitHub runner must be confirmed
before promotion. If CI is slow or unavailable the security job fails, so
deployment can still be delayed — it never emits a fake GREEN.

**Four builds**, or a fast path that runs no PR image job for a strictly
static change, are separate decisions. Four across all source changes would
require a redesigned attested trust chain linking the reviewed PR tree,
postmerge main, protected release scans and reusable host actor; the legacy
physical cutover currently expects both named push workflows. The later
static-only path could classify allowlisted inert assets by an exact base/head
diff while preserving the required `image-build` context and still building
twice on main and twice on release. It must exclude Python endpoint logic,
JS network/auth clients, Docker/Compose, security, dependencies, generated
files and changed packaging. No such bypass exists in this candidate.

Shared BuildKit cache across PR/main/protected release is intentionally out
of scope: exact OCI revision labels do not authenticate each inherited layer
from a lower-trust cache. Per-job local Docker layers remain available to the
two sequential builds within one CI job.

## Acceptance

Offline regression includes missing/duplicated run, wrong origin/repo,
wrong SHA/attempt, bad CI job/steps and manual security fallback. Candidate
still needs frozen full-suite tests, policy gates, independent review and
**hosted exact-SHA PR and then main-push proof** of the attestor's real GitHub
API response schema and success/failure contract. No host deploy is implied.
