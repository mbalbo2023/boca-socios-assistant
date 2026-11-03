# ADR 0125 — read-only rootless bridge/netfilter host hints

**Date:** 2026-11-03 ART. **Status:** PR #298 merged into
`main=a83e105d4ccec2cc59dfabce77142750de733630`; physical read-only
inspection succeeded in [run #41726757589](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41726757589).
It is **not** an approved workaround for ICC=false. Tracked by [#275](https://github.com/mbalbo2023/boca-socios-assistant/issues/275).

## Evidence and purpose

On exact `main=b7e6e59af1ad15693528f888d4d2341de6038b56`, the protected
`network-probe` [#41721217453](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41721217453)
reported `NO_GO reason=firewall_bridge_netfilter_unavailable cleanup=VERIFIED`.
Protected `network-probe-icc-true` [#41720576622](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41720576622)
reported `PASS reason=none cleanup=VERIFIED` **diagnostically only**. The exact
`ICC=false` owner-enrollment gate remains mandatory. [Moby #41913](https://github.com/moby/moby/issues/41913)
and [#50635](https://github.com/moby/moby/issues/50635) document the same
rootless/bridge-netfilter failure class, but do not inspect this droplet.

## Narrow change

Reuse existing **manual protected** `boca-first-deploy.yml` operation
`infrastructure-inspect`, already gated by `main`, expected source SHA, owner,
GitHub protected environment, dedicated pinned SSH identity, `controller`, no
image/release/envelope and non-deploy budget. After verifying the Boca daemon is
stopped, stream the reviewed `host_rootless_setup.py` helper over SSH as the
dedicated UID 10001. It performs only two fixed kernel reads:

- `/sys/module/br_netfilter` directory metadata (visible, absent or unknown).
- `/proc/sys/net/bridge/bridge-nf-call-iptables` current single-bit read
  (0, 1, unavailable, unreadable or invalid).

Use nonblocking, no-symlink reads and a fixed canonical receipt:

`BOCA_KERNEL_BRIDGE state=OBSERVED source_sha=<SHA> module=<present|absent|unknown> nf_call_iptables=<0|1|unavailable|unreadable|invalid> write_ops=none`

Runner must validate exact grammar and SHA, bounded output/timeout and no
unexpected SSH status; otherwise fail closed with a fixed `INDETERMINATE`
summary. Raw host stdout/stderr cannot become an unvalidated public log. This
new receipt is a **hint, not proof that kernel rules are functional**. Even a
visible module and sysctl=1 cannot change `ICC=false` or admit BETA.

## Non-effects and next gate

No `sudo`, `modprobe`, `sysctl -w`, Docker invocation, container, bridge,
firewall edit, host port, root account, app/worker start, personal data or Boca
navigation. Protected blackbox modules remain untouched. No other service,
especially Porota, is accessed. The owner dispatched the protected workflow
from Termius, with the observed receipt
`BOCA_KERNEL_BRIDGE state=OBSERVED source_sha=a83e105d4ccec2cc59dfabce77142750de733630 module=absent nf_call_iptables=unavailable write_ops=none`.
The inspection succeeded without changing the host. The module's catalogue
availability remains **UNKNOWN**; see the subsequent read-only candidate
[ADR0126](0126-readonly-kernel-module-availability.md).

If hints indicate missing effective capability, separately assess the impact
of any privileged global kernel action and obtain specific owner approval; no
automatic repair or relaxation to ICC=true follows this read-only diagnosis.
