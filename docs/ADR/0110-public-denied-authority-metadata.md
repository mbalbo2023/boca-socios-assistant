# ADR 0110: Identify a rejected script authority without contacting it

Status: implementation candidate under issue #27, development baseline main
`7300c1021522a28091387a1b53c4f21dd8ad5e12`, 2026-11-02 ART. The exact
integration base and final checks are recorded in the pull request and #45.
This is an offline diagnostic extension, not approval for another public
capture or any additional destination. Runtime changes are limited to the
renderer, with regression tests and reconciled documentation. The
first-rejection behavior from ADR0106 is reused.

## Evidence and narrow purpose

[Run 41537796470](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41537796470)
captured the 25 permitted documents/assets, all HTTP 200, on the stated main.
The isolated renderer returned UNKNOWN. The first denial was a GET script
outside the exact permitted origin, with a query; five later requests were
cancelled after STOP. Pre/post probes, 25-tunnel receipt and cleanup passed.
ADR0106 deliberately omitted external authorities, so that result identifies
neither a hostname nor the script's role. No provider name, CAPTCHA, analytics
purpose or dependency requirement can be inferred from it. The deleted
capture bytes cannot be recovered by this code change.

The owner authorized continuing development of this diagnostic. Printing
the validated hostname of a future rejected anonymous script is sufficient
to make a more concrete next decision without contacting that hostname.
A fixed catalog of guessed providers could hide the next unknown, so this
extension uses bounded authority syntax instead. It does not add a provider
catalog, perform DNS lookup, discover addresses or allow a request.

## Three additional fields on the existing causal denial

| Field | Contract |
| --- | --- |
| `scheme` | `http`, `https`, `ws`, `wss`, or `null` when unavailable/unsupported |
| `authority` | Canonical validated hostname/IP and explicit valid port, or `null` |
| `host_kind` | `dns_syntax`, `global_ipv4`, `global_ipv6`, or `redacted` |

Authority is reconstructed from parsed components. User information, path,
query and fragment are never copied into it. One userinfo component is
discarded; multiple raw `@` characters in the authority are ambiguous and
redacted. The existing `userinfo_redacted`, query and fragment booleans remain.
Control characters, backslashes, encoded authority separators, malformed
brackets, unsupported schemes and malformed ports fail closed. No raw URL,
exception, header, Cookie or response content is added to output.

DNS syntax is ASCII, lowercased, with one final root dot removed. It requires
at least two labels, at most 253 characters overall, labels of 1–63 characters,
letters/digits/hyphens and no leading/trailing label hyphen. ASCII `xn--`
labels remain ASCII; Unicode names are not silently converted for display.
Known local/special suffixes and numeric/hex terminal labels are refused.
This excludes ambiguous IPv4 forms such as integer, hexadecimal, octal or
short dotted addresses instead of treating them as DNS names.

`dns_syntax` means exactly syntactic validation. It does not prove that a name
resolves, has public addresses, belongs to Boca, lacks identifying labels,
or serves a particular provider role. There is no DNS lookup in this path.
The hostname itself is intentionally exposed; the confidentiality guarantee
applies to the omitted URL components, not to semantic interpretation of a
hostname. `same_origin` retains the existing exact-origin comparison and is
not replaced by suffix matching or a guessed first-party classification.

IP literals must be classified global by the pinned Python standard library
and must also be nonprivate, nonreserved, nonmulticast, nonloopback,
non-link-local and nonunspecified. IPv6 scope/zone identifiers are refused.
IPv6 output is compressed and bracketed. Explicit ports must use canonical
decimal spelling in 1–65535; empty ports, zero and leading-zero spellings
are rejected. Output authority is at most 259 ASCII characters.

The supervisor requires the exact expanded diagnostic schema and runs the
same parser over the reconstructed scheme/authority. It rejects mismatched
types, casing, delimiters, ports, IP classification or extra URL components.
A same-origin record additionally requires HTTPS and the exact Boca host.
Existing positive-result coherence, eight-record/4096-byte limits, first
causal rejection and separate post-STOP cancellation count remain intact.
Malformed child output is rejected rather than partially emitted.

## Unchanged enforcement and verification

The capture client's 25 exact paths, request/time/byte budgets, cookies,
redirect/retry policy, proxy, firewall, separate network-none renderer,
64-response limit, STOP guard and selective cleanup are unchanged. Seeing a
hostname or a global IP in a diagnostic does not insert it into any map or
grant it egress. Even another Boca subdomain remains outside the fixed map.

The first test cut reproduced 45 failures for the absent authority metadata
contract. Offline regressions cover userinfo and query/fragment omission,
malformed framing, controls, encoded separators, DNS labels and length,
private/reserved/multicast IPs, ambiguous IPv4 forms, scoped IPv6, canonical
ports, punycode spelling, supervisor tampering and byte limits. A patched
DNS function fails if any lookup is attempted. Regressions also require STOP
for a syntactically valid new authority, another Boca subdomain, an HTTP
variant and a hostname that merely embeds the Boca name.

The existing offline navigation and WebSocket fixtures now require the new
authority fields in their receipts; their URLs, behavior and public request
count are unchanged. Hosted smoke must still report their expected UNKNOWN,
all network probes and cleanup on the exact reviewed SHA. Local tests are
not proof of a new public observation. Any future real capture requires its
own concrete authorization; this candidate performs none and cannot reveal
the hostname omitted from the previous run.
