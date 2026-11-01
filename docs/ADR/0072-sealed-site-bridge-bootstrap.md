# ADR 0072: sealed intake for the private Site bridge credentials

**Status:** accepted; PR #178 integrated into
`497028ba49ec509f586051feca8876f2250ff5ac`. This is a helper
contract, not a host operation or connected Site. Initial main baseline:
`74edba458efe8cc2ce3b5f6e0deb1a8da9a0529d`.

## Decision and trust boundary

The owner-private Site #113 needs two machine values on the dedicated Boca
runtime: an existing Sites service bypass token and a separate random 32-byte
HMAC key. The Sites native secret environment stores the HMAC key as unpadded
base64url; the Boca client reads the **same raw 32 bytes**. The bypass token
bypasses the visitor gate but does not establish owner identity. Neither value
may enter source, an image, an issue, a PR, an Actions dispatch input, a log,
or a browser page as plaintext. The Site queue and client remain disabled
until the independent custody, permission and E2E gates are met.

A protected Boca Actions operation may run the pinned Boca image, without
network, as UID/GID 10001 with the Boca-only owner volume mounted at
`/run/owner`. It first initializes that volume through a **separately
reviewed** one-shot gate to UID/GID 10001, mode 0700; this helper does not
chown or create the volume. `prepare` creates an exclusive X25519 private
recipient key, mode 0400, and emits only its raw public key in unpadded
base64url and SHA-256 fingerprint. A safe recheck returns the same public key
if no bridge secrets exist. The public receipt must be taken from the exact
protected run and verified before sealing; a substituted public key would
redirect confidentiality to the substitute holder. The envelope does not
provide independent sender authentication. The protected owner/main/environment
workflow gate supplies that authorization.

An offline sender seals **both** values to that public key using an ephemeral
X25519 exchange, HKDF-SHA256 with a random 16-byte salt and domain-separated
info, and AES-256-GCM with a random 12-byte nonce. The canonical JSON AAD
binds version 1, repository `mbalbo2023/boca-socios-assistant`, purpose
`boca-site-bridge-machine-v1`, UID 10001, exact Site origin, recipient public
key/fingerprint, ephemeral public key, salt and nonce. The envelope contains
only those public fields and ciphertext/tag. Each seal uses a fresh ephemeral
key, salt and nonce; the recipient rejects duplicate JSON fields, unknown
fields, malformed encodings, wrong recipient/AAD and failed tags. The pinned
`cryptography` library implements the primitives, following its
[X25519](https://cryptography.io/en/stable/hazmat/primitives/asymmetric/x25519/),
[HKDF](https://cryptography.io/en/stable/hazmat/primitives/key-derivation-functions/)
and [AESGCM](https://cryptography.io/en/stable/hazmat/primitives/aead/) APIs.

`install` reads at most 8192 ciphertext bytes from stdin. It verifies the
private owner directory and key with descriptor-relative, no-follow, exact
UID/GID/mode checks, decrypts and validates both secrets **before** any new
file. It exclusively creates `/run/owner/site_bypass_token` as raw printable
ASCII without `Bearer` prefix or newline, and
`/run/owner/site_bridge_hmac_key` as raw 32 bytes. Both are UID/GID 10001,
mode 0400. `verify` rechecks both without returning content; only the public
recipient fingerprint is printed. A repeated installation, symlink, unsafe
mode, unknown owner state or partial pair is NO_GO. A crash between the two
writes preserves the partial state for diagnosis; the workflow must not enable
the bridge or retry blindly. Rotation/recovery needs a separate reviewed
operation. This helper never starts the app, mutates DB, dispatches Site
commands or contacts Boca.

## Verification and unproven parts

Synthetic tests cover round-trip sealing and two-file custody, wrong
recipient/tag/AAD, malformed or duplicate fields, unsafe directory/symlink,
partial-write preservation and replay refusal. Candidate
`ee11d8eb5332913f28eda48d14b1ec5e1749d0c4` passed
CI 41271955784, scan 41271955801 and review 5726355216 in PR #178. The tests
use fake tokens and keys and no network. #167B owns the protected workflow,
volume identity and ciphertext transport; #156 owns an opt-in outbound client;
#113 owns D1 permissions/queue and native Site HMAC storage. A green helper
alone proves none of those dependencies or a deployed BETA. No real Boca
login, queue, reservation or purchase is enabled.
