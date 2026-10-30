# ADR 0031: on-demand diagnostic in the single protected Boca workflow

**Status:** Proposed for issue #68, 2026-10-29. No host operation performed.

The controller remains on with `BOCA_ENGINE_MODE=off` after a gated first
installation. `boca-first-deploy.yml` gains a manual choice:
`first-install` or `diagnostic`. Both require the same protected environment,
owner, exact current `main` SHA, successful image release run, immutable
digest, fixed service/budget, pinned SSH identity and Boca-only serialization.
The agent records the proven gates for each operation and its exact
coordinates under the owner's standing direction; no additional human
approval is required. A push or PR cannot invoke either host operation.

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
establish actual droplet state; the manual job stays uninvoked until the
isolation, image, capacity, SSH and environment gates are proven.

## Boundary still missing in this candidate

This version of `diagnostic` checks real/effective UID and GID before reading
private metadata, but does not yet prove that Docker is the dedicated
rootless daemon. `_compose_env` can inherit Docker transport/context settings.
It must not be dispatched even if an environment readiness variable is set.
#79 must pin and verify the rootless socket for every phase, and #91 must
harden the identity and current-main checks for the whole manual workflow
before any host operation. #81 separately resolves rootless key
custody. This ADR is evidence for code review, not a host GO receipt.
