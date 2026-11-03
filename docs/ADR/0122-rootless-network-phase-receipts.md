# ADR0122 — Redacted phase receipts for RCA #275 rootless-network diagnostics

**Status: candidate for review (2026-11-03 ART). Host acceptance is still NO_GO.**

## Evidence and root cause of the diagnostic gap

The [protected run #342](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41640672050)
on `main=d9ad6d492592c403eed70ae85af63f8b1821a67d` returned the genuine
host receipt `BOCA_NETWORK_PROBE result=NO_GO reason=firewall_bridge_netfilter_unavailable cleanup=VERIFIED` for the original
`network-probe`. This classified the remote Docker subprocess; it did **not**
prove global kernel-module state or authorize a host-wide repair.

The [protected differential run #345](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41653887958)
on the later ICC=true candidate did not produce an accepted remote receipt.
The **runner**, not `_network_probe_error()`, emitted
`Boca network probe: NO_GO unclassified; host output withheld`. The specific origin could be a
remote preflight, network creation/inspection, SSH failure, timeout or an
invalid receipt. It cannot be inferred from that summary. A new physical
diagnostic run is **not** part of this change.

## Decision

Narrow, fail-closed observability change to the existing manually triggered
`network-probe` and `network-probe-icc-true` operations, with no new authority:

1. On a failed host preflight, emit one **fixed, redacted** receipt before
   preserving the original exception and nonzero exit. Labels are
   `preflight_boundary`, `preflight_namespace`, `preflight_owner_volume` and
   `preflight_storage`; do not interpolate host details.
2. Preserve existing fixed Docker firewall/IPAM categories on creation.
   If the cause is otherwise unknown, return `network_create`, never raw
   stderr. A failed inspection reports `network_inspect`.
3. If the exact Boca-only diagnostic-network cleanup cannot be proven, report
   `result=NO_GO reason=cleanup cleanup=INDETERMINATE` if the creation and
   inspection had passed. Preserve unknown objects. If the network had already
   failed, preserve the original classified reason and set
   `cleanup=INDETERMINATE`.
4. The Actions runner accepts **only** an anchored fixed receipt and known
   zero/one return-code combinations. An absent or malformed receipt results
   in `receipt_invalid`; SSH/remote unexpected return codes result in
   `ssh_rc_unexpected`; timeout status 124/137 results in `ssh_timeout`.
   Runner labels are not passed off as host observations. Raw SSH stdout and
   stderr remain withheld from the job summary.
5. The independent `always()` diagnostic-network cleanup and dedicated
   rootless Boca daemon stop remain mandatory, even if the preceding step
   fails. No blind retries, firewall/kernel changes, global Docker commands,
   third-party containers, published ports, or new workflow entrypoints.

These receipts improve attribution, **not** readiness. A fixed reason code
is not evidence of a successful network, a running BETA or authorized
navigation. The actual host remains NO_GO until a later specifically gated
run proves otherwise.

## Test matrix / acceptance

| Scenario | Expected sanitized receipt or runner summary | Gate |
| --- | --- | --- |
| Empty/safe staging fails | `NO_GO reason=preflight_boundary cleanup=INDETERMINATE` | fail |
| Namespace/daemon/snapshot fails | `NO_GO reason=preflight_namespace cleanup=INDETERMINATE` | fail |
| Owner-volume validation fails | `NO_GO reason=preflight_owner_volume cleanup=INDETERMINATE` | fail |
| Storage validation fails | `NO_GO reason=preflight_storage cleanup=INDETERMINATE` | fail |
| Creation fails without a known Docker subcause | `NO_GO reason=network_create cleanup=VERIFIED` | fail |
| Inspection fails, exact network removed | `NO_GO reason=network_inspect cleanup=VERIFIED` | fail |
| Cleanup fails, uncertain Boca network retained | `NO_GO reason=cleanup cleanup=INDETERMINATE` | fail |
| SSH timeout, unexpected rc, invalid/missing receipt | fixed runner-only reason, host output withheld | fail |
| Valid creation, inspection and exact cleanup | `PASS reason=none cleanup=VERIFIED` | diagnostic pass only |

Unit tests in `tests/test_network_probe_phase_receipts.py` verify the sanitized
phase outputs, original exception propagation, deletion **only** of the
identified Boca diagnostic network when safe, and refusal to claim PASS when
cleanup is uncertain. Existing tests for firewall subcategories and ICC
differential remain authoritative; full CI/security and actual host evidence
are separate gates. The candidate's SHA and CI URLs should be added to
[issue #275](https://github.com/mbalbo2023/boca-socios-assistant/issues/275)
only after they exist.

## Scope and ownership

This ADR applies only to the host-side rootless network probe and the
existing protected workflow's receipts. The user owns all actual website
navigation and authorizations. The modules
`src/boca_socios/browser/synthetic.py` and
`src/boca_socios/browser/ipc_worker.py` are **OWNER LOCKED** and were neither
opened nor altered for this work. No site navigation, installation or
real reservation is part of this candidate.
