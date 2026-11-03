# ADR 0117 — Existing Chrome on Boca droplet: read-only evidence before pilot

**Status:** candidate only (2026-11-03 ART). Issue [#281](https://github.com/mbalbo2023/boca-socios-assistant/issues/281). No host receipt yet. This is an inventory probe, **not** a deployed browser, login, queue pass or ticket reservation.

## User priority and root evidence

The owner requested that, before 12:00 ART, we evaluate an existing Chrome on the Boca droplet as an alternative for the real site login of member Fernando Balbo. The Cloud Browser safely reached the public Boca Socios login page, but an encrypted credential handoff returned to login without a verified signed-in session or visible error. The owner says those credentials are correct; do not assert they are wrong. At 11:11 ART the remaining time was 49 minutes.

The only physical Docker network receipt, [run #342](https://github.com/mbalbo2023/boca-socios-assistant/actions/runs/41640672050), was NO_GO / firewall_bridge_netfilter_unavailable, cleanup VERIFIED and Boca daemon stop SUCCESS. No BETA browser was installed by that run. The Chromium used for simulated CI is an ephemeral runner image; it is **not proof** of host Chrome installation.

## One narrowly scoped inspection

- Add one `chrome-host-inspect` choice to the **existing protected manual** `boca-first-deploy.yml`; do not add any second deploy workflow, cron, service or privileged access path.
- Gate on repo/actor/main SHA, pinned SSH host key, dedicated UID 10001, `BOCA_HOST_READONLY_ENV_READY=ready`, empty image/release/site/telegram/private-input fields, service `controller` and `0.5cpu-256m-64pids`.
- A small standard-library script checks only `shutil.which()` for four fixed executable names in the dedicated user's PATH. It does not inspect credentials, launch Chromium, check account pages, use Docker, create ports, change files, install packages or access other apps.
- Output is restricted to a fixed allowlist: `BOCA_HOST_CHROME state=PRESENT|ABSENT|NO_GO kind=<fixed-name|none> uid=10001|unverified`, with 30-second SSH timeout and raw errors withheld. Presence says *binary discoverable*, not functional Chromium sandbox or logged-in account.
- CI must verify the source and guard contracts. After merge and postmerge checks, one authorized manual run may determine the host result. If absent/unverified, remain NO_GO and do not install software as a shortcut.

## Separate later pilot gate

A real site login, queue and reserve pilot requires a verified authenticated session, Fernando's consent, one member/one ticket, a genuine live eligible event and a separately designed opt-in adapter. No credentials, cookies, one-time codes, queue passes or raw HAR may be committed to public GitHub or Actions logs. Do not bypass Queue-it, CAPTCHA, WAF or rate limits. A successful binary check alone cannot authorize that pilot or weaken other applications' isolation. The announced 2026-11-03 14:00 final sale uses CONMEBOL, not Boca Socios.

Immediately record observed run SHA/result in issues #281 and #45, README/operations/status and reclassify this ADR as observed rather than candidate only when the host receipt exists (Rule 84).
