# ADR 0258 — R252 current-base-only Compose custody before journal

**Date:** 13-NOV-2026 UTC. **Issue:** #417, checkpoint A45-R252.
**Status:** CODE_ONLY; physical APPLY and BETA deploy remain **NO_GO**.

## RCA

The R251 protected target ZIP contains byte-exact `compose.beta.yaml`, the
browser overlay and seccomp profile with bound SHA-256 digests, but neither
target release manifests nor the authenticated current-pair V2 receipt carry
an arbitrary earlier persisted Compose SHA. `PairSources.original_compose_sha`
cannot be invented. Reusing R186's hardcoded singleton hash for every
subsequent upgrade would break authentic B→C custody.

For the **present** no-base-change update only, Git's reviewed target
`compose.beta.yaml` hash is
`b9e9465d6ec8e484b615d7bd65aab5a3c150d34a9893ad181167d2099893d811`.
It happens to equal the historical base, but that Git fact is **not** evidence
of the physical host file. We therefore adopt a *restrictive equality gate*,
not a general old-source discovery mechanism.

## Decision

`CurrentBaseOnlyStageCustody` takes R251's typed proof and the existing
`SuccessorPairJournal` instance. It constructs `PairSources` solely from
the proof's immutable target bytes/hash values, setting
`original_compose_sha=base_sha` only on the strict understanding that the
live original file must prove that exact content.

The future `terminal_preflight` callback receives the **already-held**
`BocaJobLease` from `run_pair_upgrade`. Before `journal.intent` is called,
it independently verifies lease ownership, opens only the dedicated Boca
stage root via `host_cutover_stage._root_fd()` and reads the *fixed name*
`compose.beta.yaml` **twice** with `O_NOFOLLOW`, exact SHA, 32-KiB bound,
UID/GID 10001, allowed historical 0600/0644 mode and single hardlink.
Both payloads must equal the protected target bytes and the device, inode,
size, modification and change times must match. It closes the FD and
revalidates the same lease before calling the single existing durable
`SuccessorPairJournal.intent` (`O_EXCL/fsync/readback`).

`host_boca_pair_stage.prepare` already rechecks that identical original
Compose before and after writing any later attempt-scoped child stage.
Thus drift between preflight and staging also fails closed without overwriting
the working root Compose.

No new path, digest, rootless credential, GitHub workflow input or Docker
dispatcher is accepted from the owner or an Actions form. A Compose mismatch,
symlink, invalid mode, absent file, changed inode or reused attempt returns
NO_GO with no journal intent or Docker change. There is no fallback to the
legacy constant and no second lease/transaction.

## Evidence and limits

TDD RED before the new type existed; 8 focused tests GREEN, including
cross-read mutation and the real disposable lease/journal. The test fixtures
never operate the droplet. This adapter is **not yet connected to the CLI**,
and R251 still hard-rejects APPLY. Final SUCCESS/FAILURE cleanup, postflight,
protected package closure, release SHA and owner passkey remain separate gates.

If any later target changes base Compose, this exact-match-only strategy
must refuse. Such a release needs the *previous* Compose blob authenticated
under the prior Git SHA and the current physical file attested under lease.
It cannot repurpose target bytes or R188 creator pins as previous content.

No real reservations, queue bypass, TLS relaxation or Porota access.
