# ADR0264 — Reattest Boca pair after loopback health (R253)

Status: code-only, `DEPLOY NO_GO`. No host, browser, passkey or Docker action
was executed by this change.

## Root cause

The reviewed `ProductionPrivatePanelHealthWitness` authenticated the pair
before its private `GET /healthz` and verified only the Boca lease after the
HTTP response. A serving controller/binding identity change while the request
was in flight could leave the health witness attributed to the stale pair.

## Decision and evidence

Re-run the existing strict pair-and-binding attestor *after* validating the
bounded 200 response and *before* returning `HEALTH_HTTP_200`. Retain both the
held-lease verifier and the exact loopback HTTP contract. TDD reproduced a
changed controller CID between the two observations (RED) and verified its
rejection after the fix (GREEN).

This is **only** the technical schema-2 `TECHNICAL_PROOF_ONLY` path introduced
on main by R252. It must never be converted to schema-1 `TECHNICAL_ACCEPT`,
owner `LOGIN_HTTP_200`, Chrome passkey success, authenticated monitor evidence
or a BETA deployment. The old/foreign Docker resources are untouched.
