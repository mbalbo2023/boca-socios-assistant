# ADR 0026: integrate the scanned Alpine image with locked dependencies and key hardening

**Status:** Reconciliation candidate for issue #56, 2026-10-29
(America/Argentina/Buenos_Aires). No deployment or real secret use.

## Contract

The original #57 experiment merged #23 as a second parent while both source
branches were open. #23 and the corrected dependency lock #51 have since
entered main. Reconcile #57 on the integrated #55 base without reintroducing
their old commits or rewriting the vault. The final diff should contain only
the Dockerfile smoke check and this ADR. Preserve #23's hardened key-file
reader, tests and security policy from main.

Both stages must use #55's official Python 3.12.15 Alpine 3.24 image index
digest, `sha256:b658b05ce9c4eb97ec6fc19424818a1f31993659c2b505a532f470e83807815d`.
This supersedes only ADR 0010's Bookworm base choice; its lockfile and key
reader decisions still apply.
Keep #23's `uv==0.13.4` bootstrap, `uv sync --locked --no-dev --no-editable`
against `uv.lock`, and copy of the resulting virtual environment. Alpine
uses its native user/group commands. After `USER 10001:10001`, execute the
build smoke check as that identity and assert both UID and GID are 10001.
Exercise a SQLite in-memory query, storage import and AES-GCM seal/open round
trip with synthetic values in the final image. No key file is mounted or
read. Keep no published port and the simulation-only runtime.

The integrated base combines #2's package range, #51's corrected lock,
#55's strict scan and Alpine base, and #23's key hardening. Record agent
technical review of the exact #57 candidate, with resolved findings and
fresh required checks. No additional human approval is required by ADR 0038.
Run frozen sync, lint, format, strict types, full offline tests, isolation
gate, image build and the unchanged OS/library HIGH/CRITICAL scan on the
exact merge candidate. A clean scan is time-dependent and does not prove
that the container, secret mount or real third-party behavior is safe.

## Limits

The lock selects dependencies and checks project metadata, but the pinned
`uv` bootstrap and upstream package downloads remain external inputs. This
change neither provisions secrets nor exercises a live Boca session. Future
installation of a reviewed release is a separate recorded Actions decision
under the owner's standing direction, conditional on exact SHA and digest,
pinned SSH, protected environment, rootless isolation and resource preflight.
A commercial source outage is a timestamped advisory for a safe simulation
deployment; it does not waive this image-security gate or enable live behavior.
No production or unrelated workload is touched by the CI build.
