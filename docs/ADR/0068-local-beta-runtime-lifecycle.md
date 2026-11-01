# ADR 0068: explicit local BETA lifecycle before server and Site integration

**Status:** accepted; PR #164 integrated into
`df668e066d2967ad7eb82e3c9f96935af282e2e2`. No application
installation is implied.

## Decision

`LocalBetaRuntime.start()` composes one `Database`, external-key
`CredentialVault`, `MemberEnrollmentService`, SQLite outbox, `BetaCoordinator`
and the persistent `BetaCommandHost` from ADR0062. It accepts only a
`SyntheticBrowserPort`, which has no site URL, cookie or credential arguments.
This stage has no listener, outbound Site bridge or Telegram dispatch loop.
The hosting process must own a single instance and call `close()` on shutdown;
`ready` describes only the local command-loop lifecycle.

The first-install caller must explicitly set `initialize_new=True` **only**
after the protected host workflow has proven the approved Boca namespace and
data destination empty. This method refuses an existing file or symlink,
validates the private key file first, then applies the already reviewed
0001/0002/0003/0005/0006 schema through `BetaCoordinator.prepare_storage()`.
An interrupted initialization is preserved for diagnosis, never deleted or
retried over an existing path.

Default `initialize_new=False` requires an existing regular, non-symlink
database. It opens SQLite `mode=ro`, verifies required migration versions and
checksums against packaged SQL and required table presence before starting
the command host. It applies **no migration** to existing data. Known optional
versions such as the key policy or Telegram schema are accepted only with
their exact packaged checksum; unknown versions fail closed. Runtime recovery
then follows ADR0057: accepted work may safely resume; ambiguous work pauses.
No backup/restore or alteration of another workload is performed.

## Security, failure and integration boundaries

The key remains outside DB/image/repository and is never returned to the UI.
Member credentials are sealed by the existing vault; this class does not
fetch or use them for a Boca login. There is one local intent with quantity1
per member/event and only simulated completion. Read-only SQLite can interact
with WAL shared-memory files; the validation is **not** a forensic claim of
zero filesystem effects or global DB discovery. Ledger checksums and table
names do not prove every row or key version correct. The host still needs
exclusive storage ownership and a proven destination before first install.

The panel writer supplies the owner authentication, passkey bootstrap,
permissions, CSRF, TLS and WSGI application. The host writer supplies
container image, Compose, capacity and Actions. Telegram is separately
configured and explicit, never automatically sent by this lifecycle. The
owner-private Site requires an outbound service credential and a durable
queue contract that are not yet available on the host; this PR does not
silently enable a dead polling client or claim Site connectivity.

## Verification and Rule 84

Disposable SQLite/key tests cover missing storage, explicit new creation,
existing read-only restart, one command replay, key failure before writes,
existing path/symlink preservation, checksum/table drift and cancellation on
close. Candidate `46f9a48e6e6c2c7a738e5559a536e3de6011170f`
passed CI 41269722611 and scan 41269722595, with technical review
5726257987 in PR #164. These tests do not prove a served panel, Site/Telegram
delivery, droplet capacity, real navigation or a BETA installation. The root
integration writer reconciles README/status/plan and issue #45 before this
scope closes.
