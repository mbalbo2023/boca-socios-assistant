# ADR 0024: evaluate a patched Debian base without relaxing the image scan

**Status:** Proposed for issue #52, 2026-10-28. This is a review candidate,
not a deployment decision.

## Evidence and decision

The first scan of the Bookworm controller image found 61 OS vulnerabilities
at HIGH/CRITICAL severity (59 HIGH, 2 CRITICAL). A second scan with the
corrected cryptography lock eliminated the three Python package findings,
but the OS count remained 61. The reports are in Actions 40786984873 and
40787546866. A passing build or Python suite did not detect this.

Evaluate the official Python 3.12.15 slim-Trixie image at its
**multi-architecture index** digest
`sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704`
in both Dockerfile stages. This digest was read from the official Docker Hub
tag API; the amd64 image digest is a different value. Keep the Trivy scan
strict: OS and library HIGH/CRITICAL findings still fail. CI must establish
the actual change in the finding count; the Debian tracker alone does not.

Debian reports Trixie fixes for SQLite CVE-2025-7458 and
CVE-2026-11822, util-linux CVE-2026-53613 and zlib CVE-2023-45853. It
also reports other issues still open in Trixie. The scanner can report
package-level matches even when an affected binary feature is not used;
any exception would need a separate evidence-backed VEX review. No blanket
suppression or `ignore-unfixed` is added here.

## Dependencies and limits

This PR is stacked on the scanner #49, which is stacked on the corrected
cryptography lock #51 and Dependabot #2 solely to run the exact image gate.
The existing Docker hardening #23 uses a pinned Bookworm digest and a
different installation path. Its security changes must be reviewed and
combined later; this base update does not replace them. Any final combined
image requires a new scan and CI on its exact digest.

No registry publish, deployment, host operation, Boca traffic or real
credential is introduced. A green image scan would be only one gate among
independent review, main protection, safe enrollment and live-flow review.

Sources: [Docker Official Images Python manifest](https://github.com/docker-library/official-images/blob/master/library/python),
[Docker Hub tag API](https://hub.docker.com/v2/repositories/library/python/tags/3.12.15-slim-trixie),
[Debian SQLite CVE](https://security-tracker.debian.org/tracker/CVE-2025-7458),
[Debian util-linux CVE](https://security-tracker.debian.org/tracker/CVE-2026-53613),
[Debian zlib CVE](https://security-tracker.debian.org/tracker/CVE-2023-45853).
