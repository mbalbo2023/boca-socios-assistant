# ADR 0128 — Boca-only ICC compatibility for private owner enrollment

**Date:** 2026-11-04 ART. **Status:** implementation candidate in PR for RCA [#275](https://github.com/mbalbo2023/boca-socios-assistant/issues/275); deployment acceptance **not established**.

## Owner decision and evidence

On 2026-11-04, after physical [run #41854591848](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41854591848), the owner explicitly directed us to relax the security blocker and deliver the BETA. This ADR constrains that authorization to **one disposable Boca-owned owner-enrollment network**. It does not authorize global kernel, firewall or Docker configuration edits, cross-project changes, live site navigation or weaker secret custody.

Observed host:
- `ICC=false`: [run #41721217453](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41721217453) `NO_GO firewall_bridge_netfilter_unavailable cleanup=VERIFIED`.
- `ICC=true` zero-peer diagnostic: [run #41720576622](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41720576622) `PASS cleanup=VERIFIED` **only as a network probe**.
- READ_ONLY module hints: #41726757589 `module=absent nf_call_iptables=unavailable`; #41854591848 `index=listed modules_disabled=0 write_ops=none`. The kernel module is not verified loadable. Changing the global kernel is unnecessary to test this Boca-only path and could affect Porota Trading.
- Upstream explanation: [Moby issue #50635](https://github.com/moby/moby/issues/50635), [Docker bridge driver](https://docs.docker.com/engine/network/drivers/bridge/), [Linux bridge-netfilter hooks](https://docs.kernel.org/networking/bridge.html).

## Scoped decision

Change the real `owner-enroll` network `boca-socios_owner_enroll_private` to `com.docker.network.bridge.enable_icc=true` **only**. Keep:
1. Dedicated UID 10001 rootless Boca Docker daemon, Boca name/labels/unique source SHA, no access to unrelated daemon or project.
2. `enable_ip_masquerade=false`, `host_binding_ipv4=127.0.0.1`; sole published listener `127.0.0.1:8443` over owner SSH tunnel. No host networking, extra TLS, public bind or new port.
3. At most one positively identified enrollment container attached; reject foreign peers, labels, options, images and mounts. One-use capability and WebAuthn, offline private volume, 900-second expiration remain mandatory.
4. Fail-closed same-job cleanup of the disposable Boca network/container/staging, preserving owner/key/data volumes and uncertain items. `host_cleanup.py` must verify the **same ICC=true options** before removing the network; mismatches fail closed.
5. Retain historical `network-probe` on `ICC=false` and `network-probe-icc-true` on `ICC=true` as independent, no-container operations. Their previous receipts are not changed.
6. Retain CI, Trivy real scans, exact SHA/image digest provenance, branch protection and manual protected Actions, user-only site navigation, immutable browser BLACKBOX files, encrypted credentials, Chrome/Telegram owner identity.

## Security impact and limits

`ICC=true` allows inter-container communication **within this one bridge**. A malicious second container could potentially communicate with the enrollment listener if admitted; this reduces defense in depth. The design therefore checks exact network identity and rejects any peer other than the single trusted enrollment container before/after each phase. It does **not** assert equivalent firewall isolation to ICC=false nor modify the host-wide bridge netfilter hooks. A successful zero-peer probe is not proof that an actual listener, Chrome proof, or persistent BETA can start.

## Verification and release gates

- Regression checks: real enrollment creates ICC=true; both historical probes retain their distinct profiles; runner smoke creates/inspects the matching bridge; host cleanup matches the new options; foreign peer, wildcard, masquerade and mismatched ICC are rejected; no other workloads or data touched.
- Validate Ruff/format, mypy, full in-scope pytest, repo policy and both-image Trivy on the exact PR SHA. Protected main squash merge only with technical review, then postmerge CI/security.
- Manual `release-image.yml` publishes both immutable images for the exact final main SHA; `boca-first-deploy.yml` may then run `owner-prepare`, `owner-enroll` and `beta-install` only with complete protected inputs and required owner Chrome proof. No launch without those physical gates. Actual resource inspection and functional/Telegram acceptance after deploy are separate evidence.
- On any failure, preserve NO_GO, attempt selective Boca-only cleanup within the same protected workflow, document true receipt in #275 and [#45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45), and fix forward. **CI GREEN is not deployment.**

## Rejected alternatives at this stage

- `modprobe br_netfilter`, global `sysctl` or firewall/iptables changes on a host shared with Porota.
- Ignoring rootless firewall errors, enabling host network, opening more ports, disabling all security tests/Trivy, altering BLACKBOX files or bypassing workflow environment gates.
- Re-running the old ICC=false failure or installing over an unidentified pre-existing real database.

**Historical ADR0116 remains evidence of the earlier zero-peer differential and its original authorization. The owner has now superseded only the previous prohibition on `ICC=true` for the narrowly bounded real enrollment network.**
