# ADR 0082: Site custody requires an empty dedicated rootless daemon

**Status:** draft PR #196 for issue #195. On main
`451e40bf08e271f7fdf9dbb975ec5a1ed45bc298`, local `uv run pytest -q`
passed 853 tests and 29 subtests; Ruff, mypy, repository policy and diff
checks passed; the RCA ledger accepted 16 lessons and 41 executed regression
selectors in the local full-suite report. This is a source-only RCA of
the protected Site custody contract introduced in PR #181; no Site host
operation, release, token install or service activation ran as part of this
change. Exact candidate SHA, hosted checks and technical review belong in
the PR evidence after final validation.

## Cause and decision

The Site custody host path used `collect_snapshot()` to require an empty Boca
container/network namespace. That snapshot filtered project-labeled and
Boca-named containers. An unrelated or unlabeled container in the dedicated
rootless daemon could therefore remain invisible, while `site-prepare` pulled
an image and created the Boca owner volume, or `site-install` ran the sealed
credential helper. The issue was found by code review; no foreign container
on the droplet or actual unauthorized Site install was observed. A
deterministic regression first showed an unknown container could coexist with
the Site effect in the old code.

Site `prepare`, `install` and `verify` now require the full dedicated rootless
daemon container inventory to be empty. The helper checks it before any
image pull, again after pull/capacity/revision checks before volume effects,
immediately after new owner-volume identity verification before its UID/mode
initializer, immediately before the pinned Site bootstrap container, and
after that one-shot helper before a PASS receipt. Any nonempty or unavailable
inventory is NO_GO. It does not attempt to stop or inspect foreign
containers, prune resources, delete or rewrite an existing owner volume, or
retry a partial owner preparation. Existing exact owner volume driver,
labels, mountpoint, attachment, capacity, ciphertext and immutable release
checks remain in force. The sole manual workflow and host mutex are unchanged.

The inventory checks are individual preconditions, not a transactional lock
against another process creating a container between two commands. On such a
race, the later check refuses the success receipt; any already created Boca
owner volume remains for a Boca-only recovery review. Dedicated UID/rootless
identity is still required. An empty daemon inventory does not establish that
the real Site token or HMAC key is installed, that the bridge is enabled, or
that a tablet can reach Boca.

## Verification and operating gate

Tests inject a foreign rootless container at all five prepare boundaries,
including after the one-shot helper before PASS, and before existing-volume
`site-install`/`site-verify`. They require NO_GO before the next effect or
receipt and preservation of any already created Boca owner volume. The initial
regression failed against the prior implementation; the fixed tests pass
alongside the existing exact volume and envelope cases. The full local and
hosted candidate receipts are recorded in the PR after exact checks.

Protected Site custody dispatch remains NO-GO pending a reviewed current-main
candidate, matching protected release digest and real sealed material; this
source-only fix supplies no host proof. BETA, Telegram and the dormant first
install have separate gates. The integration writer reconciles central
delivery/status docs and issue #45 with actual evidence under Rule 84.
