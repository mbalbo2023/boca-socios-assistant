# ADR 0069: explicit local TLS entrypoint for the simulation panel

**Status:** accepted; PR #173 integrated into
`0161922fb68bad3c36101bf9633ba025faf52f32`. This does not establish that the
droplet serves a BETA or that a tablet can reach it.

## Decision

The default `python -m boca_socios.runtime` remains the dormant simulation
controller. `init-beta` is a one-shot first-install command: it validates the
external master key, refuses an existing SQLite path or symlink, applies the
reviewed local schema through `LocalBetaRuntime` and inserts one fixed,
synthetic event. A partial initialization is preserved for diagnosis, never
removed or retried over existing data. The protected host workflow must prove
the Boca-only namespace and destination before selecting this command.

`serve-beta` requires existing, checksum-validated local storage with that
event. It validates the owner public passkey credential, private TLS key,
certificate and exact HTTPS origin before opening a socket. It then owns one
`LocalBetaRuntime` command loop and one TLS WSGI listener, injects its member
service and command facade into `PrivatePanelApplication`, and closes both on
SIGINT/SIGTERM. The only browser port is a deterministic local synthetic
result with no URL, cookie or Boca credential method. No live Boca login,
queue admission, reservation or purchase occurs. No Telegram sender or Site
bridge starts automatically.

The server binds `BOCA_BIND_HOST=0.0.0.0` only inside the isolated Boca
container so Docker can forward the socket. The packaging contract in #167
must publish **only host `127.0.0.1:8443`**, verify effective Docker
HostConfig and reject an uncontrolled network/public listener. Binding the
container to its own `127.0.0.1` would make the host publication unreachable.
This host-loopback probe does not supply tablet access. That needs a separately
reviewed private TLS route and real owner passkey registration/proof.

| Configuration | Required value or source |
| --- | --- |
| `BOCA_RUNTIME_MODE`, `BOCA_ENGINE_MODE` | `simulation`, `off` |
| `BOCA_PANEL_ORIGIN`, `BOCA_OWNER_SUBJECT` | Exact HTTPS RP origin and configured owner |
| `BOCA_PASSKEY_CREDENTIAL_ID_FILE`, `BOCA_PASSKEY_PUBLIC_KEY_DER_FILE` | Owner public credential, separate read-only `/run/owner` mount |
| `BOCA_TLS_CERT_FILE`, `BOCA_TLS_KEY_FILE` | Certificate and private key in `/run/owner` |
| `BOCA_BIND_HOST`, `BOCA_BIND_PORT` | Container `0.0.0.0`, port `8443` under #167 |
| `BOCA_HEALTH_MODE`, `BOCA_HEALTH_CA_FILE` | `beta`; a trusted issuer bundle or synthetic test CA |

## Readiness and failure boundary

`/healthz` returns a fixed `BOCA_BETA_READY` only through the actual TLS
socket with exact Host, GET, no query, a running local command loop and a
currently validated schema/event. Otherwise it returns a fixed unavailable
body. The beta healthcheck connects to container loopback, verifies the
certificate for the configured RP hostname with strict TLS validation,
requires the exact response and fails closed. The default dormant healthcheck
still checks its SQLite migration ledger and never probes a listener.

Owner login requires a real pre-enrolled P-256 public passkey credential and
the HTTPS origin. Credential files are read through bounded, regular,
non-symlink, owner-checked descriptors; the TLS private key must be private.
They must be provisioned outside source and workflow inputs. The standard
library WSGI server is sequential and the listener is a **local access
probe**, not a public HTTP edge. One TLS client can occupy that server for up
to the five-second connection timeout, delaying every other request. This is
only suitable for the small owner-only host-loopback BETA; a future tablet
route needs a reviewed private access boundary, concurrency and denial of
service limits. Host packaging must never count green health alone as tablet
acceptance.
Health proves local readiness only; it does not prove Site connectivity,
Telegram acceptance, owner ceremony, droplet deploy or real Boca outcome.

## Verification and Rule 84

Disposable first-install/restart tests, actual loopback TLS requests, denied
unauthenticated routes, strict CA health probe, spoofed Host/plaintext,
missing/unsafe files and post-start storage loss cover the local contract.
Candidate `e86818dd87cbfd6fada494c1fe537aef19ee7834` passed
CI 41270849469 and scan 41270849494, with exact review 5726302585
in PR #173. No host service was started by these unit tests, and no external
traffic was sent. Root integrates central status, plan and issue #45 only
after reviewed merge and host evidence.
