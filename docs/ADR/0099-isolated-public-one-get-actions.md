# ADR 0099: One initial public document through an isolated Actions browser

**Status:** code candidate based on main
`032de0ebb923b4f80154e93cee3dfd1b254687ed`, 2026-11-02 ART. No public
Chromium visit, host operation, installed capability or full SPA acceptance
is claimed. The owner requested an isolated public check without droplet
changes; additional document/assets/login/queue requests remain unauthorized.

## Reuse and scope

The existing `boca-source-status.yml` gains mutually exclusive manual modes:
`http-status` retains the original one-response standard-library diagnostic;
`chromium-one-get` reuses `observe_public_home.py` and the separate browser
image. A single run never executes both public clients. The selected source,
owner actor, main ref and first attempt are checked; reruns are rejected.
PR concurrency uses a group per PR number; only manual public attempts share
the source-observation mutex, so another PR cannot replace a pending run.
PR events exercise the runner isolation and browser startup only, without
performing a public CONNECT, DNS resolution for Boca or page visit.

The observed URL remains exactly `https://bocasocios.bocajuniors.com.ar/auth/login`.
One `page.goto` is intercepted and its one `route.fetch` uses zero redirects
and zero retries. Playwright's APIRequestContext fetch receives the document,
then Chromium renders the response through `route.fulfill`; this is not an
independent Chromium-network-stack verification. JavaScript and service
workers remain disabled. Every subresource, second document, POST, popup,
redirect and other origin is refused. No fields are filled or submitted.
Existing challenge detection stops before DOM/resource inspection.

The conservative initial-form classifier remains unchanged. A document with
scripts/styles or missing SSR form returns `unknown`, not a successful fully
rendered login. Up to 64 public same-origin asset references are collected
from that document without downloading them; queries, fragments, userinfo,
external origins and unsafe paths are omitted. Truncation is explicit. This
inventory cannot establish all runtime/hydration dependencies. Any proposed
larger request budget requires a concrete owner decision after this evidence.

## Independent network barrier on the disposable runner

`run_public_observer_isolated.sh` creates only names labeled for that exact
Actions run. There is no SSH, host input, secret, persistent volume, published
port or droplet action. The nonroot browser has read-only root FS, private IPC
and cgroups, no added networking capabilities, reviewed seccomp, bounded
tmpfs/CPU/RAM/PIDs and the Chromium sandbox. It initially runs only `sleep`.

The browser attaches solely to a Docker internal bridge. Before any browser
process starts, the wrapper proves its network namespace differs from the
runner's namespace and installs IPv4 **and** IPv6 default-deny filter rules
inside that browser namespace. The only permitted IP flow is TCP to the
numeric proxy address on port 18080, with established replies. There is no
loopback exception: Docker's embedded DNS at 127.0.0.11 is denied too.

The proxy has the internal and disposable external bridge, but no published
host port. It accepts only the literal CONNECT authority for the Boca FQDN
on 443, disallows credentials/IP literals/alternate targets, and parses the
bounded TLS ClientHello before creating an upstream connection. SNI must be
exact; duplicate/encrypted SNI extensions fail closed. Only then is the fixed
host resolved once. All returned IPv4 addresses must be public; one address
is pinned, with no fallback/retry. The proxy forwards the unchanged TLS bytes;
it does not terminate TLS, mint certificates or weaken TLS verification.
After one accepted tunnel it exits. Payload sizes and wall time are bounded.

The proxy is the trusted application-layer FQDN enforcement point. It is not
a general-purpose Internet proxy or an IP/CDN allowlist presented as a domain
firewall. OS policy prevents the browser/Playwright driver from bypassing it.
TLS remains opaque: receipts name `route_fetch_count`, `accepted_tunnels` and
`upstream_connections` separately. One TLS tunnel is **not** independent proof
of one HTTP request inside TLS, nor permission to infer full-page readiness.

## Verification and failure

Before the public operation, real negative probes in the browser namespace
check a runner gateway sentinel, the proxy's other network interface, local
DNS over UDP/TCP and an IPv6 loopback sentinel. A runner-side positive check
proves the gateway sentinel exists. Firewall deny counters must increase;
the permitted proxy health endpoint and refused foreign CONNECT are checked
without contacting any public website. Chromium then launches and closes
under the same effective firewall/sandbox. The negative probes and deny
counters are checked again after a public attempt; post-probe counter increases
are required, not merely the previously recorded positive count.

The observer and proxy produce only allowlisted receipts, sanitized public
resource paths, fixed states and exception classes. They never persist HTML,
HAR, screenshots, cookies, headers, credentials or payload text. An unknown
document, failed isolation probe, unverified proxy receipt or incomplete
cleanup fails the job. EXIT/TERM cleanup removes only this run's positively
labeled containers/networks and checks that none remain. It also removes only
the exact image tagged and labeled by that run, without force; an always-run
workflow step covers a failure before the wrapper starts. Cleanup has its own
PASS/NO_GO receipt and does not overwrite an original observation failure.
A lost runner cannot
prove cleanup; no automatic retry is introduced. This cleanup concerns only
ephemeral Actions resources, not Boca's production cleanup contract.

Local regressions cover CONNECT authority/credentials, mixed private DNS,
SNI mismatch/ECH/fragmentation, real OpenSSL ClientHello bytes without network,
proxy propagation to launch/context, explicit zero retries, challenge-first
classification, safe dependency reporting and workflow mode separation.
Passing these tests is not evidence that the runner kernel or the real site
has passed. Hosted offline isolation must succeed on the exact reviewed SHA
before a manual real run; the final public receipt remains pending.
