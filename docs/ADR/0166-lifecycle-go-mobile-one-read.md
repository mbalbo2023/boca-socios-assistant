# ADR0166 — Boca lifecycle mobile GO with attested READ_ONLY observation

Status: proposed CODE_ONLY, A45-R28, issue #367. Single workflow
`.github/workflows/boca-first-deploy.yml`. Observer source owned
exclusively by #366 / ADR0165 / PR DRAFT #369. Canonical base #319 R21.14
`d03bf2a8c75003cf089632b5757206af0ebb7d2b`. This ADR updates
ADR0159 / PR #359 **only** on the old PREPARE `host_calls=0` detail.

## Accessibility P0 and decision

Tincho operates Samsung Android with Voice Access. Requiring manual
construction/base64url of 12 controller/worker IDs/config/volume pins is
inaccessible and never provides independent host attestation.

Retain exactly **two manual dispatches in the same first-deploy workflow**,
with **25 dispatch inputs unchanged**, on `refs/heads/main` and dedicated
`boca-first-deploy` Environment:

1. **PREPARE — one READ_ONLY host inspection, zero host mutations**.
   The human selects `protected-go-prepare`, checks immutable source SHA,
   controller/browser image digests and release run, and leaves
   `protected_action_context` EMPTY. Runner checks owner/main,
   successful matching release, controller+browser manifests and Option-B
   ZIP. It builds the six-field canonical ASCII base64url request with
   `version=boca-lifecycle-observe-v1`, `source_sha`,
   `controller_image`, `worker_image`, `release_run_id`,
   `observe_run_id` (actual PREPARE `GITHUB_RUN_ID`, never user pin).
   One pinned Boca-only SSH ZIP/memfd `lifecycle-observe <request>`
   under a READ_ONLY host lease attests actual controller/worker Docker IDs,
   immutable images, config hashes, browser attempt, named Boca data volume,
   and reads **one** durable `REQUESTED` legacy intent. It emits its exact
   **canonical UUIDv4 `expected_request_id`**; no action can be inferred from
   component/target alone. Missing, duplicate, changed or unhealthy => NO_GO. Host derives `bot|chromium`
   and `start|stop` from the request, not from user JSON.
   Observer emits exactly one canonical ASCII public JSON line: no credentials,
   PIN, token, SSH key or private owner content. Runner checks strict schema,
   source/image pins, length/framing and owner; computes public-context hash.
   It creates the immutable PREPARE receipt with owner/source/release,
   controller+browser manifests, exact ZIP, original PREPARE run/attempt
   and 24-hour UTC validity. Artifact `boca-protected-go-prepare`
   has observed public JSON, receipt, and internally generated
   `boca-lifecycle-apply-context.txt`. Summary shows the short PREPARE
   run ID and `GO_SHA256=SHA256(domain||canonical receipt)`.
   **host_reads=1; host_mutations=0**. Never call it `host=untouched`.

2. **Separate human approval**. Exact
   `BOCA_LIFECYCLE_GO_BINDING_SHA256` protected Environment variable
   is configured after PREPARE for that immutable receipt. This is not
   a Boolean or dispatch input, and no future unknowable APPLY run ID
   is required. Current Environment required-reviewer settings cannot be
   inspected via connector and are not assumed.

3. **APPLY — short PREPARE run ID only**. The human selects
   `lifecycle-apply` and enters only existing PREPARE run ID
   (positive decimal max20 chars) in `protected_action_context`.
   Runner attests original successful PREPARE via GitHub API: actor
   mbalbo2023/main/source SHA/run_attempt=1, loads immutable artifact,
   reads its generated context and matches PREPARE ID against input.
   It verifies receipt public-context SHA, unchanged owner/main/release,
   manifests, ZIP and 24-hour TTL plus independent protected GO.
   **No user-provided JSON/base64 or fallback token is trusted.**
   Runner injects the CURRENT APPLY GITHUB_RUN_ID only after dispatch,
   and single pinned SSH calls #356
   `lifecycle-apply <canonical_context>` under fresh Boca-only lease.
   Exact host attestation must re-read the SAME **expected_request_id**
   under lease and reject newer REQUESTED with identical component/target
   before any PREPARE replay O_EXCL/fsync marker, CLAIM or effect; ten-field terminal physical
   APPLIED/ACK receipt required. Lost/uncertain ACK => NO_GO, no retry.

## Scope, limits and evidence

- One workflow, same 25 inputs; no third manual inspection dispatch,
  new server/workflow/port/HTTPS, backups, broad Docker clean, BLACKBOX,
  Porota or other services.
- PR Actions never SSH or produce host effect, no merge/deploy/real ticket.
  GREEN source tests do not prove a live installed host; actual deployment
  needs separate protected GO and physical ACK.
- `telegram-activate` remains explicit NO_GO pending genuine #357
  same-lease host path. Cutover A and official import legacy GO remain
  unchanged until separate #364 PREPARE replay and runner authentication
  actually works; DO NOT open an effect route from proposed code.
- Observer exact implementation belongs #366/ADR0165 and ZIP allowlist
  owner. Runner only this #367 scope, tests:
  `tests/test_protected_mobile_go_r28.py`,
  `tests/test_lifecycle_mobile_workflow_r28.py` and edited prior
  workflow-test expectation. Rule84: issue #367 + DRAFT PR + exact Actions.
