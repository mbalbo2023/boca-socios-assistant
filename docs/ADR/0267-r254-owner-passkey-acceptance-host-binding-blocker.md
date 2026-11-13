# ADR 0267 — R254 owner acceptance requires a trusted installed-pair binding

**Status:** BLOCKED / DESIGN ONLY, 2026-11-13. **Issue:** #417. **No runtime,
workflow, release or host changes are included.** DEPLOY remains `NO_GO`.

## Verified code boundaries

1. `GET /ingresar` issues a one-use, process-local 120-second WebAuthn
   challenge. `POST /sesion` requires exact `Origin` and a real owner ES256
   assertion with user presence and verification; success mints a session.
   `OwnerSessions.lookup` can subsequently restore that authorization from
   the independent SQLite cookie ledger across controller restarts for up to
   the browser's rolling 400-day window. **A current authenticated cookie is
   not evidence of a fresh post-installation passkey ceremony.**
2. The current controller creation contract in
   `host_first_deploy._cutover_candidate_create_argv` supplies the fixed
   synthetic runtime, Boca-only volumes and a read-only bind of the control
   **socket directory**. It does **not** inject an authenticated exact
   `source_sha`, installation attempt, or controller/worker CIDs into the
   panel. `Settings.source_sha`, when configured for a separate Site bridge,
   is not an authoritative installed-pair attestor.
3. Exact installation identities are host-owned. The protected
   `host_on_demand_service.read_installed_binding(lease)` validates the
   `.boca-on-demand/binding.json`/archive/systemd state under an authenticated
   Boca-only lease and yields the `OnDemandInstallation` source, attempt and
   both IDs. Those host files and Docker are intentionally absent from the
   controller's mounts. The only controller→host `control.sock` protocol
   accepts a canonical 36-character lifecycle operation UUID plus newline;
   it is **not** a read-only installation-identity or owner attestation API.

## Decision

Do **not** implement an owner-acceptance button/POST, persist a receipt, or
report passkey acceptance from cookie health, WebAuthn unit fixtures, form
fields, environment variables, stale Actions artifacts or a fabricated CID.
The requested panel-only R254 scope cannot currently obtain independently
authenticated, server-observed source/attempt/CIDs. Supplying such fields
through HTML, query strings, headers or an arbitrary volume file would cross
the existing host→container trust boundary. Adding Docker/rootless-host access
to the controller would violate isolation. No broadened AF_UNIX protocol is
authorized by this design-only ADR.

## Proposed follow-up trust contract (requires separately owned host review)

1. Under a **fresh protected Boca-only host lease**, attest the live pair
   against the pinned installed binding, two exact full container IDs, image
   digests/revision labels, worker CREATED/PID0 identity, and immutable
   installation attempt. Do not infer CID from Docker name, user input or an
   old receipt. Provide a bounded, versioned, authenticated host→controller
   attestation through a newly reviewed channel available only to the
   kernel-verified running controller peer. Preserve existing lifecycle
   protocol semantics; no second port and no Docker socket mount.
2. When the owner opens the private acceptance page, issue a *new* one-use,
   short-lived, purpose-bound WebAuthn challenge which commits the exact
   installed-pair digest and an independent operation ID. An accessible
   single owner button invokes actual Chrome `navigator.credentials.get`
   with user verification required. Reject a reused long-lived cookie as
   the sole proof, a second use of the challenge, a changed host binding or
   any cross-origin request. Exact `Origin`, CSRF and one-use POST controls
   remain in force; no request body field may select SHA, attempt or CIDs.
3. Require a host-trusted recheck of the purpose-bound ES256/UP/UV assertion
   and a fresh pair observation immediately before final acceptance. Use a
   dedicated Boca-private receipt namespace with positive parent directory
   ownership, no symlink/hardlink/traversal, exclusive creation (`O_EXCL`,
   `O_NOFOLLOW`), bounded canonical digest-only bytes, `fsync` of the file
   and containing directory, and strict duplicate/failure handling. A bare
   SHA-256 of public fields is *not authentication*; any independently
   verifiable receipt must be cryptographically bound to host-only integrity
   material or an equivalent reviewed trust anchor that the container cannot
   forge. Retain neither cookie, CSRF, challenge, raw WebAuthn assertion,
   passkey/private key, bearer token, URL nor secret in the receipt or logs.
4. A subsequent **separate protected READ_ONLY verifier** must re-attest
   installed SHA/attempt/immutable CIDs, inspect the receipt safely by
   descriptor, validate canonical form and authenticity, and distinguish
   owner evidence from `/healthz`, SITE_URL, worker, monitor and SQLite
   technical proofs. It must never create/repair the receipt while reading.
   A mismatch, torn write, race, missing artifact, reboot identity drift or
   unknown monitor result is `NO_GO`; neither a green CI run nor an
   authenticated panel GET alone means BETA acceptance.

The acceptance interaction occurs asynchronously *after* deployment. A host
lease held during APPLY cannot simply be asserted to remain held while the
owner opens Chrome later. The future design must specify distinct custody
and race boundaries for host challenge issuance, user completion and final
READ_ONLY verification. It must also prove that receipt-writer authorization
does not create a second general host-operation channel outside the single
protected Boca Actions deployment workflow.

## Mandatory regression inventory before implementation

Tests must reject: old persistent cookie without new WebAuthn; fake or
replayed assertion; wrong RP/origin and missing UV/UP; duplicate CSRF or
operation; arbitrary client SHA/attempt/CID; changed two-CID binding;
foreign/stale installed pair; wrong controller peer; missing/expired host
attestation; symlink, hardlink, permissive or substituted receipt directory;
partial O_EXCL/fsync; duplicate receipt after interruption; host lease
expiration; forged public-data digest; and READ_ONLY verifier writes.
Positive tests need deterministic real ES256 fixture verification of a
purpose-bound challenge and exact server-side two-CID binding. Physical
Chrome/passkey and host result remain separately unverified until genuine
post-install receipts exist.

## Ownership / next step

R254 panel owner: this review and future private HTTP/owner WebAuthn UI only.
Host binding bridge, protected lease and separate READ_ONLY verifier require
fresh ownership coordination with the R253 same-lease and receipt owners
before implementation. No PR, push, release, Actions dispatch or deployment
is authorized by this ADR. Preserve `NO_GO` and continue technical R253
postflight work independently.
