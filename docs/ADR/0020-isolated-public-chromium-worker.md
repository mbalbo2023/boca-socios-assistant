# ADR 0020: Isolated Chromium worker for the public Boca login

Status: Proposed for issue #27, 2026-10-28. This PR provides an offline
startup gate, **not** proof that the observer has reached Boca or that a
reservation is possible.

## Decision

- Build `Dockerfile.browser` separately from the simulation controller.
  Playwright Python 1.64.1 is selected through the locked `browser` group and
  the matching official Chromium image. Actions run 40778220081 reported the
  multi-platform image index digest
  `sha256:330d401ae23c905896a0c26c66c36fc971b621519e7b11b435a8328d7bf6e031`,
  now pinned in the Dockerfile. The platform manifest is also recorded in that
  run; any later digest update needs review and a new smoke.
- Copy the reviewed issue #32 observer into this worker but keep the default
  command offline. The public observer still needs explicit command and
  environment acknowledgement. No Compose service, host port, credential,
  volume, controller import, queue client or scheduler is introduced.
- Run the CI smoke with `--network none`, nonroot UID 10002, Chromium sandbox
  requested, the upstream Playwright seccomp profile, read-only filesystem,
  private `/dev/shm`, private writable `/tmp` and home tmpfs, all capabilities
  dropped except `SYS_CHROOT`, no new privileges and limits of 1 CPU, 768 MiB
  and 128 PIDs. No `ipc: host`,
  Docker socket or access to unrelated Compose projects. `about:blank` and a
  basic JS expression show that Chromium started; this is **not** a fake
  reservation page and does not validate the real site.
- The vendored `docker/seccomp_profile.json` is from the official
  [Playwright v1.64.1 source](https://github.com/microsoft/playwright/blob/v1.64.1/utils/docker/seccomp_profile.json)
  (upstream Git blob `fddc05fb520affb145404e6f6f647ca96af8087d`,
  Apache-2.0). It permits the user namespace syscalls required by Chromium
  while retaining an errno default. Review it on updates; this profile does
  not grant user namespaces if the host kernel disables them.

## Evidence and remaining gate

Unit tests refuse root and a missing browser binary. The first Actions run
40778220081 built the image and passed quality tests, but the offline smoke
stopped with `TargetClosedError` under the configured isolation. The revised
smoke reports only the failed phase and exception class; it does not print a
  browser error payload. A later attempt will also give the nonroot browser a
  bounded private home tmpfs and temporarily log Chromium startup diagnostics
  in this **offline, no-credential** CI step only. Run 40778923578 revealed
  `sys_chroot("/proc/self/fdinfo/")` failing inside Chromium's sandbox
  zygote. The next attempt gives the browser only `SYS_CHROOT` within its
  isolated container, while retaining all other caps dropped, seccomp,
  nonroot, read-only FS and no network. This is a specific exception needed
  for sandbox startup, not permission to use host paths. GitHub Actions must
  now start and close Chromium offline and retain
the existing controller CI jobs. A successful `chromium_sandbox=True` launch
does not by itself attest every sandbox layer or prove the droplet's kernel
allows this profile. The host must be checked through a later authorized
Boca-only Actions preflight. This image is not a deployed worker yet.

One manual anonymous request to the exact public `/auth/login` can only run
later in a nonproduction worker whose OS/network egress policy permits only
that public host over HTTPS. Playwright route filters are not a firewall.
JavaScript is off, redirects are blocked, and an unknown page stops; no
account, Queue-it, CAPTCHA, booking or payment interaction belongs here.
Every live authenticated step needs its own reviewed design and owner gate.

Sources: [Playwright Python Docker guidance](https://playwright.dev/python/docs/docker),
[issue #27](https://github.com/mbalbo2023/boca-socios-assistant/issues/27).
