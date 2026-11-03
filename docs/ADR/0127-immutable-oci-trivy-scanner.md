# ADR 0127: fail-closed Trivy through the publisher's immutable OCI image

**Status:** Draft proposal for [RCA #300](https://github.com/mbalbo2023/boca-socios-assistant/issues/300), 2026-11-03 ART. No release or droplet operation.

## Observation, not speculation

- [Image security run #41730744343](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41730744343) failed on its first attempt and a repeated job attempt (126247085840, 126247605384).
- [Boca image release PR validation #41730744274](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41730744274) independently failed on the same install step.
- In all three job attempts, `setup-trivy` found version `v0.76.1`, then `bash ./trivy/contrib/install.sh` ended with exit code **6**, before executing the actual scan. The code build and other CI checks passed on this candidate; these do not imply an image security PASS.
- [Official Trivy install script](https://github.com/aquasecurity/trivy/blob/main/contrib/install.sh) uses `curl` to fetch GitHub Release archives; [curl code 6](https://curl.se/libcurl/c/libcurl-errors.html) means failed host resolution. The silent installer log does **not** identify the specific unresolved hostname and cannot independently establish an external outage's full root cause.

The failure recurs because both workflows use the same install dependency, and a retry repeats it without changing the download path. Treating it as a one-off incident left the shared CI gate unfixed.

## Decision candidate

Use Trivy **v0.76.1** as an official OCI image pinned to its **publisher-controlled GHCR digest**:

`ghcr.io/aquasecurity/trivy:0.76.1@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c`

Source: [Aqua Security's GitHub Container package](https://github.com/aquasecurity/trivy/pkgs/container/trivy), which records the digest for release v0.76.1. This follows [Trivy's official container instructions](https://trivy.dev/docs/v0.76/getting-started/installation/).

Use a single, reviewed `scripts/trivy_scan_image.sh` from GitHub-hosted ephemeral runners with only the six exact local Boca image references for the current `GITHUB_SHA`. Require that the local image exist, then scan with `--image-src docker` to prevent silent remote registry fallback. Retain vulnerabilities from OS and libraries, **HIGH/CRITICAL**, including unfixed advisories, with exit code 1 on detection and nonzero on any scanner failure. Both controller and isolated browser image must pass.

The scanner OCI is pulled by Docker through GHCR instead of downloading a binary archive from GitHub Releases. No GitHub Action version or implicit `setup-trivy` fetch is involved. The runner's Docker socket is used for **local image inspection only by the reviewed scanner**, with a read-only bind path, dropped Linux capabilities and no-new-privileges. A read-only mount of a socket does not convert the Docker API into a read-only service: the scanner is trusted with the same local runner daemon access already available to the earlier host-binary scanner. The runner is disposable, not the production droplet.

## Unchanged gates and limits

- Exact-SHA source, checkout without saved credentials, read-only PR token and GitHub-hosted runners.
- Manual `boca-image-release` on `main` only, owner actor and protected environment, unique first attempt, verified SHA, both scans before GHCR credentials, login or push.
- No `continue-on-error`, ignored results, skipped DB updates, diminished severities, removed `ignore-unfixed` coverage or automatic retry. A GHCR pull/DB network error is **NO_GO**, as are vulnerabilities, missing local image, unexpected input and scanner failure.
- No host SSH, kernel operation, Docker mutation on droplet, Boca navigation, modification or inspection of the two owner-controlled browser blackboxes, real tickets or credentials.
- A complete PR CI success with actual Trivy scan execution is required. A green code-only job or version string is insufficient, and a green scan does not remove the rootless `br_netfilter` blocker of [issue #275](https://github.com/mbalbo2023/boca-socios-assistant/issues/275).

Historical [ADR0028](0028-reviewed-image-release.md) specified the original pinned Trivy **Action** distribution. This draft changes only the distribution mechanism, not the vulnerabilities policy or release contract.
