# ADR 0030: controller stays on while its motor stays off

**Status:** Proposed for issue #65, 2026-10-29. No host operation performed.

The first deployment may leave the simulation controller running and healthy.
It does not run a browser, a queue adapter, a scheduler, a reservation motor
or a Boca request. The two independent gates are `BOCA_RUNTIME_MODE=simulation`
and `BOCA_ENGINE_MODE=off`. The resolved Compose contract requires both exact
values. Runtime configuration rejects any other engine value before opening
the key or database. A direct image run also defaults to `off`; a restart
cannot silently activate a motor. There is no code path for `on` in this PR.

The startup event records `engine=off` and `site_calls=0`; health only tests
the local SQLite migration. A GitHub-hosted ephemeral Compose smoke uses a
synthetic key and asserts the idle log and healthy status. This cannot prove
droplet readiness or site behavior. Future demand-triggered diagnostics must
be a separate, bounded operation within the single protected Boca workflow;
they must not convert container startup into an automatic reservation action.
Any live observation or reservation still needs independent design review,
consent, exact authorization and a new reviewed implementation.

Changing the environment to `on`, an unknown value, or a live runtime mode
is a startup failure (NO-GO). The deployment helper then stops only Boca and
preserves its key/volume for diagnosis; it does not retry or activate a
fallback motor.
