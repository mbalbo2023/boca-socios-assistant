# ADR 0014: Opt-in observation of the anonymous public login

Status: Proposed for issue #32, 2026-10-28. Observation code is **not executed
against Boca by CI** and does not validate a reservation workflow.

## Scope

The owner corrected the priority toward the real public portal. An earlier
single anonymous browser view by the project coordinator showed a login form
(email and password) and recovery/association links; no queue or reservation
controls were visible. This is evidence only for that public view and time,
not for a ticketing event, an authenticated member or provider behavior. A
later anonymous visit to the public root ended at `/auth/login`. The original
observer allowed only the root URL and could not classify that route.

`scripts/observe_public_home.py` is a separate opt-in Playwright program. It
requires both an explicit command acknowledgement and two environment gates;
`BOCA_OBSERVER_STOP=1` is the default kill switch. The URL is fixed to the
exact public HTTPS `/auth/login` URL, with no URL, account, cookie or password inputs. It creates an
empty ephemeral BrowserContext with JavaScript and service workers disabled,
downloads disabled, Chromium sandbox enabled, and one `page.goto`.

The context route allows only one GET for the exact public login document. It uses
`route.fetch(max_redirects=0)` and fulfills only HTTP 200, then aborts every
asset, POST, popup document, redirect or other destination. Expected
same-origin CSS, images, fonts, scripts and favicon are discarded without
invalidating the one document; a second document, POST, foreign domain or
queue/challenge path stops the observation. Playwright's
`route.continue_` is deliberately avoided because redirects can proceed
without another route callback. The program checks the final URL and visible
text in memory; it emits only the fixed `login_visible` classification. A
queue, CAPTCHA, blocked response, unknown page or any error is a stop, with
only a sanitized reason or exception class. No HTML, screenshot, HAR, cookie,
header, response body, query parameter or page text is written to output.

### Optional read-only login DOM smoke (follow-up to #32)

The explicit `--ack-one-public-visit --check-public-login-dom` mode reuses
**the same observer, same exact `/auth/login` URL and same one-GET route gate**.
It checks the HTTP 200 response, exact final URL and challenge indicators
*before* examining any form. It then requires exactly one form containing one
visible `input[type=email]`, one visible `input[type=password]` and one
visible `button[type=submit]` or `input[type=submit]`, initially disabled.
It reads only control counts, visibility and the disabled state; there is no
interaction, value extraction, credential input or form submit. This mode
does **not** depend on the site's visible copy or button accessible label;
it fails closed if semantic form markup is absent. Success is the sanitized
`login_form_disabled` state, not a login test.
The original `--ack-one-public-visit` text-only mode remains unchanged.

Both modes still require `BOCA_PUBLIC_OBSERVATION=one-shot` and
`BOCA_OBSERVER_STOP=0`, with the stop switch enabled by default. Missing,
hidden, duplicated or enabled controls become `unknown` and stop; no follow-on
navigation or retries occur. Because the real site's markup has **not** been
verified by this implementation, these selectors are a conservative
hypothesis from a previously observed public form, not a claim of live
compatibility. A Next.js client-rendered form may be absent with JavaScript
disabled and scripts aborted: an empty CSR shell produces `unknown`/stop,
**not** a false PASS. Visibility checks with CSS assets blocked cannot prove
how a fully styled, hydrated site would display the form.

The normal CI suite tests request filters, classification and browser cleanup
with doubles. No scheduled or PR workflow makes a request to Boca. Playwright
is deliberately absent from the controller dependency lock and Docker image.
The optional DOM smoke and its CLI gate are also tested with offline doubles;
the tests include a negative empty CSR-shell case, but they are not an online
Chromium or live-site pass. A controlled real observation still requires the
network isolation gate below; until then, live compatibility is NO_GO/unknown.
JavaScript is disabled; if the public portal renders its login only in the
client, the observer will return `unknown` and stop. A redirect away from
`/auth/login` also stops; the script does not follow it. The unit tests use
doubles and cannot establish whether the real public page renders without
JavaScript. Only a separate bounded run could do that. The previously viewed
root page is not evidence that this exact script succeeds.

## Gate for any future real execution

Any manual observation under the owner's standing direction must use an
Actions environment whose egress policy permits only the exact public host
over HTTPS, with no proxy bypass, and a nonproduction browser worker. The
network policy and browser sandbox must be
verified before execution; **Playwright routing alone is not an OS firewall**,
and browser internals may issue traffic outside the routed page. The script
has not been run against the live site in this PR. No production droplet
command is provided; any future droplet operation must use the dedicated Boca
Actions workflow and its objective security and resource gates. The agent
must record its technical review and exact-SHA CI. The owner does not require
a second human approval for this component.

The observer stops at the public login form. Credentials, CAPTCHA, waiting
room, Queue-it passes, authenticated screens, eligibility, booking and payment
are outside this issue. Issue #27 has draft PR #43 for an isolated Chromium
startup/teardown smoke with network disabled; that test does not run this
observer against Boca. A live reservation adapter requires its own policy,
consent, reliability and controlled technical gates. The separate source
semaphore proposed in issue #94 checks only a public HTTP status, not this
browser flow or its safety boundary.

References: [Playwright routing and redirect behavior](https://playwright.dev/python/docs/network),
[Playwright Route.fetch](https://playwright.dev/python/docs/api/class-route),
[issue #32](https://github.com/mbalbo2023/boca-socios-assistant/issues/32).
