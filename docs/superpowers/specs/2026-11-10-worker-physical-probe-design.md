# Boca isolated physical worker probe — design (2026-11-10)

## Intent and authority

The owner authorized one actual boot of the corrected Boca browser worker on the
droplet, **without Cutover**, to determine whether the previous bare
`synthetic` ModuleNotFoundError is resolved. Host diagnostics should use an
existing protected Action rather than generating a new PR for each command.
This is an infrastructure operation; the owner selected the protected Action
approach. No site navigation or ticket operation is authorized.

## Considered approaches

1. Start the installed worker CID: rejected because the installed image is the
   prior, demonstrably faulty digest, and modifying it would alter Cutover.
2. Manual SSH command as `boca-deploy`: exceptional fallback; less repeatable
   and not the owner's selected approach.
3. **Selected:** one protected Boca workflow operation, packaging a tiny
   hash-verified host program that creates and starts one disposable exact-CID
   container from the reviewed image; no shared IPC volume or controller write.

## Boundaries and positive acceptance

- Existing `boca-first-deploy.yml` owner/main/environment/SSH guard, UID/GID
  10001 and exact rootless socket `/run/user/10001/docker.sock`; no sudo.
- Only the immutable browser image produced by successful dual-image run
  `42847341532` (release #810, SHA `31cc6987c30d705113d0323b0700c156fec97eb5`)
  is admitted, with the matching controller manifest. Action source SHA is
  independently the current reviewed main commit. PR count must be zero.
- Verify original controller healthy, engine STOPPED, installed worker PID0;
  prohibit concurrent lifecycle operations via the preexisting Boca host lease.
- Docker `create` has fixed Boca-only labels and a fixed disposable name,
  `--network none`, non-root UID/GID10002, no mounts of host data or IPC
  volumes, strict reviewed seccomp, read-only filesystem, caps/cgroup limits,
  ephemeral tmpfs IPC owner10002/mode0711. No credentials or external traffic.
- Arm bounded Docker Engine attach before exactly one `start`. Commit a
  durable, exclusive marker before START, keyed to the immutable release.
  `Health.Status=healthy` and PID-positive are the worker-boot proof; bounded
  classified error/exit/OOM are the failure proof. Never emit raw logs.
- In one `finally`, stop/remove *only* the verified disposable CID; verify it
  absent, then verify original controller and worker unchanged. Unknown
  cleanup => `INDETERMINATE`, no automatic retry. A successful probe is **not**
  proof of Chrome passkey, control integration, or site navigation.
- The two owner BLACKBOX modules are not opened, edited, linted or invoked by
  runner tests. The protected host invocation starts their real worker entry
  only within this explicit owner authorization, disconnected from the site.

## Scope

Extend the existing workflow by one dispatch operation; add a minimal host
probe bundled through the existing memfd transport and a strict public receipt
verifier; add offline regression tests and this design/plan. Do not change
Cutover, the production controller, other services, Docker permissions or
legacy work. The corrected image was already published by run #810, so do not
publish another image just for the diagnostic.

## Independent review changes

- Before any SSH, authenticate successful CI on this workflow's **exact current
  main SHA** and both completed check-suite jobs; the older image release's
  GREEN result does not certify these new host commands.
- Before an image pull, verify the dedicated rootless store identity,
  filesystem/inode admission and capacity. Recheck topology and the approved
  residual floor after the pull and after exact-container cleanup. The
  downloaded immutable Boca browser image is intentionally **RETAINED** as a
  cache for the future Cutover; the disposable container is **REMOVED** by CID.
- Docker inspect contains effective compact seccomp JSON and may normalize
  `SYS_CHROOT` to `CAP_SYS_CHROOT`. Check against the reviewed profile bytes
  using the existing production verifier. Reject a drift before START, but
  still compensate by exact verified CID/name/image/labels.
- Commit one durable release-specific attempt marker **before CREATE**. If
  Docker create times out or loses its ACK, the CID is indeterminate: report
  NO_GO, do not remove by guessed name, and do not attempt a second CREATE.
  Any later investigation must first obtain a fresh read-only CID inventory.
- After health, verify runtime kernel UID/cgroups/seccomp/no-egress in the
  disposable worker. A mere Docker metadata match is insufficient.
