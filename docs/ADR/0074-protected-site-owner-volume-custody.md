# ADR 0074: protected Site owner-volume custody gate

**Status:** candidate for issue #167B, pending exact PR SHA, hosted checks and
technical review. This source change itself has no host effect. It does not
enable the Site bridge, install a BETA service or provide owner tablet access.

## Decision

The existing protected `boca-first-deploy` workflow gains three independent
manual operations: `site-prepare`, `site-install`, and `site-verify`. They use
the same owner, current-main, first-attempt, environment, fixed controller and
resource-budget gates as the existing Boca host operations. Each requires a
successful first-attempt protected image release run for the same source SHA,
an exact GHCR digest and matching release manifest before SSH. The runner
rechecks main immediately before the operation. The host script is streamed
over pinned-host-key SSH as UID 10001, with no persisted host copy.

The host helper first proves the dedicated rootless Docker socket, cgroup
delegation, Boca staging directory, CPU/memory/disk/inode capacity, empty Boca
container/network inventory and only the exact `boca-socios_boca_owner` volume
(or no volume for first preparation). It pulls the immutable image and checks
its repo digest and revision label before creating the volume. The volume must
have the local driver, fixed Boca Compose labels, no driver options and an
unredirected mountpoint under the verified rootless Docker data root.
`site-prepare` may create only that volume. Its one-shot, network-free image
container sets the new empty directory to UID/GID 10001, mode 0700. A
subsequent container runs ADR0072 `prepare` as UID/GID 10001 with no network,
read-only root, dropped capabilities and 0.25 CPU/64 MiB/16 PID limits.
`site-install` and `site-verify` require the existing owner volume. Verify
mounts it read-only. A changed or partially configured owner volume is
preserved for diagnosis, not removed or overwritten.

The only extra dispatch input is a canonical unpadded base64url encoding of
the ADR0072 sealed JSON envelope, accepted solely for `site-install`. The
runner and host pass **ciphertext only**. The host rejects oversized,
noncanonical, duplicate/unknown-field and wrong-domain envelopes before a
container is started; the pinned image independently verifies the recipient,
AES-GCM tag and two private values before exclusive writes. No plaintext
token or HMAC key is a workflow input, argument, log, repository file or
receipt. Public output is bounded to the recipient public key/fingerprint on
prepare and fingerprint on install/verify. The public prepare receipt must be
verified against the exact protected run before offline sealing; the envelope
does not authenticate its sender independently of the protected workflow.

This is a **credential custody** gate. It does not create the data/key
volumes, migrate SQLite, publish a port, start a service, contact the Site or
set `BOCA_SITE_BRIDGE_MODE=poll`. The dormant `first-install` contract remains
unchanged. A later `beta-install` needs its own reviewed source, actual owner
passkey/TLS, private access designation, host capacity and full postflight;
Telegram has separate bot/destination and delivery gates.

## Verification and current NO-GO

Unit tests cover inventory, exact volume identity and symlink rejection,
canonical ciphertext transport, fixed container argv/UID/mount/network,
bounded receipts and image-revision failure before volume creation. The PR
workflow also exercises a synthetic sealed prepare/install/verify cycle in a
disposable owner volume using a locally built image, then removes that volume.
Exact candidate SHA, hosted CI/scan and review are recorded on the PR after
execution. This test is not a protected release or droplet proof.

As observed during this implementation, the `boca-image-release` protected
environment has no `BOCA_RELEASE_ENV_READY` variable, so no successful image
release run/digest is available for these operations. Protected `stop-test`
run #41272785626 completed SUCCESS with `BOCA_STOP_TEST state=STOPPED`,
`containers=0`, `data=preserved`; the Boca test services are stopped.
**Host execution is NO-GO** until
those gates, a verified recipient receipt and securely sealed real Site
material exist. No real Site credential, Boca login, queue, reservation or
purchase was used here. The root integration writer reconciles the delivery
plan, operations/status docs and #45 with actual host evidence under Rule 84.
