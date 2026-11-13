# R251 — typed successor preflight without host effects

**Issue:** #417, checkpoint R251. **Base:** `main` at `0007d8c4100c8d9e37103f0a2bac149cfb6edf29`.
**Scope:** existing `boca-pair-upgrade-apply` CLI, without new workflows,
dispatches, Docker operations, member authentication or queue navigation.

## Design and invariants

The protected runner already authenticates eight release/observation files
and transfers one SHA-checked, allowlisted memfd ZIP. The host CLI repeats
cross-file integrity and coordinate checks but discards the valid bound inputs
and unconditionally reports `SuccessorPreflightIneligible`. R251 may return
these **typed inert inputs** plus the immutable three packaged stage files
to a future reviewed transaction adapter. A verified file is not a permission
to execute: the current `main apply` still produces `NO_GO`, and the backend
`requires_persistent_receipt=False` remains unchanged.

The original persisted `compose.beta.yaml` digest is not in the authenticated
target release payload. Do not invent it or derive it from the target Compose;
future same-lease host read/custody must bind that earlier file before a
`PairSources` and effectful stage can be constructed.

The transport source files are data only; prevent empty/oversized/duplicate
byte content; their hashes are frozen at preflight. ZIP/bootstrap provenance
cannot be replaced by a host check of a bare source SHA. All invalid or
missing entries return a fixed redacted `NO_GO`, never raw archive bytes.

## TDD sequence

1. Extend `test_host_boca_pair_upgrade_cli.py`: authentic synthetic V2
   transport yields a typed `BoundSuccessorPreflight` with target coordinates,
   three stage byte payloads and SHA-256 digests; no host I/O. Reject absent,
   duplicate and oversized stage members, mismatched current V2, malformed
   memfd entrypoint or historical R188. A syntactically valid result has
   `apply_authorized=False`.
2. Add a direct `main apply` invariant with a valid preflight result and an
   instrumented actor: no lease, no journal, no Docker, terminal `NO_GO`.
3. Implement immutable transport object and bounded parsing in
   `host_boca_pair_upgrade_cli.py`, preserving strict proof readers and the
   unconditional effect interlock in `main`.
4. Update a focused ADR explaining that R251 is **not** R252 or a deployment;
   no fake `original_compose_sha`, no fake owner passkey or monitor.
5. Run RED-before/GREEN-after focal tests, full 7.8k test suite, Ruff,
   formatting, mypy, policy, ZIP `python -I` closure and bounded measurements.
6. Publish one R251 code-only PR, exact-SHA checks and review; merge only
   GREEN, with #417 continuous evidence. Physical `DEPLOY NO_GO` persists.

## Follow-on outside R251

R252 must bind source custody under one Boca lease and connect SUCCESS and
FAILURE V2 cleanup, durable postflight and compensation. Genuine owner Chrome
passkey, SITE_URL START/STOP, worker, monitor and SQLite are separate physical
acceptance and cannot be inferred from `GET /healthz` or offline tests.
