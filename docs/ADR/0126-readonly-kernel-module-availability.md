# ADR 0126 — enumerate bridge-netfilter module availability without changing the host

**Status:** candidate implementation for RCA #275, 2026-11-03 ART. This is
**not** a physical receipt, a host repair or authorization to deploy BETA.

## Three independently verified host receipts

1. [Protected ICC=false #41721217453](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41721217453):
   `NO_GO reason=firewall_bridge_netfilter_unavailable cleanup=VERIFIED`.
2. [Temporary ICC=true #41720576622](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41720576622):
   `PASS reason=none cleanup=VERIFIED` **only for the diagnostic network**.
3. [Kernel hint #41726757589](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41726757589),
   on `main=a83e105d4ccec2cc59dfabce77142750de733630`, PR #298:
   `BOCA_KERNEL_BRIDGE state=OBSERVED ... module=absent nf_call_iptables=unavailable write_ops=none`.

Together with [Moby #50635](https://github.com/moby/moby/issues/50635), these
support a strong cause hypothesis: Docker rootless cannot enforce `ICC=false`
on the owner's private bridge without effective bridge netfilter. However,
`module=absent` alone cannot tell whether the module is installed but unloaded,
built into the kernel, absent from the host module set, or blocked by policy.

## Read-only candidate

Extend **only** the existing protected manual `infrastructure-inspect` with a
second fixed host-side Python phase after the accepted `BOCA_KERNEL_BRIDGE`
receipt. Reuse exact main SHA/actor/protected environment, dedicated UID10001
SSH, stopped-daemon preflight, no image/release/envelope, service `controller`
and resource coordinate `1.5cpu-1024m-192pids`.

The helper reads only:

- `/lib/modules/<running-kernel-release>/modules.builtin`;
- `/lib/modules/<running-kernel-release>/modules.dep`;
- `/proc/sys/kernel/modules_disabled`.

Validate the release as a single safe component. Use fixed paths, `O_RDONLY`,
`O_NOFOLLOW`, `O_NONBLOCK`, regular-file checks and a 4-MiB limit **per
catalogue**. No file names, other module contents or private paths appear in
the public receipt. The catalogue parser recognizes only the exact
`br_netfilter.ko` basename and common `.gz`, `.xz`, `.zst` compressed forms.
The `modules.dep` format is generated metadata; this is **a hint, not a
guaranteed or stable ABI**. Unknown, missing, truncated, symlinked and
malformed metadata cannot become a positive finding.

Canonical receipt:

`BOCA_KERNEL_AVAIL state=OBSERVED source_sha=<40-hex> index=<builtin|listed|not_listed|unknown|inconsistent> modules_disabled=<0|1|unavailable|unreadable|invalid> write_ops=none`

- `builtin`: the built-in catalogue lists the name; not proof of live bridge hooks.
- `listed`: the dependency catalogue lists the name; not proof it can be loaded.
- `not_listed`: both complete catalogues were read without finding the name;
  not proof the kernel lacks a compatible capability.
- `unknown`: at least one required catalogue cannot be trusted; fail closed.
- `inconsistent`: both indexes list the name; do not infer readiness.
- `modules_disabled=1`: the kernel reports a policy that prevents loading
  additional modules. `0` still does not grant privilege to load one.

The runner validates exact SHA, strict enum grammar, bounded bytes, zero SSH
status and matching read-only operation. A mismatched or unavailable receipt
is `INDETERMINATE`, with raw SSH stdout/stderr withheld. Unit tests simulate
catalogue combinations, missing/symlink/FIFO/oversized data, false module
names, invalid kernel-release components, unauthorized effects and forged SSH
receipts. Existing owner rootless/cleanup and blackbox restrictions remain.

## Security, approval and next physical gate

This phase has **no writes, subprocess module loads, sudo, Docker, sysctl,
iptables/nftables, network creation, port use, secrets or Boca navigation**.
It changes no other application. The two owner-locked navigation files are not
opened, interpreted or executed. A PR must pass frozen dependency, Ruff,
Mypy, in-scope pytest, policy checks, security and exact-SHA merge gates
before a single new owner-dispatched protected run.

Even `index=listed modules_disabled=0` **does not authorize** `modprobe` or
`owner-enroll`: loading a module changes the host globally and could affect
Porota and other bridge/firewall paths. Such a change requires a separate
owner decision and cross-service impact assessment, or a separately approved
Boca isolation architecture/host. Never bypass ICC=false or treat the green
diagnostic as a deployed BETA.
