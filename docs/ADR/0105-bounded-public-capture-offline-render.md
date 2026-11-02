# ADR 0105: Approved public byte capture and offline Chromium rendering

Status: implementation candidate based on main `5ddfba5`, 2026-11-02 ART.
The owner authorized continuation of the concrete plan in the public-source
report, including at most 25 anonymous GETs. This change implements that
bounded scope; it does not record a new public observation, deployment or
completed acceptance. A reviewed exact SHA, successful hosted offline smoke,
and one explicit manual dispatch remain required before the real capture.

## Existing evidence and scope

[Run 41481095746](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41481095746)
observed one initial public document, returned UNKNOWN, and verified the
runner's pre/post isolation and cleanup. Its 26 sanitized references are
historical evidence, not a complete runtime dependency graph. The previous
one-GET and HTTP-status modes remain unchanged and mutually exclusive with
the new `chromium-capture-25` choice in `boca-source-status.yml`. PRs execute
only synthetic offline checks. There is no SSH, droplet access, new service,
published port, credential input or deployment change.

The new trusted stdlib client fetches `/auth/login` once. It parses the fresh
raw HTML without executing JS and requires exactly the 24 static references
listed in `public-source-validation-2026-11-02.md`. An absent or new resource,
query, fragment, alternate origin, malformed URL, base tag, refresh, srcset,
challenge or incompatible publication stops before downloading any static.
This is deliberately more conservative than selecting a subset: it cannot
silently fetch a formerly observed path that is no longer referenced. Root
and favicon metadata are recognized but never downloaded. Neither this
HTML inventory nor regex inspection is represented as proof of all CSS/JS
dependencies; any later unmapped request stops the offline render.

## Capture and transport boundary

`public_observer_bundle.py` owns the immutable list, size limits, inventory,
private schema and content hashes. `public_observer_capture.py` opens one
fresh `HTTPSConnection` per fixed GET through the numeric internal proxy.
The CONNECT authority and TLS SNI are the exact Boca FQDN on 443; the stdlib
verifies its certificate with the normal trust store. There is no TLS
termination, generated certificate or MITM. Headers are fixed: no Cookie or
Authorization, `Connection: close`, `Accept-Encoding: identity`. No cookie
jar, redirect follower, retry loop or caller-selected URL exists. Set-Cookie
is neither retained nor reused; original response headers are never exported.

Requests are serial, with starts at least 500 ms apart. An OS interval timer
bounds the entire request, including TLS, headers and streaming body, to
`min(8 seconds, remaining capture budget)`. Socket timeouts alone would not
bound a slow streaming response. One monotonic 120-second deadline covers
spacing, all requests, validation, proxy completion and bundle creation;
each request cannot reset it. The body budgets are HTML 1 MiB, each JS 2 MiB,
CSS 512 KiB, each font 1 MiB, combined 12 MiB. Compressed content, invalid
type, non-200 status, truncation and excess bytes fail closed. There are at
most 25 attempted HTTP requests, counted by this trusted HTTP client.

The existing namespace firewall, probes and proxy are reused. Capture mode
allows at most 25 CONNECTs. The proxy validates every visible ClientHello,
resolves the fixed FQDN only once to an entirely public IPv4 answer set, pins
one address, and never falls back. A local fixed `/finish/N` control message
must match accepted and upstream counts; this also produces a truthful
terminal receipt for a partial attempt. A 26th CONNECT is refused. These are
TLS tunnel counts, **not an independent inspection of encrypted HTTP**.
Default one-GET proxy behavior still exits after one accepted tunnel.

## Private transfer and zero-egress rendering

Captured bytes exist only in the capturer's private tmpfs, exclusive directory
0700 and regular file 0600. The schema contains only fixed paths, fixed MIME
types, base64 body bytes and SHA-256; it has no original headers. Both ends
revalidate size, provenance, exact paths/count, hashes and initial inventory.
Transfer is a bounded anonymous pipe between two `docker exec` processes,
never `tee`, host files, HTTP, artifacts, HAR, screenshots or logs. Export
removes the source bundle even on error; render removes its bundle in a
finally block. Docker cleanup destroys both tmpfs mounts after failure,
timeout or a normal run. Public receipts contain only fixed states/reasons,
known paths, sizes, hashes and counters. GitHub identifies the selected SHA.

Rendering occurs in a **different** nonroot sandboxed container created with
`--network none`, without the proxy or its internal bridge. Docker network
mode and the sole `lo` interface are checked before the render. Genuine HTML,
JS, CSS and fonts are fulfilled at their original HTTPS URLs only from the
validated bundle. No HTML is fabricated or altered in real mode, no fields
are filled, and no form is submitted. Original response headers/Set-Cookie
are not forwarded. Service workers are blocked; workers, popups, downloads,
navigation, WebSockets, XHR/fetch, credential headers, runtime errors and any
resource outside the map invalidate the result. At most 64 responses are
allowed; the next request stops. A separate supervisor imposes a 20-second
wall deadline on the render child, including its cleanup, so a stuck close
cannot extend the budget. The wrapper then removes the entire container.

The bounded observation window checks late requests and closes the context
before committing a result. Every exception, including a later browser or
Playwright close error, invalidates a provisional DOM observation. No finite
window can prove absence of arbitrary future timers or remote API needs.
The positive result is named `offline_capture_render / DOM_OBSERVED` with
`connected_site=false`; it proves only the visible, disabled login
form in an offline snapshot. UNKNOWN is not treated as site acceptance,
and neither result authorizes login, queue access, reservation or purchase.

## Verification and remaining gates

Offline tests exercise raw-URL rejection, inventory changes, body/transfer
bounds and hashes, TLS client configuration, no-retry behavior, serial
spacing, real streaming wall alarms, the global deadline, partial proxy
completion, refusal of tunnel 26, one DNS resolution, dynamic request
rejection, the 64-response budget and late-close invalidation. Test imports
use explicit source loaders; the prior console-pytest collection regression
now covers all new modules without a global PYTHONPATH workaround.

The hosted PR smoke retains the real IPv4/IPv6/gateway/DNS denial probes
before and after, Chromium sandbox startup, and selective image/container/
network cleanup. In the separate network-none renderer it uses explicitly
synthetic bytes: the positive fixture requires captured JS to create the
form; four negative fixtures must stop on fetch, WebSocket, navigation and a blob Worker.
Synthetic results can never bear public-capture provenance. Local unit
tests cannot replace this Docker/kernel/Chromium run on the exact SHA.

Review caught two candidate defects before any public execution: a late
browser close could preserve provisional DOM success, and awaiting text
inside `any()` created an async generator. Regressions
`test_late_browser_cleanup_failure_invalidates_provisional_dom` and
`test_renderer_runs_full_adapter_and_challenge_gate_without_network` cover
the corrected paths. No public rerun or server installation was used to
diagnose either issue. RCA #262 and fixing PR #263 record both regressions.
The first candidate passed hosted CI, security and the real offline
Docker/Chromium smoke; the [source report](../quality/public-source-validation-2026-11-02.md)
records exact head, test-merge SHA, equivalent tree and run receipts. Any
later candidate still needs its own final checks and review. The authorized
one-time capture subsequently ran as 41512196530 on main 6f7fa0939d28df7c315440bba15237b0c1bfbe77:
all 25 GETs returned 200, but the real offline renderer stopped UNKNOWN on an
unmapped resource. Isolation and cleanup passed. The source report preserves
the receipts; RCA #264 addresses missing denied-resource identity. No further
public request is authorized by this correction or observation.
