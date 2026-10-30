# ADR 0010: Reproducible container dependency graph and defensive key loading

Status: Proposed for issue #8, 2026-10-28. Simulation mode only.

The former 0444 file-secret exception was removed by
[ADR 0034](0034-rootless-key-custody.md); the implementation requires
owner-only key permissions.

## Decision

Pin the official Python 3.12.15 slim-bookworm base by **multi-architecture
image index digest** in both Docker build and runtime stages. Build the
installed Python virtual environment using the repository's `uv.lock` with
`uv sync --locked --no-dev --no-editable`, and copy the non-editable venv to
runtime. Pin the `uv` installer version. The runtime remains non-root,
read-only at the Compose layer and free of `pip install` network resolution.

Require platform support for `O_NOFOLLOW` (fail closed if unavailable), and
use `fstat` on an opened descriptor to reduce symlink races and check the key
file is regular, safely owned and not group/world-readable or writable.
The dedicated key volume presents a 0400 file to container UID 10001;
the controller must never modify its read-only mount.
Open using `O_NONBLOCK` as well so special files like FIFOs cannot block
before regular-file verification. Bound the encoded key read to 128 bytes
and reject malformed/oversized
content before interpreting it as an AES-256 key. Avoid placing passwords
or key contents in exception messages, code, logs or CI.

## Trade-offs and limitations

- Full SHA digest pinning prevents silent changes to the base manifest. It
  does not automatically provide OS security patches; update and rescan by
  a future reviewed digest PR and retest the image.
- `uv.lock` pins Python dependency candidates, but package index/network,
  installer bootstrap and underlying build toolchain are not attested by
  this repository as a bitwise reproducible build. Future deployment needs
  SBOM, provenance and container vulnerability scanning as a separate gate.
- The rootless volume design still needs an isolated trial of actual UID
  mapping, mount mode and key access before host installation.
- A single process that can decrypt stored credentials remains powerful:
  DB and key disclosure together expose them. Keep storage, encryption key,
  backup and operator UI access strictly separated.
- This change does not deploy to or inspect a production host, alter any
  unrelated stack or enable a live browser/Queue-it adapter.

## Evidence

- Official base digest identified from [Docker Hub Python 3.12.15 slim
  bookworm](https://hub.docker.com/layers/library/python/3.12.15-slim-bookworm/images/sha256-2ed6491b93cd49272ee6de2b5a38440c3448360322c089fc23e370722d74179d).
- [uv locked sync](https://docs.astral.sh/uv/reference/cli/#uv-sync),
  [Docker Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/),
  [Docker image digest pinning](https://docs.docker.com/build/building/best-practices/#pin-base-image-versions).
- Tests reject symlink, insecure permissions, malformed/oversized contents,
  non-regular and relative paths; existing encrypt/decrypt tests still pass.
- GitHub `image-build` must prove Dockerfile and lockfile integration before
  this PR may be considered for review. No deployment is authorized.
