# R182 — owner transfer and consolidated SIMULATION_ONLY BETA

## Intent

The owner instructed on 2026-11-12 that the stalled #417 chat no longer
owns deployment. The active agent now coordinates #12's tested PR #484 with
#417's existing deployment path, without another parallel host operation or
separate approval round for this already authorized simulation milestone.

## Approaches considered

1. **Wait for real Boca/Queue-it before any deployment:** rejected by owner;
   these providers are unavailable and the simulation does not require them.
2. **Merge the dormant #12 contracts and perform one reviewed Boca PAIR
   upgrade:** selected; one code/release SHA, existing protected workflow,
   no real login, no validation of token URLs, all unrelated workloads safe.
3. **Relax CI/host/secret/identity gates to move faster:** rejected; those
   protect the existing 8443 session, data volume and other Docker projects.

## Functional contract

- The private `/monitor/tokens` exists without claiming a token was observed;
  both Queue-it and Boca channels remain OFF absent vetted producers.
- Missing sector-preferences sidecar is a visible disabled optional feature;
  the existing member profile and BETA controller remain usable. A separate,
  explicit protected migration is required before sector editing is accepted.
- Browser/worker starts only under the owner-controlled existing mechanism.
  No reservations or real login; zero foreign Docker mutations.

## Release and physical gate

The existing #484 branch receives this narrow policy amendment and goes
through exact-SHA CI/review, protected merge, postmerge CI, brand-new dual
release artifacts and positive Boca-only READ_ONLY host observations. Only
then does the same owner run one `boca-pair-upgrade-apply`, verify ACCEPTED,
cleanup and postflight. Failures preserve NO_GO and trigger RCA; never
reinterpret status as a successful deploy.

No code or document alone authorizes circumventing required GitHub Environment
or Actions restrictions. Actual access failures remain stop conditions.
