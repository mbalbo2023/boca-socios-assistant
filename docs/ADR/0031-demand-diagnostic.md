# ADR 0031: on-demand diagnostic in the single protected Boca workflow

**Status:** Proposed for issue #68, 2026-10-29. No host operation performed.

The controller remains on with `BOCA_ENGINE_MODE=off` after a separately
approved first installation. `boca-first-deploy.yml` gains a manual choice:
`first-install` or `diagnostic`. Both require the same protected environment,
owner, exact current `main` SHA, successful image release run, immutable
digest, fixed service/budget, pinned SSH identity and Boca-only serialization.
The reviewer must approve each operation for the exact coordinates and
window. A push or PR cannot invoke either host operation.

`diagnostic` is read-only. It checks the reviewed Compose SHA and resolved
host model, dedicated UID/path/key metadata without reading key contents,
then inspects only the Boca controller and its image. It requires the exact
digest and source revision, Compose project/service labels, nonroot UID,
simulation mode, engine `off`, healthy status, read-only root, fixed CPU,
memory and PID limits, no privileged mode and no published ports. The
response is a bounded aggregate status without environment variables,
credentials, cookies, tokens or DB rows. No pull, up, stop, restart, shell in
the container, retry or Boca website request occurs.

This is a diagnostic for the **same currently approved main commit** as the
installed image. If main or Compose changed after installation, it fails
closed. An upgrade or recovery needs its own design/review, not a disguised
first-install retry or diagnostic override. A passing local test cannot
establish actual droplet state; the manual job stays uninvoked until all
human and environment gates are proven.
