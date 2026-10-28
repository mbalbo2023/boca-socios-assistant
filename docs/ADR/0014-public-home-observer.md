# ADR 0014: Opt-in observation of the anonymous public home

Status: Proposed for issue #32, 2026-10-28. Observation code is **not executed
against Boca by CI** and does not validate a reservation workflow.

## Scope

The owner corrected the priority toward the real public portal. An earlier
single anonymous browser view by the project coordinator showed a login form
(email and password) and recovery/association links; no queue or reservation
controls were visible. This is evidence only for that public view and time,
not for a ticketing event, an authenticated member or provider behavior.

`scripts/observe_public_home.py` is a separate opt-in Playwright program. It
requires both an explicit command acknowledgement and two environment gates;
`BOCA_OBSERVER_STOP=1` is the default kill switch. The URL is fixed to the
HTTPS root, with no URL, account, cookie or password inputs. It creates an
empty ephemeral BrowserContext with JavaScript and service workers disabled,
downloads disabled, Chromium sandbox enabled, and one `page.goto`.

The context route allows only one GET for the exact root document. It uses
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

The normal CI suite tests request filters, classification and browser cleanup
with doubles. No scheduled or PR workflow makes a request to Boca. Playwright
is deliberately absent from the controller dependency lock and Docker image.
JavaScript is disabled; if the public portal renders its login only in the
client, the observer will return `unknown` and stop. The fake tests cannot
establish which rendering mode the current public site uses.

## Gate for any future real execution

One authorized manual observation must use an environment whose egress policy
permits only the exact public host over HTTPS, with no proxy bypass, and a
nonproduction browser worker. The network policy and browser sandbox must be
verified before execution; **Playwright routing alone is not an OS firewall**,
and browser internals may issue traffic outside the routed page. The script
has not been run against the live site in this PR. No production droplet
command is provided; any future droplet operation must use an owner-approved
GitHub Actions workflow, independently reviewed and authorized.

The observer stops at the public login form. Credentials, CAPTCHA, waiting
room, Queue-it passes, authenticated screens, eligibility, booking and payment
are outside this issue. Issue #27 remains a separate, uncompleted synthetic
container/Chromium smoke task. A live reservation adapter requires its own
policy, consent, reliability and owner-approval gates.

References: [Playwright routing and redirect behavior](https://playwright.dev/python/docs/network),
[Playwright Route.fetch](https://playwright.dev/python/docs/api/class-route),
[issue #32](https://github.com/mbalbo2023/boca-socios-assistant/issues/32).
