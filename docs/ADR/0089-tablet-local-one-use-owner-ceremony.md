# ADR 0089: one-use owner ceremony emitter on the tablet

**Status:** candidate in issue #215, based on `main=8fdbec97262a525821eb87f3fbc27f1841a5d2ec`.
This is reviewable code, not an Android enrollment, TLS trust installation,
host owner-volume install or BETA activation. PR/CI/review evidence belongs in
the candidate PR and the central checkpoint after integration.

## Context and decision

The served BETA refuses to start until the real owner passkey and matching TLS
files exist in its private owner volume. The inert
`OwnerPasskeyRegistration` verifier cannot be called through an anonymous host
route. The owner chose a private tablet forward to the host's
`127.0.0.1:8443` and the exact `https://localhost:8443` RP origin. Therefore
the first credential must be created and proved **on the tablet itself** at
that final origin, before the tablet's port 8443 is given to the tunnel.

The separate `owner_ceremony` candidate runs only on the owner's device. It
creates a new-only 0700 device directory with a private P-256 TLS leaf key,
`DNS:localhost` leaf certificate and public local CA certificate. The CA key
exists only while signing and is discarded; no certificate/key is committed.
The leaf expires after 30 days and the CA after 90 days; expiry or rotation
requires a later reviewed owner-custody path, not silent renewal. File reads
reject symlinks, unsafe ownership/modes, hard links and mismatched TLS/CA.
The in-memory TLS handshake checks the key, chain, SAN and validity before a
listener opens. Actual Android browser trust of a user CA is **unverified**.
No warning bypass is acceptable.

The emitter binds only device IPv4 `127.0.0.1:8443` over TLS, with no socket
reuse, public interface or outbound request. It serves a small Spanish,
accessible one-page UI; GET has no challenge or owner credential. Before
`begin()`, the local owner supplies a fresh 256-bit base64url capability
through a non-echoing device TTY and enters the same value in the browser.
This is a local physical bootstrap, not a static shared secret, anonymous
begin, forwarded identity header or GitHub credential. The process holds a
hash only, expires it after 120 seconds and consumes the single attempt; an
invalid attempt closes the emitter. A second random process-local session
token protects creation/proof/abort. POST requires trusted TLS scheme, exact
Host and Origin, bounded JSON, and no query string. It rejects mismatched
origin/host, replay, malformed input and wrong session without a secret-bearing
error. Default HTTP logs and exception traceback output are suppressed;
responses use no-store, no-referrer, strict CSP and no CORS.

The browser calls `navigator.credentials.create()` with ES256, RP
`localhost`, UV required and attestation none, then `get()` with the newly
created ID and UV required. The unchanged ADR0071 verifier checks challenge,
origin, RP hash, attested COSE/SPKI match, flags, signature and one-use proof.
On success only, the emitter combines the **public** credential ID/SPKI with
its device-held TLS leaf/key/CA and calls
`owner_bootstrap.seal_for_recipient` using the public recipient key and
fingerprint from a protected `owner-prepare` receipt. It returns only the
bounded canonical sealed JSON envelope encoded in unpadded base64url for the
existing protected `owner-install` contract, then closes the listener. No
passkey private key is exported. The browser has a Copy button with explicit
success/failure status; clipboard behavior is unverified on the real device.
The envelope is held in page memory until copy or closure, with no local file,
history, URL or server log. A client abort after a successful server response
may lose the envelope and leave an uninstalled orphan credential; there is no
automatic retry, overwrite or recovery shortcut.

## Gates and limits

Synthetic tests can verify file mode/TLS chain, exact origin/Host/CSRF,
capability expiry, create/get UV, replay, wrong signature, canonical envelope
and one-use close. They cannot prove physical identity, Android Chrome's
support for the narrow no-extension COSE/ES256 format and response accessors,
biometric/PIN ceremony, CA installation/trust, browser clipboard availability,
malware-free device, or Android/iOS same-credential interoperability. The
owner must physically execute and observe these gates before any real
owner-install. The fresh capability must come from a trusted local 256-bit
generator; no token, private key, envelope or real credential is entered into
GitHub issues, PRs, code, CI logs or screenshots. Public recipient
key/fingerprint must be compared to the protected Actions receipt; the
emitter cannot independently attest the host. The ciphertext handoff to
`owner-install` needs its own private-channel review, including GitHub Actions
input retention, before a real dispatch.

Once the emitter has stopped and its device listener has released 8443, the
separate tablet SSH forward may be started. The forward, exact TLS origin and
real owner assertion against the deployed panel remain #209 acceptance gates.
The existing single stored credential must be proven from iOS or a separately
reviewed multi-credential design is needed. No transient host enrollment
endpoint, SSH key grant, real Boca login, queue, reservation or purchase is
introduced. A green candidate has **NO_GO** status for real device and host
operations until these physical and protected gates are recorded.
