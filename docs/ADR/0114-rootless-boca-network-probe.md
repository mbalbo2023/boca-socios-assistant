# ADR 0114 — Probe an isolated Boca rootless bridge without a Chrome enrollment

**Status: candidate PR #277, RCA #275.** This operation has **not** run on the droplet. Its GitHub Actions and disposable-runner results must be evaluated on the exact PR SHA, and any host response must be recorded separately.

## Host evidence

The owner supplied the actual GitHub Job Summary for [run #317](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41573026189/attempts/1#summary-125710095673): `Boca owner enrollment: NO_GO reason=network_create before Chrome use`. The same run reported `BOCA_OWNER_ENROLL_CLEANUP state=CLEANED`, container/network/staging/marker absent, all persistent owner/key/data volumes preserved, and `BOCA_STOP_TEST state=STOPPED containers=0`. The rootless image was pulled and the private staging volume was prepared before the bridge creation stage.

This narrows the failure to the exact `docker network create` operation (or its return-ID validation), **not** the tablet's Termius SSH forwarding or the yet-to-be-created Chrome HTTP listener. The underlying Docker error was never published and therefore remains unknown. `network_create` is a *phase*, not a confirmed kernel/iptables/IPAM diagnosis.

Docker officially supports the bridge options for disabling IP masquerading, disabling inter-container communication and pinning default publish address to `127.0.0.1`. Docker Rootless networking involves RootlessKit and can have separate prerequisites. Do not claim the daemon on this droplet supports those options or change its configuration without actual evidence.

## Minimal diagnostic contract

Use only the already-protected, manually dispatched `.github/workflows/boca-first-deploy.yml` with a new choice `network-probe`. **There is no second deployment workflow.** The environment, `main` verification, fixed Boca SSH key, dedicated UID 10001, rootless Docker socket, cgroup boundary and exact source SHA stay binding. No `image_ref`, release run, browser ref, owner secret, private URL or Telegram envelope is accepted. Budget stays `0.5cpu-256m-64pids` as a workflow coordinate, not a demand to launch a container.

After verifying that Boca has exactly its prepared owner volume, no application containers, no Boca network and safe staging/storage, temporarily start its *existing dedicated* rootless daemon. Attempt **only** the same owner-enrollment Boca network definition:

- `docker network create --driver bridge` with `enable_ip_masquerade=false`, `enable_icc=false` and `host_binding_ipv4=127.0.0.1`.
- Exact Boca project/network labels and original `boca-socios_owner_enroll_private` name, never a shared/default Docker network.
- No image pull, no container, no published port, no HTTP listener, no token, no direct public-site request and no interaction with another droplet workload.

Accept a positive network ID and inspect exact labels, options and empty membership. On failure classify the **private** subprocess error into the fixed list: firewall, IPAM exhausted/overlap, already exists, permission, invalid config, unsupported, timeout, or unclassified. No raw stderr, network address inventory, credentials or kernel logs leave the host. Emit only `BOCA_NETWORK_PROBE result=PASS|NO_GO reason=<fixed> cleanup=VERIFIED|INDETERMINATE`.

Within the same remote operation, `finally` proves and removes only the exact unused Boca diagnostic network. An independent `always()` job step repeats the positive-identity absence verification/cleanup after SSH interruptions; a final `always()` step stops the dedicated Boca daemon. Any unverified identity, unexpected container, foreign network, timeout, leftover or failed stop stays **NO_GO/INDETERMINATE**, never a silent retry or broad `docker prune`.

## Admission and next decision

The PR must pass strict tests, lint, formatting, type checking, security audit, workflow validation and disposable-runner smoke with exact source SHA before merging. A network-probe dispatch after merge is a **diagnostic only** and may legitimately return failed/NO_GO with a meaningful reason. It does not configure the owner's passkey, install BETA, send Telegram, or authorize changes to Nginx/firewall/rootful Docker, other ports, Porota Trading or shared services. Based on its *actual* result, derive the smallest safe fix and prove it independently before another `owner-enroll`.

Official reference:
- https://docs.docker.com/engine/network/drivers/bridge/
- https://docs.docker.com/engine/security/rootless/troubleshoot/
