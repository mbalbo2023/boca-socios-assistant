# ADR 0062: one persistent command loop for the private BETA panel

**Status:** Accepted on merge of PR #161 for issue #159. Before that merge,
this document describes an unmerged candidate; neither state proves an
installed application.

## Context and decision

ADR0057's `BetaCoordinator` owns a long-lived asynchronous worker and calls
`recover()` only at exclusive startup. A synchronous WSGI handler must not use
`asyncio.run()` on every POST: that destroys the loop while an accepted command
may still be active. The panel needs a small internal boundary to reuse the
coordinator without treating a test identity or HTML as authentication.

`BetaCommandHost.start(coordinator)` starts one dedicated event-loop thread,
runs startup recovery and returns synchronous `begin`, `status`, and `stop`
methods. The panel injects this facade into its server application. All calls
have finite request deadlines; `close()` stops new submissions, cancels/joins
the coordinator and joins the loop. The synthetic browser port is required to
cooperate with cancellation. Exactly one host instance may own startup recovery
for the application process. A second process must not call `recover()` while
the first is alive; SQLite's ordinary command claim does not provide an
exclusive cross-process startup lease.

| Operation | Internal contract |
| --- | --- |
| `begin(command_id, member_id, event_id)` | Persist or reuse the one local intent; return `CommandSnapshot` |
| `status(command_id, member_id)` | Read only; wrong or unknown member returns `None` |
| `stop(command_id, member_id)` | Durable idempotent stop; wrong or unknown member returns `None` |
| `failed` | Local coordinator/loop unavailable; no claim about external Boca |
| `close()` | Cancel and join local work; never a host-wide Docker operation |

The caller authenticates and authorizes the owner and selected member/event,
supplies a canonical command UUID, checks CSRF and request size, and redacts
unexpected exceptions. This module has no HTTP listener or role provider. It
does not create/migrate SQLite: `BetaCoordinator.prepare_storage()` remains an
explicit first-install step after the candidate's data-provenance and host
gates. It does not start Telegram or make a live Boca request.

## Failure and recovery

A request timeout raises `CommandResultUnknown`; the coordinator may have
committed an intent after the deadline. The UI must query **the same command
ID** and never generate another ID to infer that the first request failed.
Unexpected storage exceptions are redacted at the facade boundary. A failed
startup closes the loop and exposes no listener. Shutdown relies on the
injected synthetic port's cancellation contract; a port that blocks the event
loop or ignores cancellation is outside this bridge's guarantee and must be
isolated separately before use. Command outcomes remain local simulation only,
with `external_confirmation=not_observed` even when state is `completed`.

## Verification and limits

Synthetic temporary-SQLite tests cover separate synchronous requests on one
loop, concurrent aliases and the one-ticket SQL constraint, wrong-member
denial, running stop/cancellation, accepted-command startup recovery,
completed-command restart without replay, timeout ambiguity and absent/broken
schema without implicit initialization. The exact candidate SHA, CI runs and
review belong to PR #161 for issue #159. These tests
do not prove a WSGI listener, owner authentication, TLS, Site integration,
Telegram delivery, Chromium on the droplet or a real Boca flow. The root
integration writer will reconcile central status and #45 before closing this
delivery under Rule 84.
