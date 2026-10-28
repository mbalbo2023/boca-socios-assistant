# Public technical findings (2026-10-28)

The public Boca Socios Next.js JavaScript bundle shows:

- Base API gateway: https://bocasocios-gw.bocajuniors.com.ar
- Client HTTP configuration withCredentials true.
- On response errorCode 50000, web navigation can replace location
  with newRedirectUrl.
- The mobile branch interprets Queue-it-style c/e identifiers and
  state inqueue.
- When step is passed, requests can carry queueittoken to the gateway.
- There is a route name /queueit/validate.

These are verified strings/branches in the public client, **not**
confirmation that a real event queue is active on a particular day.
Original public audit supplied by the owner, dated 2026-10-28.

Useful primary sources:

- https://www.queue-it.com/developers/how-queue-it-works/
- https://queue-it.com/developers/bots-abuse-management/
- https://queue-it.com/developers/connectors/node-js-connector/
- https://github.com/queueit/ios-webui-sdk

## Unknown until authorized observation

- Whether the protected path is before/after login for each action.
- Whether several sessions of one member get distinct and usable QueueIDs.
- Prequeue randomization/configuration on the specific Boca event.
- Queue pass expiry, session binding and transaction checks.
- Eligibility and payment/reservation workflows.

Neither the code nor screenshots prove that sending or cloning a queue URL
will produce a valid reservation. Do not write production code that relies
on these unknowns without a separate verified experiment.

