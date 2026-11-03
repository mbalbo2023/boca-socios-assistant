# ADR 0116 — Boca-only ICC=true network differential probe

**Status: Physically attempted, still NO_GO; exact root cause not determined.** 2026-11-03 ART. This ADR records the diagnostic authority and genuine evidence. A passing offline test or merged PR is **not** a passing host receipt.

**Latest differential evidence:** the [protected ICC=true run #345](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41653887958) returned the **runner-side** fallback `Boca network probe: NO_GO unclassified; host output withheld`; it did **not** prove that the remote Docker cause was `unclassified`. The failed stage is unknown. The candidate [ADR0122](0122-rootless-network-phase-receipts.md) proposes fixed, privacy-safe host/runner phase receipts before considering any additional physical probe; no retry is implied.

## Exact physical starting evidence

- Prior original `network-probe` on `main=d9ad6d492592c403eed70ae85af63f8b1821a67d`: [protected run #342](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41640672050), exact allowlisted `BOCA_NETWORK_PROBE result=NO_GO reason=firewall_bridge_netfilter_unavailable cleanup=VERIFIED`.
- Its network cleanup and Boca-only rootless daemon stop succeeded. No BETA, container, image, local/public port, passkey, Chrome, Telegram or purchase/reservation ran. More general failure codes in #317/#329/#337 are superseded **as diagnostics**, not deleted.
- The real `owner-enroll` bridge sets `com.docker.network.bridge.enable_icc=false`. The [Moby maintainers' report #50635](https://github.com/moby/moby/issues/50635) identifies a compatible rootless failure when bridge netfilter is unavailable, with `icc=false` causing a firewall rule that cannot be installed. This is a *testable hypothesis*, not a confirmed global kernel inspection.

## Authorized differential, bounded by Boca identity

1. Implement **new manual-only** protected Actions operation `network-probe-icc-true`, using the same exact current `main` SHA gate, deploy environments, pinned SSH/UID 10001, source transfer, approved service and minimal budget as original `network-probe`.
2. Require empty `image_ref`, release run ID and site envelope; no image pull or container create/start/attach, port publication, or owner secret. Use only the exclusive prepared and stopped Boca rootless daemon.
3. Start with empty Boca staging, verified empty relevant inventory and exact owner volume. Create only one temporary `boca-socios_owner-enroll-private` bridge with Boca compose labels, explicit `enable_ip_masquerade=false`, `enable_icc=true` and host binding `127.0.0.1`. Reject unknown metadata/options or attached peer. Never change the real enrollment's `icc=false`.
4. Always attempt exact-name/labels/options/no-peers selective network removal, run a **separate `always()` cleanup step** and **always stop** the Boca daemon. If its identity is not proven, retain unknown object and return `INDETERMINATE` instead of removing anything else. Never prune Docker broadly.
5. Emit only fixed allowlisted `BOCA_NETWORK_PROBE result=PASS|NO_GO reason=<bounded-code> cleanup=VERIFIED|INDETERMINATE` plus independent cleanup receipt. Do not expose raw stderr, topology, host paths, IDs, credentials or personal data.
6. Run locally reproducible unit/contract tests, protected PR CI/security, review, merge; **only after main postmerge GREEN**, dispatch the single physical operation. Preserve immutable source SHA, logs, job steps and verification in [RCA #275](https://github.com/mbalbo2023/boca-socios-assistant/issues/275) and canonical [checkpoint #45](https://github.com/mbalbo2023/boca-socios-assistant/issues/45).

## Outcome interpretation and forbidden shortcuts

- `PASS` with `cleanup=VERIFIED` and separate daemon stop confirms *only* that a zero-peer temporary bridge can be created under the ICC=true configuration. It supports, but does not fully prove, ICC=false as the blocker. **It does not unblock owner-enroll, BETA, Chrome nor Telegram**; changing actual enrollment isolation needs a separate security design, consent and acceptance gates.
- `NO_GO` further narrows the host cause by a bounded reason code; preserve a safe no-deploy state and investigate a distinct hypothesis with evidence. No blind retries.
- **Never** load kernel modules, alter sysctl/iptables/nftables/UFW, global/rootful Docker, or another service's networking, even if a workaround appears convenient. No cross-project changes, backup, HTTPS/certificates, port 9000 or root account. Portal remains 127.0.0.1:8443 via SSH tunnel when later separately proven ready.

## Resumption and Rule 84

Project remains simulation-only and isolated. Source tests are distinct from the physical protected Actions receipt. After physical run, update these top-of-file status sections and issues #275/#45 promptly, including exact SHAs and cleanup/stop evidence. No Work agent credits or supervision workflow are prerequisites: GitHub CI and the user-authorized manual Actions are the execution platform.
