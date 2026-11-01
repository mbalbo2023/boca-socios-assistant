# ADR 0073: opt-in outbound signed Site bridge for synthetic local commands

**Status:** Accepted on merge of PR #179 for issue #156. Before merge,
this is an unmerged candidate. Code acceptance does not activate the Site,
install credentials or prove a droplet connection.

## Decision and trust boundary

The BETA server from ADR0069 keeps its loopback TLS owner panel. With
`BOCA_SITE_BRIDGE_MODE=off` (default), no Site secret is read and no Site
request or worker is started. Explicit `poll` additionally requires exact
private Site origin
`https://boca-socios-consola-demo-20261031.mbalbo14901.chatgpt.site`,
verified 40-character source SHA, owner-only files
`/run/owner/site_bypass_token` and `/run/owner/site_bridge_hmac_key` and the
protected host workflow's reviewed activation. The first is an ASCII bypass
bearer; the second is separate raw 32-byte HMAC material. They are read
through bounded, non-following private regular-file descriptors, never
logged, persisted in SQLite, sent as workflow input or stored in Site D1.
The sealed provisioning helper in ADR0072 and #167B owns custody; this PR
does not create or install real secret material.

The worker uses only outbound HTTPS to the pinned Site port 443, verifies
normal CA and hostname, and never follows redirects. Each JSON POST is at
most 2048 bytes and gets a fresh UUID nonce, decimal Unix seconds and an
unpadded base64url HMAC-SHA256 over this exact UTF-8 canonical message:

```text
boca-site-bridge-v1\n{ts}\n{nonce}\nPOST\n{path}\n{sha256(raw_body).lowercase_hex}\n
```

The machine bypass header alone supplies **no owner identity**. The separate
HMAC key and D1 nonce/replay fence authorize only the fixed machine routes.
The owner-facing Site route must independently require owner identity and
same-origin validation; it never receives member passwords. Site D1 stores
opaque IDs, a synthetic operation and a delivery receipt, not encrypted or
plaintext Boca credentials.

## Durable operation and failure

The worker sends a bounded redacted local SQLite-intent projection heartbeat
at most every 20 seconds, leases at most one D1 row per five-second tick and
acknowledges only a known local snapshot/result. Begin is allowed only for
the one fixed synthetic event; stop uses an existing command ID. Member ID
must exist locally. The Site's `operation_id` is a transport receipt key;
`command_id` is the durable local idempotency key. A redelivery after a
30-second lease first reads the local command status and never creates a new
command ID. A timeout with unknown commit is **not** acknowledged as failure;
the lease can expire and retry inspection of the same key. A rejected ack
may similarly redeliver safely. The Site's ack is a delivery receipt at
`accepted`, `running`, or another observed state; it is **not** a terminal
Boca outcome. Local final state remains in the owner panel/SQLite. The Site
shows delivery counts and heartbeat aggregates, not per-command finality.

The transport sends no real Boca request. A remote 403, 409, 503, TLS or
malformed response cannot create a local command; remote outage leaves the
Site heartbeat stale. The owner panel remains usable when remote delivery is
unavailable. The worker marks unexpected local failure, and the beta health
endpoint then fails; routine remote unavailability does not make local
health green evidence of Site connectivity. Shutdown joins the worker before
closing the local command host and best-effort reports `stopping`; Site
freshness remains the authority if that final request cannot be delivered.

## Verification and Rule 84

Tests use only synthetic keys, temporary SQLite and injected HTTPS response
doubles. They cover canonical HMAC, pinned destination/secret file checks,
redirect and malformed response rejection, one-command recovery after an
ack loss, wrong event/member denial, stop idempotency, default-off startup
and missing-secret fail-before-listener. Hosted exact SHA CI/scan and agent
technical review belong in the PR. This is code-level evidence only: the
Site D1 route remains disabled until separate reviewed secret provisioning,
owner Site activation, protected Actions E2E, tablet/private access and
stop-test receipts. No real Boca login, queue, reservation or purchase is
part of this bridge.
