# ADR 0071: inert owner passkey creation and possession proof

**Status:** accepted; PR #174 integrated into
`74edba458efe8cc2ce3b5f6e0deb1a8da9a0529d` from baseline
`0161922fb68bad3c36101bf9633ba025faf52f32`. This is a code-only
contract. It does not enroll the real owner, open a listener, install files,
select an external origin or establish tablet access.

## Decision and ceremony

The standalone `OwnerPasskeyRegistration` accepts one exact HTTPS origin, its
hostname as RP ID and the configured owner subject. Missing/mismatched origin
fails construction. `begin()` issues one process-local, random, 120-second
creation challenge and opaque operation ID; only one ceremony may be pending.
The caller must already have established an **independent trusted first-owner
bootstrap boundary** before calling it. This module is not that boundary and
must not be wired to an anonymous HTTP route, a forwarded identity header or
an unreviewed operator token.

The owner browser calls `navigator.credentials.create()` at that exact origin
with `attestation: "none"`, RP ID, ES256 (`alg: -7`), 120-second timeout and
required user verification. The caller transmits base64url `rawId`,
`clientDataJSON`, `getAuthenticatorData()`, `getPublicKey()` (DER SPKI) and
`getPublicKeyAlgorithm()`. The server checks the one-use challenge, creation
type, exact origin, non-cross-origin context, RP hash, UP/UV/AT bits, embedded
credential ID and ES256 P-256 COSE point against the browser's SPKI. It accepts
only the narrow no-extension EC2/ES256 encoding; unsupported authenticators
fail closed. No attestation statement or device provenance is trusted. The
W3C API explicitly permits the browser accessors when attestation is not
required: <https://www.w3.org/TR/webauthn-3/>.

Creation alone does not release public credential material. It produces a
second fresh 120-second `navigator.credentials.get()` challenge, restricted
to the just-created credential with required UV and the same RP ID. The
existing `PasskeyOwnerAuthentication` verifier checks the signed assertion,
exact origin, RP hash, credential ID and one-use challenge. `finish()` returns
`PublicCredential(credential_id, public_key_der)` only after that proof. Any
failed creation/proof consumes its operation; expiry or process restart drops
the pending state. The proof establishes possession of the matching private
key, not the human's legal identity or authenticator hardware provenance.

## Protected file contract and missing bootstrap

The two returned fields are **raw binary bytes**, not base64, JSON or PEM:

| Runtime file | Payload | Constraint |
| --- | --- | --- |
| `/run/owner/credential_id` | `PublicCredential.credential_id` | 16–1024 bytes, exact raw ID |
| `/run/owner/public_key.der` | `PublicCredential.public_key_der` | canonical P-256 SPKI DER |

The #169 runtime reads those files from its protected owner mount and also
requires the configured exact origin/subject and separate TLS certificate/key.
This module never writes to disk or exports an authenticator private key. A
later protected Actions provisioning workflow must receive these bytes over a
reviewed private channel, install atomically with Boca-only ownership/mode
and verify the file hash/length without logging the payload. No such workflow
or real owner credential is delivered here. Recovery/replacement after loss
needs the same independent owner authorization; there is no reset or fallback
endpoint in this change.

The host-loopback `127.0.0.1:8443` publication in #167 is only a local HTTPS
test boundary. A tablet needs an actual private route and a stable HTTPS RP
origin before credential creation. A Boca-only Tailscale Serve route to that
loopback port is a possible private path, conditional on tailnet ownership,
tablet enrollment, ACL, DNS/certificate, proxy topology and measured host
capacity. Tailscale Serve itself is documented at
<https://tailscale.com/kb/1312/serve>. No tailnet, tablet enrollment, origin,
certificate, route or Boca-only sidecar has been verified. Do not change a
shared host Tailscale service or expose the loopback listener to public
internet by inference. The origin cannot be switched after creation without
registering a new credential for the new RP.

## Evidence and limits

Synthetic tests create disposable P-256 keys, exercise exact origin/RP/UV,
challenge expiry and replay, COSE/SPKI matching, malformed creation and wrong
proof signature, then feed returned bytes to the existing panel verifier.
Candidate `91c05f6a75499f3643af06834262ae6a1527e468` passed
CI 41271084422, scan 41271084439 and preview 41271084425,
with exact review 5726310354 in PR #174. This does not demonstrate the owner's
tablet/browser, private HTTPS route, first-owner authorization, protected
provisioning, host capacity or a deployed BETA. No Boca credentials, login,
queue, reservation or purchase are used. The root integration writer owns
central status/plan and issue #45 reconciliation under Rule 84.
