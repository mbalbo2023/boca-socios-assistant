#!/usr/bin/env bash
# Scan an exact locally built Boca image with the official, immutable Trivy OCI image.
# This avoids the setup-trivy GitHub Releases binary download (curl exit 6).
set -euo pipefail

if [[ $# -ne 1 || ! "${GITHUB_SHA:-}" =~ ^[0-9a-f]{40}$ || -z "${RUNNER_TEMP:-}" ]]; then
  printf 'BOCA_TRIVY result=NO_GO reason=invalid_runner_contract\n' >&2
  exit 2
fi

image_ref="$1"
case "$image_ref" in
  "boca-socios-scan:${GITHUB_SHA}"|\
  "boca-browser-scan:${GITHUB_SHA}"|\
  "boca-release-validation:${GITHUB_SHA}"|\
  "boca-browser-release-validation:${GITHUB_SHA}"|\
  "ghcr.io/mbalbo2023/boca-socios-assistant:sha-${GITHUB_SHA}"|\
  "ghcr.io/mbalbo2023/boca-socios-assistant-browser:sha-${GITHUB_SHA}") ;;
  *)
    printf 'BOCA_TRIVY result=NO_GO reason=unreviewed_image_reference\n' >&2
    exit 2
    ;;
esac

if [[ "${GITHUB_ACTIONS:-}" != true || "${RUNNER_ENVIRONMENT:-}" != github-hosted ]]; then
  printf 'BOCA_TRIVY result=NO_GO reason=untrusted_runner\n' >&2
  exit 2
fi

docker image inspect "$image_ref" >/dev/null
cache_dir="${RUNNER_TEMP}/boca-trivy-cache"
mkdir -p "$cache_dir"
socket_gid="$(stat -c %g /var/run/docker.sock)"
if [[ ! "$socket_gid" =~ ^[0-9]+$ ]]; then
  printf 'BOCA_TRIVY result=NO_GO reason=invalid_local_docker_socket\n' >&2
  exit 2
fi

# Published by Aqua Security itself, manifest digest for Trivy v0.76.1.
# Pin both version and full immutable digest; never use :latest.
scanner_image='ghcr.io/aquasecurity/trivy:0.76.1@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c'

docker run --rm --pull=missing \
  --user "$(id -u):$(id -g)" --group-add "$socket_gid" \
  --security-opt=no-new-privileges --cap-drop=ALL \
  --mount type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock,readonly \
  --mount "type=bind,source=${cache_dir},target=/tmp/trivy-cache" \
  --env HOME=/tmp --env TRIVY_CACHE_DIR=/tmp/trivy-cache \
  "$scanner_image" image \
  --image-src docker --scanners vuln --vuln-type os,library \
  --severity HIGH,CRITICAL --ignore-unfixed=false --exit-code 1 \
  --format table --timeout 10m "$image_ref"
