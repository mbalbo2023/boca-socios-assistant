# ADR-0257 — Technical postflight health proof is not owner acceptance

**Status:** Proposed CODE_ONLY, 2026-11-13. **Issue:** #417, R252.

## Decision

Keep schema-1 `BOCA_PAIR_POSTFLIGHT` as the original strict login-required
contract. Its `LOGIN_HTTP_200` and monitor evidence are not relaxed. Introduce
a separate `BOCA_PAIR_POSTFLIGHT_TECHNICAL_V2` schema-2 receipt, constructed
only through explicit `capture_technical_postflight` and validated only through
`verify_technical_postflight`. The two receipt formats are not interchangeable.

Schema 2 requires the genuine bounded GET-only controller loopback `/healthz`
attestor (`HEALTH_HTTP_200`), not `/ingresar`, Chrome, or a WebAuthn challenge.
The technical reader never calls the authenticated monitor endpoint. Its
`source=NOT_CONNECTED` and `observations=0` describe **the attestor's lack of a
monitor session**; they are not assertions of live producer connectivity or
zero observed provider tokens. Receipt includes `owner_monitor=NOT_ATTESTED`,
`passkey_chrome=NOT_ATTESTED`, and `beta_deploy=NO_GO`.

Both modes retain the same authenticated release, pair, CREATED/PID0/Exit0
worker, rootless identity, retained graph, volume structural custody, SITE_URL
saved/mirror, cold-start entrypoint, final cleanup V2 on-disk readback,
same-lease verification and double-snapshot stability guards. The technical
contract does not acquire/release the lease or persist evidence itself.

## Rejected alternative

Replacing `LOGIN_HTTP_200` with `HEALTH_HTTP_200` in the existing schema would
silently downgrade the legacy verifier and permit a health check to masquerade
as owner acceptance. Supplying artificial successful monitor callbacks would
make live tokens appear verified without an authenticated producer. Both are
disallowed.

## Consequence and next integration boundary

R252 is CODE_ONLY, not an installed-release acceptance. The protected host
runner must deliberately bind the technical reader, call the new capture
under its already-held same Boca-only lease *after final cleanup*, write the
canonical v2 bytes via O_EXCL/fsync and read them back before releasing the
lease. The protected bundle must include the reviewed source modules; no
workflow or ZIP change is part of this ADR. Physical owner Chrome/passkey,
monitor and UI acceptance are separate post-deployment checks. Effectful APPLY
remains independently interlocked, and BETA stays NO_GO until complete.

## Verification

Focused synthetic tests enforce version isolation, genuine-health source
requirement, empty monitor reads, duplicate/noncanonical rejection, same-lease
double snapshot, cleanup/site/worker/volume guards, and unchanged v1 behavior.
No tests in this code-only change establish a physical droplet state.
