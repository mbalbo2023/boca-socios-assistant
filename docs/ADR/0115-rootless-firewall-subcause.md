# ADR 0115 — Rootless Docker firewall subcause, no host-wide workaround

**Status:** PR #278 integrated on `main=b1610b7d0a378671bf2884486ec2c0ddf2c53936`;
follow-up diagnostic PR #279. RCA #275 remains open. This ADR
records host evidence and diagnostic changes, **not** host repair or deployment.

## Additional physical evidence — protected run #342 (2026-11-03 ART)

Following integration of #279 at `main=d9ad6d492592c403eed70ae85af63f8b1821a67d`, the [protected rootless probe #342](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41640672050) returned exactly `BOCA_NETWORK_PROBE result=NO_GO reason=firewall_bridge_netfilter_unavailable cleanup=VERIFIED`. The independent cleanup and dedicated Boca rootless daemon stop succeeded. This is specific evidence about the *subprocess diagnostic*, **not** direct proof that a global kernel module is unloaded, or authority to load it. No app image, container, port, BETA, Chrome enrollment or Telegram was installed. Owner enrollment still uses ICC=false. See [ADR0116](0116-rootless-icc-true-differential-probe.md) for the owner-approved isolated ICC=true differential experiment; no production alteration is implied.

## Subsequent host observation — protected run #337

The owner executed [run #337 / 41636437171](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41636437171)
on that exact `main`, with `operation=network-probe`, no image or release
inputs. The actual log reported:

`BOCA_NETWORK_PROBE result=NO_GO reason=firewall_unsupported cleanup=VERIFIED`

Source/SSH, dedicated rootless daemon start, independent network cleanup
and daemon stop succeeded. No image, container, port, private Chrome proof,
passkey, BETA or Telegram operation ran. The classification narrows #329's
`firewall` to a *family* of unsupported firewall operations, but the host
stderr was intentionally not disclosed. In PR #278's classifier the code can
mean `Operation not supported`, an unloaded iptables match, or a
`bridge-nf-call-iptables` reference. These are alternatives, **not three
confirmed findings**; no specific kernel module, rule or backend is proven.

## Follow-up PR #279 — four fixed subcategories

In the same bounded private-stderr classification, distinguish:

- `firewall_chain_add_unsupported`: explicit CHAIN_ADD failure with
  `Operation not supported`;
- `firewall_operation_unsupported`: other explicit unsupported operation;
- `firewall_match_unavailable`: explicit iptables match load failure;
- `firewall_bridge_netfilter_unavailable`: an explicitly absent
  `bridge-nf-call-iptables` path.

An ambiguous bridge-netfilter mention still returns the historical
`firewall_unsupported` fallback. This change does not inspect a module,
select a backend, change kernel state or guarantee a fix. Tests must prove
the code is deterministic and does not expose command stderr. Only the
receipt allowlist changes in the **same** manual workflow; exact SHA/actor,
rootless identity, network options, cleanup and stopped daemon remain
unchanged. No new host operation occurs from an ordinary PR check.

## Observed on the Boca droplet (2026-11-03 ART)

The owner dispatched one protected `network-probe` on main
`eee0173ebafebf31d372bba3816ca6aadd138ffd`, run
[41629150243](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41629150243).
Its *actual job log* contains exactly:

`BOCA_NETWORK_PROBE result=NO_GO reason=firewall cleanup=VERIFIED`

The protected SSH/source gate, rootless start, independent cleanup and
dedicated-daemon stop all passed. The run did not publish images, start
containers, open ports, install BETA or configure a passkey. The host owner
volume remains preserved. The original Docker stderr stayed private and was
classified by `_network_probe_error()`; the broad `firewall` label
means the error contained `iptables`, `nftables` or `netfilter`.
It does **not** prove a particular kernel module, nft/legacy mismatch,
permissions, failure chain, or a problem with another application's firewall.

## Safe offline enhancement

Integrated PR #278 refined the **existing** `network-probe` result to
return only fixed bounded categories when Docker's underlying stderr actually
contains a recognized message:

- `firewall_backend_mismatch`: explicit nft/legacy incompatibility
- `firewall_table_missing`: an explicitly absent firewall table
- `firewall_chain_missing`: an explicitly absent chain or match target
- `firewall_unsupported`: an unsupported rule/match/bridge netfilter operation
- `firewall_permission`: denied operation in a firewall command
- `firewall_lock_denied`: inability to open the xtables lock
- `firewall`: a firewall-related error without a trustworthy subcause
- Existing `unclassified`, IPAM and other reason codes retain their meaning.

Input to the classifier must remain a bounded Docker subprocess diagnostic.
No raw stderr, IP addresses, paths, command output, UID lists, account tokens,
personal secrets or random host data may be emitted. The Actions receipt is
still a strict allowlist. Cleanup remains `finally` plus independent
`always()` and last-stop, even if the attempt fails. No auto-retry.

## Why not "fix" it by disabling the firewall

Docker's bridge networks depend on firewall rules for inter-network
isolation and port handling. Docker explicitly warns against turning
off iptables rule management as a general workaround. RootlessKit also
introduces network namespace semantics that differ from rootful Docker.
Docker Engine 29 has an experimental nftables backend, not a guaranteed
compatible solution for this particular host. Even
`enable_ip_masquerade=false` does not promise that Docker will avoid
all firewall rules.

A narrower confirmed **host cause receipt** may justify evaluating the smallest
Boca-scoped change. Test it without modifying Porota or global iptables,
UFW, nftables, sysctl, the default Docker daemon, host routes or other
ports. Do not silently use the Docker default bridge or host networking,
which would change the accepted isolation model.

## Execution boundary and acceptance

PR checks run on disposable GitHub workers, with synthetic failures.
They **cannot** prove the real host kernel/backend or run privileged Boca
host actions. The GitHub connector does not currently expose a fresh
`workflow_dispatch` call. The existing protected workflow on `main`
retains the only approved host route, and **no issue_comment, push,
PR or unprotected branch trigger will access the droplet**.

Before any host attempt: exact green candidate/review, protected main,
rootless identity, owner volume + no app namespace, SHA and isolated
cleanup gates. A new actual run must be evaluated on its own: a
successful PR does not prove a runtime solution. Reuse no Chrome
one-use URL and do not repeat failed `owner-enroll` as a substitute
for RCA.

Official sources:
- https://docs.docker.com/engine/network/packet-filtering-firewalls/
- https://docs.docker.com/engine/network/firewall-iptables/
- https://docs.docker.com/engine/security/rootless/troubleshoot/
- https://docs.docker.com/engine/network/firewall-nftables/
