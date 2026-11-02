# ADR 0106: Bounded, sanitized identity of an offline-render rejection

Status: code candidate for RCA #264, based on main
`6f7fa0939d28df7c315440bba15237b0c1bfbe77`, 2026-11-02 ART.
No new public request or host operation is authorized or performed by this
change. The previously approved single capture has already been consumed.

## Observed failure and cause

[Run 41512196530, job 125506598762](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41512196530/job/125506598762)
completed all 25 allowed GETs with status 200 and 25 TLS tunnels. The
offline renderer returned `UNKNOWN / resource_outside_map` with 30 internal
requests. Pre/post isolation and selective cleanup passed. The public
receipt did not identify the rejected resource, and captured content was
deleted as required. Its identity cannot now be reconstructed from that
receipt. In particular, 30 internal attempts minus 25 captured resources is
**not** evidence of five missing dependencies: requests can be duplicated
or aborted only because an earlier request stopped the renderer.

The isolation gate behaved correctly. The code defect is missing diagnostic
identity at the rejection boundary, which prevents a concrete, scoped
follow-up decision. It does not justify a reinstall, relaxing the guard,
silently extending the static map or repeating the consumed capture.

## Diagnostic contract

`RenderGuard` retains the first intrinsic rejection with its fixed cause,
method, resource kind, exact-origin boolean and a safe path classification.
Once STOP is active, later requests only increment `cancelled_after_stop`;
they are not reported as new dependencies. The `requestfailed` event caused
by the guard's own abort cannot replace the original cause. A failure while
closing the context preserves already sanitized diagnostics and still
invalidates acceptance.

`internal_requests` now counts evaluated requests through the first STOP;
subsequent cancellations belong only to `cancelled_after_stop`. The existing
limit of 64 allowed responses is unchanged (decision 65 stops). Keeping
post-STOP callbacks out of the decision count prevents a burst of already
cancelled requests from exceeding the supervisor's 65-decision schema and
discarding the very diagnostic needed to explain the initial rejection.
Historical receipts used a combined count and must not be compared directly
with the new evaluated-request count.

Each diagnostic contains exactly these fields:

| Field | Allowed output |
| --- | --- |
| `cause` | Fixed rejection enum |
| `method` | Fixed HTTP method enum; unexpected values become `OTHER` |
| `kind` | Fixed Playwright resource-kind enum; unexpected values become `other` |
| `same_origin` | Boolean for the exact expected HTTPS authority |
| `path` | A recognized public static path or `null` |
| `path_class` | `known`, `next_static`, `redacted`, `external` or `invalid` |
| `query_redacted` | Boolean only; no query names or values |
| `fragment_redacted` | Boolean only; no fragment value |
| `userinfo_redacted` | Boolean only; no username or password |

Literal paths are limited to the existing capture list, login/root/favicon
metadata, and a separate strict diagnostic grammar for Next static filenames:
known chunk prefixes or a numeric chunk ID followed by a 16-digit hex build
hash; 16-digit hex CSS names; and the corresponding hashed TTF naming form.
Other filenames, page segments, encoded values and arbitrary paths are
redacted. There is no hash or fingerprint of a potentially sensitive path,
query, fragment or user information. External authorities and their paths
are never emitted. Input is not normalized into a permitted URL or truncated
into an acceptable path.

This grammar is **for identification only**. A newly recognized static name
remains absent from the capture map and is still rejected. Tests explicitly
require `resource_outside_map` for such a name. The existing
`sanitized_resources` helper is not reused: it omits unsupported kinds and
external entries entirely, lacks redaction flags and accepts arbitrary
same-origin paths. Changing it would alter the separate one-GET contract.

The diagnostic object is bounded to eight records and 4096 ASCII JSON bytes;
the current terminal STOP policy produces at most one causal record. The
separate cancellation counter saturates at 65535. The supervisor revalidates
the exact schema, enum membership, strict boolean/integer types, path grammar,
origin/path coherence and byte limit before exposing child output. A
`DOM_OBSERVED` result cannot contain a denial or post-STOP cancellation, and
the first recorded cause must match `blocked_reason`. A contradictory or
malformed child receipt produces UNKNOWN with an empty diagnostic object.
No headers, cookies, bodies, exception text or raw URLs enter the receipt.

## Verification and remaining work

The first regression cut reproduced eleven failures because the rejection
metadata API did not exist. Tests now cover denied navigation with query and
fragment redaction, user information, external/opaque/encoded/oversized URLs,
sensitive path suppression, the strict static-name grammar, schema/byte/item
limits, prior-STOP cancellation, self-generated `requestfailed`, close errors
and contradictory positive receipts. RCA selectors include:

- `test_denied_navigation_identifies_only_sanitized_cause_and_separates_prior_stop`
- `test_denied_metadata_never_exports_arbitrary_paths_userinfo_or_values`
- `test_safe_static_diagnostic_identity_never_expands_the_render_map`
- `test_supervisor_rejects_diagnostic_schema_privacy_and_size_violations`
- `test_supervisor_refuses_positive_or_inconsistent_denial_receipts`
- `test_renderer_runs_full_adapter_and_challenge_gate_without_network`
- `test_many_post_stop_cancellations_preserve_causal_diagnostic_through_supervisor`

The existing offline navigation fixture uses a synthetic favicon URL with
query/fragment sentinels. Its hosted smoke must show the favicon path,
GET/document identity and `query_redacted=true`, without the sentinel values,
while retaining UNKNOWN and a verified expected STOP. The existing positive
and fetch/WebSocket/worker fixtures, kernel probes and cleanup continue in
the same PR smoke. The workflow, proxy, capture client, static map, request
budgets, retry policy and network barriers are unchanged.

Independent review, exact-SHA CI and hosted offline stdout evidence remain
required for this candidate. No local adapter test is a new real-site
observation. Any future public execution requires a concrete owner decision;
this diagnostics change cannot recover the deleted bytes or identify the
previous run's rejected URL retrospectively.
