# ADR 0086: protected owner passkey and TLS custody before BETA install

**Status:** proposed in issue #207. Code and runner checks are pending review;
no owner credential, TLS key or private tablet route has been provisioned on the
droplet. This proposal does not mark BETA operational.

## Decision

Add `owner-prepare`, `owner-install` and `owner-verify` to the existing
manual `boca-first-deploy` workflow. They require the repository owner, exact
current `main`, first run attempt, protected `boca-first-deploy` environment,
the Boca-only mutex, the successful protected release run, matching immutable
digest/manifest, pinned SSH host key and existing resource limit. The
origin and owner subject come from protected environment secrets and must be
set before preparation. They bind the envelope and the image-side verification.
This is a separate gate before `BOCA_BETA_ENV_READY`; it cannot start BETA.

The host script first checks the dedicated rootless boundary, *full* daemon
container inventory, Boca namespace, storage capacity and exact owner volume
identity. It rejects staged Compose and any data/key/network volume. It pulls
the exact reviewed image and verifies digest/revision before creating a new
owner volume. If already present, that volume must be local, labeled and
unredirected, unattached and the only Boca volume. A network-free, read-only
image container with UID/GID10001, dropped capabilities and 0.25 CPU/64 MiB/16
PID limits prepares a new X25519 recipient key in the owner directory. The
same fixed container boundary installs ciphertext with a capped 4 MiB memory
tmpfs, or verifies a read-only owner mount. No host config, app, DB, master key,
proxy, DNS, port, Site or Telegram service is changed.

Only the public recipient key and fingerprint leave `owner-prepare`. An
offline sender must obtain the genuine owner's two-step
`OwnerPasskeyRegistration` proof at the **final** exact HTTPS RP origin,
then seal its raw credential ID and canonical P-256 SPKI DER together with the
matching TLS certificate, unencrypted private key and health CA. The sender
API checks shapes, key and in-memory TLS trust/hostname before sealing.
The envelope has a purpose-specific X25519/HKDF/AES-GCM domain, fresh
ephemeral/salt/nonce, repository, UID, exact origin/subject and recipient
fingerprint in authenticated data. The workflow input holds only canonical
unpadded base64url ciphertext. The host checks bounded framing; the pinned
image checks the authentication tag and material again before owner-volume
writes. It creates five files exclusively as UID10001 mode0400 under a
UID10001 mode0700 directory, then checks content and TLS again. An existing,
symlinked or partial target fails closed and remains for Boca-only review;
there is no overwrite or automatic retry. The passkey's private key never
leaves the owner's device. No certificate, secret or credential ID appears in
the receipt.

## Identity and private route remain explicit gates

The protected workflow actor is the repository owner, but that alone does
not constitute a physical WebAuthn registration or validate a private tablet
route. A trusted first-owner bootstrap boundary, a stable private HTTPS
hostname reachable from the actual tablet, its DNS/certificate/CA and an
access policy must be established and reviewed before the real owner ceremony.
The current host `127.0.0.1:8443` publish is only loopback. A Boca-specific
Tailscale Serve route remains a conditional option; no tailnet/device/ACL or
shared-host proxy state has been verified. Do not install synthetic credentials
on the droplet, switch RP ID after enrollment or set the BETA marker based on
these code checks. Owner credential recovery/replacement needs a separately
reviewed authorization and rotation procedure.

## Evidence and Rule 84

Synthetic tests exercise sealed prepare/install/verify, wrong recipient,
origin/subject, tampering, TLS mismatch, exclusive writes, partial-state
preservation, full daemon inventory and immutable image ordering. The PR
workflow also runs the image in a disposable, network-free owner volume with
generated synthetic keys/certificates. Record the exact candidate SHA, CI,
image scan, PR runner smoke and technical review before integration. These
tests do not prove tablet access or a real owner passkey. The affected delivery
plan, status and operations documents and issue #45 must distinguish code
integration from host execution under Rule 84.
