# ADR 0079: image-side owner and TLS preflight without a listener

**Status:** integrated by PR #189 in
`63965b087fbd6d7a68308302bb8baf2e08975674`. Exact candidate
`b2b34a17f207f7021d09bb63455f7aafa7ba958d` passed CI 41274671069,
scan 41274671077, release/deploy validation 41274671053/41274671118 and
review 5726527799. Baseline was `b92e2abacd63d1654dfb6d795f718af2ea283589`.
It has not run on the droplet and does not provide tablet access.

## Decision

The pinned Boca image exposes two explicit, read-only commands:

| Exact argv | Required mounts | Success stdout (one line including newline) |
| --- | --- | --- |
| `python -m boca_socios.runtime check-beta-owner` | `/run/owner:ro` | `{"event":"beta_owner_ready","mode":"simulation","engine":"off"}` |
| `python -m boca_socios.runtime check-beta-config` | `/run/owner:ro`, `/run/secrets:ro` | `{"event":"beta_config_ready","mode":"simulation","engine":"off"}` |

Both run as UID/GID 10001 with the exact `serve-beta` Compose environment,
network disabled and no data volume. The first runs before any key or data
volume creation; the second runs after the protected helper exclusively
creates the Boca master key and before it creates/initializes data. The
deployment helper must require exit 0 **and byte-exact stdout**. Failure
returns exit 1 with only `{"event":"beta_owner_unavailable"}` or
`{"event":"beta_config_unavailable"}` plus newline, respectively, and no
stderr details. It must preserve any pre-existing or partially created Boca
volume for diagnosis rather than retry over it.

The owner check validates simulation/engine off, a canonical HTTPS DNS RP
origin and owner subject, internal `0.0.0.0:8443` bind configuration, and
exact fixed file paths. `/run/owner` must be a non-symlink directory owned by
the running UID/GID with mode 0700; `credential_id`, `public_key.der`,
`tls.crt`, `tls.key` and `health-ca.pem` must be regular, single-link files on
that volume, same UID/GID and mode 0400. Descriptor-relative no-follow reads
are bounded. The public passkey is a canonical ES256 P-256 SPKI DER with a
16–1024-byte raw ID, accepted by the panel verifier for the exact RP. The
TLS key/cert pair is loaded into an in-memory server context, and a client
context trusting **only** `health-ca.pem` performs an in-memory TLS handshake
against the exact RP hostname. This tests key pairing, issuer trust, SAN and
validity time without binding a socket or contacting a service. The full
check additionally validates the separate master key through the existing
vault reader and any explicitly configured Site bridge files through the
existing local transport constructor; it sends no Site request.

The commands do not open or create a database, migrate storage, start a
listener, register a passkey, write owner files, run Docker or send network
traffic. They do not test the actual private proxy route, DNS resolution,
tablet trust store, host port publication, cgroup budget, runtime readiness or
owner authentication. The protected workflow and later postflight must still
verify those distinct conditions. A successful synthetic proof with a test
key/certificate cannot authorize installing it as the owner's identity.

## First-owner and tablet gate

PR #174 provides an inert two-step WebAuthn create/get proof, but no
independent authorization of the first owner. Before a real owner credential
can be provisioned, the owner must use a reviewed, stable private HTTPS origin
and physically approve the authenticator ceremony there. A Boca-only private
route such as Tailscale Serve remains a conditional design, needing verified
tailnet/device membership, ACL, origin DNS/certificate and proxy capacity.
The existing host `127.0.0.1:8443` publication cannot be opened directly
from a tablet. The real public credential, TLS material and CA must reach the
protected owner volume through a separately reviewed private custody path;
no browser, chat, repository or workflow plaintext input is implied by this
preflight. Actual owner tablet login, denial of third parties and restart
acceptance remain unverified.

Synthetic tests cover valid no-socket/no-DB execution, wrong SAN/CA/expiry/key,
unsafe owner modes/symlink, invalid passkey, missing master key and fixed
redacted CLI receipts. Exact candidate SHA, Actions runs and technical review
are recorded above and in PR #189. The root integration writer owns central plan,
status and issue #45 under Rule 84. No real Boca login, queue, reservation or
purchase is part of this change.
