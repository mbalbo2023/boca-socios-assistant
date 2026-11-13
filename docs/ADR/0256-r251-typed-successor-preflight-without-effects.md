# ADR 0256 — R251 typed successor preflight, still PRE-EFFECT NO_GO

**Date:** 13-NOV-2026 UTC. **Issue:** #417. **Base:** main
`0007d8c4100c8d9e37103f0a2bac149cfb6edf29` after PR #496.
**Decision:** introduce a typed, immutable preflight result, **not** a deployment
authorization. R186 must not be retried and no new host operation is triggered.

## RCA and change

The R247/R250 host CLI authenticated the runner-bound eight-evidence tuple,
current B→C pair, and original R188 custody, but discarded the successful
result and threw `SuccessorPreflightIneligible` unconditionally. That prevents
the next reviewed actor from consuming verified coordinates without duplicating
parsing. It also conceals which missing contract is genuinely the effect gate.

R251 instead returns `BoundSuccessorPreflight`: `BoundSuccessorInputs` plus
the exact `compose.beta.yaml`, `compose.beta.browser.yaml` and
`docker/seccomp_profile.json` bytes from the already-allowlisted, SHA-verified
protected memfd bundle, with separately recorded SHA-256 digests. Missing,
zero-length, oversized or identical source blobs fail closed. The frozen
result revalidates its own digests even when directly constructed; this
proves only local integrity, never provenance. The original
installed Compose digest is intentionally **absent**: the target Compose SHA
cannot prove the persisted old Compose. That old identity must be captured
and matched within the future single Boca lease before constructing
`PairSources` or mutating a stage file.

`BoundSuccessorPreflight.apply_authorized` is always `False`; there is no
`execute`, no lease object and no Docker API in this value. The CLI `apply`
caller **still throws a hard `SuccessorPreflightIneligible` after obtaining
the typed result**. The effect backend remains
`PostflightGatedSuccessorBackend.requires_persistent_receipt=False`, its
`SuccessorPostflightGate` is not wired, and `PhysicalSuccessorIntegrations`
still refuses cleanup. Thus a valid R251 preflight cannot run R186, acquire a
mutation lease, create a journal or cause a Docker command.

The standalone host parser is *not* a substitute for the earlier protected
runner GitHub authenticity, ZIP SHA and exact bootstrap allowlist checks.
Its source digests are integrity records inside that already-authenticated
transport; they are not independent release signatures.

## Evidence and next dependency

TDD saw a RED test when the old preflight raised even for a valid synthetic
V2 tuple. The same test and new negative source/entrypoint tests are GREEN
after the typed return. The direct CLI invariant asserts that even a valid
preflight does not call `run_pair_upgrade` and still emits a canonical
`NO_GO` with `commit_started=false`.

R252 must separately deliver single-lease physical source custody, the
SUCCESS/FAILURE V2 cleanup bridges, terminal journal and structural
postflight. A technical install receipt cannot represent physical Chrome
WebAuthn login or authenticated monitor activity. Those remain subsequent
owner acceptance, with `DEPLOY NO_GO` until both sets of real evidence exist.

**Boundaries:** no Porota, no shared Docker cleanup, no real reservation,
no queue bypass or TLS disable; all eventual droplet commands through the
existing protected Boca GitHub Action. No workflow or image changes in R251.
