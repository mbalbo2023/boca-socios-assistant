# ADR 0076: disposable TLS acceptance inside the Boca container

**Status:** candidate in issue #183. The code is not a host operation; the
exact PR/CI/review and any later protected invocation are separate evidence.
Baseline when claimed: main `b92e2abacd63d1654dfb6d795f718af2ea283589`
after RCA #186. Authorization: [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45#issuecomment-6552258326).

## Decision and isolation

An explicit `python -m boca_socios.acceptance.host_probe` inside the reviewed
`controller` image may exercise a synthetic BETA journey **without using the
installed application's data or owner material**. The CLI requires UID10001,
staging, simulation, engine off and the fixed `/data/boca.sqlite3` container
configuration, then creates a unique private directory under the container's
`/tmp` tmpfs. It constructs Settings explicitly from that directory; it never
uses `Settings.from_environment()` for its database, key, passkey, certificate
or Site bridge. The temporary database is new only, the AES key and public
credential/certificate/private TLS key are generated locally, and the bridge
is explicitly off. There is no Telegram sender or Boca client in this entrypoint.

The probe starts the actual `init-beta` service composition, then `serve-beta`
through a verified, self-signed test CA and RP hostname over **container
loopback only**. It checks unauthorized routes, a signed ES256 owner assertion,
cross-origin denial, synthetic member enrollment/list with redaction and exact
POST replay, command completion/notice/status, terminal stop route, server
shutdown, new-session rejection after restart, canonical deduplication of a
new command UUID, unchanged schema and one quantity-one intent/notice. The
real synthetic worker returns a local result and has no URL, login or checkout
port. Active-command cancellation remains covered by #170, not by this probe's
immediate deterministic worker.

The receipt has fixed fields: sample count, median/p95 HTTPS client latency,
elapsed/process CPU time, process peak RSS (KiB on Linux), scratch bytes and
one member/intent/notice. These are measurements of this disposable process,
not capacity of the installed controller or a tablet SLA. Every HTTP client
connection has a finite timeout, polling has a deadline, the final temporary
footprint is checked below 8 MiB within a 16 MiB container tmpfs, and both
TLS server/command threads must close. Unexpected
failure emits only a fixed NO_GO reason, never private paths or response data.

## Protected operation still needed

The host owner of #182 controls the **only** manual Actions workflow, digest,
source, first-attempt, SSH/UID, container identity, mutex and capacity gates.
This PR neither changes that workflow nor invokes the probe on the droplet.
A later reviewed operation may run this module by exact Docker exec in the
positively identified Boca controller; it must preserve `/data`, `/run/owner`
and `/run/secrets`, record the receipt and stop Boca services after tests.
Synthetic CLI PASS is insufficient to claim the installed DB/owner credential,
private tablet path, Site connection, Telegram receipt or physical accessibility.
No reservation, purchase, Boca account mutation, backup or other workload is
part of the probe. Root reconciles the central plan/status and checkpoint #45
under Rule 84 after integration and actual host evidence.
