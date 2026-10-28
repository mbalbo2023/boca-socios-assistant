# ADR 0026: integrate the scanned Alpine image with locked dependencies and key hardening

**Status:** Proposed for issue #56, 2026-10-28. No deployment.

## Contract

Use the passing image experiment #55 as the base and merge the existing
security PR #23 as a second parent. Preserve #23's hardened key-file reader,
tests and security policy as-is; only reconcile the conflicting Dockerfile.
Its two stages must use #55's official Python 3.12.15 Alpine 3.24 image index
digest, `sha256:b658b05ce9c4eb97ec6fc19424818a1f31993659c2b505a532f470e83807815d`.
This supersedes only ADR 0010's Bookworm base choice; its lockfile and key
reader decisions still apply.
Keep #23's `uv==0.13.4` bootstrap, `uv sync --locked --no-dev --no-editable`
against `uv.lock`, copy of the resulting virtual environment and import
smoke check. Alpine needs its native user/group commands; retain UID/GID
10001, no published port and simulation-only runtime. Exercise SQLite and
AES-GCM in the final image with synthetic in-memory values.

The resulting branch combines #2's package range, #51's corrected lock,
#49's strict image scan, #55's Alpine base and #23's key hardening. All of
those source PRs need independent human review. The combined PR must pass
frozen sync, lint, format, strict types, full offline tests, isolation gate,
image build and the unchanged OS/library HIGH/CRITICAL scan on its own
exact PR merge candidate. A clean scan is time-dependent and does not prove
that the container, secret mount or real third-party behavior is safe.

## Limits

The lock selects dependencies and checks project metadata, but the pinned
`uv` bootstrap and upstream package downloads remain external inputs. This
change neither provisions secrets nor exercises a live Boca session. Future
installation of a reviewed release needs a separate authorization for the
exact image digest and host isolation preflight. No production or unrelated
workload is touched by the CI build.
